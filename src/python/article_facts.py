"""
article_facts.py - воспроизводимый расчёт эмпирических показателей для научной переработки статьи
по итоговому слою exports/final/baresand_genesis_v7b.gpkg (СК EPSG:3576).

Скрипт вычисляет и сверяет со сводками stats_v7.md, table_districts_v7.md и cadastre_v7b:
1. Контрольные суммы продукта v7b по классам, размерным группам и широтным поясам.
2. Показатели оголённых песков в границах нефтегазовых месторождений (oilfields/Efield_region.shp и сверка
   с Field_region.shp): охват покрытием 128 тайлов, отсутствие двойного счёта через объединение полигонов (union_all),
   распределение внутри и вне месторождений, рейтинги Топ-15 по площади и удельной доле, сравнение со статьёй 2022 г.
3. Разбивку эоловых и техногенных песков по физико-географическим субрегионам (ареалам), удалённость от гидросети,
   распределение по абсолютным высотам (ортометрическая ЦМР ALOS AW3D30 v4.1 / MERIT Hydro и эллипсоидальная ArcticDEM)
   в сравнении с гипсометрией всего покрытия, а также квантили относительного превышения (h_local600, h_local1200, h_chan).
4. Порайонные площади, доли в классе и удельные плотности (% от покрытой площади района) в сравнении с табл. 1 2022 г.
5. Анатомию техногенной нарушенности по операционному слою отводов ЕГРН (редакция v7b) и возрастной срез (age2000 по
   Hansen GFC 2000 г., Landsat 1984–1995 гг., Sentinel-2 2017–2019 гг.) по районам, широтам и природным зонам.

Запуск:
    PYTHONIOENCODING=utf-8 python -u python/article_facts.py
"""
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
from rasterio.features import rasterize
from rasterio.windows import Window, from_bounds
import shapely

# ════════════════════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ И ПУТИ (без хардкода в теле функций)
# ════════════════════════════════════════════════════════════════════════════

ROOT = Path(r'D:\test\baresand_zapsib')
WIN_AUX_PREFIX = r'\\?\D:\test\baresand_zapsib\exports\aux'

PRODUCT_GPKG = ROOT / 'exports' / 'final' / 'baresand_genesis_v7b.gpkg'
CADASTRE_GPKG = ROOT / 'exports' / 'final' / 'baresand_anthro_cadastre_v7b.gpkg'
AOI_GEOJSON = ROOT / 'exports' / 'aoi_v2.geojson'
COVERAGE_GPKG = Path(WIN_AUX_PREFIX) / 'coverage_tiles.gpkg'
ADMIN_GPKG = Path(WIN_AUX_PREFIX) / 'admin6_aoi.gpkg'

EFIELD_SHP = ROOT / 'oilfields' / 'Efield_region.shp'
FIELD_SHP = ROOT / 'oilfields' / 'Field_region.shp'

BASELEVEL_CSV = ROOT / 'exports' / 'qc' / 'dem' / 'baselevel_compare.csv'
DEM_MASS_CSV = ROOT / 'exports' / 'qc' / 'dem' / 'dem_evidence_mass.csv'

LOCAL_AW3D30_TIF = Path(r'E:\DEM\AW3D30\AW3D30_v41.tif')
LOCAL_ARCTICDEM_TIF = Path(r'E:\DEM\ArcticDEM\ArcticDEM_10m.tif')
LOCAL_TANDEM_TIF = Path(r'E:\DEM\TanDEM\TanDEM_X_30m.tif')

TARGET_CRS = 3576
CITY_BUFFER_M = 50.0
EAST_SECTOR_LON = 79.0
DEM_NODATA_FLOOR = -1000.0
AW3D_OVERVIEW_LEVEL = 4
ARCTICDEM_OVERVIEW_LEVEL = 4

# Пороги геоморфологического районирования и анализа
YAMAL_NORTH_LAT = 70.0          # рубеж озёр Нейто и Ямбуто (Сизов, Лобжанидзе, 2022)
YAMAL_CENTRAL_MIN_LAT = 67.5    # южная граница центрально-ямальского ареала (оз. Яррото – Щукинская возв.)
TAZ_PENINSULA_MIN_LAT = 67.45   # основание Тазовского п-ова между Обской и Тазовской губами
TAZ_PENINSULA_MAX_LAT = 69.20   # мыс Поворотный / выход в Обскую губу
TAZ_PENINSULA_MIN_LON = 73.30   # восточный берег Обской губы
TAZ_PENINSULA_MAX_LON = 78.20   # западный берег Тазовской губы
GYDAN_MIN_LAT = 68.35           # южный рубеж Гыданского п-ова восточнее Тазовской губы
HYDRO_BUFFER_2022_M = 500.0     # буфер 500 м от воды, русел и моря (стр. 28 статьи 2022 г.)
TERRACE_CHANNEL_DIST_M = 2000.0 # приречно-террасовая зона относительно русел MERIT
LINEAR_INFRA_DIST_M = 100.0     # буфер примыкания к дорогам / линейным объектам OSM

ELEV_BINS = [-np.inf, 0, 10, 20, 30, 45, 60, 80, 100, 150, np.inf]
ELEV_LABELS = ['< 0 м', '0–10 м', '10–20 м', '20–30 м', '30–45 м', '45–60 м', '60–80 м', '80–100 м', '100–150 м', '>= 150 м']
QUANTILES = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]

# Справочные данные статьи 2022 г. (Сизов, Лобжанидзе, 2022, табл. 1–3)
DISTRICTS_2022_NAT = {
    'Ямальский': (1203.07, 62.58, 1.02),
    'Надымский': (255.24, 13.28, 0.26),
    'Тазовский': (223.83, 11.64, 0.17),
    'Пуровский': (190.28, 9.90, 0.18),
    'Усть-Енисейский + Долгано-Ненецкий': (26.41, 1.38, 0.03),
    'Приуральский': (19.50, 1.01, 0.03),
    'Туруханский': (3.34, 0.17, 0.00),
    'Красноселькупский': (0.81, 0.04, 0.00),
    'Шурышкарский': (0.05, 0.00, 0.00),
    'Белоярский': (0.00, 0.00, 0.00),
    'Нижневартовский': (0.00, 0.00, 0.00),
    'Сургутский': (0.00, 0.00, 0.00),
}
DISTRICTS_2022_ANT = {
    'Пуровский': (201.02, 67.45, 0.19),
    'Надымский': (30.25, 10.15, 0.03),
    'Тазовский': (28.30, 9.50, 0.02),
    'Ямальский': (18.68, 6.27, 0.02),
    'Красноселькупский': (7.91, 2.65, 0.01),
    'Туруханский': (5.70, 1.91, 0.00),
    'Усть-Енисейский + Долгано-Ненецкий': (4.83, 1.63, 0.00),
    'Нижневартовский': (0.91, 0.30, 0.00),
    'Приуральский': (0.37, 0.13, 0.00),
    'Сургутский': (0.05, 0.02, 0.00),
    'Белоярский': (0.00, 0.00, 0.00),
    'Шурышкарский': (0.00, 0.00, 0.00),
}

REF_FIELDS_2022 = {
    'Уренгойское': {'nat_ha': 1914.31, 'ant_ha': 3458.38, 'nat_pct': None, 'ant_pct': None},
    'Западно-Тамбейское': {'nat_ha': 1623.09, 'ant_ha': None, 'nat_pct': 4.82, 'ant_pct': None},
    'Малоямальское': {'nat_ha': 1229.31, 'ant_ha': None, 'nat_pct': 2.63, 'ant_pct': None},
    'Западно-Сеяхинское': {'nat_ha': 1177.77, 'ant_ha': None, 'nat_pct': 2.17, 'ant_pct': None},
    'Ямбургское': {'nat_ha': 1012.03, 'ant_ha': 703.00, 'nat_pct': None, 'ant_pct': None},
    'Суторминское': {'nat_ha': 888.55, 'ant_ha': 2120.03, 'nat_pct': 1.36, 'ant_pct': 3.24},
    'Утреннее': {'nat_ha': 699.70, 'ant_ha': None, 'nat_pct': None, 'ant_pct': None},
    'Малыгинское': {'nat_ha': 614.71, 'ant_ha': None, 'nat_pct': None, 'ant_pct': None},
    'Восточно-Таркосалинское': {'nat_ha': 563.60, 'ant_ha': 629.97, 'nat_pct': None, 'ant_pct': None},
    'Тасийское': {'nat_ha': 540.69, 'ant_ha': None, 'nat_pct': 1.19, 'ant_pct': None},
    'Южно-Тамбейское': {'nat_ha': 438.19, 'ant_ha': None, 'nat_pct': None, 'ant_pct': None},
    'Штормовое': {'nat_ha': 359.55, 'ant_ha': None, 'nat_pct': None, 'ant_pct': None},
    'Вынгаяхинское': {'nat_ha': None, 'ant_ha': 802.79, 'nat_pct': None, 'ant_pct': 2.07},
    'Сугмутское': {'nat_ha': None, 'ant_ha': 568.47, 'nat_pct': None, 'ant_pct': None},
    'Бованенковское': {'nat_ha': None, 'ant_ha': 549.48, 'nat_pct': None, 'ant_pct': None},
    'Русское': {'nat_ha': None, 'ant_ha': 525.46, 'nat_pct': None, 'ant_pct': 1.64},
    'Вынгапуровское': {'nat_ha': None, 'ant_ha': 523.98, 'nat_pct': None, 'ant_pct': None},
    'Комсомольское': {'nat_ha': None, 'ant_ha': 522.07, 'nat_pct': None, 'ant_pct': None},
    'Муравленковское': {'nat_ha': None, 'ant_ha': 517.87, 'nat_pct': None, 'ant_pct': 1.76},
    'Еты-Пуровское': {'nat_ha': None, 'ant_ha': 509.85, 'nat_pct': None, 'ant_pct': None},
    'Сандибинское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': 1.51, 'ant_pct': 3.56},
    'Трехбугорное': {'nat_ha': None, 'ant_ha': None, 'nat_pct': 2.35, 'ant_pct': None},
    'Усть-Юрибейское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': 1.65, 'ant_pct': None},
    'Пайсятское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': 1.58, 'ant_pct': None},
    'Северо-Пуровское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': 1.33, 'ant_pct': None},
    'Верхнетиутейское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': 0.97, 'ant_pct': None},
    'Сядорское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': 0.96, 'ant_pct': None},
    'Апакопурское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': None, 'ant_pct': 2.82},
    'Чатылькинское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': None, 'ant_pct': 2.23},
    'Барсуковское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': None, 'ant_pct': 2.21},
    'Северо-Янгтинское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': None, 'ant_pct': 2.02},
    'Спорышевское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': None, 'ant_pct': 1.93},
    'Новопурпейское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': None, 'ant_pct': 1.84},
    'Ево-Яхинское': {'nat_ha': None, 'ant_ha': None, 'nat_pct': None, 'ant_pct': 1.52},
}


# ════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ════════════════════════════════════════════════════════════════════════════

def weighted_quantiles(values: np.ndarray, weights: np.ndarray, qs: list[float]) -> np.ndarray:
    """Взвешенные по площади квантили."""
    mask = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not mask.any():
        return np.full(len(qs), np.nan)
    v = values[mask]
    w = weights[mask]
    order = np.argsort(v)
    v = v[order]
    w = w[order]
    cw = np.cumsum(w) - 0.5 * w
    cw /= w.sum()
    return np.interp(qs, cw, v)


def clean_efield_name(row: pd.Series) -> str:
    """Восстановление русского названия месторождения в Efield_region.shp (7 записей в UTF-8 внутри cp1251)."""
    nr = row.get('Name_Russ')
    if isinstance(nr, str) and nr.strip():
        try:
            return nr.encode('cp1251').decode('utf-8').strip()
        except UnicodeError:
            return nr.strip()
    n1 = row.get('NUMBER_1')
    return str(n1).strip() if pd.notna(n1) else f"ID_{row['NUMBER']}"


def load_admin_districts(cov_geom) -> tuple[gpd.GeoDataFrame, dict[str, str]]:
    """Загрузка районов OSM admin_level=6 и присоединение городских округов к районам с наибольшей общей границей."""
    adm = gpd.read_file(ADMIN_GPKG, layer='admin')
    d6 = adm[(adm['admin_level'].astype(str) == '6') & adm['name'].notna()].to_crs(TARGET_CRS)
    d6 = d6.dissolve(by='name').reset_index()
    d6['geometry'] = shapely.make_valid(d6.geometry)
    is_city = d6['name'].str.startswith('городской округ')
    host = {}
    for _, cty in d6[is_city].iterrows():
        best, blen = None, 0.0
        for _, dst in d6[~is_city].iterrows():
            ln = cty.geometry.boundary.intersection(dst.geometry.buffer(CITY_BUFFER_M)).length
            if ln > blen:
                best, blen = dst['name'], ln
        host[cty['name']] = best
    d6['district'] = [host.get(n, n) for n in d6['name']]
    d6['area_cov_km2'] = d6.geometry.intersection(cov_geom).area / 1e6
    return d6, host


def assign_subregion(district: str | float, lon: float, lat: float) -> str:
    """Разнесение контуров по 8 непересекающимся физико-географическим субрегионам (ареалам)."""
    d_str = district if isinstance(district, str) else ''
    # 1. Полуостров Ямал (Ямальский район)
    if 'Ямальский' in d_str:
        if lat >= YAMAL_NORTH_LAT:
            return '1а. П-ов Ямал: северный ареал (>= 70° с. ш.)'
        if lat >= YAMAL_CENTRAL_MIN_LAT:
            return '1б. П-ов Ямал: южно-центральный ареал (67,5–70° с. ш.)'
        return '1в. П-ов Ямал: южная низменная окраина (< 67,5° с. ш.)'

    # 2. Тазовский полуостров (между Обской и Тазовской губами, в составе Надымского и Тазовского р-нов)
    if (TAZ_PENINSULA_MIN_LAT <= lat <= TAZ_PENINSULA_MAX_LAT
            and TAZ_PENINSULA_MIN_LON <= lon <= TAZ_PENINSULA_MAX_LON
            and ('Надымский' in d_str or 'Тазовский' in d_str or d_str == '')):
        return '3. Тазовский полуостров'

    # 3. Полуостров Гыдан (в границах Тазовского/Надымского р-нов ЯНАО и восточного крыла до Енисейского залива ~83,5° в. д.)
    if lat >= GYDAN_MIN_LAT and lon > TAZ_PENINSULA_MIN_LON:
        if 'Тазовский' in d_str or 'Надымский' in d_str:
            return '2а. Полуостров Гыдан (сектор ЯНАО)'
        if d_str == '' and lon < 83.5:
            return '2б. Полуостров Гыдан (восточное крыло вне границ OSM, >=79° в. д.)'

    # 4. Приенисейско-Таймырский сектор (Туруханский округ и территория вне районов OSM восточнее 79° в. д., кроме Гыдана)
    if 'Туруханский' in d_str or (d_str == '' and lon >= EAST_SECTOR_LON):
        return '6. Приенисейско-таймырский сектор'

    # 5. Приуральско-Нижнеобский сектор
    if 'Приуральский' in d_str or 'Шурышкарский' in d_str:
        return '4б. Приуральско-Нижнеобский сектор'

    # 6. Материковые бассейны и террасы Надыма, Пура и Таза (Надымский, Пуровский, Красноселькупский, юг Тазовского)
    if any(k in d_str for k in ('Надымский', 'Пуровский', 'Красноселькупский', 'Тазовский')) or d_str == '':
        return '4а. Бассейны, террасы и междуречья Надыма, Пура и Таза'

    # 7. Сургутско-Нижневартовский (Среднеобский) таёжный пояс ХМАО южнее Сибирских Увалов
    return '5. Сургутско-Нижневартовский таёжный пояс (ХМАО)'


def sample_dem_window(tif_path: Path, ovr_level: int, xs: np.ndarray, ys: np.ndarray,
                      cov_geom_in_raster_crs=None) -> tuple[np.ndarray, np.ndarray | None]:
    """Быстрое оконное чтение локального растра ЦМР на заданном уровне пирамиды для точек и всего покрытия маски."""
    with rasterio.open(tif_path, overview_level=ovr_level) as src:
        pad = 0.2 if src.crs.is_geographic else 20_000.0
        win = from_bounds(float(xs.min() - pad), float(ys.min() - pad),
                          float(xs.max() + pad), float(ys.max() + pad), src.transform)
        win = win.round_offsets().round_lengths().intersection(Window(0, 0, src.width, src.height))
        arr = src.read(1, window=win).astype(np.float32)
        arr[arr <= DEM_NODATA_FLOOR] = np.nan
        w_tr = src.window_transform(win)

        rows, cols = rasterio.transform.rowcol(w_tr, xs, ys)
        rows = np.asarray(rows)
        cols = np.asarray(cols)
        ok = (rows >= 0) & (rows < arr.shape[0]) & (cols >= 0) & (cols < arr.shape[1])
        pts_z = np.full(len(xs), np.nan, dtype=np.float32)
        pts_z[ok] = arr[rows[ok], cols[ok]]

        cov_z_weights = None
        if cov_geom_in_raster_crs is not None:
            mask_cov = rasterize([(cov_geom_in_raster_crs, 1)], out_shape=arr.shape, transform=w_tr,
                                 fill=0, dtype='uint8') == 1
            if src.crs.is_geographic:
                # Вес ячейки пропорционален cos(широты) для равноплощадной гипсометрии территории
                row_lats = w_tr.f + w_tr.e * (np.arange(arr.shape[0]) + 0.5)
                cos_w = np.cos(np.radians(row_lats))[:, None] * np.ones((1, arr.shape[1]), dtype=np.float32)
                valid = mask_cov & np.isfinite(arr)
                cov_z_weights = (arr[valid], cos_w[valid])
            else:
                valid = mask_cov & np.isfinite(arr)
                cov_z_weights = (arr[valid], np.ones(int(valid.sum()), dtype=np.float32))
        return pts_z, cov_z_weights


def compute_exact_intersection_areas(sand_geoms: np.ndarray, sand_areas_ha: np.ndarray,
                                     target_union_geom) -> np.ndarray:
    """Точная площадь пересечения контуров песка с объединённым полигоном без двойного счёта (га)."""
    tree = shapely.STRtree(sand_geoms)
    parts = shapely.get_parts(target_union_geom)
    cand_idx = np.unique(tree.query(parts, predicate='intersects')[1])
    within_idx = np.unique(tree.query(parts, predicate='contains')[1])

    in_ha = np.zeros(len(sand_geoms), dtype=np.float64)
    in_ha[within_idx] = sand_areas_ha[within_idx]
    boundary_idx = np.setdiff1d(cand_idx, within_idx)
    if len(boundary_idx) > 0:
        inter_geoms = shapely.intersection(sand_geoms[boundary_idx], target_union_geom)
        in_ha[boundary_idx] = np.minimum(shapely.area(inter_geoms) / 1e4, sand_areas_ha[boundary_idx])
    return in_ha


# ════════════════════════════════════════════════════════════════════════════
# ОСНОВНОЙ РАСЧЁТ
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    t0 = time.time()
    print('1. Загрузка baresand_genesis_v7b.gpkg и границ покрытия...')
    cols = [
        'id', 'area_ha', 'area_km2', 'genesis', 'genesis_main', 'shoal_type',
        'h_local600', 'h_local1200', 'h_chan', 'dist_channel_m', 'dist_water_m', 'dist_sea_m',
        'd_road_any', 'd_linear', 'd_industrial', 'd_place',
        'cad_status', 'cad_in_ha', 'cad_out_ha', 'cad_none_ha', 'cad_big_ha',
        'cad_exc10_ha', 'cad_exc20_ha', 'cad_ind_ha', 'cad_vri_ha', 'cad_ezp_ha',
        'cad_np_ha', 'cad_terr_ha', 'cad_forest_ha', 'cad_agri_ha', 'cad_misc_ha',
        'age2000', 'bare2000_frac', 'l85_dark_frac', 'bare_s2_frac', 'hansen_covered', 'not_sand_suspect'
    ]
    g = pyogrio.read_dataframe(PRODUCT_GPKG, layer='genesis', columns=cols)
    assert g.crs.to_epsg() == TARGET_CRS, f'Ожидалась СК EPSG:{TARGET_CRS}, получена {g.crs}'

    aoi_gdf = gpd.read_file(AOI_GEOJSON).to_crs(TARGET_CRS)
    aoi_geom = shapely.make_valid(aoi_gdf.geometry.union_all())
    aoi_km2 = aoi_geom.area / 1e6

    cov_gdf = gpd.read_file(COVERAGE_GPKG, layer='coverage').to_crs(TARGET_CRS)
    cov_geom = shapely.make_valid(cov_gdf.geometry.union_all())
    cov_km2 = cov_geom.area / 1e6

    centroids = g.geometry.centroid
    c4326 = gpd.GeoSeries(centroids, crs=TARGET_CRS).to_crs(4326)
    g['lon'] = c4326.x.to_numpy()
    g['lat'] = c4326.y.to_numpy()

    # Проверка базовых контрольных сумм со stats_v7.md
    tot_n = len(g)
    tot_km2 = g['area_ha'].sum() / 100.0
    geom_km2 = g.geometry.area.sum() / 1e6
    cls_km2 = (g.groupby('genesis_main')['area_ha'].sum() / 100.0).to_dict()
    cls_n = g.groupby('genesis_main')['id'].size().to_dict()
    print(f'   Контуров: {tot_n:,}, площадь по area_ha: {tot_km2:.2f} км² (по геометрии EPSG:3576: {geom_km2:.2f} км²)')
    print(f'   По классам (км²): { {k: round(v, 2) for k, v in cls_km2.items()} }')
    assert tot_n == 575_054
    assert abs(tot_km2 - 8155.7) < 0.1
    assert abs(cls_km2['aeolian'] - 2729.7) < 0.1
    assert abs(cls_km2['anthropogenic'] - 1876.2) < 0.1
    assert abs(cls_km2['alluvial_littoral'] - 3506.0) < 0.1
    assert abs(cls_km2['undefined'] - 43.8) < 0.1

    # ── 2. АДМИНИСТРАТИВНЫЕ РАЙОНЫ И ФИЗИКО-ГЕОГРАФИЧЕСКИЕ СУБРЕГИОНЫ ──
    print('\n2. Привязка к административным районам и субрегионам...')
    d6, city_host = load_admin_districts(cov_geom)
    pts = gpd.GeoDataFrame(g[['id']], geometry=centroids, crs=TARGET_CRS)
    joined = gpd.sjoin(pts, d6[['name', 'district', 'geometry']], how='left', predicate='within')
    joined = joined[~joined.index.duplicated()]
    g['osm_admin_name'] = joined['name'].to_numpy()
    g['district'] = joined['district'].to_numpy()
    g['is_city_okr'] = g['osm_admin_name'].fillna('').str.startswith('городской округ')
    g['subregion'] = [assign_subregion(d, lon, lat) for d, lon, lat in zip(g['district'], g['lon'], g['lat'])]

    # Строка агрегированной таблицы 4 статьи
    def row_table4(d, lon):
        if not isinstance(d, str):
            return 'Восточный сектор' if lon >= EAST_SECTOR_LON else 'Вне районов'
        for k in ('Ямальский', 'Тазовский', 'Надымский', 'Пуровский', 'Приуральский'):
            if k in d:
                return k
        return 'Прочие районы'

    g['row_t4'] = [row_table4(d, lon) for d, lon in zip(g['district'], g['lon'])]

    # ── 3. НЕФТЕГАЗОВЫЕ МЕСТОРОЖДЕНИЯ ──
    print('\n3. Пространственный анализ по нефтегазовым месторождениям (Efield_region.shp)...')
    ef = gpd.read_file(EFIELD_SHP, encoding='cp1251').to_crs(TARGET_CRS)
    ef['geometry'] = shapely.make_valid(ef.geometry)
    ef['field_name'] = [clean_efield_name(r) for _, r in ef.iterrows()]
    ef['poly_km2'] = ef.geometry.area / 1e6
    ef['cov_inter_geom'] = ef.geometry.intersection(cov_geom)
    ef['poly_cov_km2'] = ef['cov_inter_geom'].area / 1e6

    ef_cov = ef[ef['poly_cov_km2'] > 0].copy().reset_index(drop=True)
    ef_aoi_n = int(ef.intersects(aoi_geom).sum())
    ef_cov_within_n = int(ef.within(cov_geom).sum())
    ef_cov_cent_n = int(ef.geometry.centroid.within(cov_geom).sum())

    # Северное подмножество (без ХМАО — аналог контура статьи 2022 г. севернее Сибирских Увалов)
    ef_cov['is_north_2022'] = ef_cov['OBLAST'] != 'Khanty-Mansi Autonomous Area'
    ef_north = ef_cov[ef_cov['is_north_2022']].copy().reset_index(drop=True)

    # Объединение всех полигонов месторождений для гарантированного отсутствия двойного счёта
    fields_union_all = shapely.unary_union(ef_cov.geometry.to_numpy())
    fields_union_north = shapely.unary_union(ef_north.geometry.to_numpy())
    fields_union_all_km2 = fields_union_all.area / 1e6
    fields_union_cov_km2 = fields_union_all.intersection(cov_geom).area / 1e6
    fields_union_north_cov_km2 = fields_union_north.intersection(cov_geom).area / 1e6

    sand_geoms = g.geometry.to_numpy()
    sand_areas_ha = g['area_ha'].to_numpy()
    g['in_field_ha'] = compute_exact_intersection_areas(sand_geoms, sand_areas_ha, fields_union_all)
    g['out_field_ha'] = g['area_ha'] - g['in_field_ha']
    g['in_north_field_ha'] = compute_exact_intersection_areas(sand_geoms, sand_areas_ha, fields_union_north)
    g['cent_in_field'] = shapely.contains(fields_union_all, centroids.to_numpy())
    g['cent_in_north_field'] = shapely.contains(fields_union_north, centroids.to_numpy())

    assert abs((g['in_field_ha'].sum() + g['out_field_ha'].sum()) / 100.0 - tot_km2) < 1e-6

    # Расчёт по уникальным месторождениям (dissolve трансграничных частей с одинаковым названием, N=437)
    # и по отдельным полигонам Efield_region.shp (N=449)
    ef_diss = ef_cov[['field_name', 'NAM', 'OBLAST', 'is_north_2022', 'geometry']].dissolve(
        by='field_name',
        aggfunc={'NAM': 'first', 'OBLAST': lambda s: ' + '.join(sorted(set(s.dropna()))), 'is_north_2022': 'any'}
    ).reset_index()
    ef_diss['geometry'] = shapely.make_valid(ef_diss.geometry)
    ef_diss['field_km2'] = ef_diss.geometry.area / 1e6
    ef_diss['field_cov_km2'] = ef_diss.geometry.intersection(cov_geom).area / 1e6
    ef_diss['cov_frac'] = ef_diss['field_cov_km2'] / ef_diss['field_km2']

    sand_tree = shapely.STRtree(sand_geoms)
    gen_arr = g['genesis_main'].to_numpy()

    def per_field_table(fdf: gpd.GeoDataFrame, name_col: str, area_col: str, cov_area_col: str) -> pd.DataFrame:
        rows = []
        for idx_f, row in fdf.iterrows():
            fgeom = row.geometry
            cands = sand_tree.query(fgeom, predicate='intersects')
            if len(cands) == 0:
                rows.append({
                    'name': row[name_col], 'oblast': row['OBLAST'], 'type': row['NAM'],
                    'is_north': bool(row['is_north_2022']),
                    'field_km2': row[area_col], 'field_cov_km2': row[cov_area_col],
                    'aeol_ha': 0.0, 'aeol_n': 0, 'aeol_max_km2': 0.0,
                    'anth_ha': 0.0, 'anth_n': 0, 'anth_max_km2': 0.0,
                    'shoal_ha': 0.0, 'undef_ha': 0.0,
                })
                continue
            c_geoms = sand_geoms[cands]
            c_areas = sand_areas_ha[cands]
            c_gen = gen_arr[cands]
            inside = shapely.contains(fgeom, c_geoms)
            a_ha = np.empty(len(cands), dtype=np.float64)
            a_ha[inside] = c_areas[inside]
            if (~inside).any():
                inter = shapely.intersection(c_geoms[~inside], fgeom)
                a_ha[~inside] = np.minimum(shapely.area(inter) / 1e4, c_areas[~inside])
            pos = a_ha > 0
            c_gen = c_gen[pos]
            a_ha = a_ha[pos]

            m_ae = c_gen == 'aeolian'
            m_an = c_gen == 'anthropogenic'
            m_sh = c_gen == 'alluvial_littoral'
            m_un = c_gen == 'undefined'
            rows.append({
                'name': row[name_col], 'oblast': row['OBLAST'], 'type': row['NAM'],
                'is_north': bool(row['is_north_2022']),
                'field_km2': row[area_col], 'field_cov_km2': row[cov_area_col],
                'aeol_ha': float(a_ha[m_ae].sum()), 'aeol_n': int(m_ae.sum()),
                'aeol_max_km2': float(a_ha[m_ae].max() / 100.0) if m_ae.any() else 0.0,
                'anth_ha': float(a_ha[m_an].sum()), 'anth_n': int(m_an.sum()),
                'anth_max_km2': float(a_ha[m_an].max() / 100.0) if m_an.any() else 0.0,
                'shoal_ha': float(a_ha[m_sh].sum()),
                'undef_ha': float(a_ha[m_un].sum()),
            })
        out = pd.DataFrame(rows)
        out['aeol_km2'] = out['aeol_ha'] / 100.0
        out['anth_km2'] = out['anth_ha'] / 100.0
        out['aeol_pct_full'] = 100.0 * out['aeol_km2'] / out['field_km2']
        out['anth_pct_full'] = 100.0 * out['anth_km2'] / out['field_km2']
        out['aeol_pct_cov'] = np.where(out['field_cov_km2'] > 0, 100.0 * out['aeol_km2'] / out['field_cov_km2'], 0.0)
        out['anth_pct_cov'] = np.where(out['field_cov_km2'] > 0, 100.0 * out['anth_km2'] / out['field_cov_km2'], 0.0)
        return out

    ft_diss = per_field_table(ef_diss, 'field_name', 'field_km2', 'field_cov_km2')
    ft_poly = per_field_table(ef_cov, 'field_name', 'poly_km2', 'poly_cov_km2')

    # Проверка чувствительности к старому шейпу Field_region.shp (2011 г.)
    fr = gpd.read_file(FIELD_SHP, encoding='cp1251').to_crs(TARGET_CRS)
    fr['geometry'] = shapely.make_valid(fr.geometry)
    fr_cov = fr[fr.intersects(cov_geom)].copy()
    fr_union = shapely.unary_union(fr_cov.geometry.to_numpy())
    fr_in_ha = compute_exact_intersection_areas(sand_geoms, sand_areas_ha, fr_union)
    fr_cls_km2 = pd.Series(fr_in_ha / 100.0).groupby(g['genesis_main']).sum().to_dict()

    # ── 4. ГИПСОМЕТРИЯ И ОТНОСИТЕЛЬНЫЙ РЕЛЬЕФ ──
    print('\n4. Расчёт гипсометрии (ортометрическая AW3D30 v4.1 и эллипсоидальная ArcticDEM) и превышений h...')
    cov_4326 = gpd.GeoSeries([cov_geom], crs=TARGET_CRS).to_crs(4326).iloc[0]
    cov_north_3576 = cov_geom.difference(
        d6[d6['district'].isin([
            'Сургутский район', 'Нижневартовский район', 'Белоярский район',
            'Ханты-Мансийский район', 'Октябрьский район', 'Берёзовский район', 'Нефтеюганский район'
        ])].geometry.union_all()
    )
    cov_north_4326 = gpd.GeoSeries([cov_north_3576], crs=TARGET_CRS).to_crs(4326).iloc[0]

    z_ortho_cov = None
    z_ortho_north_cov = None
    if LOCAL_AW3D30_TIF.exists():
        g['z_ortho'], z_ortho_cov = sample_dem_window(
            LOCAL_AW3D30_TIF, AW3D_OVERVIEW_LEVEL, g['lon'].to_numpy(), g['lat'].to_numpy(), cov_4326
        )
        _, z_ortho_north_cov = sample_dem_window(
            LOCAL_AW3D30_TIF, AW3D_OVERVIEW_LEVEL, g['lon'].to_numpy(), g['lat'].to_numpy(), cov_north_4326
        )
    else:
        g['z_ortho'] = np.nan

    if LOCAL_ARCTICDEM_TIF.exists():
        c32643 = gpd.GeoSeries(centroids, crs=TARGET_CRS).to_crs(32643)
        g['z_ellip'], _ = sample_dem_window(
            LOCAL_ARCTICDEM_TIF, ARCTICDEM_OVERVIEW_LEVEL, c32643.x.to_numpy(), c32643.y.to_numpy(), None
        )
    else:
        g['z_ellip'] = np.nan

    # Точные 2-метровые медианы ArcticDEM из dem_evidence_mass.csv (146 379 контуров шага 5)
    if DEM_MASS_CSV.exists():
        dm = pd.read_csv(DEM_MASS_CSV, usecols=['id', 'h_cont']).drop_duplicates('id')
        g = g.merge(dm, on='id', how='left')
    else:
        g['h_cont'] = np.nan

    # ── 5. ПЕЧАТЬ СТРУКТУРИРОВАННЫХ РЕЗУЛЬТАТОВ ──
    print('\n' + '=' * 90)
    print('СВОДКА 1: НЕФТЕГАЗОВЫЕ МЕСТОРОЖДЕНИЯ')
    print('=' * 90)
    print(f'Полигонов Efield_region.shp всего в РФ: {len(ef)}, пересекают AOI: {ef_aoi_n}')
    print(f'Пересекают покрытие 128 тайлов: {len(ef_cov)} полигонов (центроид в покрытии: {ef_cov_cent_n}, целиком в покрытии: {ef_cov_within_n})')
    print(f'Уникальных названий месторождений в покрытии: {len(ef_diss)} (в северном контуре без ХМАО: {int(ef_diss["is_north_2022"].sum())} уникальных / {len(ef_north)} полигонов)')
    print(f'Площадь объединения месторождений (без двойного счёта): полная = {fields_union_all_km2:,.1f} км², в покрытии = {fields_union_cov_km2:,.1f} км² ({100*fields_union_cov_km2/cov_km2:.2f}% покрытия)')
    print(f'В северном контуре без ХМАО площадь м-ний в покрытии = {fields_union_north_cov_km2:,.1f} км²')
    print(f'Сверка со старым шейпом Field_region.shp (2011 г., {len(fr_cov)} полигонов): внутри м-ний км² = { {k: round(v, 2) for k, v in fr_cls_km2.items()} }')

    print('\n--- Площадь песков внутри и вне границ месторождений (точный intersection с union_all, без двойного счёта) ---')
    inout = g.groupby('genesis_main').agg(
        total_km2=('area_ha', lambda s: s.sum() / 100.0),
        in_km2=('in_field_ha', lambda s: s.sum() / 100.0),
        out_km2=('out_field_ha', lambda s: s.sum() / 100.0),
        in_north_km2=('in_north_field_ha', lambda s: s.sum() / 100.0),
        n_inter=('in_field_ha', lambda s: int((s > 0).sum())),
        n_cent=('cent_in_field', lambda s: int(s.sum())),
        n_cent_north=('cent_in_north_field', lambda s: int(s.sum())),
    )
    inout['in_pct'] = 100.0 * inout['in_km2'] / inout['total_km2']
    inout['out_pct'] = 100.0 * inout['out_km2'] / inout['total_km2']
    print(inout.round(2).to_string())

    print('\n--- Морфометрия контуров внутри границ месторождений (для сопоставления со стр. 25 статьи 2022 г.) ---')
    for mode_label, mask_col, val_col in [
        ('Все м-ния покрытия: фрагменты внутри границ (in_field_ha > 0)', g['in_field_ha'] > 0, 'in_field_ha'),
        ('Все м-ния покрытия: целые контуры с центроидом в м-нии', g['cent_in_field'], 'area_ha'),
        ('Северный контур (без ХМАО): фрагменты внутри границ', g['in_north_field_ha'] > 0, 'in_north_field_ha'),
        ('Северный контур (без ХМАО): целые контуры с центроидом в м-нии', g['cent_in_north_field'], 'area_ha'),
    ]:
        print(f'\n[{mode_label}]')
        sub = g[mask_col]
        st = sub.groupby('genesis_main')[val_col].agg(
            N='size',
            sum_km2=lambda s: s.sum() / 100.0,
            mean_ha='mean',
            median_ha='median',
            max_km2=lambda s: s.max() / 100.0,
            n_gt1km2=lambda s: int((s > 100.0).sum()),
        )
        print(st.round(3).to_string())

    print('\n--- Число месторождений с присутствием песков ---')
    for lbl, df_f in [('Уникальные м-ния (N=437)', ft_diss),
                      ('Уникальные м-ния северного контура без ХМАО (N=220)', ft_diss[ft_diss['is_north']]),
                      ('Полигоны Efield_region (N=449)', ft_poly),
                      ('Полигоны северного контура без ХМАО (N=230)', ft_poly[ft_poly['is_north']])]:
        n_ae = int((df_f['aeol_ha'] > 0).sum())
        n_an = int((df_f['anth_ha'] > 0).sum())
        n_any = int(((df_f['aeol_ha'] > 0) | (df_f['anth_ha'] > 0)).sum())
        print(f'  {lbl}: всего={len(df_f)}, с эоловыми={n_ae}, с техногенными={n_an}, с эол. или техн.={n_any}')

    # Структура техногенных песков вне месторождений
    ant = g[g['genesis_main'] == 'anthropogenic'].copy()
    ant['np_terr_frac'] = np.clip((ant['cad_np_ha'].fillna(0) + ant['cad_terr_ha'].fillna(0)) / np.maximum(ant['area_ha'], 1e-9), 0, 1)
    ant['out_np_terr_km2'] = (ant['out_field_ha'] * ant['np_terr_frac']) / 100.0
    near_lin = (ant['d_road_any'].fillna(9e9) <= LINEAR_INFRA_DIST_M) | (ant['d_linear'].fillna(9e9) <= LINEAR_INFRA_DIST_M) | (ant['cad_ezp_ha'].fillna(0) > 0)
    print('\n--- Анатомия техногенных песков ВНЕ границ месторождений ---')
    tot_out_ant = ant['out_field_ha'].sum() / 100.0
    out_in_np = ant['out_np_terr_km2'].sum()
    out_city_okr = ant.loc[ant['is_city_okr'], 'out_field_ha'].sum() / 100.0
    out_non_np_near_lin = (ant.loc[near_lin, 'out_field_ha'] * (1 - ant.loc[near_lin, 'np_terr_frac'])).sum() / 100.0
    out_non_np_other = tot_out_ant - out_in_np - out_non_np_near_lin
    print(f'  Всего техногенных вне месторождений: {tot_out_ant:.2f} км² ({100*tot_out_ant/(ant["area_ha"].sum()/100):.1f}% класса)')
    print(f'  - в землях и на территории населённых пунктов / вахтовых посёлков / промзон: {out_in_np:.2f} км² (в городских округах OSM вне м-ний: {out_city_okr:.2f} км²)')
    print(f'  - вне НП в коридорах дорог, трубопроводов и ЕЗП (<= 100 м, притрассовые карьеры и отсыпки): {out_non_np_near_lin:.2f} км²')
    print(f'  - прочие объекты вне месторождений и вне НП (> 100 м от учтённых трасс OSM): {out_non_np_other:.2f} км²')

    # Кадастровый статус внутри vs вне месторождений (по центроиду контура / доле в м-нии)
    ant['field_zone'] = np.where(ant['in_field_ha'] >= 0.5 * ant['area_ha'], 'внутри месторождений (>=50%)', 'вне месторождений (<50%)')
    print('\n--- Техногенные пески: ЕГРН внутри vs вне месторождений ---')
    fz_cad = ant.groupby('field_zone').agg(
        N=('id', 'size'),
        km2=('area_ha', lambda s: s.sum() / 100.0),
        cad_in_km2=('cad_in_ha', lambda s: s.sum() / 100.0),
        exceed10_km2=('cad_exc10_ha', lambda s: s.sum() / 100.0),
        noallot_km2=('area_ha', lambda s: s[ant.loc[s.index, 'cad_status'] == 'unreg'].sum() / 100.0),
        cad_none_km2=('cad_none_ha', lambda s: s.sum() / 100.0),
    )
    fz_cad['in_pct'] = 100.0 * fz_cad['cad_in_km2'] / fz_cad['km2']
    fz_cad['noallot_pct'] = 100.0 * fz_cad['noallot_km2'] / fz_cad['km2']
    print(fz_cad.round(2).to_string())

    # Топ-15 таблиц месторождений (доля в сумме по м-ниям считается строго от union_all без двойного счёта!)
    tot_ae_on_fields = float(g.loc[g['genesis_main'] == 'aeolian', 'in_field_ha'].sum())
    tot_an_on_fields = float(g.loc[g['genesis_main'] == 'anthropogenic', 'in_field_ha'].sum())
    ft_diss['aeol_share_of_fields_pct'] = 100.0 * ft_diss['aeol_ha'] / tot_ae_on_fields
    ft_diss['anth_share_of_fields_pct'] = 100.0 * ft_diss['anth_ha'] / tot_an_on_fields

    cols_show_ae = ['name', 'oblast', 'field_km2', 'field_cov_km2', 'aeol_n', 'aeol_ha', 'aeol_km2', 'aeol_pct_cov', 'aeol_pct_full', 'aeol_share_of_fields_pct']
    cols_show_an = ['name', 'oblast', 'field_km2', 'field_cov_km2', 'anth_n', 'anth_ha', 'anth_km2', 'anth_pct_cov', 'anth_pct_full', 'anth_share_of_fields_pct']

    print('\n--- ТОП-15 месторождений по ПЛОЩАДИ ЭОЛОВЫХ песков (весь регион, уникальные м-ния) ---')
    print(ft_diss.sort_values('aeol_ha', ascending=False)[cols_show_ae].head(15).round(2).to_string(index=False))

    print('\n--- ТОП-15 месторождений по ПЛОЩАДИ ТЕХНОГЕННЫХ песков (весь регион, уникальные м-ния) ---')
    print(ft_diss.sort_values('anth_ha', ascending=False)[cols_show_an].head(15).round(2).to_string(index=False))

    print('\n--- ТОП-15 месторождений по ПЛОЩАДИ ТЕХНОГЕННЫХ песков (СЕВЕРНЫЙ КОНТУР без ХМАО — прямое сравнение с табл. 2 2022 г.) ---')
    print(ft_diss[ft_diss['is_north']].sort_values('anth_ha', ascending=False)[cols_show_an].head(15).round(2).to_string(index=False))

    print('\n--- ТОП-15 месторождений по УДЕЛЬНОЙ ДОЛЕ (%) ЭОЛОВЫХ песков (ранжирование по доле в покрытии aeol_pct_cov) ---')
    print(ft_diss[ft_diss['aeol_ha'] > 0].sort_values('aeol_pct_cov', ascending=False)[cols_show_ae].head(15).round(2).to_string(index=False))

    print('\n--- ТОП-15 месторождений по УДЕЛЬНОЙ ДОЛЕ (%) ТЕХНОГЕННЫХ песков (весь регион, ранжирование по anth_pct_cov) ---')
    print(ft_diss[ft_diss['anth_ha'] > 0].sort_values('anth_pct_cov', ascending=False)[cols_show_an].head(15).round(2).to_string(index=False))

    print('\n--- ТОП-15 месторождений по УДЕЛЬНОЙ ДОЛЕ (%) ТЕХНОГЕННЫХ песков (СЕВЕРНЫЙ КОНТУР без ХМАО, ранжирование по anth_pct_cov) ---')
    print(ft_diss[ft_diss['is_north'] & (ft_diss['anth_ha'] > 0)].sort_values('anth_pct_cov', ascending=False)[cols_show_an].head(15).round(2).to_string(index=False))

    print('\n--- ПРЯМОЕ СОПОСТАВЛЕНИЕ СО ВСЕМИ МЕСТОРОЖДЕНИЯМИ ТАБЛ. 2 И 3 СТАТЬИ 2022 Г. ---')
    comp_rows = []
    for fname, ref in REF_FIELDS_2022.items():
        m = ft_diss[ft_diss['name'] == fname]
        if m.empty:
            m = ft_diss[ft_diss['name'].str.contains(fname[:6], case=False)]
        if not m.empty:
            r = m.iloc[0]
            comp_rows.append({
                'Месторождение': r['name'],
                'Субъект': r['oblast'],
                'S_м-ния_км2': round(r['field_km2'], 2),
                '2022_эол_га': ref['nat_ha'],
                'v7b_эол_га': round(r['aeol_ha'], 2),
                '2022_эол_%': ref['nat_pct'],
                'v7b_эол_%': round(r['aeol_pct_full'], 2),
                '2022_техн_га': ref['ant_ha'],
                'v7b_техн_га': round(r['anth_ha'], 2),
                '2022_техн_%': ref['ant_pct'],
                'v7b_техн_%': round(r['anth_pct_full'], 2),
            })
        else:
            comp_rows.append({'Месторождение': fname, 'Субъект': 'НЕ НАЙДЕНО'})
    print(pd.DataFrame(comp_rows).to_string(index=False))

    # Отдельно проверим Вынгапуровское по двум субъектным полигонам (ЯНАО vs ХМАО)
    print('\n--- Трансграничные месторождения (раздельно по субъектам в Efield_region.shp) ---')
    dup_names = ef_cov['field_name'].value_counts()
    dup_list = dup_names[dup_names > 1].index.tolist()
    print(ft_poly[ft_poly['name'].isin(dup_list)][['name', 'oblast', 'field_km2', 'aeol_ha', 'anth_ha', 'anth_pct_full']].sort_values(['name', 'oblast']).round(2).to_string(index=False))

    # ── СВОДКА 2: СУБРЕГИОНЫ, ГИДРОСЕТЬ, ГИПСОМЕТРИЯ И ПРЕВЫШЕНИЯ ──
    print('\n' + '=' * 90)
    print('СВОДКА 2: ГЕОМОРФОЛОГИЧЕСКИЕ СУБРЕГИОНЫ, ГИПСОМЕТРИЯ И ОТНОСИТЕЛЬНЫЕ ПРЕВЫШЕНИЯ')
    print('=' * 90)
    sr_piv = g.pivot_table(index='subregion', columns='genesis_main', values='area_ha', aggfunc='sum', fill_value=0.0) / 100.0
    sr_n = g.pivot_table(index='subregion', columns='genesis_main', values='id', aggfunc='size', fill_value=0)
    sr_piv['всего_км2'] = sr_piv.sum(axis=1)
    sr_piv['эол_%_класса'] = 100.0 * sr_piv['aeolian'] / sr_piv['aeolian'].sum()
    sr_piv['техн_%_класса'] = 100.0 * sr_piv['anthropogenic'] / sr_piv['anthropogenic'].sum()
    sr_piv['эол_N'] = sr_n['aeolian']
    sr_piv['техн_N'] = sr_n['anthropogenic']
    sr_piv['эол_ср_га'] = 100.0 * sr_piv['aeolian'] / np.maximum(sr_n['aeolian'], 1)
    sr_piv['техн_ср_га'] = 100.0 * sr_piv['anthropogenic'] / np.maximum(sr_n['anthropogenic'], 1)
    print('\n--- Разбивка по физико-географическим субрегионам (100% площади маски) ---')
    print(sr_piv.round(2).to_string())
    print('Контроль сумм по субрегионам:', sr_piv[['aeolian', 'anthropogenic', 'alluvial_littoral', 'undefined', 'всего_км2']].sum().round(2).to_dict())

    # Доля приречно-террасовых vs водораздельных эоловых песков в бассейнах Надыма, Пура и Таза и связь с 500 м буфером на Ямале и Гыдане
    ae = g[g['genesis_main'] == 'aeolian'].copy()
    ae['near_hydro_500m'] = (
        (ae['dist_water_m'].fillna(9e9) <= HYDRO_BUFFER_2022_M)
        | (ae['dist_channel_m'].fillna(9e9) <= HYDRO_BUFFER_2022_M)
        | (ae['dist_sea_m'].fillna(9e9) <= HYDRO_BUFFER_2022_M)
    )
    ae['near_chan_2km'] = ae['dist_channel_m'].fillna(9e9) <= TERRACE_CHANNEL_DIST_M
    print('\n--- Приуроченность эоловых песков к бортам долин/котловин (<= 500 м от воды/русел/моря и <= 2 км от русел) ---')
    hyd_sr = ae.groupby('subregion').apply(
        lambda df: pd.Series({
            'aeol_km2': df['area_ha'].sum() / 100.0,
            'pct_le500m_hydro': 100.0 * df.loc[df['near_hydro_500m'], 'area_ha'].sum() / df['area_ha'].sum(),
            'pct_gt500m_hydro': 100.0 * df.loc[~df['near_hydro_500m'], 'area_ha'].sum() / df['area_ha'].sum(),
            'pct_le2km_channel': 100.0 * df.loc[df['near_chan_2km'], 'area_ha'].sum() / df['area_ha'].sum(),
        }), include_groups=False
    )
    print(hyd_sr.round(2).to_string())
    yg_mask = ae['subregion'].str.startswith(('1а.', '1б.', '1в.', '2а.', '2б.'))
    print(f'На Ямале и Гыдане суммарно вне 500-м водно-эрозионного буфера: '
          f'{100.0 * ae.loc[yg_mask & ~ae["near_hydro_500m"], "area_ha"].sum() / ae.loc[yg_mask, "area_ha"].sum():.2f}% площади эоловых песков '
          f'(в статье 2022 г. по буферу TanDEM90 было 3,81%)')

    # Гипсометрия (абсолютные высоты)
    print('\n--- Гипсометрическое распределение (ортометрическая высота AW3D30 v4.1 над геоидом EGM96, центроид, overview 4 ≈ 1 км) ---')
    if g['z_ortho'].notna().any():
        for label_sub, df_sub in [
            ('Весь обработанный регион', g),
            ('Северный контур (без ХМАО, аналог 2022 г.)', g[~g['subregion'].str.startswith('5.')]),
        ]:
            print(f'\n[{label_sub}]')
            for cls in ('aeolian', 'anthropogenic', 'alluvial_littoral'):
                s = df_sub[df_sub['genesis_main'] == cls].dropna(subset=['z_ortho'])
                tot_w = s['area_ha'].sum()
                qs = weighted_quantiles(s['z_ortho'].to_numpy(), s['area_ha'].to_numpy(), QUANTILES)
                in_10_60 = 100.0 * s.loc[(s['z_ortho'] >= 10) & (s['z_ortho'] < 60), 'area_ha'].sum() / tot_w
                in_30_45 = 100.0 * s.loc[(s['z_ortho'] >= 30) & (s['z_ortho'] < 45), 'area_ha'].sum() / tot_w
                in_0_10 = 100.0 * s.loc[(s['z_ortho'] >= 0) & (s['z_ortho'] < 10), 'area_ha'].sum() / tot_w
                in_ge60 = 100.0 * s.loc[s['z_ortho'] >= 60, 'area_ha'].sum() / tot_w
                print(f'  {cls:18s} (N={len(s):,}, {tot_w/100:.1f} км²): 0-10м={in_0_10:.1f}%, 10-60м={in_10_60:.1f}% '
                      f'(30-45м={in_30_45:.1f}%), >=60м={in_ge60:.1f}% | взвеш. q5/10/25/50/75/90/95 = {np.round(qs, 1).tolist()}')
                bins_s = pd.cut(s['z_ortho'], ELEV_BINS, right=False, labels=ELEV_LABELS)
                b_tab = (s.groupby(bins_s, observed=False)['area_ha'].sum() / tot_w * 100.0).round(2)
                print('    ступенчато (%):', b_tab.to_dict())

        if z_ortho_cov is not None:
            zv, zw = z_ortho_cov
            b_cov = pd.Series(zw).groupby(pd.cut(zv, ELEV_BINS, right=False, labels=ELEV_LABELS), observed=False).sum()
            b_cov_pct = (100.0 * b_cov / zw.sum()).round(2)
            qs_cov = weighted_quantiles(zv, zw, QUANTILES)
            print(f'\n  Фон (вся покрытая территория 906 325 км²): ступенчато (%) = {b_cov_pct.to_dict()}')
            print(f'  Фон (вся покрытая территория): q5/10/25/50/75/90/95 = {np.round(qs_cov, 1).tolist()}')
        if z_ortho_north_cov is not None:
            zvn, zwn = z_ortho_north_cov
            bn_cov = pd.Series(zwn).groupby(pd.cut(zvn, ELEV_BINS, right=False, labels=ELEV_LABELS), observed=False).sum()
            bn_cov_pct = (100.0 * bn_cov / zwn.sum()).round(2)
            qsn_cov = weighted_quantiles(zvn, zwn, QUANTILES)
            print(f'  Фон (северный контур без ХМАО): ступенчато (%) = {bn_cov_pct.to_dict()}')
            print(f'  Фон (северный контур без ХМАО): q5/10/25/50/75/90/95 = {np.round(qsn_cov, 1).tolist()}')

    print('\n--- Эллипсоидальные высоты ArcticDEM и смещение геоида ---')
    if g['z_ellip'].notna().any() and g['z_ortho'].notna().any():
        both = g.dropna(subset=['z_ellip', 'z_ortho'])
        geoid_diff = both['z_ellip'] - both['z_ortho']
        print('  Разность (ArcticDEM_ellip - AW3D30_ortho) по контурам песка p5/25/50/75/95 (м):',
              np.percentile(geoid_diff, [5, 25, 50, 75, 95]).round(2).tolist())
        for cls in ('aeolian', 'anthropogenic', 'alluvial_littoral'):
            s = g[g['genesis_main'] == cls].dropna(subset=['z_ellip'])
            tot_w = s['area_ha'].sum()
            qs = weighted_quantiles(s['z_ellip'].to_numpy(), s['area_ha'].to_numpy(), QUANTILES)
            in_lt0 = 100.0 * s.loc[s['z_ellip'] < 0, 'area_ha'].sum() / tot_w
            in_10_60 = 100.0 * s.loc[(s['z_ellip'] >= 10) & (s['z_ellip'] < 60), 'area_ha'].sum() / tot_w
            print(f'  ArcticDEM эллипс. {cls:18s} (покрытие {len(s)/len(g[g.genesis_main==cls]):.3f}): <0м={in_lt0:.1f}%, '
                  f'10-60м={in_10_60:.1f}% | взвеш. q5/10/25/50/75/90/95 = {np.round(qs, 1).tolist()}')

    # Относительные превышения h_local600, h_local1200, h_chan
    print('\n--- Относительное превышение над локальным базисом (1: эталон разработки 640 контуров baselevel_compare.csv) ---')
    if BASELEVEL_CSV.exists():
        bl = pd.read_csv(BASELEVEL_CSV)
        bl['main_truth'] = bl['truth'].replace({'river_shoal': 'alluvial_littoral', 'lake_shoal': 'alluvial_littoral'})
        for grp_col, title in [('truth', 'По детальным эталонным классам (640 контуров)'),
                               ('main_truth', 'По основным эталонным классам (640 контуров)')]:
            print(f'[{title}]')
            for hcol in ('h_local600', 'h_local1200', 'h_chan'):
                rows_q = []
                for cl_name, sub in bl.groupby(grp_col):
                    s = sub.dropna(subset=[hcol])
                    uq = np.percentile(s[hcol], [5, 10, 25, 50, 75, 90, 95])
                    wq = weighted_quantiles(s[hcol].to_numpy(), s['area_ha'].to_numpy(), QUANTILES)
                    rows_q.append({
                        'class': cl_name, 'metric': hcol, 'n': len(s),
                        'unw_p10': uq[1], 'unw_p25': uq[2], 'unw_p50': uq[3], 'unw_p75': uq[4], 'unw_p90': uq[5],
                        'w_p25': wq[2], 'w_p50': wq[3], 'w_p75': wq[4],
                    })
                print(pd.DataFrame(rows_q).round(2).to_string(index=False))

    print('\n--- Относительное превышение в полях baresand_genesis_v7b.gpkg (146 027 контуров зоны шага 5: прирусловые и бывшие undefined) ---')
    for hcol in ('h_local600', 'h_local1200', 'h_chan'):
        rows_q = []
        for cl_name, sub in g.groupby('genesis_main'):
            s = sub.dropna(subset=[hcol])
            if s.empty:
                continue
            uq = np.percentile(s[hcol], [5, 10, 25, 50, 75, 90, 95])
            wq = weighted_quantiles(s[hcol].to_numpy(), s['area_ha'].to_numpy(), QUANTILES)
            rows_q.append({
                'class': cl_name, 'metric': hcol, 'n': len(s), 'km2': s['area_ha'].sum() / 100.0,
                'share_cls_area_%': 100.0 * s['area_ha'].sum() / sub['area_ha'].sum(),
                'unw_p10': uq[1], 'unw_p25': uq[2], 'unw_p50': uq[3], 'unw_p75': uq[4], 'unw_p90': uq[5],
                'w_p10': wq[1], 'w_p25': wq[2], 'w_p50': wq[3], 'w_p75': wq[4], 'w_p90': wq[5],
            })
        print(pd.DataFrame(rows_q).round(2).to_string(index=False))

    # ── СВОДКА 3: ПОРАЙОННАЯ УДЕЛЬНАЯ ПЛОТНОСТЬ В СРАВНЕНИИ С 2022 Г. ──
    print('\n' + '=' * 90)
    print('СВОДКА 3: ПОРАЙОННОЕ РАСПРЕДЕЛЕНИЕ И УДЕЛЬНАЯ ПЛОТНОСТЬ (% ОТ ПЛОЩАДИ РАЙОНА В ПОКРЫТИИ)')
    print('=' * 90)
    dist_area = d6.groupby('district')['area_cov_km2'].sum()
    dist_piv = g.pivot_table(index='district', columns='genesis_main', values='area_ha', aggfunc='sum', fill_value=0.0) / 100.0
    dist_piv['area_cov_km2'] = dist_area
    dist_piv['aeol_pct_cls'] = 100.0 * dist_piv['aeolian'] / cls_km2['aeolian']
    dist_piv['aeol_density_%'] = 100.0 * dist_piv['aeolian'] / dist_piv['area_cov_km2']
    dist_piv['anth_pct_cls'] = 100.0 * dist_piv['anthropogenic'] / cls_km2['anthropogenic']
    dist_piv['anth_density_%'] = 100.0 * dist_piv['anthropogenic'] / dist_piv['area_cov_km2']
    dist_piv['shoal_density_%'] = 100.0 * dist_piv['alluvial_littoral'] / dist_piv['area_cov_km2']
    print(dist_piv.sort_values('anthropogenic', ascending=False).round(3).to_string())

    # Площадь покрытия восточного сектора (вне районов OSM восточнее 79° в. д.)
    adm_union = d6.geometry.union_all()
    unassigned_cov_geom = cov_geom.difference(adm_union)
    # Разделим по меридиану 79° в. д.
    east_box_4326 = shapely.box(EAST_SECTOR_LON, 58.0, 95.0, 76.0)
    east_box_3576 = gpd.GeoSeries([east_box_4326], crs=4326).to_crs(TARGET_CRS).iloc[0]
    east_sector_cov_km2 = unassigned_cov_geom.intersection(east_box_3576).area / 1e6
    outside_west_cov_km2 = unassigned_cov_geom.area / 1e6 - east_sector_cov_km2
    print(f'\nПлощадь покрытия вне районов OSM: восточный сектор (>=79° в. д.) = {east_sector_cov_km2:,.1f} км², '
          f'западнее 79° в. д. (акватории губ) = {outside_west_cov_km2:,.1f} км²')

    # Сводная таблица 4 с удельными плотностями
    t4_piv = g.pivot_table(index='row_t4', columns='genesis_main', values='area_ha', aggfunc='sum', fill_value=0.0) / 100.0
    row_cov_map = {}
    for k in ('Ямальский', 'Тазовский', 'Надымский', 'Пуровский', 'Приуральский'):
        m_k = [idx for idx in dist_area.index if k in idx]
        row_cov_map[k] = float(dist_area.loc[m_k].sum())
    other_k = [idx for idx in dist_area.index if not any(k in idx for k in ('Ямальский', 'Тазовский', 'Надымский', 'Пуровский', 'Приуральский'))]
    row_cov_map['Прочие районы'] = float(dist_area.loc[other_k].sum())
    row_cov_map['Восточный сектор'] = east_sector_cov_km2
    row_cov_map['Вне районов'] = outside_west_cov_km2
    t4_piv['cov_km2'] = pd.Series(row_cov_map)
    in_rows = t4_piv.index != 'Вне районов'
    t4_piv['aeol_share_%'] = 100.0 * t4_piv['aeolian'] / t4_piv.loc[in_rows, 'aeolian'].sum()
    t4_piv['anth_share_%'] = 100.0 * t4_piv['anthropogenic'] / t4_piv.loc[in_rows, 'anthropogenic'].sum()
    t4_piv['aeol_dens_%'] = 100.0 * t4_piv['aeolian'] / t4_piv['cov_km2']
    t4_piv['anth_dens_%'] = 100.0 * t4_piv['anthropogenic'] / t4_piv['cov_km2']
    print('\n--- Сводная Таблица 4 (с покрытой площадью и удельными долями %) ---')
    print(t4_piv.reindex(['Ямальский', 'Тазовский', 'Надымский', 'Пуровский', 'Приуральский',
                          'Восточный сектор', 'Прочие районы', 'Вне районов']).round(3).to_string())

    # ── СВОДКА 4: ЕГРН (РЕДАКЦИЯ v7b) И ВОЗРАСТНОЙ СРЕЗ age2000 ──
    print('\n' + '=' * 90)
    print('СВОДКА 4: АНАТОМИЯ ТЕХНОГЕННОЙ НАРУШЕННОСТИ, ЕГРН (v7b) И ВОЗРАСТ НАРУШЕНИЙ')
    print('=' * 90)
    for lyr in ('anthro_in', 'anthro_exceed', 'anthro_noallot'):
        info = pyogrio.read_info(CADASTRE_GPKG, layer=lyr)
        gdf_l = pyogrio.read_dataframe(CADASTRE_GPKG, layer=lyr, columns=[c for c in ('area_ha', 'grp', 'kind', 'age2000') if c in info['fields']], read_geometry=True)
        km2_l = gdf_l.geometry.area.sum() / 1e6
        print(f'  Слой {lyr:15s}: объектов = {len(gdf_l):,}, площадь геометрии = {km2_l:.2f} км²')
        if lyr == 'anthro_noallot' and 'kind' in gdf_l.columns:
            print('    по полю kind (none vs touch):')
            print(gdf_l.assign(km2=gdf_l.geometry.area / 1e6).groupby('kind').agg(N=('km2', 'size'), km2=('km2', 'sum')).round(2).to_string())

    # Сводка по cad_status и возрастному полю age2000
    print('\n--- cad_status x age2000 в классе anthropogenic ---')
    cs_tab = ant.groupby('cad_status').agg(
        N=('id', 'size'),
        total_km2=('area_ha', lambda s: s.sum() / 100.0),
        in_allot_km2=('cad_in_ha', lambda s: s.sum() / 100.0),
        exc10_km2=('cad_exc10_ha', lambda s: s.sum() / 100.0),
        exc20_km2=('cad_exc20_ha', lambda s: s.sum() / 100.0),
    )
    print(cs_tab.round(2).to_string())

    age_tab = ant.groupby('age2000', dropna=False).agg(
        N=('id', 'size'),
        total_km2=('area_ha', lambda s: s.sum() / 100.0),
        in_allot_km2=('cad_in_ha', lambda s: s.sum() / 100.0),
        cad_none_km2=('cad_none_ha', lambda s: s.sum() / 100.0),
        exc10_km2=('cad_exc10_ha', lambda s: s[ant.loc[s.index, 'cad_status'] == 'cross'].sum() / 100.0),
        exc10_N=('id', lambda s: int((ant.loc[s.index, 'cad_status'] == 'cross').sum())),
        noallot_km2=('area_ha', lambda s: s[ant.loc[s.index, 'cad_status'] == 'unreg'].sum() / 100.0),
        noallot_N=('id', lambda s: int((ant.loc[s.index, 'cad_status'] == 'unreg').sum())),
    )
    print('\n--- Распределение по age2000 (весь техногенный класс) ---')
    print(age_tab.round(2).to_string())

    # Поширотный, порайонный и макрозональный разрез возраста техногенных песков!
    ant['lat_band'] = pd.cut(ant['lat'], [60, 64, 66, 68, 70, 74], right=False,
                             labels=['< 64° с. ш.', '64–66° с. ш.', '66–68° с. ш.', '68–70° с. ш.', '>= 70° с. ш.'])

    def macro_zone(row):
        d = row['district'] if isinstance(row['district'], str) else ''
        sr = row['subregion']
        if sr.startswith('5.'):
            return '1. Таёжный пояс ХМАО (Сургутский, Нижневартовский и др.)'
        if 'Пуровский' in d:
            return '2. Пуровский район (северная тайга / лесотундра ЯНАО)'
        if 'Надымский' in d or 'Красноселькупский' in d or 'Приуральский' in d or 'Шурышкарский' in d:
            return '3. Надымский, Приуральский и Красноселькупский р-ны'
        if 'Ямальский' in d or 'Тазовский' in d:
            return '4. Арктические п-ова и тундра ЯНАО (Ямальский и Тазовский р-ны)'
        return '5. Приенисейско-таймырский сектор (Туруханский и вост. >=79°)'

    ant['macro_zone'] = [macro_zone(r) for _, r in ant.iterrows()]

    def summarize_age_and_cad(df_grp: pd.DataFrame, group_col: str) -> pd.DataFrame:
        piv_a = df_grp.pivot_table(index=group_col, columns='age2000', values='area_ha', aggfunc='sum', fill_value=0.0, observed=False) / 100.0
        for col_a in ('new', 'mid', 'old', 'na'):
            if col_a not in piv_a.columns:
                piv_a[col_a] = 0.0
        piv_a = piv_a[['new', 'mid', 'old', 'na']]
        piv_a['total_km2'] = piv_a.sum(axis=1)
        known = piv_a['new'] + piv_a['mid'] + piv_a['old']
        piv_a['known_km2'] = known
        piv_a['new_%_known'] = np.where(known > 0, 100.0 * piv_a['new'] / known, np.nan)
        piv_a['mid_%_known'] = np.where(known > 0, 100.0 * piv_a['mid'] / known, np.nan)
        piv_a['old_%_known'] = np.where(known > 0, 100.0 * piv_a['old'] / known, np.nan)
        piv_a['new_vs_old_%'] = np.where((piv_a['new'] + piv_a['old']) > 0,
                                         100.0 * piv_a['new'] / (piv_a['new'] + piv_a['old']), np.nan)
        cad_res = df_grp.groupby(group_col, observed=False).apply(
            lambda sub: pd.Series({
                'in_allot_km2': sub['cad_in_ha'].sum() / 100.0,
                'in_allot_%': 100.0 * sub['cad_in_ha'].sum() / np.maximum(sub['area_ha'].sum(), 1e-9),
                'exceed10_km2': sub.loc[sub['cad_status'] == 'cross', 'cad_exc10_ha'].sum() / 100.0,
                'noallot_km2': sub.loc[sub['cad_status'] == 'unreg', 'area_ha'].sum() / 100.0,
                'cad_none_km2': sub['cad_none_ha'].sum() / 100.0,
            }), include_groups=False
        )
        return pd.concat([piv_a, cad_res], axis=1)

    print('\n--- Поширотный разрез возраста (age2000, покрытие Hansen GFC 60–70° с. ш.) и ЕГРН ---')
    print(summarize_age_and_cad(ant, 'lat_band').round(2).to_string())

    print('\n--- Макрозональный разрез возраста (северная тайга ХМАО / Пуровского р-на против арктических п-овов!) ---')
    print(summarize_age_and_cad(ant, 'macro_zone').round(2).to_string())

    print('\n--- Детальный порайонный разрез возраста и ЕГРН (топ-10 районов по площади техногена + восточный сектор) ---')
    ant['dist_or_east'] = np.where(ant['district'].notna(), ant['district'],
                                   np.where(ant['lon'] >= EAST_SECTOR_LON, 'восточный сектор (>=79° в. д.)', 'вне районов'))
    dist_age_cad = summarize_age_and_cad(ant, 'dist_or_east').sort_values('total_km2', ascending=False)
    print(dist_age_cad.head(12).round(2).to_string())

    print(f'\nГотово за {time.time() - t0:.1f} с.')


if __name__ == '__main__':
    main()
