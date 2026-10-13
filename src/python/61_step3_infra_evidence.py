"""
61_step3_infra_evidence.py — улики шага 3 (антропоген) для остатка маски после шагов 1–2.

Вход:  exports/baresand_genesis_step2_v3_split.gpkg (genesis = unassigned: остаток, anthro_suspect, сухие части разреза)
       exports/osm/osm_infra_AOI.gpkg (60_step3_osm_extract.py), exports/landsat_1985_brightness.vrt (30 м)
Улики (EPSG:3576):
  OSM:   d_road_major/minor/track/any, d_rail, d_linear (трубопроводы/ЛЭП/аэродромы), d_industrial (промплощадки, карьеры),
         d_building, d_place (+ place_type, place_pop) — расстояния до ближайшего объекта, м (cap DIST_CAP_M);
         osm_overlap — доля площади контура внутри «следа» инфраструктуры (промполигоны ∪ здания ∪ буферы дорог/ж.д./линий)
  Форма: compact = 4πA/P², rect = A / A(мин. описанный прямоугольник), elong = длина/ширина прямоугольника,
         convex = A / A(выпуклая оболочка), ero15 = A(buffer −15 м)/A (тонкость: дороги → 0), nv_km — вершин упрощённого
         (8 м) контура на км периметра (правильные формы — мало вершин)
  1985:  l85_mean, l85_dark_frac (яркость < L85_DARK — растительность/вода в 1985: песок появился позже),
         l85_bright_frac (≥ L85_BRIGHT — светлая поверхность в 1985: песок или лишайник). Порог яркости песка не
         разделяет песок и лишайниковую тундру (фон p75 = 2050, p90 = 2460) — A0 только как подтверждение.
  Сеть:  d_net — расстояние до ближайшей сети дорог (anthro_suspect) или «далёкой» сухой части разреза шага 2.
Выход: exports/qc/step3/step3_evidence.csv (по id), чекпоинты по блокам.
Запуск: python -u python/61_step3_infra_evidence.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio.features import rasterize
from scipy import ndimage
from shapely.strtree import STRtree

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC3 = EXPORTS / 'qc' / 'step3'
SRC = EXPORTS / 'baresand_genesis_step2_v3_split.gpkg'
OSM = EXPORTS / 'osm' / 'osm_infra_AOI.gpkg'
L85 = EXPORTS / 'landsat_1985_brightness.vrt'
OUT = QC3 / 'step3_evidence.csv'
EA_CRS = 'EPSG:3576'

DIST_CAP_M = 5000.0
ROAD_BUF_M = {'major': 25.0, 'minor': 15.0, 'track': 12.0, 'path': 5.0, 'other': 12.0}
RAIL_BUF_M = 15.0
LINEAR_BUF_M = 25.0
L85_DARK = 1700.0
L85_BRIGHT = 2300.0
SIMPLIFY_M = 8.0
ERO_M = 15.0


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def nearest_dist(tree: STRtree, geoms: np.ndarray, cap: float = DIST_CAP_M) -> np.ndarray:
    """Расстояние до ближайшего объекта дерева (м), cap если дальше."""
    d = np.full(len(geoms), cap, dtype='float32')
    if len(tree.geometries) == 0:
        return d
    idx, dist = tree.query_nearest(geoms, max_distance=cap, return_distance=True, all_matches=False)
    d[idx[0]] = dist
    return d


def overlap_frac(geoms: np.ndarray, foot: np.ndarray) -> np.ndarray:
    """Доля площади контура внутри объединения «следов» (по пересекающимся парам; перекрытия следов режутся cap=1)."""
    frac = np.zeros(len(geoms), dtype='float32')
    if len(foot) == 0:
        return frac
    tree = STRtree(foot)
    ci, fi = tree.query(geoms, predicate='intersects')
    if len(ci) == 0:
        return frac
    inter = shapely.area(shapely.intersection(geoms[ci], foot[fi]))
    s = np.bincount(ci, weights=inter, minlength=len(geoms))
    frac[:] = np.minimum(s / shapely.area(geoms), 1.0)
    return frac


def main() -> None:
    t0 = time.time()
    QC3.mkdir(parents=True, exist_ok=True)
    log('читаю остаток маски...')
    g = gpd.read_file(SRC, where="genesis = 'unassigned'").to_crs(EA_CRS).reset_index(drop=True)
    geoms = g.geometry.values
    log(f'контуров: {len(g):,} | {g.area_km2.sum():.0f} км²')
    ev = pd.DataFrame({'id': g['id'].values})

    # ── форма ──
    log('морфометрия...')
    area = shapely.area(geoms)
    perim = shapely.length(geoms)
    mrr = shapely.minimum_rotated_rectangle(geoms)
    mrr_area = shapely.area(mrr)
    # стороны описанного прямоугольника: по первым трём вершинам внешнего кольца (5 точек); вырожденные (линия/точка) — по bounds
    is_poly = shapely.get_type_id(mrr) == 3
    long = np.zeros(len(geoms)); short = np.zeros(len(geoms))
    pts = shapely.get_coordinates(shapely.get_exterior_ring(mrr[is_poly])).reshape(-1, 5, 2)
    s1 = np.hypot(*(pts[:, 1] - pts[:, 0]).T); s2 = np.hypot(*(pts[:, 2] - pts[:, 1]).T)
    long[is_poly], short[is_poly] = np.maximum(s1, s2), np.minimum(s1, s2)
    if (~is_poly).any():
        b = shapely.bounds(mrr[~is_poly])
        long[~is_poly] = np.maximum(b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]); short[~is_poly] = 0
    ev['area_ha'] = area / 1e4
    ev['compact'] = np.where(perim > 0, 4 * np.pi * area / perim ** 2, 0)
    ev['rect'] = np.where(mrr_area > 0, area / mrr_area, 0)
    ev['elong'] = np.where(short > 0, long / short, 99)
    ev['mrr_short_m'] = short
    ev['mrr_long_m'] = long
    ev['convex'] = area / shapely.area(shapely.convex_hull(geoms))
    ev['ero15'] = shapely.area(shapely.buffer(geoms, -ERO_M)) / area
    nv = shapely.get_num_coordinates(shapely.simplify(geoms, SIMPLIFY_M))
    ev['nv_km'] = nv / np.maximum(perim / 1000, 1e-3)
    cen = shapely.centroid(geoms)
    ev.to_csv(QC3 / 'step3_evidence_shape.csv', index=False)
    log('  форма готова (чекпоинт)')

    # ── OSM ──
    log('OSM: расстояния...')
    roads = gpd.read_file(OSM, layer='roads')
    rail = gpd.read_file(OSM, layer='rail')
    linear = gpd.read_file(OSM, layer='linear')
    ind = gpd.read_file(OSM, layer='industrial')
    bld = gpd.read_file(OSM, layer='buildings')
    places = gpd.read_file(OSM, layer='places')
    log(f'  roads {len(roads):,} | rail {len(rail):,} | linear {len(linear):,} | industrial {len(ind):,} | buildings {len(bld):,} | places {len(places):,}')
    for cls in ('major', 'minor', 'track'):
        ev[f'd_road_{cls}'] = nearest_dist(STRtree(roads.loc[roads['cls'] == cls, 'geometry'].values), geoms)
    ev['d_road_any'] = nearest_dist(STRtree(roads.loc[roads['cls'] != 'path', 'geometry'].values), geoms)
    ev['d_rail'] = nearest_dist(STRtree(rail.geometry.values), geoms)
    ev['d_linear'] = nearest_dist(STRtree(linear.geometry.values), geoms)
    ev['d_industrial'] = nearest_dist(STRtree(ind.geometry.values), geoms)
    ev['d_building'] = nearest_dist(STRtree(bld.geometry.values), geoms)
    ptree = STRtree(places.geometry.values)
    pi, pd_ = ptree.query_nearest(cen, max_distance=50000, return_distance=True, all_matches=False)
    ev['d_place'] = 50000.0
    ev.loc[pi[0], 'd_place'] = pd_
    ev['place_type'] = ''
    ev.loc[pi[0], 'place_type'] = places['place'].values[pi[1]]
    ev['place_pop'] = np.nan
    ev.loc[pi[0], 'place_pop'] = places['population'].values[pi[1]]
    log('OSM: доля площади в следе инфраструктуры...')
    foot = [shapely.buffer(roads.loc[roads['cls'] == c, 'geometry'].values, w) for c, w in ROAD_BUF_M.items() if c != 'path']
    foot += [shapely.buffer(rail.geometry.values, RAIL_BUF_M), shapely.buffer(linear.geometry.values, LINEAR_BUF_M),
             ind.geometry.values, bld.geometry.values]
    foot = np.concatenate([f for f in foot if len(f)])
    ev['osm_overlap'] = overlap_frac(geoms, foot)
    ev.to_csv(QC3 / 'step3_evidence_osm.csv', index=False)
    log('  OSM готов (чекпоинт)')

    # ── сеть anthro_suspect / далёкие сухие части ──
    net = g[(g['anthro_suspect'] == 1) | (g['part_kind'].fillna('') == 'far')]
    ev['d_net'] = nearest_dist(STRtree(net.geometry.values), geoms)
    ev['is_net'] = ((g['anthro_suspect'] == 1) | (g['part_kind'].fillna('') == 'far')).astype('int8').values
    ev['is_dry_part'] = g['step2_rule'].fillna('').str.contains('split_dry|whole_dry').astype('int8').values

    # ── Landsat 1985 ──
    log('Landsat-1985: читаю растр...')
    with rasterio.open(L85) as src:
        l85 = src.read(1)
        ltr, lcrs = src.transform, src.crs
    valid = l85 > 0
    dark = (l85 < L85_DARK) & valid
    bright = l85 >= L85_BRIGHT
    log('Landsat-1985: растеризация контуров...')
    g30 = g.to_crs(lcrs)
    lab = rasterize(((geom, i + 1) for i, geom in enumerate(g30.geometry)), out_shape=l85.shape, transform=ltr,
                    fill=0, all_touched=True, dtype='uint32')
    idx = np.arange(1, len(g) + 1, dtype='uint32')
    cnt = ndimage.sum(valid.astype('uint8'), lab, index=idx)
    ev['l85_mean'] = np.round(np.where(cnt > 0, ndimage.sum(np.where(valid, l85, 0), lab, index=idx) / np.maximum(cnt, 1), np.nan), 0)
    del l85
    ev['l85_dark_frac'] = np.round(np.where(cnt > 0, ndimage.sum(dark.astype('uint8'), lab, index=idx) / np.maximum(cnt, 1), np.nan), 3)
    ev['l85_bright_frac'] = np.round(np.where(cnt > 0, ndimage.sum(bright.astype('uint8'), lab, index=idx) / np.maximum(cnt, 1), np.nan), 3)
    del lab, dark, bright, valid

    cen_ll = gpd.GeoSeries(cen, crs=EA_CRS).to_crs('EPSG:4326')
    ev['lat'], ev['lon'] = cen_ll.y.round(4).values, cen_ll.x.round(4).values
    for c in ('genesis', 'step2_rule', 'anthro_suspect', 'part_kind', 'parent_id', 'dist_sea_m', 'dist_water_m', 'flood_frac0'):
        if c in g.columns:
            ev[c] = g[c].values
    ev.to_csv(OUT, index=False, encoding='utf-8')
    log(f'сохранено {OUT} | {(time.time() - t0) / 60:.1f} мин')
    print(ev[['d_road_any', 'd_industrial', 'osm_overlap', 'rect', 'ero15', 'l85_dark_frac']].describe().round(2).to_string())


if __name__ == '__main__':
    main()
