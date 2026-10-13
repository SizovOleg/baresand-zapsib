"""
BareSand — Генезис, ШАГ 2: улики «речные и озёрные отмели» для остатка после шага 1.

Физика класса: отмель — песок в зоне периодического затопления, примыкающий к водоёму.
Улики (все локально, без GEE):
  water90        — постоянная вода GSW occurrence ≥ WATER_OCC на сетке MERIT 90 м (max-ресэмпл,
                   чтобы не рвать узкие русла); связные компоненты → водные объекты.
  тип объекта    — 'river', если внутри компоненты MERIT UPA ≥ UPA_RIVER_MIN (значимый водоток),
                   иначе 'lake'; площадь компоненты, макс. UPA.
  dist_water_m   — расстояние от контура до ближайшей воды (EDT по полосам широты, анизотропия учтена);
                   nearest_type / comp_area_km2 / comp_upa — атрибуты ближайшего водного объекта.
  flood_frac0    — доля площади контура с GSW occurrence > 0 (W0 по DNA §6.5.3, по ДОЛЕ площади);
  flood_frac10   — доля с occurrence ≥ 10 (регулярное затопление).
  hnd_min, upa_max, gsw_seas_max — из littoral_v2 (join по id).

Вход:  exports/baresand_genesis_step1_v3.gpkg (genesis == 'unassigned', в т.ч. остатки разрезов)
       exports/hnd_AOI.vrt, upa_AOI.vrt (MERIT 90 м), gsw_occurrence_AOI.vrt (30 м),
       exports/baresand_littoral_v2.gpkg (атрибуты по id)
Выход: exports/qc/step2/water90_labels.tif, water90_dist.tif, water90_nearest.tif (чекпоинты)
       exports/qc/step2/water_components.csv (id компоненты → тип, площадь, UPA)
       exports/qc/step2/step2_evidence.gpkg / .csv  (контуры в WATER_ZONE_M от воды)

Запуск: python -u python/50_step2_water_evidence.py
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
ATTRS = EXPORTS / 'baresand_littoral_v2.gpkg'
HND = EXPORTS / 'hnd_AOI.vrt'
UPA = EXPORTS / 'upa_AOI.vrt'
GSW = EXPORTS / 'gsw_occurrence_AOI.vrt'

WATER_OCC = 50            # постоянная вода
UPA_RIVER_MIN = 50.0      # км² водосбора → компонента считается рекой
WATER_ZONE_M = 3000.0     # контуры дальше — не кандидаты (dist пишем как cap)
DIST_CAP_M = 5000.0
STRIP_ROWS = 1200         # полосы EDT (~1° широты на 90 м)
STRIP_OVERLAP = 120       # перекрытие полос (~11 км) > DIST_CAP
EA_CRS = 'EPSG:3576'

T0 = time.time()


def log(msg: str) -> None:
    print(f'[{(time.time()-T0)/60:5.1f} мин] {msg}', flush=True)


def load_ref():
    with rasterio.open(HND) as src:
        return src.height, src.width, src.transform, src.crs


def build_water90(H, W, tr, crs) -> np.ndarray:
    p = QC2 / 'water90_mask.tif'
    if p.exists():
        with rasterio.open(p) as s:
            return s.read(1).astype(bool)
    log('GSW → сетка MERIT 90 м (max-ресэмпл)...')
    with rasterio.open(GSW) as src:
        occ = src.read(1)
        dst = np.zeros((H, W), dtype='uint8')
        reproject(occ, dst, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=tr, dst_crs=crs, resampling=Resampling.max)
    water = dst >= WATER_OCC
    with rasterio.open(p, 'w', driver='GTiff', height=H, width=W, count=1, dtype='uint8',
                       crs=crs, transform=tr, compress='deflate') as d:
        d.write(water.astype('uint8'), 1)
    return water


def components(water: np.ndarray, tr, crs) -> tuple[np.ndarray, pd.DataFrame]:
    p_lab = QC2 / 'water90_labels.tif'
    p_csv = QC2 / 'water_components.csv'
    if p_lab.exists() and p_csv.exists():
        with rasterio.open(p_lab) as s:
            return s.read(1), pd.read_csv(p_csv)
    log('связные компоненты воды...')
    lab, n = ndimage.label(water, structure=np.ones((3, 3)))
    log(f'  компонент: {n:,}')
    H, W = water.shape
    rows = np.arange(H)
    lat_rows = tr.f + tr.e * (rows + 0.5)
    cell_km2_row = (abs(tr.e) * 111.32) * (abs(tr.a) * 111.32 * np.cos(np.radians(lat_rows)))
    weights = np.repeat(cell_km2_row[:, None], W, axis=1).astype('float32')
    idx = np.arange(1, n + 1)
    area = ndimage.sum(weights, lab, index=idx)
    del weights
    with rasterio.open(UPA) as s:
        upa = s.read(1)
    upa = np.nan_to_num(upa, nan=0.0).astype('float32')
    max_upa = ndimage.maximum(upa, lab, index=idx)
    del upa
    comp = pd.DataFrame({'comp': idx, 'area_km2': area, 'max_upa_km2': max_upa})
    comp['type'] = np.where(comp['max_upa_km2'] >= UPA_RIVER_MIN, 'river', 'lake')
    comp.to_csv(p_csv, index=False)
    with rasterio.open(p_lab, 'w', driver='GTiff', height=H, width=W, count=1, dtype='int32',
                       crs=crs, transform=tr, compress='deflate') as d:
        d.write(lab.astype('int32'), 1)
    log(f'  рек: {(comp.type == "river").sum():,}, озёр: {(comp.type == "lake").sum():,}')
    return lab.astype('int32'), comp


def distance_and_nearest(water: np.ndarray, lab: np.ndarray, tr, crs) -> tuple[np.ndarray, np.ndarray]:
    p_d, p_n = QC2 / 'water90_dist.tif', QC2 / 'water90_nearest.tif'
    if p_d.exists() and p_n.exists():
        with rasterio.open(p_d) as s:
            d = s.read(1)
        with rasterio.open(p_n) as s:
            nn = s.read(1)
        return d, nn
    log('EDT до воды по полосам широты...')
    H, W = water.shape
    dist = np.full((H, W), DIST_CAP_M, dtype='float32')
    near = np.zeros((H, W), dtype='int32')
    dy = abs(tr.e) * 111_320.0
    for r0 in range(0, H, STRIP_ROWS):
        a = max(0, r0 - STRIP_OVERLAP)
        b = min(H, r0 + STRIP_ROWS + STRIP_OVERLAP)
        sub = water[a:b]
        if not sub.any():
            continue
        lat_c = tr.f + tr.e * ((a + b) / 2)
        dx = abs(tr.a) * 111_320.0 * math.cos(math.radians(lat_c))
        edt, (ri, ci) = ndimage.distance_transform_edt(~sub, sampling=(dy, dx), return_indices=True)
        nl = lab[a:b][ri, ci]
        s0, s1 = r0 - a, r0 - a + min(STRIP_ROWS, H - r0)
        dist[r0:r0 + (s1 - s0)] = np.minimum(edt[s0:s1], DIST_CAP_M).astype('float32')
        near[r0:r0 + (s1 - s0)] = nl[s0:s1]
        log(f'  полоса {r0}/{H}')
    for p, arr, dt in ((p_d, dist, 'float32'), (p_n, near, 'int32')):
        with rasterio.open(p, 'w', driver='GTiff', height=H, width=W, count=1, dtype=dt,
                           crs=crs, transform=tr, compress='deflate') as d:
            d.write(arr, 1)
    return dist, near


def main() -> None:
    QC2.mkdir(parents=True, exist_ok=True)
    H, W, tr, crs = load_ref()
    log(f'опорная сетка MERIT: {H} x {W}')
    water = build_water90(H, W, tr, crs)
    lab, comp = components(water, tr, crs)
    dist, near = distance_and_nearest(water, lab, tr, crs)
    del water

    # ── контуры остатка ──
    log('контуры unassigned...')
    g = gpd.read_file(STEP1)
    g = g[g['genesis'] != 'shoal'].copy()
    log(f'  {len(g):,} контуров')

    ckpt = QC2 / 'step2_contour_evidence_partial.csv'
    if ckpt.exists():
        # возобновление: тяжёлые этапы уже посчитаны
        log('чекпоинт таблицы по контурам найден — пропускаю растеризацию и EDT-минимумы')
        part = pd.read_csv(ckpt)
        g = g.merge(part, on='id', how='left')
        del lab, dist, near
        finalize(g)
        return
    gw = g.to_crs(crs)

    # растеризация контуров на сетке 90 м (id = позиция+1)
    log('растеризация на 90 м...')
    gw = gw.reset_index(drop=True)
    shapes = ((geom, i + 1) for i, geom in enumerate(gw.geometry))
    clab = rasterize(shapes, out_shape=(H, W), transform=tr, fill=0, all_touched=True, dtype='int32')
    idx = np.arange(1, len(gw) + 1)
    log('минимум расстояния и ближайший водоём по контурам...')
    dmin = ndimage.minimum(dist, clab, index=idx)
    pos = ndimage.minimum_position(dist, clab, index=idx)
    pos = np.array([(p if p is not None else (0, 0)) for p in pos])
    near_comp = near[pos[:, 0], pos[:, 1]]
    g['dist_water_m'] = np.round(dmin, 0)
    g['near_comp'] = near_comp
    del clab, dist, near

    # атрибуты ближайшего водоёма
    comp = comp.set_index('comp')
    g['nearest_type'] = g['near_comp'].map(comp['type']).fillna('none')
    g['comp_area_km2'] = g['near_comp'].map(comp['area_km2']).round(3)
    g['comp_upa_km2'] = g['near_comp'].map(comp['max_upa_km2']).round(1)
    g.loc[g['dist_water_m'] >= DIST_CAP_M, ['nearest_type']] = 'none'

    # ── доля затопления (30 м, GSW) ──
    log('доля площади под водой (GSW 30 м)...')
    with rasterio.open(GSW) as src:
        occ = src.read(1)
        gtr, gcrs = src.transform, src.crs
    g30 = g.to_crs(gcrs).reset_index(drop=True)
    shapes = ((geom, i + 1) for i, geom in enumerate(g30.geometry))
    clab30 = rasterize(shapes, out_shape=occ.shape, transform=gtr, fill=0, all_touched=True, dtype='uint32')
    idx30 = np.arange(1, len(g30) + 1, dtype='uint32')
    cnt = ndimage.sum(np.ones_like(occ, dtype='uint8'), clab30, index=idx30)
    f0 = ndimage.sum((occ > 0).astype('uint8'), clab30, index=idx30)
    f10 = ndimage.sum((occ >= 10).astype('uint8'), clab30, index=idx30)
    del clab30, occ
    g['flood_frac0'] = np.round(np.where(cnt > 0, f0 / np.maximum(cnt, 1), np.nan), 3)
    g['flood_frac10'] = np.round(np.where(cnt > 0, f10 / np.maximum(cnt, 1), np.nan), 3)

    # чекпоинт таблицы по контурам (тяжёлые этапы позади) — при повторе грузится отсюда
    g.drop(columns='geometry')[['id', 'dist_water_m', 'near_comp', 'nearest_type', 'comp_area_km2',
                                 'comp_upa_km2', 'flood_frac0', 'flood_frac10']].to_csv(
        QC2 / 'step2_contour_evidence_partial.csv', index=False)
    log('чекпоинт таблицы по контурам сохранён')

    finalize(g)


def finalize(g: gpd.GeoDataFrame) -> None:
    """Join атрибутов, координаты, запись выходов, сводка."""
    # ── join HND/UPA/seasonality (в step1_v3 эти колонки есть только для прибрежной зоны — заменяем полными) ──
    g = g.drop(columns=[c for c in ('hnd_min', 'upa_max', 'gsw_seas_max', 'gsw_occ_mean', 'gsw_occ_max') if c in g.columns])
    attrs = gpd.read_file(ATTRS, ignore_geometry=True)[['id', 'hnd_min', 'upa_max', 'gsw_seas_max']]
    g = g.merge(attrs, on='id', how='left')

    cen = g.geometry.centroid.set_crs(EA_CRS, allow_override=True).to_crs('EPSG:4326')
    g['lat'], g['lon'] = cen.y.round(4), cen.x.round(4)

    cols = ['id', 'parent_id', 'area_ha', 'area_km2', 'dist_water_m', 'nearest_type', 'comp_area_km2',
            'comp_upa_km2', 'flood_frac0', 'flood_frac10', 'hnd_min', 'upa_max', 'gsw_seas_max',
            'lat', 'lon', 'geometry']
    out = g[cols]
    zone = out[out['dist_water_m'] <= WATER_ZONE_M]
    zone.to_file(QC2 / 'step2_evidence.gpkg', layer='evidence', driver='GPKG')
    out.drop(columns='geometry').to_csv(QC2 / 'step2_evidence_all.csv', index=False, encoding='utf-8')
    zone.drop(columns='geometry').to_csv(QC2 / 'step2_evidence.csv', index=False, encoding='utf-8')

    log('── сводка ──')
    print(f'  в зоне ≤{WATER_ZONE_M:.0f} м от воды: {len(zone):,} контуров, {zone.area_km2.sum():.0f} км² '
          f'из {len(out):,} / {out.area_km2.sum():.0f} км²')
    for t in ('river', 'lake'):
        z = zone[zone.nearest_type == t]
        print(f'  ближайший водоём {t:5s}: {len(z):,} конт | {z.area_km2.sum():.0f} км² | '
              f'dist p50={z.dist_water_m.median():.0f} м | flood_frac0 p50={z.flood_frac0.median():.2f} | hnd p50={z.hnd_min.median():.1f}')
    for thr in (100, 300, 500, 1000):
        z = zone[zone.dist_water_m <= thr]
        print(f'  dist ≤ {thr:>4} м: {len(z):6,} конт | {z.area_km2.sum():7.1f} км² | flood_frac0>0.2: '
              f'{(z.flood_frac0 > 0.2).sum():6,} | hnd≤3: {(z.hnd_min <= 3).sum():6,}')
    log(f'сохранено в {QC2}')


if __name__ == '__main__':
    main()
