"""
BareSand — Расстояние до МОРЯ по береговой линии OSM (замена GSW-варианта 44).

Почему не GSW: локальный растр GSW обрезан по полигону AOI (суша) — море в нём есть
только там, где линия AOI случайно ушла в воду. GEE недоступен (квота). OSM land polygons
(osmdata.openstreetmap.de) дают точную береговую линию, губы тегированы как coastline.

Море = всё вне land-полигонов OSM. Отсечки «залив → река» по секторам долготы
(Обь 66.8°N, Таз/Пур 67.3°N, Енисей 69.7°N) — берег южнее отсечки считается речным
и в шаг 1 не идёт.

Для контуров прибрежной зоны (dist до границы AOI < COASTAL_ZONE_M, lat > 66°N):
  dist_sea_m — расстояние до морской береговой линии (EPSG:3576, м).

Выход (совместим с 45_step1_shoal_v2.py):
  exports/qc/sea_coastline.gpkg          — морская береговая линия (после отсечек)
  exports/qc/sea_shore_buffer.gpkg       — буфер SHORE_BUFFER_M от берега со стороны суши
  exports/qc/coastal_zone_evidence.gpkg/.csv

Запуск: python -u python/44b_sea_distance_osm.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import box, shape as shape_
from shapely.ops import unary_union

sys.stdout.reconfigure(encoding='utf-8')

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC = EXPORTS / 'qc'
LAND_SHP = EXPORTS / 'aux' / 'osm_land' / 'land-polygons-split-4326' / 'land_polygons.shp'
STEP1 = EXPORTS / 'baresand_genesis_step1.gpkg'
ATTRS = EXPORTS / 'baresand_littoral_v2.gpkg'
AOI = EXPORTS / 'aoi_v2.geojson'
OUT_COAST = QC / 'sea_coastline.gpkg'
OUT_SHORE = QC / 'sea_shore_buffer.gpkg'
OUT_GPKG = QC / 'coastal_zone_evidence.gpkg'
OUT_CSV = QC / 'coastal_zone_evidence.csv'

# v3: Обь — до 67.0°N (визуальная QC: OSM-берег идёт по реке до вершины дельты, 66.3–66.8°N — речные пески)
RIVER_CUTOFFS = [(-180.0, 74.0, 67.0), (74.0, 80.0, 67.3), (80.0, 180.0, 69.7)]
COASTAL_ZONE_M = 5000.0
COASTAL_LAT_MIN = 66.0
# v3: буфер по ОБЕ стороны линии (мокрый пляж лежит мористее OSM-линии) и шире — пляжи Ямала 500–2000 м
SHORE_BUFFER_M = 700.0
STRIP_M = 25_000.0          # полоса вокруг границы AOI, в которой режем land-полигоны
EA_CRS = 'EPSG:3576'
# Енисейский залив: западный берег 69.7–71.7°N в OSM не оттрассирован как coastline → берём из GSW
YENISEI_GSW_BOX = (80.0, 69.7, 84.8, 72.2)   # lon_min, lat_min, lon_max, lat_max (EPSG:4326)
GSW_PERM_OCC = 80
GSW = EXPORTS / 'gsw_occurrence_AOI.vrt'


def sea_coastline() -> tuple[gpd.GeoSeries, gpd.GeoDataFrame]:
    aoi = gpd.read_file(AOI).to_crs(EA_CRS)
    aoi_geom = aoi.geometry.union_all()
    strip = aoi_geom.boundary.buffer(STRIP_M)
    strip_wgs = gpd.GeoSeries([strip], crs=EA_CRS).to_crs('EPSG:4326').iloc[0]
    print('  читаю OSM land polygons в bbox полосы...', flush=True)
    land = gpd.read_file(LAND_SHP, bbox=tuple(strip_wgs.bounds)).to_crs(EA_CRS)
    print(f'  land-полигонов: {len(land):,}', flush=True)
    land_u = unary_union(land.geometry.values)
    coast = land_u.boundary.intersection(strip)
    # + Енисейский залив из GSW (OSM coastline там обрывается ~71.7°N)
    yen = yenisei_gulf_shoreline()
    if yen is not None and not yen.is_empty:
        coast = unary_union([coast, yen])
        print('  добавлен берег Енисейского залива из GSW')
    # v3: отсечки река/залив — ГЕОМЕТРИЧЕСКИ (вырезаем всё южнее lat_min в каждом секторе долготы),
    # а не по центроиду сегмента: длинный сегмент вдоль Оби с центроидом севернее отсечки раньше
    # целиком проходил в «море».
    south = []
    for lo, hi, lat_min in RIVER_CUTOFFS:
        b = box(max(lo, -179.9), 50.0, min(hi, 179.9), lat_min)
        south.append(b)
    south_u = gpd.GeoSeries(south, crs='EPSG:4326').segmentize(0.02).to_crs(EA_CRS).union_all()
    coast = coast.difference(south_u)
    coast = gpd.GeoSeries([coast], crs=EA_CRS).explode(index_parts=False).reset_index(drop=True)
    coast = coast[~coast.is_empty & (coast.length > 0)].reset_index(drop=True)
    print(f'  сегментов морской береговой линии: {len(coast):,}; длина {coast.length.sum()/1000:,.0f} км')
    gpd.GeoDataFrame(geometry=coast, crs=EA_CRS).to_file(OUT_COAST, layer='coastline', driver='GPKG')
    # v3: буфер берега ПО ОБЕ СТОРОНЫ линии (без пересечения с сушей OSM)
    shore = unary_union(coast.buffer(SHORE_BUFFER_M).values)
    shore_gdf = gpd.GeoDataFrame({'buffer_m': [SHORE_BUFFER_M]}, geometry=[shore], crs=EA_CRS)
    shore_gdf.to_file(OUT_SHORE, layer='shore_buffer', driver='GPKG')
    return coast, shore_gdf


def yenisei_gulf_shoreline():
    """Береговая линия Енисейского залива из локального GSW (постоянная вода, крупнейшая компонента в окне)."""
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.features import shapes
    from scipy import ndimage
    lon0, lat0, lon1, lat1 = YENISEI_GSW_BOX
    with rasterio.open(GSW) as src:
        win = from_bounds(lon0, lat0, lon1, lat1, transform=src.transform).round_offsets().round_lengths()
        occ = src.read(1, window=win, boundless=True, fill_value=0)
        tr = src.window_transform(win)
        crs = src.crs
    perm = occ >= GSW_PERM_OCC
    lab, n = ndimage.label(perm, structure=np.ones((3, 3)))
    if n == 0:
        return None
    sizes = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1))
    big = np.argmax(sizes) + 1
    gulf = lab == big
    polys = [shape_(g) for g, v in shapes(gulf.astype('uint8'), mask=gulf, transform=tr) if v == 1]
    g = gpd.GeoSeries(polys, crs=crs).to_crs(EA_CRS)
    return unary_union(g.values).boundary


def main() -> None:
    t0 = time.time()
    print('═══════════════════════════════════════')
    print('РАССТОЯНИЕ ДО МОРЯ (OSM coastline) — ПРИБРЕЖНАЯ ЗОНА')
    print('═══════════════════════════════════════')
    if not LAND_SHP.exists():
        print(f'!!! нет {LAND_SHP} — дождись распаковки OSM land polygons')
        sys.exit(1)
    coast, _ = sea_coastline()

    g = gpd.read_file(STEP1)   # EPSG:3576
    cen = g.geometry.centroid.set_crs(EA_CRS, allow_override=True).to_crs('EPSG:4326')
    g['lat'] = cen.y.round(4)
    g['lon'] = cen.x.round(4)
    g = g[(g['dist_aoi_boundary_m'] < COASTAL_ZONE_M) & (g['lat'] > COASTAL_LAT_MIN)].copy()
    attrs = gpd.read_file(ATTRS, ignore_geometry=True)[['id', 'hnd_min', 'upa_max', 'gsw_occ_mean',
                                                        'gsw_occ_max', 'gsw_seas_max']]
    g = g.merge(attrs, on='id', how='left', validate='1:1')
    print(f'  контуров в зоне: {len(g):,} | shoal по шагу 1: {(g.genesis == "shoal").sum():,}', flush=True)

    coast_gdf = gpd.GeoDataFrame(geometry=coast, crs=EA_CRS)
    near = gpd.sjoin_nearest(g[['id', 'geometry']], coast_gdf, how='left', distance_col='dist_sea_m')
    near = near.drop_duplicates('id')[['id', 'dist_sea_m']]
    g = g.merge(near, on='id', how='left')
    g['dist_sea_m'] = g['dist_sea_m'].round(0)

    cols = ['id', 'genesis', 'area_ha', 'area_km2', 'dist_aoi_boundary_m', 'lat', 'lon',
            'hnd_min', 'upa_max', 'gsw_occ_mean', 'gsw_occ_max', 'gsw_seas_max', 'dist_sea_m', 'geometry']
    g = g[cols]
    g.to_file(OUT_GPKG, layer='coastal', driver='GPKG')
    g.drop(columns='geometry').to_csv(OUT_CSV, index=False, encoding='utf-8')

    sh = g[g.genesis == 'shoal']
    un = g[g.genesis != 'shoal']
    print('')
    for thr in (30, 100, 300, 500, 1000):
        a = sh[sh.dist_sea_m <= thr]
        b = un[un.dist_sea_m <= thr]
        print(f'  dist_sea<={thr:>4} м: shoal-шага-1 {len(a):5,} ({a.area_km2.sum():6.1f} км²) | '
              f'вне класса {len(b):5,} ({b.area_km2.sum():6.1f} км²)')
    far = sh[sh.dist_sea_m > 500]
    print(f'  shoal шага 1 дальше 500 м от моря: {len(far):,} ({far.area_km2.sum():.1f} км²)')
    print(f'\nСохранено: {OUT_GPKG}\n           {OUT_COAST}\n           {OUT_SHORE}')
    print(f'Время: {(time.time()-t0)/60:.1f} мин')


if __name__ == '__main__':
    main()
