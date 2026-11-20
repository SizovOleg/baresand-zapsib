"""
159_age_north70.py - возраст техногенных контуров (age2000) без данных: север 70° с. ш. по Hansen GFC через GEE.

Определение (то же, что в продукте). python/66_step3_temporal_evidence.py: по композиту ~2000 г. Hansen GFC-2019-v1.7
(first: red, NIR, SWIR1, SWIR2, uint8, сетка 0,00025°) пиксель «голый в 2000», если red >= RED_MIN и NDVI < NDVI_MAX
(NDVI = (NIR - red) / max(NIR + red, 1)); bare2000_frac = доля таких пикселей среди пикселей 30 м, задетых контуром
(растеризация all_touched в EPSG:4326, пиксели не взвешиваются). python/133_cadastre_anthro.py, функция age2000:
new при bare2000_frac < 0,30, old при >= 0,70, mid между ними, na без данных. Константы и функция берутся из самих
скриптов 66 и 133 (importlib), чтобы определения не разошлись.

Данные. Локально (I:/Hansen/First2000) есть только листы 70N_060E, 70N_070E, 70N_080E (60-70° с. ш.). Листы 80N берутся
из GEE (UMD/hansen/global_forest_change_2019_v1_7, каналы first_b30, first_b40, first_b50, first_b70, datamask) окнами
вокруг контура через ee.data.computePixels в память; на диск пиксели не пишутся. Сетка окна привязана к сетке продукта
(начало -180°, 80°, шаг 0,00025°), поэтому пиксели те же, что в локальных листах (проверено побайтно на окне у Надыма).

Шаг 0. Шов данных: окно 400 x 300 пикселей из GEE против того же окна локального листа 70N_070E (все 4 канала).
Шаг 1. Шов двух реализаций: случайная выборка техногенных контуров южнее 70° с известным age2000 (и отдельно крупные
контуры), класс по GEE против класса в слое. Две реализации на стороне GEE: B (окно пикселей + та же растеризация
all_touched, что в 66) и A (серверная reduceRegions, среднее с долевыми весами пикселей; справочно).
Шаг 2. Все техногенные контуры с age2000 = na (1 851) по реализации B; доля площади севернее 70° без пригодных данных
композита (маска данных 0, вода по маске Hansen с обнулёнными каналами, снег/лёд и пересвет по спектру).
Шаг 3. Пересчёт чисел статьи и приложения с новыми значениями: класс в целом, группы ЕГРН (слои
baresand_anthro_cadastre_v7b.gpkg, табл. S11.5, S11.6), широтные пояса и макрозоны article_facts.py.
Прежние числа воспроизводятся и сверяются с опубликованными (assert), затем подставляется новый возраст.

Выход: exports/qc/article_v3_extra/age_north70_*.csv (в т. ч. age_north70_new_age2000.csv: id, новый age2000).
Итоговый слой не меняется. Запуск (из корня проекта):
    PYTHONIOENCODING=utf-8 python -u python/159_age_north70.py
"""
import importlib.util
import json
import math
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
import shapely
import shapely.geometry
from affine import Affine
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds

HERE = Path(__file__).resolve().parent
PYDIR = HERE
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PYDIR))
import article_facts as caf  # noqa: E402
import cpu_limit  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore', category=DeprecationWarning)   # GEE: ассет 2019_v1_7 помечен устаревшим, берём именно его

import ee  # noqa: E402

# ════════════════════════════════════════════════════════════════════════════
# ПАРАМЕТРЫ
# ════════════════════════════════════════════════════════════════════════════
ROOT = Path(r'D:\test\baresand_zapsib')
OUT_DIR = ROOT / 'exports' / 'qc' / 'article_v3_extra'
GEE_PROJECT = 'nodal-thunder-481307-u1'
HANSEN_ASSET = 'UMD/hansen/global_forest_change_2019_v1_7'     # та же версия, что локальные листы GFC-2019-v1.7
BANDS = ['first_b30', 'first_b40', 'first_b50', 'first_b70', 'datamask']
RES = 0.00025                    # шаг сетки Hansen, градусы
GRID_X0, GRID_Y0 = -180.0, 80.0  # начало сетки Hansen в GEE (crsTransform ассета)
MARGIN_PX = 3                    # запас окна вокруг контура, пикселей
TILE_PX = 2500                   # предел стороны одного запроса computePixels (5 каналов x 2500^2 < 48 МБ)
WORKERS = 6                      # параллельных запросов к GEE
RETRIES = 4
NORTH_LAT = 70.0                 # граница локальных листов 70N
N_SEAM = 600                     # случайная выборка контуров южнее 70° для проверки шва
SEAM_BIG_HA = 100.0              # и все контуры южнее 70° не меньше этой площади
SEAM_MIN_AREA_AGREE = 0.95       # порог согласия по площади
SEED = 20261120
SNOW_RED_MIN, SNOW_NDSI_MIN = 100, 0.40   # снег/лёд: яркий red при низком SWIR1, (red - SWIR1) / (red + SWIR1)
BRIGHT_RED_MIN = 200                       # пересвет (облака, снег)
LOCAL_FIRST = Path(r'I:\Hansen\First2000\Hansen_GFC-2019-v1.7_first_70N_070E.tif')   # локальный лист для сверки каналов
BAND_CHECK_WIN = (72.5, 65.6, 400, 300)   # окно сверки: левый верхний угол (долгота, широта), ширина, высота в пикселях
LAT_BINS = [60, 64, 66, 68, 70, 74]
# подписи поясов дословно как в article_facts.main (для сверки строк таблиц)
LAT_LABELS = ['< 64° с. ш.', '64–66° с. ш.', '66–68° с. ш.', '68–70° с. ш.', '>= 70° с. ш.']

# опубликованные числа (прежняя редакция табл. S11.5 и S11.6) для сверки воспроизведения
PUB_CLASS_PCT = {'new': 51.6, 'mid': 16.4, 'old': 25.3, 'na': 6.8}
PUB_EXCEED_PCT = {'new': 33.8, 'mid': 20.1, 'old': 38.4, 'na': 7.7}
PUB_NOALLOT_PCT = {'new': 71.5, 'mid': 9.4, 'old': 16.15, 'na': 2.9}
PUB_ARCTIC_NEW_PCT_KNOWN = 88.6


def load_module(name: str, fname: str):
    """Импорт скрипта проекта с именем, начинающимся с цифры."""
    spec = importlib.util.spec_from_file_location(name, PYDIR / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M66 = load_module('step3_temporal', '66_step3_temporal_evidence.py')
M133 = load_module('cadastre_anthro', '133_cadastre_anthro.py')
RED_MIN, NDVI_MAX = M66.RED_MIN, M66.NDVI_MAX
assert (RED_MIN, NDVI_MAX) == (60, 0.15), (RED_MIN, NDVI_MAX)
assert (M133.NEW_BARE_MAX, M133.OLD_BARE_MIN) == (0.30, 0.70)
age2000 = M133.age2000
AGE_ORDER = list(M133.AGE_ORDER)

T0 = time.time()


def log(msg: str) -> None:
    print(f'[{(time.time() - T0) / 60:5.1f} мин] {msg}', flush=True)


# ════════════════════════════════════════════════════════════════════════════
# GEE: ОКНА ПИКСЕЛЕЙ (реализация B) И СЕРВЕРНАЯ СВОДКА (реализация A)
# ════════════════════════════════════════════════════════════════════════════

def hansen_image() -> ee.Image:
    return ee.Image(HANSEN_ASSET).select(BANDS)


def fetch_window(img: ee.Image, gx0: float, gy0: float, w: int, h: int) -> np.ndarray:
    """Окно w x h пикселей с левым верхним углом (gx0, gy0) на сетке Hansen; повтор при сбое."""
    req = {'expression': img, 'fileFormat': 'NUMPY_NDARRAY',
           'grid': {'dimensions': {'width': w, 'height': h},
                    'affineTransform': {'scaleX': RES, 'shearX': 0, 'translateX': gx0,
                                        'shearY': 0, 'scaleY': -RES, 'translateY': gy0},
                    'crsCode': 'EPSG:4326'}}
    for k in range(RETRIES):
        try:
            return ee.data.computePixels(req)
        except Exception as e:  # сеть, лимиты GEE: повтор с паузой, после последней попытки ошибка наверх
            if k == RETRIES - 1:
                raise
            print(f'  повтор computePixels ({k + 1}): {e!r}', file=sys.stderr, flush=True)
            time.sleep(2 ** k)


def check_bands_vs_local(img: ee.Image) -> pd.DataFrame | None:
    """Шов данных: окно GEE против того же окна локального листа first (каналы 1-4 = first_b30, b40, b50, b70)."""
    if not LOCAL_FIRST.exists():
        print(f'  локального листа {LOCAL_FIRST} нет: сверка каналов пропущена', flush=True)
        return None
    x0, y0, w, h = BAND_CHECK_WIN
    arr = fetch_window(img, x0, y0, w, h)
    with rasterio.open(LOCAL_FIRST) as s:
        win = from_bounds(x0, y0 - h * RES, x0 + w * RES, y0, s.transform).round_offsets().round_lengths()
        loc = s.read(window=win)
    rows = []
    for i, b in enumerate(BANDS[:4]):
        g, lo = arr[b].astype(int), loc[i].astype(int)
        rows.append({'band_gee': b, 'band_local': i + 1, 'dtype_gee': str(arr[b].dtype), 'dtype_local': str(loc.dtype),
                     'equal_frac': float((g == lo).mean()), 'max_abs_diff': int(np.abs(g - lo).max()),
                     'mean_gee': float(g.mean()), 'mean_local': float(lo.mean())})
    return pd.DataFrame(rows)


def window_for(bounds: tuple[float, float, float, float]) -> tuple[float, float, int, int]:
    """Окно на сетке Hansen, накрывающее bounds (EPSG:4326) с запасом MARGIN_PX."""
    x0, y0, x1, y1 = bounds
    c0 = math.floor((x0 - GRID_X0) / RES) - MARGIN_PX
    r0 = math.floor((GRID_Y0 - y1) / RES) - MARGIN_PX
    c1 = math.ceil((x1 - GRID_X0) / RES) + MARGIN_PX
    r1 = math.ceil((GRID_Y0 - y0) / RES) + MARGIN_PX
    return GRID_X0 + c0 * RES, GRID_Y0 - r0 * RES, c1 - c0, r1 - r0


def contour_stats(img: ee.Image, geom) -> dict:
    """bare2000_frac по правилу 66 (all_touched, пиксели без весов) и показатели качества композита по контуру."""
    gx0, gy0, w, h = window_for(geom.bounds)
    arr = None
    for r0 in range(0, h, TILE_PX):
        for c0 in range(0, w, TILE_PX):
            hh, ww = min(TILE_PX, h - r0), min(TILE_PX, w - c0)
            part = fetch_window(img, gx0 + c0 * RES, gy0 - r0 * RES, ww, hh)
            if arr is None:
                arr = np.zeros((h, w), dtype=part.dtype)
            arr[r0:r0 + hh, c0:c0 + ww] = part
    tr = Affine(RES, 0, gx0, 0, -RES, gy0)
    m = ~geometry_mask([geom], out_shape=(h, w), transform=tr, all_touched=True)
    px = int(m.sum())
    if px == 0:
        return {'px': 0}
    red = arr['first_b30'][m]
    nir = arr['first_b40'][m]
    sw1 = arr['first_b50'][m].astype('float32')
    dm = arr['datamask'][m]
    ndvi = (nir.astype('float32') - red) / np.maximum(nir.astype('float32') + red, 1)   # как в 66
    bare = (red >= RED_MIN) & (ndvi < NDVI_MAX)
    ndsi = (red - sw1) / np.maximum(red + sw1, 1)
    zero = (arr['first_b30'][m] == 0) & (arr['first_b40'][m] == 0) & (arr['first_b50'][m] == 0) & (arr['first_b70'][m] == 0)
    return {
        'px': px, 'bare2000_gee': float(bare.mean()), 'red2000_gee': float(red.mean()),
        'dm0_frac': float((dm == 0).mean()), 'dm2_frac': float((dm == 2).mean()), 'zero_frac': float(zero.mean()),
        'snow_frac': float(((ndsi >= SNOW_NDSI_MIN) & (red >= SNOW_RED_MIN)).mean()),
        'bright_frac': float((red >= BRIGHT_RED_MIN).mean()),
    }


def run_windows(gdf4326: gpd.GeoDataFrame, label: str) -> pd.DataFrame:
    """Реализация B для набора контуров (параллельные запросы к GEE)."""
    img = hansen_image()
    ids = gdf4326['id'].to_numpy()
    geoms = gdf4326.geometry.to_numpy()
    out: list[dict] = [None] * len(ids)

    def job(i: int) -> None:
        d = contour_stats(img, geoms[i])
        d['id'] = int(ids[i])
        out[i] = d

    t = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for k, _ in enumerate(ex.map(job, range(len(ids)))):
            if (k + 1) % 250 == 0:
                log(f'  {label}: {k + 1}/{len(ids)} контуров')
    log(f'  {label}: {len(ids)} контуров за {(time.time() - t) / 60:.1f} мин')
    return pd.DataFrame(out)


def run_server_mean(gdf4326: gpd.GeoDataFrame, max_bytes: int = 3_000_000) -> pd.DataFrame:
    """Реализация A (справочно): reduceRegions, среднее маски «голый в 2000» с долевыми весами пикселей.
    Партии по объёму геометрии (предел запроса GEE 10 МБ)."""
    img = hansen_image()
    red = img.select('first_b30').toFloat()
    nir = img.select('first_b40').toFloat()
    ndvi = nir.subtract(red).divide(nir.add(red).max(1))
    bare = red.gte(RED_MIN).And(ndvi.lt(NDVI_MAX)).rename('bare')
    rows = []

    def flush(feats: list) -> None:
        fc = bare.reduceRegions(collection=ee.FeatureCollection(feats), reducer=ee.Reducer.mean(),
                                crs='EPSG:4326', crsTransform=[RES, 0, GRID_X0, 0, -RES, GRID_Y0])
        for f in fc.getInfo()['features']:
            rows.append({'id': f['properties']['id'], 'bare2000_srv': f['properties'].get('mean')})

    feats, size = [], 0
    for i, geom in zip(gdf4326['id'], gdf4326.geometry):
        gj = shapely.geometry.mapping(geom)
        nbytes = len(json.dumps(gj))
        if feats and size + nbytes > max_bytes:
            flush(feats)
            feats, size = [], 0
        feats.append(ee.Feature(ee.Geometry(gj, 'EPSG:4326', False), {'id': int(i)}))
        size += nbytes
    if feats:
        flush(feats)
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════════════════
# ТАБЛИЦЫ
# ════════════════════════════════════════════════════════════════════════════

def agreement(df: pd.DataFrame, col_ref: str, col_new: str) -> tuple[pd.DataFrame, float, float]:
    """Матрица совпадений классов (контуры и км2) и доля совпадений по числу и по площади."""
    cnt = pd.crosstab(df[col_ref], df[col_new], margins=True)
    km2 = pd.crosstab(df[col_ref], df[col_new], values=df['area_ha'] / 100.0, aggfunc='sum', margins=True).fillna(0.0)
    ok = df[col_ref] == df[col_new]
    by_n = ok.mean()
    by_a = df.loc[ok, 'area_ha'].sum() / df['area_ha'].sum()
    tab = cnt.astype(str) + ' / ' + km2.round(2).astype(str)
    return tab, by_n, by_a


def shares(df: pd.DataFrame, area_col: str, age_col: str) -> pd.Series:
    """Доли площади по возрасту, %."""
    s = df.groupby(age_col)[area_col].sum().reindex(AGE_ORDER, fill_value=0.0)
    return 100.0 * s / s.sum()


def known_shares(df: pd.DataFrame, group_col: str, age_col: str) -> pd.DataFrame:
    """Площадь, доли new/mid/old от датированной площади и new/(new+old) по группам (как summarize_age_and_cad)."""
    p = df.pivot_table(index=group_col, columns=age_col, values='area_ha', aggfunc='sum', fill_value=0.0,
                       observed=False) / 100.0
    for a in AGE_ORDER:
        if a not in p.columns:
            p[a] = 0.0
    p = p[AGE_ORDER]
    p['total_km2'] = p.sum(axis=1)
    known = p['new'] + p['mid'] + p['old']
    p['known_km2'] = known
    for a in ('new', 'mid', 'old'):
        p[f'{a}_%_known'] = np.where(known > 0, 100.0 * p[a] / known, np.nan)
    p['new_vs_old_%'] = np.where(p['new'] + p['old'] > 0, 100.0 * p['new'] / (p['new'] + p['old']), np.nan)
    p['na_%'] = 100.0 * p['na'] / p['total_km2']
    return p


def macro_zone(district, subregion: str) -> str:
    """Копия вложенной функции macro_zone из article_facts.main (сверяется по опубликованным 88,6 %)."""
    d = district if isinstance(district, str) else ''
    if subregion.startswith('5.'):
        return '1. Таёжный пояс ХМАО (Сургутский, Нижневартовский и др.)'
    if 'Пуровский' in d:
        return '2. Пуровский район (северная тайга / лесотундра ЯНАО)'
    if 'Надымский' in d or 'Красноселькупский' in d or 'Приуральский' in d or 'Шурышкарский' in d:
        return '3. Надымский, Приуральский и Красноселькупский р-ны'
    if 'Ямальский' in d or 'Тазовский' in d:
        return '4. Арктические п-ова и тундра ЯНАО (Ямальский и Тазовский р-ны)'
    return '5. Приенисейско-таймырский сектор (Туруханский и вост. >=79°)'


# ════════════════════════════════════════════════════════════════════════════
# ОСНОВНОЙ РАСЧЁТ
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    cpu_limit.apply()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ee.Initialize(project=GEE_PROJECT)
    pd.set_option('display.width', 250)
    pd.set_option('display.max_columns', 30)

    log('техногенные контуры итогового слоя...')
    cols = ['id', 'area_ha', 'genesis_main', 'bare2000_frac', 'hansen_covered', 'age2000', 'cad_status', 'cad_in_ha',
            'cad_none_ha', 'cad_exc10_ha', 'step6_rule']
    a = pyogrio.read_dataframe(caf.PRODUCT_GPKG, layer='genesis', columns=cols, where="genesis_main = 'anthropogenic'")
    assert a.crs.to_epsg() == caf.TARGET_CRS
    a4326 = a.to_crs(4326)
    cen = gpd.GeoSeries(a.geometry.centroid, crs=caf.TARGET_CRS).to_crs(4326)
    a['lon'], a['lat'] = cen.x.to_numpy(), cen.y.to_numpy()
    b = a4326.geometry.bounds
    a['lat_min'], a['lat_max'] = b['miny'].to_numpy(), b['maxy'].to_numpy()
    # возраст в слое совпадает с правилом 133 по bare2000_frac
    assert (age2000(a['bare2000_frac']).to_numpy() == a['age2000'].to_numpy()).all()
    na = a['age2000'] == 'na'
    log(f'  контуров {len(a):,} ({a.area_ha.sum() / 100:.1f} км2); age2000 = na: {int(na.sum()):,} '
        f'({a.loc[na, "area_ha"].sum() / 100:.1f} км2), из них севернее {NORTH_LAT:.0f}°: '
        f'{int((na & (a.lat >= NORTH_LAT)).sum()):,} ({a.loc[na & (a.lat >= NORTH_LAT), "area_ha"].sum() / 100:.1f} км2); '
        f'пересекают {NORTH_LAT:.0f}°: {int(((a.lat_min < NORTH_LAT) & (a.lat_max >= NORTH_LAT)).sum())}')

    # ── шаг 0: каналы GEE против локального листа ──
    log(f'шаг 0: окно {BAND_CHECK_WIN[2]} x {BAND_CHECK_WIN[3]} пикселей из GEE против локального листа...')
    bc = check_bands_vs_local(hansen_image())
    if bc is not None:
        print(bc.round(3).to_string(index=False))
        bc.to_csv(OUT_DIR / 'age_north70_bandcheck.csv', index=False, encoding='utf-8')
        assert (bc['equal_frac'] == 1.0).all() and (bc['dtype_gee'] == bc['dtype_local']).all(), 'каналы GEE и листа разошлись'

    # ── шаг 1: шов ──
    log('шаг 1: проверка шва на контурах южнее 70° с известным возрастом...')
    south_known = a[(a.lat_max < NORTH_LAT) & ~na]
    rng = np.random.default_rng(SEED)
    pick = rng.choice(len(south_known), size=N_SEAM, replace=False)
    seam = south_known.iloc[pick].copy()
    seam['stratum'] = 'random'
    big = south_known[(south_known.area_ha >= SEAM_BIG_HA) & ~south_known.index.isin(seam.index)].copy()
    big['stratum'] = f'>= {SEAM_BIG_HA:.0f} га'
    seam = pd.concat([seam, big])
    resB = run_windows(a4326.loc[seam.index, ['id', 'geometry']], 'шов, окна')
    resA = run_server_mean(a4326.loc[seam.index, ['id', 'geometry']])
    seam = seam.merge(resB, on='id', how='left').merge(resA, on='id', how='left')
    seam['age_B'] = age2000(seam['bare2000_gee'])
    seam['age_A'] = age2000(seam['bare2000_srv'])
    seam['d_B'] = seam['bare2000_gee'] - seam['bare2000_frac']
    seam['d_A'] = seam['bare2000_srv'] - seam['bare2000_frac']
    seam.drop(columns='geometry').to_csv(OUT_DIR / 'age_north70_seam.csv', index=False, encoding='utf-8')
    seam_ok = {}
    for strat in ('random', f'>= {SEAM_BIG_HA:.0f} га'):
        s = seam[seam['stratum'] == strat]
        for impl in ('B', 'A'):
            tab, by_n, by_a = agreement(s, 'age2000', f'age_{impl}')
            d = s[f'd_{impl}'].abs()
            print(f'\n[{strat}, n = {len(s)}] слой (строки) против GEE-{impl} (столбцы), контуров / км2:')
            print(tab.to_string())
            print(f'  согласие: по числу {100 * by_n:.1f} %, по площади {100 * by_a:.1f} %; |Δ bare2000_frac|: '
                  f'медиана {d.median():.3f}, p90 {d.quantile(0.9):.3f}, max {d.max():.3f}, '
                  f'точно (< 0,0005) у {100 * (d < 0.0005).mean():.1f} %')
            seam_ok[(strat, impl)] = by_a
    if seam_ok[('random', 'B')] < SEAM_MIN_AREA_AGREE:
        bad = seam[(seam['stratum'] == 'random') & (seam['age2000'] != seam['age_B'])]
        print('\nРасхождения B (первые 20):')
        print(bad[['id', 'area_ha', 'lat', 'lon', 'bare2000_frac', 'bare2000_gee', 'px', 'step6_rule']].head(20).to_string())
        raise SystemExit(f'Согласие по площади {100 * seam_ok[("random", "B")]:.1f} % ниже '
                         f'{100 * SEAM_MIN_AREA_AGREE:.0f} %: перенос на север остановлен, нужен разбор причины')

    # ── шаг 2: все контуры без возраста ──
    log('шаг 2: все контуры с age2000 = na через GEE...')
    res = run_windows(a4326.loc[na, ['id', 'geometry']], 'na')
    nn = a.loc[na].drop(columns='geometry').merge(res, on='id', how='left')
    nn['age2000_new'] = age2000(nn['bare2000_gee'])
    nn['north70'] = nn['lat'] >= NORTH_LAT
    nn[['id', 'age2000_new', 'bare2000_gee', 'px', 'area_ha', 'lat', 'lon', 'north70', 'red2000_gee', 'dm0_frac',
        'dm2_frac', 'zero_frac', 'snow_frac', 'bright_frac']].to_csv(OUT_DIR / 'age_north70_na_contours.csv',
                                                                     index=False, encoding='utf-8')
    nn[['id', 'age2000_new']].rename(columns={'age2000_new': 'age2000'}).to_csv(
        OUT_DIR / 'age_north70_new_age2000.csv', index=False, encoding='utf-8')
    print('\nНовый возраст контуров без данных (контуров / км2):')
    print(pd.crosstab(nn['north70'].map({True: f'>= {NORTH_LAT:.0f}°', False: f'< {NORTH_LAT:.0f}°'}),
                      nn['age2000_new'], values=nn['area_ha'] / 100.0, aggfunc='sum', margins=True).round(2).to_string())
    print(pd.crosstab(nn['north70'], nn['age2000_new'], margins=True).to_string())
    north = nn[nn['north70']]
    w = north['area_ha']
    q = {k: float((north[k] * w).sum() / w.sum()) for k in ('dm0_frac', 'dm2_frac', 'zero_frac', 'snow_frac', 'bright_frac')}
    unusable = north[['dm0_frac', 'zero_frac', 'snow_frac', 'bright_frac']].clip(upper=1.0)
    any_bad = np.minimum(unusable['dm0_frac'] + unusable['zero_frac'] + unusable['snow_frac'] + unusable['bright_frac'], 1.0)
    print(f'\nКачество композита 2000 г. севернее {NORTH_LAT:.0f}° (доля площади контуров, взвешено по площади): '
          f'маска данных 0: {100 * q["dm0_frac"]:.2f} %; вода по маске Hansen (datamask 2): {100 * q["dm2_frac"]:.2f} %; '
          f'все каналы 0: {100 * q["zero_frac"]:.2f} %; снег/лёд: {100 * q["snow_frac"]:.2f} %; red >= {BRIGHT_RED_MIN}: '
          f'{100 * q["bright_frac"]:.2f} %; верхняя оценка непригодного (сумма) {100 * float((any_bad * w).sum() / w.sum()):.2f} %; '
          f'контуров с px = 0: {int((north["px"] == 0).sum())}')
    pd.DataFrame([q]).to_csv(OUT_DIR / 'age_north70_quality.csv', index=False, encoding='utf-8')

    # ── шаг 3: пересчёт чисел статьи ──
    log('шаг 3: пересчёт долей...')
    new_map = dict(zip(nn['id'], nn['age2000_new']))
    a['age_upd'] = a['age2000']
    a.loc[na, 'age_upd'] = a.loc[na, 'id'].map(new_map)
    a['age_upd'] = a['age_upd'].fillna('na')

    out_rows = []

    def put(table: str, group: str, before: pd.Series, after: pd.Series) -> None:
        for k in AGE_ORDER:
            out_rows.append({'table': table, 'group': group, 'age': k, 'before': before.get(k, np.nan),
                             'after': after.get(k, np.nan)})

    cls_b, cls_a = shares(a, 'area_ha', 'age2000'), shares(a, 'area_ha', 'age_upd')
    assert all(abs(round(cls_b[k], 1) - v) < 0.051 for k, v in PUB_CLASS_PCT.items()), cls_b
    put('класс, % площади', 'весь класс', cls_b, cls_a)

    lay = {}
    for lyr, grp in (('anthro_in', 'в отводах (слой anthro_in)'), ('anthro_exceed', 'превышение отвода'),
                     ('anthro_noallot', 'без отвода')):
        d = pyogrio.read_dataframe(caf.CADASTRE_GPKG, layer=lyr, columns=['id', 'area_ha', 'age2000'], read_geometry=False)
        d['age_upd'] = d['age2000']
        m = d['age2000'] == 'na'
        d.loc[m, 'age_upd'] = d.loc[m, 'id'].map(new_map).fillna('na')
        lay[lyr] = d
        sb, sa = shares(d, 'area_ha', 'age2000'), shares(d, 'area_ha', 'age_upd')
        put('группы ЕГРН, % площади группы', grp, sb, sa)
        print(f'  {grp}: {d.area_ha.sum() / 100:.1f} км2, частей {len(d):,}')
    sb = shares(lay['anthro_exceed'], 'area_ha', 'age2000')
    assert all(abs(sb[k] - v) < 0.06 for k, v in PUB_EXCEED_PCT.items()), sb
    sb = shares(lay['anthro_noallot'], 'area_ha', 'age2000')
    assert all(abs(sb[k] - v) < 0.06 for k, v in PUB_NOALLOT_PCT.items()), sb
    # «в отводах» по площади отводов контура (cad_in_ha, как табл. S11.5)
    a['cad_in_ha0'] = a['cad_in_ha'].fillna(0.0)
    put('группы ЕГРН, % площади группы', 'в отводах (cad_in_ha)', shares(a, 'cad_in_ha0', 'age2000'),
        shares(a, 'cad_in_ha0', 'age_upd'))

    # табл. S11.5 и S11.6 до и после
    s115 = []
    for col in ('age2000', 'age_upd'):
        t = a.groupby(col).agg(N=('id', 'size'), km2=('area_ha', lambda s: s.sum() / 100),
                               in_km2=('cad_in_ha', lambda s: s.sum() / 100),
                               none_km2=('cad_none_ha', lambda s: s.sum() / 100)).reindex(AGE_ORDER).fillna(0)
        t.loc['всего'] = t.sum()
        t['in_%'] = 100 * t['in_km2'] / t['km2']
        t['none_%'] = 100 * t['none_km2'] / t['km2']
        t['version'] = 'до' if col == 'age2000' else 'после'
        s115.append(t)
    s115 = pd.concat(s115)
    s115.to_csv(OUT_DIR / 'age_north70_S11_5.csv', encoding='utf-8')
    print('\nТабл. S11.5 (до / после):')
    print(s115.round(2).to_string())
    s116 = []
    for lyr in ('anthro_exceed', 'anthro_noallot'):
        d = lay[lyr]
        for col in ('age2000', 'age_upd'):
            t = d.groupby(col).agg(N=('id', 'size'), km2=('area_ha', lambda s: s.sum() / 100)).reindex(AGE_ORDER).fillna(0)
            t.loc['всего'] = t.sum()
            t['%'] = 100 * t['km2'] / t.loc['всего', 'km2']
            t['layer'] = lyr
            t['version'] = 'до' if col == 'age2000' else 'после'
            s116.append(t)
    s116 = pd.concat(s116)
    s116.to_csv(OUT_DIR / 'age_north70_S11_6.csv', encoding='utf-8')
    print('\nТабл. S11.6 (до / после):')
    print(s116.round(2).to_string())

    # широтные пояса и макрозоны
    log('районы и ареалы (load_admin_districts)...')
    cov = gpd.read_file(caf.COVERAGE_GPKG, layer='coverage').to_crs(caf.TARGET_CRS)
    cov_geom = shapely.make_valid(cov.geometry.union_all())
    d6, _ = caf.load_admin_districts(cov_geom)
    pts = gpd.GeoDataFrame(a[['id']], geometry=a.geometry.centroid, crs=caf.TARGET_CRS)
    j = gpd.sjoin(pts, d6[['name', 'district', 'geometry']], how='left', predicate='within')
    j = j[~j.index.duplicated()]
    a['district'] = j['district'].to_numpy()
    a['subregion'] = [caf.assign_subregion(d, lo, la) for d, lo, la in zip(a['district'], a['lon'], a['lat'])]
    a['macro_zone'] = [macro_zone(d, s) for d, s in zip(a['district'], a['subregion'])]
    a['lat_band'] = pd.cut(a['lat'], LAT_BINS, right=False, labels=LAT_LABELS)
    a['dist_or_east'] = np.where(a['district'].notna(), a['district'],
                                 np.where(a['lon'] >= caf.EAST_SECTOR_LON, 'восточный сектор (>=79° в. д.)', 'вне районов'))
    blocks = []
    for gcol, title in (('lat_band', 'широтные пояса'), ('macro_zone', 'макрозоны'), ('dist_or_east', 'районы')):
        kb = known_shares(a, gcol, 'age2000')
        ka = known_shares(a, gcol, 'age_upd')
        kb['version'], ka['version'] = 'до', 'после'
        both = pd.concat([kb, ka]).reset_index().rename(columns={gcol: 'group'})
        both['table'] = title
        blocks.append(both)
        if gcol == 'dist_or_east':
            sel = [x for x in both['group'].unique() if any(k in str(x) for k in ('Ямальский', 'Тазовский', 'Надымский', 'Пуровский'))]
            both = both[both['group'].isin(sel)]
        print(f'\n{title} (доли от датированной площади, %):')
        print(both[['group', 'version', 'total_km2', 'known_km2', 'new', 'mid', 'old', 'na', 'new_%_known', 'mid_%_known',
                    'old_%_known', 'new_vs_old_%', 'na_%']].round(2).to_string(index=False))
    kb = known_shares(a, 'macro_zone', 'age2000')
    arc = [i for i in kb.index if i.startswith('4.')][0]
    assert abs(kb.loc[arc, 'new_%_known'] - PUB_ARCTIC_NEW_PCT_KNOWN) < 0.051, kb.loc[arc]
    pd.concat(blocks).to_csv(OUT_DIR / 'age_north70_bands_zones.csv', index=False, encoding='utf-8')
    res_tab = pd.DataFrame(out_rows)
    res_tab.to_csv(OUT_DIR / 'age_north70_shares.csv', index=False, encoding='utf-8')
    print('\nДоли возраста, % площади (до -> после):')
    print(res_tab.pivot_table(index=['table', 'group'], columns='age', values=['before', 'after'], sort=False)
          .round(1).to_string())
    log('готово')


if __name__ == '__main__':
    main()
