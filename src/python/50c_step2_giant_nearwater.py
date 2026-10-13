"""
50c_step2_giant_nearwater.py — доля площади гиганта у воды (для освобождения цепочек баров из антропогенного пре-фильтра).

Проблема: пре-фильтр техногена в 51 (≥ 20 га ∧ ero50 < 0.15 ∧ flood < 0.5) ловит тонкие цепочки побочней вдоль
меандрирующих рек (138791 — 189 га, ero50 0.12, flood 0.40; эксперт: речная отмель целиком). Сети дорог месторождений
тоже тонкие, но лежат в основном далеко от воды: у Бованенково (132009) flood 0.26 — порог по затоплению их не разделяет.
Признак: near100_frac — доля пикселей контура ближе NEAR_M от постоянной воды (GSW occ ≥ WATER_OCC) или русловой сети
MERIT. Цепочка баров прижата к руслу (≈ 0.8–1.0), сеть дорог — нет (≤ 0.3).

Вход:  exports/baresand_genesis_step2_<tag>.gpkg (anthro_suspect = 1) либо все unassigned-гиганты ≥ NET_AREA_HA (--all)
Выход: exports/qc/step2/giants_nearwater.csv — id, near100_frac, occ_pos_frac, n_px; используется в 51 (--net-near).
Запуск: python -u python/50c_step2_giant_nearwater.py --tag v3
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import argparse
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from scipy import ndimage as ndi

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC2 = EXPORTS / 'qc' / 'step2'
GSW_OCC = EXPORTS / 'gsw_occurrence_AOI.vrt'
CHANNEL_DIST = QC2 / 'channel90_dist.tif'
OUT = QC2 / 'giants_nearwater.csv'
EA_CRS = 'EPSG:3576'

PX_M = 30.0
PAD_M = 400.0
WATER_OCC = 50
NEAR_M = 100.0
NET_AREA_HA = 20.0


def window(occ_src, chd_src, geom):
    x0, y0, x1, y1 = geom.bounds
    x0, y0, x1, y1 = x0 - PAD_M, y0 - PAD_M, x1 + PAD_M, y1 + PAD_M
    w, h = int(np.ceil((x1 - x0) / PX_M)), int(np.ceil((y1 - y0) / PX_M))
    tr = from_origin(x0, y1, PX_M, PX_M)
    with WarpedVRT(occ_src, crs=EA_CRS, transform=tr, width=w, height=h, resampling=Resampling.nearest) as v:
        occ = v.read(1)
    with WarpedVRT(chd_src, crs=EA_CRS, transform=tr, width=w, height=h, resampling=Resampling.nearest) as v:
        chd = v.read(1)
    water = occ >= WATER_OCC
    dist_w = ndi.distance_transform_edt(~water) * PX_M if water.any() else np.full(occ.shape, 1e6, dtype='float32')
    dmin = np.minimum(dist_w, chd)
    inside = rasterize([(geom, 1)], out_shape=(h, w), transform=tr, fill=0, all_touched=True).astype(bool)
    return occ[inside], dmin[inside]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='v3')
    ap.add_argument('--all', action='store_true', help='все unassigned-гиганты ≥ NET_AREA_HA, не только anthro_suspect')
    a = ap.parse_args()
    t0 = time.time()
    src = EXPORTS / f'baresand_genesis_step2_{a.tag}.gpkg'
    where = f"genesis = 'unassigned' AND area_ha >= {NET_AREA_HA}" if a.all else 'anthro_suspect = 1'
    g = gpd.read_file(src, where=where).to_crs(EA_CRS)
    print(f'контуров: {len(g):,} ({where})')
    rows = []
    with rasterio.open(GSW_OCC) as occ_src, rasterio.open(CHANNEL_DIST) as chd_src:
        for k, r in enumerate(g.itertuples(), start=1):
            occ, dmin = window(occ_src, chd_src, r.geometry)
            n = len(dmin)
            rows.append(dict(id=int(r.id), n_px=n, near100_frac=round(float((dmin <= NEAR_M).mean()), 3) if n else np.nan,
                             occ_pos_frac=round(float((occ > 0).mean()), 3) if n else np.nan))
            if k % 200 == 0:
                print(f'  {k:,} / {len(g):,}', flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False, encoding='utf-8')
    print(f'near100_frac квантили: {df.near100_frac.quantile([.1, .25, .5, .75, .9]).round(2).to_dict()}')
    for thr in (0.5, 0.6, 0.7, 0.8):
        s = df[df.near100_frac >= thr]
        print(f'  near100 ≥ {thr}: {len(s)} конт')
    print(f'сохранено {OUT} | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
