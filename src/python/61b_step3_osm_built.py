"""
61b_step3_osm_built.py — уточнение OSM-улик шага 3 по итогам QC итерации 1: только построенные дороги.

Проблема: highway=track / winter_road / path в OSM — зимники и колеи без полотна; в тундре Ямала они дают d_road_any = 0
у природных раздувов и ложный «след» у мелочи (страты road_small 55%, near_new 74%, adjacent). Одновременно OSM-линия
насыпной дороги смещена от полотна на 20–30 м — буфер 12–25 м не покрывает обочины (одна дорога рвётся на «техноген»/«природа»).

Считает по остатку (те же контуры, что в 61):
  d_road_built     — расстояние до построенной дороги (major/minor/other, без track/path), м, cap DIST_CAP_M
  osm_overlap_built — доля площади в следе: промполигоны ∪ здания ∪ буферы построенных дорог (major BUF_MAJOR, minor/other
                      BUF_MINOR) ∪ ж.д. ∪ линии (трубопроводы/ЛЭП/аэродромы)
  track_touch      — доля площади в буфере колей/зимников (BUF_TRACK) — отдельный слабый признак
Выход: колонки добавляются в exports/qc/step3/step3_evidence.csv (перезапись файла).
Запуск: python -u python/61b_step3_osm_built.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.strtree import STRtree

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC3 = EXPORTS / 'qc' / 'step3'
SRC = EXPORTS / 'baresand_genesis_step2_v3_split.gpkg'
OSM = EXPORTS / 'osm' / 'osm_infra_AOI.gpkg'
EVID = QC3 / 'step3_evidence.csv'
EA_CRS = 'EPSG:3576'
DIST_CAP_M = 5000.0
BUF_MAJOR, BUF_MINOR, BUF_TRACK, BUF_RAIL, BUF_LINEAR = 40.0, 30.0, 12.0, 20.0, 25.0
BUILT = ('major', 'minor', 'other')


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def nearest_dist(tree: STRtree, geoms, cap: float = DIST_CAP_M) -> np.ndarray:
    d = np.full(len(geoms), cap, dtype='float32')
    if len(tree.geometries):
        idx, dist = tree.query_nearest(geoms, max_distance=cap, return_distance=True, all_matches=False)
        d[idx[0]] = dist
    return d


def overlap_frac(geoms, foot) -> np.ndarray:
    frac = np.zeros(len(geoms), dtype='float32')
    if len(foot) == 0:
        return frac
    ci, fi = STRtree(foot).query(geoms, predicate='intersects')
    if len(ci):
        inter = shapely.area(shapely.intersection(geoms[ci], foot[fi]))
        frac[:] = np.minimum(np.bincount(ci, weights=inter, minlength=len(geoms)) / shapely.area(geoms), 1.0)
    return frac


def main() -> None:
    t0 = time.time()
    ev = pd.read_csv(EVID)
    log('читаю остаток маски...')
    g = gpd.read_file(SRC, where="genesis = 'unassigned'", columns=['id']).to_crs(EA_CRS)
    g = g.set_index('id').loc[ev['id'].values]                      # тот же порядок, что в evidence
    geoms = g.geometry.values
    roads = gpd.read_file(OSM, layer='roads')
    rail = gpd.read_file(OSM, layer='rail')
    linear = gpd.read_file(OSM, layer='linear')
    ind = gpd.read_file(OSM, layer='industrial')
    bld = gpd.read_file(OSM, layer='buildings')
    built = roads[roads['cls'].isin(BUILT)]
    tracks = roads[roads['cls'] == 'track']
    log(f'построенных дорог: {len(built):,} | колей/зимников: {len(tracks):,}')
    ev['d_road_built'] = nearest_dist(STRtree(built.geometry.values), geoms)
    foot = [shapely.buffer(built.loc[built['cls'] == 'major', 'geometry'].values, BUF_MAJOR),
            shapely.buffer(built.loc[built['cls'] != 'major', 'geometry'].values, BUF_MINOR),
            shapely.buffer(rail.geometry.values, BUF_RAIL), shapely.buffer(linear.geometry.values, BUF_LINEAR),
            ind.geometry.values, bld.geometry.values]
    ev['osm_overlap_built'] = overlap_frac(geoms, np.concatenate([f for f in foot if len(f)]))
    ev['track_touch'] = overlap_frac(geoms, shapely.buffer(tracks.geometry.values, BUF_TRACK))
    ev.to_csv(EVID, index=False, encoding='utf-8')
    log(f'сохранено {EVID.name}: d_road_built ≤150: {(ev.d_road_built <= 150).sum():,} (было d_road_any: {(ev.d_road_any <= 150).sum():,}); '
        f'overlap_built ≥0.3: {(ev.osm_overlap_built >= 0.3).sum():,} (было {(ev.osm_overlap >= 0.3).sum():,}); track_touch>0: {(ev.track_touch > 0).sum():,} | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
