"""
158_buffer_background.py - фон 500-метровой полосы у воды, русел и моря (приложение S13; «табл. 2.3» ниже:
прежний расчёт долей по контурам целиком).

Вопрос. В статье сказано, что 61-90 % площади эоловых песков лежит не далее 500 м от воды, русел или моря. Без доли самой
территории в той же полосе это не доказывает приуроченности раздувов к долинам и берегам. Скрипт считает для каждого
ареала (assign_subregion из article_facts.py) долю территории покрытия маски (128 тайлов) в полосе и ставит рядом
долю площади эоловых песков в той же полосе, а также отношение «доля песков / доля территории». То же для полосы 2 км
от русел.

Слои полосы те же, что у полей итогового слоя (шаг 2 каскада, docs/METHODS.md, пп. 5.1, 5.2, DATA.md):
- вода: постоянная вода GSW occurrence >= 50 на сетке MERIT 90 м (max-ресэмпл), расстояние EDT до центров ячеек воды;
  растр exports/qc/step2/water90_dist.tif (python/50_step2_water_evidence.py, поле dist_water_m);
- русла: ячейки MERIT upa >= 20 км2, расстояние EDT; растр exports/qc/step2/channel90_dist.tif
  (python/50b_step2_channel_evidence.py, поле dist_channel_m);
- море: морская береговая линия OSM после отсечек «залив -> река» и берег Енисейского залива по GSW;
  exports/qc/sea_coastline.gpkg (python/44b_sea_distance_osm.py, поле dist_sea_m).
Особенности данных: граница AOI не берег, поэтому море берётся по береговой линии OSM и по суше OSM
(land polygons), а не по границе AOI; локальный GSW обрезан по AOI, поэтому моря в растре воды нет почти нигде, и оно
учитывается отдельно (береговая линия + акватория вне суши OSM внутри покрытия считается лежащей в полосе).

Метод. Расчёт на подсетке 30 м (ровно 1/3 ячейки MERIT; сетка GSW 30 м совпадает с ней со сдвигом 1 строка, 2 столбца).
Ячейка 30 м берёт признаки полосы у родительской ячейки 90 м (как поля контуров: расстояние до центра ячейки 90 м).
Площадь ячейки считается на эллипсоиде WGS84 (через аутентичную широту). Знаменатели: вся территория ареала в покрытии и
только суша (без постоянной воды GSW occurrence >= 50 на 30 м и без акватории вне суши OSM). Пески: каждый пиксель 30 м
контура (правило центра) относится к ареалу своего контура (по центроиду, как в табл. 2.3); доля площади песков в полосе
считается по пикселям (часть контура в полосе). Для сверки с табл. 2.3 приводится и прежнее определение по контурам
(контур целиком в полосе, если хоть одна его часть ближе 500 м; поля слоя, NaN = далеко).

Дополнительно: составляющие полосы (вода, русла, море по отдельности); профиль суши и эоловых песков по расстоянию до
ближайшей воды или русла (0, 0-100, 100-250, 250-500, 500-1000 м, 1-2 км, далее 2 км) и пояса профиля 0-100 м,
100-1000 м, далее 1 км; доля природных песков (эоловые + отмели + неопределённые) в полосе для сравнения с 2022 г.

Проверки шва: (1) векторная функция ареалов на ячейках против assign_subregion на случайных точках; (2) поля
dist_water_m / dist_channel_m слоя против минимума растров по ячейкам 90 м, задетым контуром (all_touched), на выборке
эоловых контуров и на всех эоловых контурах с пустыми полями; (3) табл. 2.3 воспроизводится по полям слоя.

Выход: exports/qc/article_v3_extra/buffer_background_*.csv (summary, profile, territory, sand, проверки), суммы проходов
buffer_background_accum.npz, сводка в stdout.
Запуск (из корня проекта; полный проход около 8 мин, --reuse пересчитывает таблицы из сохранённых сумм):
    PYTHONIOENCODING=utf-8 python -u python/158_buffer_background.py [--reuse]
"""
import argparse
import math
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
import shapely
from affine import Affine
from rasterio.features import geometry_mask, rasterize
from rasterio.windows import Window

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import article_facts as caf  # noqa: E402  (функции ареалов и районов, пути продукта)
import cpu_limit  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')

# ════════════════════════════════════════════════════════════════════════════
# ПАРАМЕТРЫ
# ════════════════════════════════════════════════════════════════════════════
ROOT = Path(r'D:\test\baresand_zapsib')
EXPORTS = ROOT / 'exports'
AUX = Path('\\\\?\\' + str(EXPORTS / 'aux'))       # «aux» зарезервировано в Windows: только с префиксом \\?\
WATER_DIST_TIF = EXPORTS / 'qc' / 'step2' / 'water90_dist.tif'
CHAN_DIST_TIF = EXPORTS / 'qc' / 'step2' / 'channel90_dist.tif'
GSW_TIF = EXPORTS / 'gsw_occurrence_AOI.vrt'
COAST_GPKG = EXPORTS / 'qc' / 'sea_coastline.gpkg'
LAND_SHP = AUX / 'osm_land' / 'land-polygons-split-4326' / 'land_polygons.shp'
OUT_DIR = EXPORTS / 'qc' / 'article_v3_extra'

BAND_M = caf.HYDRO_BUFFER_2022_M            # 500 м (как в табл. 2.3 и статье 2022 г.)
CHAN_BAND_M = caf.TERRACE_CHANNEL_DIST_M    # 2 000 м от русел MERIT
DIST_EDGES_M = [0.5, 100.0, 250.0, 500.0, 1000.0, 2000.0]   # профиль: границы классов расстояния до воды или русла
NEAR_BINS, MID_BINS, FAR_BINS = (0, 1), (2, 3, 4), (5, 6)   # 0-100 м, 100-1000 м, далее 1 км
NATURAL = ('aeolian', 'alluvial_littoral', 'undefined')     # природные пески (для сравнения со статьёй 2022 г.)
DIST_LABELS = ['0 (ячейка воды или русла)', '0-100 м', '100-250 м', '250-500 м', '500-1000 м', '1-2 км', '> 2 км']
WATER_OCC = 50                              # постоянная вода, как в 50_step2_water_evidence.py
SUB = 3                                     # подсетка: 90 м / 3 = 30 м
STRIP_ROWS90 = 200                          # строк сетки 90 м в полосе обработки
LAND_BBOX = (60.0, 60.0, 92.0, 74.0)        # окно чтения суши OSM (EPSG:4326)
N_CHECK_SUB = 40_000                        # случайных точек для проверки векторной функции ареалов
N_CHECK_DIST = 20_000                       # эоловых контуров для проверки полей расстояний по растрам
SEED = 20261120
WGS84_A, WGS84_F = 6378137.0, 1 / 298.257223563

CLASSES = ['aeolian', 'anthropogenic', 'alluvial_littoral', 'undefined']
# названия ареалов дословно как возвращает caf.assign_subregion (совпадение проверяется assert при загрузке)
SUBREGIONS = [
    '1а. П-ов Ямал: северный ареал (>= 70° с. ш.)',
    '1б. П-ов Ямал: южно-центральный ареал (67,5–70° с. ш.)',
    '1в. П-ов Ямал: южная низменная окраина (< 67,5° с. ш.)',
    '2а. Полуостров Гыдан (сектор ЯНАО)',
    '2б. Полуостров Гыдан (восточное крыло вне границ OSM, >=79° в. д.)',
    '3. Тазовский полуостров',
    '4а. Бассейны, террасы и междуречья Надыма, Пура и Таза',
    '4б. Приуральско-Нижнеобский сектор',
    '5. Сургутско-Нижневартовский таёжный пояс (ХМАО)',
    '6. Приенисейско-таймырский сектор',
]
# сводные группы ареалов для сравнения со статьёй 2022 г.
GROUPS = {
    'Ямал (1а-1в)': ('1а.', '1б.', '1в.'),
    'Гыдан (2а-2б)': ('2а.', '2б.'),
    'Ямал + Гыдан (1а-2б), сопоставимо с 2022 г.': ('1а.', '1б.', '1в.', '2а.', '2б.'),
    'Ямал + Гыдан + Тазовский п-ов (1а-3)': ('1а.', '1б.', '1в.', '2а.', '2б.', '3.'),
    'Всё покрытие': tuple(s.split(' ')[0] for s in SUBREGIONS),
}
REF_2022 = {'territory_in_band_pct': 87.2, 'sand_in_band_pct': 96.19}   # стр. 28 статьи 2022 г.

T0 = time.time()


def log(msg: str) -> None:
    print(f'[{(time.time() - T0) / 60:5.1f} мин] {msg}', flush=True)


# ════════════════════════════════════════════════════════════════════════════
# ГЕОМЕТРИЯ СЕТКИ
# ════════════════════════════════════════════════════════════════════════════

def authalic_sin(lat_deg: np.ndarray) -> np.ndarray:
    """sin аутентичной широты на эллипсоиде WGS84 (для точной площади ячеек сетки широта-долгота)."""
    e2 = WGS84_F * (2 - WGS84_F)
    e = math.sqrt(e2)
    s = np.sin(np.radians(lat_deg))

    def q(sp):
        return (1 - e2) * (sp / (1 - e2 * sp * sp) - (1 / (2 * e)) * np.log((1 - e * sp) / (1 + e * sp)))
    return q(s) / q(np.array(1.0))


def row_areas_m2(tr: Affine, row0: int, nrows: int) -> np.ndarray:
    """Площадь ячейки (м2) для строк row0..row0+nrows-1 сетки с преобразованием tr (EPSG:4326)."""
    e2 = WGS84_F * (2 - WGS84_F)
    e = math.sqrt(e2)
    qp = (1 - e2) * (1 / (1 - e2) - (1 / (2 * e)) * math.log((1 - e) / (1 + e)))
    rq2 = WGS84_A ** 2 * qp / 2
    lat_top = tr.f + tr.e * (row0 + np.arange(nrows))
    lat_bot = lat_top + tr.e
    return rq2 * math.radians(abs(tr.a)) * np.abs(authalic_sin(lat_top) - authalic_sin(lat_bot))


# ════════════════════════════════════════════════════════════════════════════
# АРЕАЛЫ НА ЯЧЕЙКАХ (векторная копия caf.assign_subregion)
# ════════════════════════════════════════════════════════════════════════════

def district_flags(names: list[str]) -> dict[str, np.ndarray]:
    """Признаки района по тексту названия (те же проверки вхождения, что в assign_subregion); индекс 0 = вне районов."""
    def arr(pred) -> np.ndarray:
        return np.array([False] + [pred(n) for n in names])
    return {
        'empty': np.array([True] + [False] * len(names)),
        'yamal': arr(lambda d: 'Ямальский' in d),
        'nad_taz': arr(lambda d: 'Надымский' in d or 'Тазовский' in d),
        'turukh': arr(lambda d: 'Туруханский' in d),
        'priural': arr(lambda d: 'Приуральский' in d or 'Шурышкарский' in d),
        'basin': arr(lambda d: any(k in d for k in ('Надымский', 'Пуровский', 'Красноселькупский', 'Тазовский'))),
    }


def subregion_codes(dcode: np.ndarray, lon: np.ndarray, lat: np.ndarray, fl: dict[str, np.ndarray]) -> np.ndarray:
    """Код ареала 1..10 (индекс в SUBREGIONS + 1) по коду района, долготе и широте; порядок правил как в assign_subregion."""
    empty, yamal = fl['empty'][dcode], fl['yamal'][dcode]
    nad_taz, turukh = fl['nad_taz'][dcode], fl['turukh'][dcode]
    priural, basin = fl['priural'][dcode], fl['basin'][dcode]
    taz_box = ((lat >= caf.TAZ_PENINSULA_MIN_LAT) & (lat <= caf.TAZ_PENINSULA_MAX_LAT)
               & (lon >= caf.TAZ_PENINSULA_MIN_LON) & (lon <= caf.TAZ_PENINSULA_MAX_LON))
    gyd = (lat >= caf.GYDAN_MIN_LAT) & (lon > caf.TAZ_PENINSULA_MIN_LON)
    conds = [
        yamal & (lat >= caf.YAMAL_NORTH_LAT),
        yamal & (lat >= caf.YAMAL_CENTRAL_MIN_LAT),
        yamal,
        taz_box & (nad_taz | empty),
        gyd & nad_taz,
        gyd & empty & (lon < 83.5),
        turukh | (empty & (lon >= caf.EAST_SECTOR_LON)),
        priural,
        basin | empty,
    ]
    codes = [1, 2, 3, 6, 4, 5, 10, 8, 7]
    return np.select(conds, codes, default=9).astype(np.uint8)


# ════════════════════════════════════════════════════════════════════════════
# ЗАГРУЗКА
# ════════════════════════════════════════════════════════════════════════════

def load_product(cov_geom, d6: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Итоговый слой: поля расстояний, ареал контура по центроиду (как в article_facts.main)."""
    cols = ['id', 'area_ha', 'genesis_main', 'dist_water_m', 'dist_channel_m', 'dist_sea_m']
    g = pyogrio.read_dataframe(caf.PRODUCT_GPKG, layer='genesis', columns=cols)
    assert g.crs.to_epsg() == caf.TARGET_CRS
    cen = g.geometry.centroid
    c4326 = gpd.GeoSeries(cen, crs=caf.TARGET_CRS).to_crs(4326)
    g['lon'], g['lat'] = c4326.x.to_numpy(), c4326.y.to_numpy()
    pts = gpd.GeoDataFrame(g[['id']], geometry=cen, crs=caf.TARGET_CRS)
    j = gpd.sjoin(pts, d6[['name', 'district', 'geometry']], how='left', predicate='within')
    j = j[~j.index.duplicated()]
    g['district'] = j['district'].to_numpy()
    g['subregion'] = [caf.assign_subregion(d, lo, la) for d, lo, la in zip(g['district'], g['lon'], g['lat'])]
    return g


def contour_level_table(g: gpd.GeoDataFrame) -> pd.DataFrame:
    """Табл. 2.3 по полям слоя: контур в полосе, если хоть одно поле расстояния <= порога (NaN = далеко)."""
    ae = g[g['genesis_main'] == 'aeolian']
    near = ((ae['dist_water_m'].fillna(9e9) <= BAND_M) | (ae['dist_channel_m'].fillna(9e9) <= BAND_M)
            | (ae['dist_sea_m'].fillna(9e9) <= BAND_M))
    chan = ae['dist_channel_m'].fillna(9e9) <= CHAN_BAND_M
    t = pd.DataFrame({
        'aeol_km2': ae.groupby('subregion')['area_ha'].sum() / 100.0,
        'aeol_band500_km2': ae[near].groupby('subregion')['area_ha'].sum() / 100.0,
        'aeol_chan2km_km2': ae[chan].groupby('subregion')['area_ha'].sum() / 100.0,
    }).fillna(0.0)
    return t


# ════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКИ ШВА
# ════════════════════════════════════════════════════════════════════════════

def check_subregion_raster(dist_r: np.ndarray, tr90: Affine, names: list[str], fl: dict[str, np.ndarray],
                           d6: gpd.GeoDataFrame, cov4326) -> pd.DataFrame:
    """Векторная функция ареалов на растре районов против assign_subregion на случайных точках покрытия."""
    rng = np.random.default_rng(SEED)
    xmin, ymin, xmax, ymax = cov4326.bounds
    lon = rng.uniform(xmin, xmax, N_CHECK_SUB * 3)
    lat = rng.uniform(ymin, ymax, N_CHECK_SUB * 3)
    inside = shapely.contains_xy(cov4326, lon, lat)
    lon, lat = lon[inside][:N_CHECK_SUB], lat[inside][:N_CHECK_SUB]
    # эталон: точка -> район sjoin (как у контуров) -> assign_subregion
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lon, lat), crs=4326).to_crs(caf.TARGET_CRS)
    j = gpd.sjoin(pts, d6[['district', 'geometry']], how='left', predicate='within')
    j = j[~j.index.duplicated()]
    ref = np.array([caf.assign_subregion(d, lo, la) for d, lo, la in zip(j['district'], lon, lat)])
    # растр: район ячейки 90 м под точкой, ареал по координатам центра ячейки (как в основном расчёте)
    col = np.floor((lon - tr90.c) / tr90.a).astype(int)
    row = np.floor((lat - tr90.f) / tr90.e).astype(int)
    lon_c = tr90.c + (col + 0.5) * tr90.a
    lat_c = tr90.f + (row + 0.5) * tr90.e
    code = subregion_codes(dist_r[row, col], lon_c, lat_c, fl)
    got = np.array(SUBREGIONS)[code - 1]
    ok = got == ref
    res = pd.DataFrame({'ref': ref, 'ok': ok}).groupby('ref')['ok'].agg(['size', 'mean'])
    res.loc['ВСЕГО'] = [len(ok), ok.mean()]
    return res


def check_distance_fields(g: gpd.GeoDataFrame, wdist: np.ndarray, cdist: np.ndarray, tr90: Affine) -> pd.DataFrame:
    """Минимум растров расстояния по ячейкам 90 м, задетым контуром (all_touched, как в 50/50b), против полей слоя."""
    ae = g[g['genesis_main'] == 'aeolian']
    rng = np.random.default_rng(SEED)
    samp = ae.iloc[rng.choice(len(ae), size=min(N_CHECK_DIST, len(ae)), replace=False)]
    extra = ae[ae['dist_water_m'].isna() | ae['dist_channel_m'].isna()]
    sel = pd.concat([samp, extra[~extra.index.isin(samp.index)]])
    geoms = sel.geometry.to_crs(4326).to_numpy()
    inv = ~tr90
    H, W = wdist.shape
    rows = []
    for (idx, r), geom in zip(sel.iterrows(), geoms):
        x0, y0, x1, y1 = geom.bounds
        c0, r0 = inv * (x0, y1)
        c1, r1 = inv * (x1, y0)
        c0, r0 = max(int(math.floor(c0)) - 1, 0), max(int(math.floor(r0)) - 1, 0)
        c1, r1 = min(int(math.ceil(c1)) + 1, W), min(int(math.ceil(r1)) + 1, H)
        wtr = tr90 * Affine.translation(c0, r0)
        m = ~geometry_mask([geom], out_shape=(r1 - r0, c1 - c0), transform=wtr, all_touched=True)
        if not m.any():
            rows.append((r['id'], r['dist_water_m'], r['dist_channel_m'], np.nan, np.nan, idx in samp.index))
            continue
        rows.append((r['id'], r['dist_water_m'], r['dist_channel_m'],
                     float(np.round(wdist[r0:r1, c0:c1][m].min())), float(np.round(cdist[r0:r1, c0:c1][m].min())),
                     idx in samp.index))
    return pd.DataFrame(rows, columns=['id', 'dist_water_m', 'dist_channel_m', 'water_raster_m', 'chan_raster_m', 'random'])


# ════════════════════════════════════════════════════════════════════════════
# ОСНОВНОЙ РАСЧЁТ ПО ПОЛОСАМ
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description='Фон полосы 500 м и 2 км: территория против эоловых песков.')
    ap.add_argument('--reuse', action='store_true',
                    help='взять суммы проходов по полосам из buffer_background_accum.npz (без растеризации)')
    args = ap.parse_args()
    cpu_limit.apply()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    log('покрытие, районы OSM (load_admin_districts из article_facts)...')
    cov = gpd.read_file(caf.COVERAGE_GPKG, layer='coverage').to_crs(caf.TARGET_CRS)
    cov_geom = shapely.make_valid(cov.geometry.union_all())
    cov4326 = gpd.GeoSeries([cov_geom], crs=caf.TARGET_CRS).to_crs(4326).iloc[0]
    d6, _ = caf.load_admin_districts(cov_geom)
    names = sorted(d6['district'].dropna().unique().tolist())
    name_code = {n: i + 1 for i, n in enumerate(names)}
    fl = district_flags(names)

    log('итоговый слой и ареалы контуров...')
    g = load_product(cov_geom, d6)
    log(f'  контуров {len(g):,}, эоловых {int((g.genesis_main == "aeolian").sum()):,}')
    t23 = contour_level_table(g)

    with rasterio.open(WATER_DIST_TIF) as s:
        tr90, H90, W90, crs90 = s.transform, s.height, s.width, s.crs
        wdist = s.read(1)
    with rasterio.open(CHAN_DIST_TIF) as s:
        assert s.transform == tr90 and s.shape == (H90, W90)
        cdist = s.read(1)
    log(f'растры расстояний 90 м: {H90} x {W90}')

    # растр районов на сетке 90 м: первая строка d6 побеждает (как ~duplicated в sjoin), поэтому жжём в обратном порядке
    d6_4326 = d6.to_crs(4326)
    shapes_d = [(geom, name_code[d]) for geom, d in zip(d6_4326.geometry[::-1], d6_4326['district'][::-1])
                if isinstance(d, str)]
    dist_r = rasterize(shapes_d, out_shape=(H90, W90), transform=tr90, fill=0, dtype='uint8')
    log('растр районов готов; проверка векторной функции ареалов...')
    chk_sub = check_subregion_raster(dist_r, tr90, names, fl, d6, cov4326)
    print(chk_sub.round(4).to_string())
    chk_sub.to_csv(OUT_DIR / 'buffer_background_check_subregion.csv', encoding='utf-8')

    log('проверка полей расстояний по растрам...')
    chk_d = check_distance_fields(g, wdist, cdist, tr90)
    chk_d.to_csv(OUT_DIR / 'buffer_background_check_distfields.csv', index=False, encoding='utf-8')
    rnd = chk_d[chk_d['random']]
    for fld, rcol in (('dist_water_m', 'water_raster_m'), ('dist_channel_m', 'chan_raster_m')):
        ok = rnd[fld].notna() & rnd[rcol].notna()
        diff = (rnd.loc[ok, fld] - rnd.loc[ok, rcol]).abs()
        side_f = rnd.loc[ok, fld] <= BAND_M
        side_r = rnd.loc[ok, rcol] <= BAND_M
        print(f'  {fld}: выборка {int(ok.sum()):,}; |поле - растр| = 0 у {100 * (diff < 0.5).mean():.2f} %, '
              f'p99 {diff.quantile(0.99):.0f} м; сторона порога {BAND_M:.0f} м совпала у {100 * (side_f == side_r).mean():.2f} %')
    # табл. 2.3 с пустыми полями, заполненными минимумом растра (поля пусты у контуров дальше 3 км и у части разрезов)
    fill = chk_d.set_index('id')
    g_f = g.copy()
    for fld, rcol in (('dist_water_m', 'water_raster_m'), ('dist_channel_m', 'chan_raster_m')):
        m = g_f[fld].isna() & g_f['id'].isin(fill.index)
        g_f.loc[m, fld] = g_f.loc[m, 'id'].map(fill[rcol])
    t23f = contour_level_table(g_f)
    nan_w = chk_d[chk_d['dist_water_m'].isna()]
    nan_c = chk_d[chk_d['dist_channel_m'].isna()]
    print(f'  эоловые с пустым dist_water_m: {len(nan_w):,}; по растру <= {BAND_M:.0f} м: '
          f'{int((nan_w.water_raster_m <= BAND_M).sum()):,}, <= 3000 м: {int((nan_w.water_raster_m <= 3000).sum()):,}, '
          f'минимум {nan_w.water_raster_m.min():.0f} м')
    print(f'  эоловые с пустым dist_channel_m: {len(nan_c):,}; по растру <= {BAND_M:.0f} м: '
          f'{int((nan_c.chan_raster_m <= BAND_M).sum()):,}, <= {CHAN_BAND_M:.0f} м: {int((nan_c.chan_raster_m <= CHAN_BAND_M).sum()):,}')

    # береговая линия моря: буфер BAND_M (EPSG:3576) -> EPSG:4326
    coast = gpd.read_file(COAST_GPKG, layer='coastline')
    assert coast.crs.to_epsg() == caf.TARGET_CRS
    sea_buf = gpd.GeoSeries([shapely.union_all(coast.geometry.buffer(BAND_M).to_numpy())], crs=caf.TARGET_CRS)
    sea_buf4326 = sea_buf.to_crs(4326).iloc[0]
    log(f'буфер берега моря {BAND_M:.0f} м: {sea_buf.area.iloc[0] / 1e6:,.0f} км2')

    land = gpd.read_file(LAND_SHP, bbox=LAND_BBOX)
    land_geoms = land.geometry.to_numpy()
    land_tree = shapely.STRtree(land_geoms)
    log(f'суша OSM: {len(land):,} полигонов в окне')

    # пески: код = ареал * 8 + класс (1..4), правило центра пикселя 30 м
    g4326 = g.geometry.to_crs(4326).to_numpy()
    sub_idx = g['subregion'].map({s: i + 1 for i, s in enumerate(SUBREGIONS)}).to_numpy()
    assert not np.isnan(sub_idx.astype(float)).any(), 'ареал контура вне списка SUBREGIONS'
    cls_idx = g['genesis_main'].map({c: i + 1 for i, c in enumerate(CLASSES)}).to_numpy()
    assert not np.isnan(cls_idx.astype(float)).any(), 'класс вне списка CLASSES'
    sand_code = (sub_idx * 8 + cls_idx).astype(np.uint8)
    sand_tree = shapely.STRtree(g4326)

    tr30 = tr90 * Affine.scale(1.0 / SUB)
    W30 = W90 * SUB
    gsw = rasterio.open(GSW_TIF)
    # сдвиг сетки GSW относительно подсетки 30 м (ожидается 1 строка, 2 столбца)
    off_c = (gsw.transform.c - tr30.c) / tr30.a
    off_r = (gsw.transform.f - tr30.f) / tr30.e
    assert abs(gsw.transform.a - tr30.a) < 1e-12 and abs(off_c - round(off_c)) < 1e-6 and abs(off_r - round(off_r)) < 1e-6, \
        'сетка GSW не совпадает с подсеткой 30 м'
    off_c, off_r = int(round(off_c)), int(round(off_r))
    log(f'сетка GSW = подсетка 30 м со сдвигом строк {off_r}, столбцов {off_c}')

    NB = len(DIST_EDGES_M) + 1            # классы расстояния до ближайшей воды или русла
    NF_T, NF_S = 64, 32                   # флаги: вода500, русло500, море500, русло2км, (вода30 у территории), море30
    K_T = (len(SUBREGIONS) + 1) * NF_T * NB
    K_S = 90 * NF_S * NB
    terr = np.zeros(K_T)
    sand = np.zeros(K_S)
    cols90 = np.arange(W90)
    lon90 = tr90.c + (cols90 + 0.5) * tr90.a

    accum = OUT_DIR / 'buffer_background_accum.npz'
    rows90 = [] if args.reuse else range(0, H90, STRIP_ROWS90)
    for r0 in rows90:
        r1 = min(H90, r0 + STRIP_ROWS90)
        n90 = r1 - r0
        tr_s90 = tr90 * Affine.translation(0, r0)
        # признаки 90 м
        lat90 = tr90.f + (np.arange(r0, r1) + 0.5) * tr90.e
        sub90 = subregion_codes(dist_r[r0:r1], np.broadcast_to(lon90, (n90, W90)),
                                np.broadcast_to(lat90[:, None], (n90, W90)), fl)
        seab = rasterize([(sea_buf4326, 1)], out_shape=(n90, W90), transform=tr_s90, fill=0, dtype='uint8').astype(bool)
        wd, cd = wdist[r0:r1], cdist[r0:r1]
        f90 = ((wd <= BAND_M).astype(np.uint8) | ((cd <= BAND_M).astype(np.uint8) << 1) | (seab.astype(np.uint8) << 2)
               | ((cd <= CHAN_BAND_M).astype(np.uint8) << 3))
        d90 = np.digitize(np.minimum(wd, cd), DIST_EDGES_M, right=True).astype(np.uint8)
        del seab, wd, cd
        # подсетка 30 м
        R0, n30 = r0 * SUB, n90 * SUB
        tr_s30 = tr30 * Affine.translation(0, R0)
        sub30 = np.repeat(np.repeat(sub90, SUB, axis=0), SUB, axis=1)
        f30 = np.repeat(np.repeat(f90, SUB, axis=0), SUB, axis=1)
        d30 = np.repeat(np.repeat(d90, SUB, axis=0), SUB, axis=1)
        del sub90, f90, d90
        bbox = shapely.box(tr90.c, lat90[-1] + tr90.e, tr90.c + W90 * tr90.a, lat90[0] - tr90.e)
        cov30 = rasterize([(cov4326, 1)], out_shape=(n30, W30), transform=tr_s30, fill=0, dtype='uint8').astype(bool)
        if not cov30.any():
            continue
        li = land_tree.query(bbox, predicate='intersects')
        land30 = rasterize(((land_geoms[i], 1) for i in li), out_shape=(n30, W30), transform=tr_s30, fill=0,
                           dtype='uint8').astype(bool) if len(li) else np.zeros((n30, W30), bool)
        sea30 = cov30 & ~land30
        del land30
        win = Window(-off_c, R0 - off_r, W30, n30)
        occ = gsw.read(1, window=win, boundless=True, fill_value=0)
        water30 = occ >= WATER_OCC
        del occ
        area_row = row_areas_m2(tr30, R0, n30)
        # территория: ареал ячейки x флаги x класс расстояния, только в покрытии
        flags_t = f30.astype(np.int64) | (water30.astype(np.int64) << 4) | (sea30.astype(np.int64) << 5)
        rr, cc = np.nonzero(cov30)
        idx = rr.astype(np.int64) * K_T + (sub30[rr, cc].astype(np.int64) * NF_T + flags_t[rr, cc]) * NB + d30[rr, cc]
        cnt = np.bincount(idx, minlength=n30 * K_T).reshape(n30, K_T)
        terr += (cnt * area_row[:, None]).sum(axis=0)
        del rr, cc, idx, cnt, cov30, sub30, flags_t, water30
        # пески
        si = sand_tree.query(bbox, predicate='intersects')
        if len(si):
            sr = rasterize(((g4326[i], int(sand_code[i])) for i in si), out_shape=(n30, W30), transform=tr_s30,
                           fill=0, dtype='uint8')
            rr, cc = np.nonzero(sr)
            fl_s = f30[rr, cc].astype(np.int64) | (sea30[rr, cc].astype(np.int64) << 4)
            idx = rr.astype(np.int64) * K_S + (sr[rr, cc].astype(np.int64) * NF_S + fl_s) * NB + d30[rr, cc]
            cnt = np.bincount(idx, minlength=n30 * K_S).reshape(n30, K_S)
            sand += (cnt * area_row[:, None]).sum(axis=0)
            del sr, rr, cc, idx, cnt, fl_s
        del f30, d30, sea30
        log(f'  строки 90 м {r0}-{r1} из {H90}: территория {terr.sum() / 1e6:,.0f} км2, пески {sand.sum() / 1e6:,.1f} км2')
    gsw.close()

    # ── таблицы ──
    if args.reuse:
        z = np.load(accum)
        terr, sand = z['terr'], z['sand']
        assert terr.shape == (K_T,) and sand.shape == (K_S,), 'суммы посчитаны с другой разбивкой кодов'
        log(f'суммы проходов взяты из {accum.name}')
    else:
        np.savez(accum, terr=terr, sand=sand)
    ct = np.arange(K_T)
    ft = (ct % (NF_T * NB)) // NB
    tt = pd.DataFrame({'code': ct, 'km2': terr / 1e6, 'sub': ct // (NF_T * NB), 'dbin': ct % NB,
                       'w500': (ft & 1).astype(bool), 'c500': ((ft >> 1) & 1).astype(bool),
                       's500': ((ft >> 2) & 1).astype(bool), 'chan2km': ((ft >> 3) & 1).astype(bool),
                       'water': ((ft >> 4) & 1).astype(bool), 'sea': ((ft >> 5) & 1).astype(bool)})
    tt['band'] = tt['w500'] | tt['c500'] | tt['s500'] | tt['sea']
    tt = tt[tt['km2'] > 0]
    tt['subregion'] = tt['sub'].map(lambda k: SUBREGIONS[k - 1] if k > 0 else 'нет')
    tt.to_csv(OUT_DIR / 'buffer_background_territory.csv', index=False, encoding='utf-8')
    cs = np.arange(K_S)
    fs = (cs % (NF_S * NB)) // NB
    st = pd.DataFrame({'code': cs, 'km2': sand / 1e6, 'sand': cs // (NF_S * NB), 'dbin': cs % NB,
                       'w500': (fs & 1).astype(bool), 'c500': ((fs >> 1) & 1).astype(bool),
                       's500': ((fs >> 2) & 1).astype(bool), 'chan2km': ((fs >> 3) & 1).astype(bool),
                       'sea': ((fs >> 4) & 1).astype(bool)})
    st['band'] = st['w500'] | st['c500'] | st['s500'] | st['sea']
    st = st[(st['km2'] > 0) & (st['sand'] > 0)]
    st['subregion'] = st['sand'].map(lambda k: SUBREGIONS[k // 8 - 1])
    st['class'] = st['sand'].map(lambda k: CLASSES[k % 8 - 1])
    st.to_csv(OUT_DIR / 'buffer_background_sand.csv', index=False, encoding='utf-8')

    def pct(df: pd.DataFrame, mask: pd.Series) -> float:
        return 100 * df.loc[mask, 'km2'].sum() / df['km2'].sum()

    def summarize(prefixes: tuple[str, ...]) -> dict[str, float]:
        """Доли территории и эоловых песков в полосах для набора ареалов."""
        t = tt[tt['subregion'].str.startswith(prefixes)]
        land = t[~t['water'] & ~t['sea']]
        s = st[st['subregion'].str.startswith(prefixes) & (st['class'] == 'aeolian')]
        sn = st[st['subregion'].str.startswith(prefixes) & st['class'].isin(NATURAL)]
        c = t23[t23.index.str.startswith(prefixes)].sum()
        cf = t23f[t23f.index.str.startswith(prefixes)].sum()
        out = {
            'terr_km2': t['km2'].sum(), 'land_km2': land['km2'].sum(),
            'water_sea_pct': pct(t, t['water'] | t['sea']),
            'terr_band_pct': pct(t, t['band']), 'land_band_pct': pct(land, land['band']),
            'terr_chan_pct': pct(t, t['chan2km']), 'land_chan_pct': pct(land, land['chan2km']),
            'land_w500_pct': pct(land, land['w500']), 'land_c500_pct': pct(land, land['c500']),
            'land_s500_pct': pct(land, land['s500']),
            'aeol_px_km2': s['km2'].sum(), 'aeol_vec_km2': c['aeol_km2'],
            'aeol_band_px_pct': pct(s, s['band']),
            'aeol_band_cont_pct': 100 * c['aeol_band500_km2'] / c['aeol_km2'],
            'aeol_band_cont_fill_pct': 100 * cf['aeol_band500_km2'] / cf['aeol_km2'],
            'aeol_chan_px_pct': pct(s, s['chan2km']),
            'aeol_chan_cont_pct': 100 * c['aeol_chan2km_km2'] / c['aeol_km2'],
            'aeol_chan_cont_fill_pct': 100 * cf['aeol_chan2km_km2'] / cf['aeol_km2'],
            'aeol_w500_px_pct': pct(s, s['w500']), 'aeol_c500_px_pct': pct(s, s['c500']),
            'aeol_s500_px_pct': pct(s, s['s500']),
            'nat_band_px_pct': pct(sn, sn['band']),
            'land_mid_pct': pct(land, land['dbin'].isin(MID_BINS)), 'aeol_mid_pct': pct(s, s['dbin'].isin(MID_BINS)),
            'land_near_pct': pct(land, land['dbin'].isin(NEAR_BINS)), 'aeol_near_pct': pct(s, s['dbin'].isin(NEAR_BINS)),
            'land_far_pct': pct(land, land['dbin'].isin(FAR_BINS)), 'aeol_far_pct': pct(s, s['dbin'].isin(FAR_BINS)),
        }
        out['ratio_nat_band_land'] = out['nat_band_px_pct'] / out['land_band_pct']
        out['ratio_mid'] = out['aeol_mid_pct'] / out['land_mid_pct']
        out['ratio_near'] = out['aeol_near_pct'] / out['land_near_pct']
        out['ratio_far'] = out['aeol_far_pct'] / out['land_far_pct']
        out['ratio_band_land'] = out['aeol_band_px_pct'] / out['land_band_pct']
        out['ratio_band_terr'] = out['aeol_band_px_pct'] / out['terr_band_pct']
        out['ratio_chan_land'] = out['aeol_chan_px_pct'] / out['land_chan_pct']
        out['ratio_band_cont_land'] = out['aeol_band_cont_pct'] / out['land_band_pct']
        out['ratio_w500_land'] = out['aeol_w500_px_pct'] / out['land_w500_pct']
        out['ratio_c500_land'] = out['aeol_c500_px_pct'] / out['land_c500_pct']
        out['ratio_s500_land'] = out['aeol_s500_px_pct'] / out['land_s500_pct'] if out['land_s500_pct'] > 0 else np.nan
        out['out_band_land_pct'] = 100 - out['land_band_pct']
        out['out_band_aeol_px_pct'] = 100 - out['aeol_band_px_pct']
        return out

    def profile(prefixes: tuple[str, ...]) -> pd.DataFrame:
        """Распределение суши и эоловых песков по расстоянию до ближайшей воды или русла (без моря), % и отношение."""
        t = tt[tt['subregion'].str.startswith(prefixes) & ~tt['water'] & ~tt['sea']]
        s = st[st['subregion'].str.startswith(prefixes) & (st['class'] == 'aeolian')]
        sn = st[st['subregion'].str.startswith(prefixes) & st['class'].isin(NATURAL)]
        lt = t.groupby('dbin')['km2'].sum().reindex(range(NB), fill_value=0.0)
        ls = s.groupby('dbin')['km2'].sum().reindex(range(NB), fill_value=0.0)
        ln = sn.groupby('dbin')['km2'].sum().reindex(range(NB), fill_value=0.0)
        out = pd.DataFrame({'bin': DIST_LABELS, 'land_km2': lt.values, 'land_pct': 100 * lt.values / lt.sum(),
                            'aeol_km2': ls.values, 'aeol_pct': 100 * ls.values / ls.sum()})
        out['ratio'] = out['aeol_pct'] / out['land_pct']
        out['nat_pct'] = 100 * ln.values / ln.sum()       # природные пески: не зависят от разделения эоловые / отмели
        out['nat_ratio'] = out['nat_pct'] / out['land_pct']
        return out

    rows = {s: summarize((s.split(' ')[0],)) for s in SUBREGIONS}
    rows.update({k: summarize(v) for k, v in GROUPS.items()})
    summ = pd.DataFrame(rows).T
    summ.to_csv(OUT_DIR / 'buffer_background_summary.csv', encoding='utf-8')

    pd.set_option('display.width', 250)
    print('\n' + '=' * 100)
    print(f'ПОЛОСА {BAND_M:.0f} М ОТ ВОДЫ GSW / РУСЕЛ MERIT (>= 20 км2) / МОРЯ: ТЕРРИТОРИЯ И ЭОЛОВЫЕ ПЕСКИ')
    print('=' * 100)
    show = ['terr_km2', 'water_sea_pct', 'terr_band_pct', 'land_band_pct', 'aeol_vec_km2', 'aeol_band_px_pct',
            'aeol_band_cont_pct', 'aeol_band_cont_fill_pct', 'ratio_band_land', 'ratio_band_terr']
    print(summ[show].round(2).to_string())
    print('\n' + '=' * 100)
    print(f'ПОЛОСА {CHAN_BAND_M:.0f} М ОТ РУСЕЛ MERIT')
    print('=' * 100)
    show2 = ['terr_chan_pct', 'land_chan_pct', 'aeol_chan_px_pct', 'aeol_chan_cont_pct', 'aeol_chan_cont_fill_pct',
             'ratio_chan_land']
    print(summ[show2].round(2).to_string())
    print('\n' + '=' * 100)
    print(f'СОСТАВЛЯЮЩИЕ ПОЛОСЫ {BAND_M:.0f} М (доли суши и эоловых песков по пикселям, %; отношение песков к суше)')
    print('=' * 100)
    show3 = ['land_w500_pct', 'aeol_w500_px_pct', 'ratio_w500_land', 'land_c500_pct', 'aeol_c500_px_pct', 'ratio_c500_land',
             'land_s500_pct', 'aeol_s500_px_pct', 'ratio_s500_land']
    print(summ[show3].round(2).to_string())
    print('\nПОЯСА ПРОФИЛЯ (суша без воды и моря; эоловые по пикселям), % и отношение; природные пески в полосе 500 м')
    show4 = ['land_near_pct', 'aeol_near_pct', 'ratio_near', 'land_mid_pct', 'aeol_mid_pct', 'ratio_mid', 'land_far_pct',
             'aeol_far_pct', 'ratio_far', 'nat_band_px_pct', 'ratio_nat_band_land']
    print(summ[show4].round(2).to_string())
    prof_rows = []
    for name, pref in list(GROUPS.items()) + [(s_, (s_.split(' ')[0],)) for s_ in SUBREGIONS]:
        pr = profile(pref)
        pr.insert(0, 'group', name)
        prof_rows.append(pr)
    prof = pd.concat(prof_rows)
    prof.to_csv(OUT_DIR / 'buffer_background_profile.csv', index=False, encoding='utf-8')
    print('\nПРОФИЛЬ: распределение суши и эоловых песков по расстоянию до ближайшей воды GSW или русла MERIT, %')
    for name in ('Ямал + Гыдан (1а-2б), сопоставимо с 2022 г.', SUBREGIONS[0], SUBREGIONS[1], SUBREGIONS[3],
                 SUBREGIONS[6], SUBREGIONS[8], 'Всё покрытие'):
        print(f'\n[{name}]')
        print(prof[prof['group'] == name].drop(columns='group').round(2).to_string(index=False))
    print('\nКонтроль: площадь территории в покрытии по растру = '
          f'{tt["km2"].sum():,.0f} км2 (вектор {cov_geom.area / 1e6:,.0f}); эоловые пиксели = '
          f'{st.loc[st["class"] == "aeolian", "km2"].sum():,.1f} км2 (вектор {t23["aeol_km2"].sum():,.1f})')
    yg = summ.loc['Ямал + Гыдан (1а-2б), сопоставимо с 2022 г.']
    print(f'Ямал + Гыдан: территория в полосе {yg.terr_band_pct:.1f} % (суша {yg.land_band_pct:.1f} %), эоловые '
          f'{yg.aeol_band_px_pct:.1f} % по пикселям / {yg.aeol_band_cont_pct:.1f} % по контурам; '
          f'2022 г.: {REF_2022["territory_in_band_pct"]} % и {REF_2022["sand_in_band_pct"]} %')
    log('готово')


if __name__ == '__main__':
    main()
