"""
80_step4_evidence.py — улики шага 4 (эоловый / неопределённый) для остатка после шага 3.

Вход:  exports/baresand_genesis_step3_v4e.gpkg (genesis = 'unassigned' — остаток 412 тыс. контуров со всеми уликами шагов 2–3),
       exports/baresand_genesis_step2_v3_split.gpkg (тип ближайшего водоёма, русловая сеть, сезонность GSW).
Считает (DNA §6.5.4, E2/E3):
  n_nb_2km, area_nb_2km_ha — число и площадь других контуров остатка в радиусе 2 км (кластерность: дефляционное поле) — по растру
                              плотности центроидов 250 м, круговое окно R = 2 км (FFT-свёртка);
  dist_big_m, big_id        — расстояние до ближайшего контура остатка ≥ BIG_HA (5 га) и его id (наследование метки мелочью < 1 га);
  mrr_az, orient_ok         — азимут длинной оси описанного прямоугольника (0–180°) и попадание в сектор ветров W–E … NW–SE
                              (ORIENT_SECTOR), только при elong ≥ ELONG_MIN;
  nearest_type, dist_channel_m, comp_area_km2, comp_upa_km2, gsw_seas_max — из шага 2 (для частей — по parent_id).
Выход: exports/qc/step4/step4_evidence.csv (id, area_ha, lat, lon + новые колонки; остальные улики берутся из продукта v4e в 81).
Запуск: python -u python/80_step4_evidence.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.signal import fftconvolve
from shapely.strtree import STRtree

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC4 = EXPORTS / 'qc' / 'step4'
SRC = EXPORTS / 'baresand_genesis_step3_v4e.gpkg'
SRC2 = EXPORTS / 'baresand_genesis_step2_v3_split.gpkg'
OUT = QC4 / 'step4_evidence.csv'
EA_CRS = 'EPSG:3576'
CELL_M = 250.0
R_CLUSTER_M = 2000.0
BIG_HA = 5.0
D_BIG_CAP_M = 5000.0
ELONG_MIN = 1.5
ORIENT_SECTOR = (80.0, 160.0)      # азимут длинной оси (0–180, от севера по часовой): W–E = 90°, NW–SE = 135°
STEP2_COLS = ['nearest_type', 'dist_channel_m', 'comp_area_km2', 'comp_upa_km2', 'gsw_seas_max']


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def cluster_density(x: np.ndarray, y: np.ndarray, w: np.ndarray, cell: float, r: float) -> np.ndarray:
    """Сумма весов w других точек в круге радиуса r вокруг каждой точки (растр cell м, FFT-свёртка с диском)."""
    x0, y0 = x.min() - r - cell, y.min() - r - cell
    ix = ((x - x0) // cell).astype(int)
    iy = ((y - y0) // cell).astype(int)
    grid = np.zeros((iy.max() + int(r // cell) + 2, ix.max() + int(r // cell) + 2), dtype='float32')
    np.add.at(grid, (iy, ix), w.astype('float32'))
    k = int(np.ceil(r / cell))
    yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
    disk = ((xx ** 2 + yy ** 2) * cell ** 2 <= r ** 2).astype('float32')
    conv = fftconvolve(grid, disk, mode='same')
    return np.maximum(conv[iy, ix] - w, 0.0)          # без самого контура


def main() -> None:
    t0 = time.time()
    QC4.mkdir(parents=True, exist_ok=True)
    log('читаю остаток шага 3...')
    g = gpd.read_file(SRC, columns=['id', 'parent_id', 'area_ha', 'elong'], where="genesis = 'unassigned'").to_crs(EA_CRS)
    log(f'  {len(g):,} контуров, {g.area_ha.sum() / 100:,.0f} км²')
    geoms = g.geometry.values
    cen = shapely.centroid(geoms)
    x, y = shapely.get_x(cen), shapely.get_y(cen)
    ll = gpd.GeoSeries(cen, crs=EA_CRS).to_crs('EPSG:4326')
    ev = pd.DataFrame({'id': g['id'].values, 'area_ha': g['area_ha'].values, 'lat': ll.y.round(4).values, 'lon': ll.x.round(4).values})

    log('кластерность (растр 250 м, круг 2 км)...')
    ev['n_nb_2km'] = np.rint(cluster_density(x, y, np.ones(len(g)), CELL_M, R_CLUSTER_M)).astype('int32')
    ev['area_nb_2km_ha'] = cluster_density(x, y, g['area_ha'].values, CELL_M, R_CLUSTER_M).round(2)

    log(f'ближайший крупный контур (≥ {BIG_HA:.0f} га)...')
    big = g['area_ha'].values >= BIG_HA
    tree = STRtree(geoms[big])
    big_ids = g['id'].values[big]
    idx, dist = tree.query_nearest(geoms, max_distance=D_BIG_CAP_M, return_distance=True, exclusive=True, all_matches=False)
    ev['dist_big_m'] = np.float32(D_BIG_CAP_M)
    ev['big_id'] = -1
    ev.loc[idx[0], 'dist_big_m'] = dist.astype('float32')
    ev.loc[idx[0], 'big_id'] = big_ids[idx[1]]
    log(f'  крупных {int(big.sum()):,}; мелких с крупным соседом ≤ 2 км: {int(((ev.dist_big_m <= 2000) & (ev.area_ha < 1)).sum()):,} из {int((ev.area_ha < 1).sum()):,}')

    log('ориентация длинной оси (описанный прямоугольник)...')
    env = shapely.oriented_envelope(geoms)
    coords, cidx = shapely.get_coordinates(env, return_index=True)
    az = np.full(len(g), np.nan, dtype='float32')
    counts = np.bincount(cidx, minlength=len(g))
    ok = counts == 5
    first = np.zeros(len(g), dtype=int)
    first[1:] = np.cumsum(counts)[:-1]
    p0, p1, p2 = coords[first[ok]], coords[first[ok] + 1], coords[first[ok] + 2]
    s1, s2 = p1 - p0, p2 - p1
    l1, l2 = np.hypot(s1[:, 0], s1[:, 1]), np.hypot(s2[:, 0], s2[:, 1])
    longside = np.where((l1 >= l2)[:, None], s1, s2)
    a = np.degrees(np.arctan2(longside[:, 0], longside[:, 1])) % 180.0      # от севера по часовой, ось — mod 180
    az[ok] = a
    ev['mrr_az'] = np.round(az, 1)
    el = g['elong'].fillna(1.0).values
    orient = (az >= ORIENT_SECTOR[0]) & (az <= ORIENT_SECTOR[1]) & (el >= ELONG_MIN)
    ev['orient_ok'] = np.where(el >= ELONG_MIN, orient.astype('int8'), -1)          # -1 = ось не определена (компактный контур)
    log(f'  вытянутых (elong ≥ {ELONG_MIN}): {int((el >= ELONG_MIN).sum()):,}, из них в секторе ветров: {int(orient.sum()):,} ({100 * orient.sum() / max(1, (el >= ELONG_MIN).sum()):.0f} %)')

    log('поля шага 2 (тип водоёма, русло, сезонность GSW)...')
    s2 = gpd.read_file(SRC2, columns=['id'] + STEP2_COLS, read_geometry=False)
    s2 = s2.set_index('id')
    key = np.where(ev['id'].isin(s2.index), ev['id'], g['parent_id'].fillna(-1).astype(int).values)
    m = s2.reindex(key)
    for c in STEP2_COLS:
        ev[c] = m[c].values
    log(f'  найдено по id/parent_id: {int(ev["nearest_type"].notna().sum()):,} из {len(ev):,}')

    ev.to_csv(OUT, index=False, encoding='utf-8')
    log(f'сохранено {OUT} | {(time.time() - t0) / 60:.1f} мин')
    print(ev[['n_nb_2km', 'area_nb_2km_ha', 'dist_big_m', 'mrr_az']].describe(percentiles=[.1, .5, .9]).round(1).to_string())
    print('nearest_type:', ev['nearest_type'].value_counts(dropna=False).to_dict())


if __name__ == '__main__':
    main()
