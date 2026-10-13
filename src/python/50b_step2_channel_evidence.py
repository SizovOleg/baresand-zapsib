"""
BareSand — Шаг 2, доп. улики (по итогам визуальной QC v1):
  dist_channel_m — расстояние от контура до русловой сети MERIT (UPA ≥ CH_UPA_MIN км²) на сетке 90 м.
                   Узкие реки (<90 м) отсутствуют в постоянной воде GSW → нужен независимый признак реки.
  comp_elong     — вытянутость водной компоненты: (bbox_w² + bbox_h²) / площадь_в_ячейках. Река ≫ озеро.
                   Проточные озёра с UPA ≥ 50 ошибочно типизировались как «река».
  comp_seas_max  — макс. сезонность GSW (2021, мес/год) внутри компоненты: 0 → воды в 2021 нет →
                   спущенное озеро (хасырей): occurrence хранит историю, seasonality — текущее состояние.

Вход:  exports/qc/step2/water90_labels.tif (компоненты), exports/upa_AOI.vrt, exports/gsw_seasonality_AOI.vrt,
       exports/baresand_genesis_step1_v3.gpkg (unassigned), exports/qc/step2/water_components.csv
Выход: exports/qc/step2/water_components.csv (+ elong, seas_max), exports/qc/step2/step2_evidence_extra.csv
Запуск: python -u python/50b_step2_channel_evidence.py
"""
import sys
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject
from rasterio.features import rasterize
from scipy import ndimage

sys.stdout.reconfigure(encoding='utf-8')

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC2 = EXPORTS / 'qc' / 'step2'
STEP1 = EXPORTS / 'baresand_genesis_step1_v3.gpkg'
UPA = EXPORTS / 'upa_AOI.vrt'
SEAS = EXPORTS / 'gsw_seasonality_AOI.vrt'
LABELS = QC2 / 'water90_labels.tif'
COMP = QC2 / 'water_components.csv'
OUT = QC2 / 'step2_evidence_extra.csv'
CH_UPA_MIN = 20.0
DIST_CAP_M = 5000.0
STRIP_ROWS, STRIP_OVERLAP = 1200, 120
T0 = time.time()


def log(m: str) -> None:
    print(f'[{(time.time()-T0)/60:5.1f} мин] {m}', flush=True)


def edt_strips(mask: np.ndarray, tr) -> np.ndarray:
    H, W = mask.shape
    dist = np.full((H, W), DIST_CAP_M, dtype='float32')
    dy = abs(tr.e) * 111_320.0
    for r0 in range(0, H, STRIP_ROWS):
        a, b = max(0, r0 - STRIP_OVERLAP), min(H, r0 + STRIP_ROWS + STRIP_OVERLAP)
        sub = mask[a:b]
        if not sub.any():
            continue
        lat_c = tr.f + tr.e * ((a + b) / 2)
        dx = abs(tr.a) * 111_320.0 * math.cos(math.radians(lat_c))
        edt = ndimage.distance_transform_edt(~sub, sampling=(dy, dx))
        s0, s1 = r0 - a, r0 - a + min(STRIP_ROWS, H - r0)
        dist[r0:r0 + (s1 - s0)] = np.minimum(edt[s0:s1], DIST_CAP_M).astype('float32')
    return dist


def main() -> None:
    with rasterio.open(LABELS) as s:
        lab = s.read(1)
        tr, crs = s.transform, s.crs
    H, W = lab.shape
    log(f'сетка {H} x {W}')

    # ── русловая сеть по UPA ──
    p_dist = QC2 / 'channel90_dist.tif'
    if p_dist.exists():
        with rasterio.open(p_dist) as s:
            dist_ch = s.read(1)
    else:
        with rasterio.open(UPA) as s:
            upa = np.nan_to_num(s.read(1), nan=0.0)
        ch = upa >= CH_UPA_MIN
        del upa
        log(f'русловых ячеек (UPA≥{CH_UPA_MIN:.0f}): {int(ch.sum()):,}')
        dist_ch = edt_strips(ch, tr)
        with rasterio.open(p_dist, 'w', driver='GTiff', height=H, width=W, count=1, dtype='float32',
                           crs=crs, transform=tr, compress='deflate') as d:
            d.write(dist_ch, 1)
        log('EDT до русел готов')

    # ── статистика компонент: вытянутость и сезонность ──
    comp = pd.read_csv(COMP)
    n = int(comp['comp'].max())
    objs = ndimage.find_objects(lab, max_label=n)
    cells = ndimage.sum(np.ones_like(lab, dtype='uint8'), lab, index=np.arange(1, n + 1))
    elong = np.full(n, np.nan)
    for i, sl in enumerate(objs):
        if sl is None:
            continue
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        elong[i] = (h * h + w * w) / max(cells[i], 1)
    comp['elong'] = np.round(elong[comp['comp'].values - 1], 1)
    with rasterio.open(SEAS) as s:
        seas = s.read(1)
        seas90 = np.zeros((H, W), dtype='uint8')
        reproject(seas, seas90, src_transform=s.transform, src_crs=s.crs, dst_transform=tr, dst_crs=crs,
                  resampling=Resampling.max)
        del seas
    comp['seas_max'] = ndimage.maximum(seas90, lab, index=comp['comp'].values)
    del seas90
    comp.to_csv(COMP, index=False)
    log(f'компоненты: elong p50 река={comp[comp.type=="river"].elong.median():.0f}, озеро={comp[comp.type=="lake"].elong.median():.0f}; '
        f'компонент с seas_max=0 (спущенные): {(comp.seas_max == 0).sum():,}')

    # ── по контурам: dist_channel ──
    g = gpd.read_file(STEP1)
    g = g[g['genesis'] != 'shoal'].to_crs(crs).reset_index(drop=True)
    clab = rasterize(((geom, i + 1) for i, geom in enumerate(g.geometry)), out_shape=(H, W), transform=tr,
                     fill=0, all_touched=True, dtype='int32')
    idx = np.arange(1, len(g) + 1)
    dmin = ndimage.minimum(dist_ch, clab, index=idx)
    out = pd.DataFrame({'id': g['id'].values, 'dist_channel_m': np.round(dmin, 0)})
    # ближайшая водная компонента — по растрам расстояния/ближайшего из 50 (near_comp в улики не записан)
    with rasterio.open(QC2 / 'water90_dist.tif') as s:
        dist_w = s.read(1)
    with rasterio.open(QC2 / 'water90_nearest.tif') as s:
        near = s.read(1)
    pos = ndimage.minimum_position(dist_w, clab, index=idx)
    pos = np.array([(p if p is not None else (0, 0)) for p in pos])
    out['near_comp'] = near[pos[:, 0], pos[:, 1]]
    del dist_w, near, clab
    out = out.merge(comp[['comp', 'elong', 'seas_max']].rename(
        columns={'comp': 'near_comp', 'elong': 'comp_elong', 'seas_max': 'comp_seas_max'}), on='near_comp', how='left')
    out.to_csv(OUT, index=False)
    log(f'сохранено {OUT}: dist_channel≤150 м у {(out.dist_channel_m <= 150).sum():,} контуров')


if __name__ == '__main__':
    main()
