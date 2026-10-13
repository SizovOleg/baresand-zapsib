"""
prepare_assets.py - подготовка слоёв BareSand к загрузке в ассеты Google Earth Engine для мини-приложения
repo/gee_app/baresand_app.js (2026-10-13).

Что делает (ничего не загружает и не публикует; только пишет файлы в папку --out):
- векторные слои: отбор полей (имена до 10 знаков, ограничение шейпфайла), упрощение геометрии (Дуглас-Пейкер с
  сохранением топологии каждого контура, в метрах EPSG:3576), исправление невалидных геометрий, перепроецирование в
  EPSG:4326 (так хранит векторы GEE; документация GEE советует перепроецировать до загрузки), запись шейпфайла UTF-8
  (.cpg) и ZIP-архива на каждый слой (Code Editor принимает ZIP с одним шейпфайлом);
- итоговый слой genesis: производные поля gcode (код класса для растра и стиля), rule и rule_step (правило и шаг,
  на котором контур получил итоговый класс; вычисляются обратным проходом по полям истории классов, см. derive_rule);
- растры плотности exports/figures/density_*_centroid_*.tif (черновик v8 исключён): копия в COG без изменения значений
  (га/км², nodata 0), по ключу --density-epsg перепроецирование (ближайший сосед);
- проверки: число объектов до и после, изменение площади от упрощения (по слою и максимум по объекту), невалидные и
  пустые геометрии, число вершин (всего, максимум на объект, объекты больше --max-vertices), длина текстовых полей в
  байтах (предел dbf 254), размеры .shp и .dbf (предел формата 2 ГБ), сумма плотности (га/км² x площадь ячейки = км²
  класса); итоги в manifest.csv и в выводе, код возврата 1 при ошибке проверки;
- не выкладываются кадастровые номера (поля cad_nums, cad_num): только производные классы и площади;
- --scenes-js: фрагмент JavaScript со списком сцен Sentinel-2 по тайлам (exports/aux/tile_scenes.csv, скрипт 126) и
  кандидатами по следу ассета тайла (_test/scene_registry_check.csv), для вставки в baresand_app.js.

Источники (только чтение):
  exports/final/baresand_genesis_v7.gpkg (genesis), exports/final/baresand_anthro_cadastre_v7.gpkg (anthro_in,
  anthro_exceed, anthro_noallot после перестройки скриптом 133; слоя нет: пропуск с предупреждением),
  exports/baresand_contours_v2.gpkg (contours: первичный вектор, 30_vectorize_local.py), exports/final/aoi/*.shp,
  exports/aux/coverage_tiles.gpkg (tiles, 123) + exports/aux/tile_scenes.csv (126), oilfields/Efield_region.shp
  (cp1251, обрезка по охвату района), exports/osm/osm_infra_AOI.gpkg (roads), exports/figures/density_*.tif (145).

Упрощение: контуры маски пиксельные (лестница с шагом 10 м). Допуск 5 м убирает только лишние вершины на прямых
(на пробе 882 контура у Надыма: -17 % вершин, площадь без изменений), лестницу срезает допуск больше 7,07 м (половина
диагонали пикселя): 7,5 м даёт -49 % вершин при изменении суммарной площади +0,1 %, но у 20 % мелких контуров площадь
меняется больше 5 %. По умолчанию 7,5 м для слоёв из маски (contours_v2, genesis_v7, anthro_*), 5 м для дорог,
50 м для границ; если упрощение невалидно, пусто или меняет площадь контура больше --max-area-change (5 %), у контура
остаётся исходная геометрия. Атрибуты площади берутся из источника, упрощение влияет только на показ. Для показа на мелких масштабах в приложении используется не упрощённый вектор,
а растр классов (экспорт в GEE, README) и растры плотности.

Запуск (полный, долгий: чтение около 2 ГБ GeoPackage, сотни тысяч контуров):
  PYTHONIOENCODING=utf-8 python -u repo/gee_app/prepare_assets.py --out repo/gee_app/upload
Проверка на подмножестве (охват в градусах: долгота, широта):
  PYTHONIOENCODING=utf-8 python -u repo/gee_app/prepare_assets.py --out repo/gee_app/_test/out --bbox 72.3 65.4 72.9 65.7
Только часть слоёв: --only genesis_v7,anthro_in; без растров: --skip-rasters; фрагмент сцен: --scenes-js.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
import traceback
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.stdout.reconfigure(encoding='utf-8')

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer

ROOT = Path(r'D:\test\baresand_zapsib')
APP_DIR = ROOT / 'repo' / 'gee_app'
sys.path.insert(0, str(ROOT / 'python'))

WORK_CRS = 3576        # метры, равноплощадная (как итоговые слои)
OUT_CRS = 4326         # так хранит векторы GEE
DBF_TEXT_MAX = 254     # байт на текстовое поле dbf
FILE_MAX = 2 * 1024 ** 3   # предел формата для .shp и .dbf
TOL_MASK = 7.5             # м: допуск упрощения слоёв из маски (срезает лестницу пикселей 10 м, см. docstring)

# коды классов (поле gcode): растр классов и стиль в приложении; порядок как в легенде приложения
GCODE = {'aeolian': 1, 'river_shoal': 2, 'lake_shoal': 3, 'shoal': 4, 'anthropogenic': 5, 'undefined': 6}

# поля итогового слоя: исходное -> имя в шейпфайле (до 10 знаков)
GENESIS_FIELDS = {
    'id': 'id', 'parent_id': 'parent_id', 'area_ha': 'area_ha', 'genesis': 'genesis', 'genesis_main': 'gen_main',
    'shoal_type': 'shoal_type', 'shoal_type_src': 'shoal_src', 'step6_rule': 'step6_rule', 'genesis_v6': 'gen_v6',
    'expert_note': 'note', 'cad_status': 'cad_status', 'cad_in_ha': 'cad_in_ha', 'cad_out_ha': 'cad_out_ha',
    'cad_exc10_ha': 'exc10_ha', 'age2000': 'age2000',
}
# не выкладываются: кадастровые номера (выгрузки ЕГРН не распространяются, публикуются только производные классы;
# repo/docs/DATA.md, раздел 11)
DROP_FIELDS = {'cad_nums', 'cad_num'}
# поля истории, нужные только для вычисления rule (в выход не пишутся)
HISTORY_FIELDS = ['genesis_step2', 'genesis_step3', 'genesis_v2e', 'genesis_v3e', 'genesis_v4', 'shoal_rule',
                  'step2_rule', 'step3_rule', 'step4_rule', 'step5_rule']


@dataclass
class VectorSpec:
    """Описание векторного слоя: источник, поля, допуск упрощения (м), дополнительная обработка."""
    src: Path
    layer: str | None
    fields: dict[str, str] | None          # None: все поля (имена укорачиваются автоматически)
    tol: float
    read_fields: list[str] = field(default_factory=list)   # прочитать дополнительно (для derive)
    encoding: str | None = None
    crs_override: int | None = None
    derive: Callable[[gpd.GeoDataFrame], gpd.GeoDataFrame] | None = None
    clip_aoi: bool = False
    optional: bool = False                # нет источника или слоя: предупреждение, а не ошибка


def derive_rule(d: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Правило и шаг, на котором контур получил итоговый класс.

    Стадии и поля класса после них (repo/docs/DATA.md, раздел 4.3): шаги 1-2 genesis_step2, шаг 3 genesis_step3,
    шаг 4 genesis_v2e, шаг 5 genesis_v3e, шаг 6 genesis_v4 (v4), genesis_v6 (разрез v5), genesis (исправления v7).
    Обратный проход: берётся самая ранняя стадия, начиная с которой класс уже не менялся. Её правило: шаг 1
    shoal_rule (морская отмель), шаг 2 step2_rule, шаги 3-5 step3_rule, step4_rule, step5_rule, шаг 6 step6_rule.
    Пустое правило стадии записывается как 'step<N>' (класс дан стадией без кода правила)."""
    s = lambda c: d[c].fillna('').astype(str)   # noqa: E731
    final = s('genesis')
    stages = [  # (класс после стадии, номер шага, правило стадии)
        (s('genesis_step2'), None, None),
        (s('genesis_step3'), 3, s('step3_rule')),
        (s('genesis_v2e'), 4, s('step4_rule')),
        (s('genesis_v3e'), 5, s('step5_rule')),
        (s('genesis_v4'), 6, s('step6_rule')),
        (s('genesis_v6'), 6, s('step6_rule')),
        (final, 6, s('step6_rule')),
    ]
    k = pd.Series(len(stages) - 1, index=d.index)      # индекс стадии, с которой класс не менялся
    stable = pd.Series(True, index=d.index)
    for i in range(len(stages) - 2, -1, -1):
        stable &= stages[i][0].eq(final)
        k = k.where(~stable, i)
    rule = pd.Series('', index=d.index, dtype=object)
    step = pd.Series(0, index=d.index, dtype='int64')
    for i, (_, n, r) in enumerate(stages):
        m = k.eq(i)
        if i == 0:   # шаги 1-2: морская отмель шага 1 или отмель шага 2 (в т. ч. v3_marine_leak: шаг 2 -> морская)
            r2 = s('step2_rule')
            sea = m & final.eq('shoal') & r2.eq('')
            rule[sea] = s('shoal_rule')[sea].replace('', 'step1')
            step[sea] = 1
            oth = m & ~sea
            rule[oth] = r2[oth].replace('', 'step2')
            step[oth] = 2
        else:
            rule[m] = r[m].replace('', f'step{n}')
            step[m] = n
    return rule, step


def derive_genesis(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """gcode, rule, rule_step для итогового слоя; поля истории удаляются."""
    g = g.copy()
    g['gcode'] = g['genesis'].map(GCODE).fillna(0).astype('int64')
    g['rule'], g['rule_step'] = derive_rule(g)
    return g.drop(columns=[c for c in HISTORY_FIELDS if c in g.columns])


def join_scenes(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Следы тайлов + сцена из реестра 126 (scene_id, date, cloud)."""
    sc = pd.read_csv(ROOT / 'exports' / 'aux' / 'tile_scenes.csv')
    sc = sc.rename(columns={'cloud_scene': 'cloud'})[['tile', 'scene_id', 'date', 'cloud']]
    return g.merge(sc, on='tile', how='left')


def specs() -> dict[str, VectorSpec]:
    """Слои приложения (имя выходного файла = имя ассета в README)."""
    fin = ROOT / 'exports' / 'final'
    cad = fin / 'baresand_anthro_cadastre_v7.gpkg'
    out = {
        'aoi': VectorSpec(fin / 'aoi' / 'baresand_aoi_v2.shp', None, {'name': 'name', 'area_km2': 'area_km2'}, 50.0),
        'coverage': VectorSpec(fin / 'aoi' / 'mask_coverage_128tiles.shp', None, {'name': 'name', 'area_km2': 'area_km2'},
                               50.0),
        'tiles': VectorSpec(ROOT / 'exports' / 'aux' / 'coverage_tiles.gpkg', 'tiles', None, 0.0, derive=join_scenes),
        'contours_v2': VectorSpec(ROOT / 'exports' / 'baresand_contours_v2.gpkg', 'contours',
                                  {'id': 'id', 'area_ha': 'area_ha'}, TOL_MASK),
        'genesis_v7': VectorSpec(fin / 'baresand_genesis_v7.gpkg', 'genesis', None, TOL_MASK,
                                 read_fields=list(GENESIS_FIELDS) + HISTORY_FIELDS, derive=derive_genesis),
        'oilfields': VectorSpec(ROOT / 'oilfields' / 'Efield_region.shp', None,
                                {'NUMBER_1': 'name_ru', 'NAME_FIELD': 'name_en', 'TYPE': 'type', 'TYPE_1': 'stage_ru',
                                 'STAGES': 'stage_en'}, 0.0, encoding='cp1251', crs_override=4326, clip_aoi=True),
        'osm_roads': VectorSpec(ROOT / 'exports' / 'osm' / 'osm_infra_AOI.gpkg', 'roads',
                                {'highway': 'highway', 'cls': 'cls', 'winter': 'winter', 'name': 'name'}, 5.0),
    }
    # кадастровые классы техногена (решение автора 13.10.2026; слои пишет 133 после перестройки)
    for name in ('anthro_in', 'anthro_exceed', 'anthro_noallot'):
        out[name] = VectorSpec(cad, name, None, TOL_MASK, optional=True)
    return out


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def bbox_in_crs(bbox: tuple[float, float, float, float] | None, crs) -> tuple[float, float, float, float] | None:
    """Охват (долгота, широта) в системе координат источника."""
    if bbox is None:
        return None
    tr = Transformer.from_crs(4326, crs, always_xy=True)
    xs, ys = tr.transform([bbox[0], bbox[2], bbox[0], bbox[2]], [bbox[1], bbox[1], bbox[3], bbox[3]])
    return min(xs), min(ys), max(xs), max(ys)


def short_names(cols: list[str]) -> dict[str, str]:
    """Имена полей до 10 знаков, уникальные (как при записи шейпфайла, но предсказуемо)."""
    out, used = {}, set()
    for c in cols:
        n = c[:10]
        k = 1
        while n in used:
            suf = f'_{k}'
            n = c[:10 - len(suf)] + suf
            k += 1
        used.add(n)
        out[c] = n
    return out


def simplify(geom: np.ndarray, tol: float, max_change: float) -> tuple[np.ndarray, dict]:
    """Упрощение с откатом к исходной геометрии при невалидном, пустом или сильно изменённом результате."""
    st = {'n_invalid_src': int((~shapely.is_valid(geom)).sum()), 'n_reverted': 0, 'n_fixed': 0}
    src = np.where(shapely.is_valid(geom), geom, shapely.make_valid(geom))
    if tol <= 0:
        return src, st
    simp = shapely.simplify(src, tol, preserve_topology=True)
    bad = ~shapely.is_valid(simp)
    if bad.any():
        simp[bad] = shapely.make_valid(simp[bad])
        st['n_fixed'] = int(bad.sum())
    a0, a1 = shapely.area(src), shapely.area(simp)
    poly = a0 > 0
    rel = np.zeros(len(src))
    rel[poly] = np.abs(a1[poly] - a0[poly]) / a0[poly]
    revert = shapely.is_empty(simp) | (poly & (rel > max_change))
    # make_valid может вернуть коллекцию с линиями: у полигонального слоя оставляем только полигоны
    gt = shapely.get_type_id(simp)
    revert |= poly & ~np.isin(gt, [3, 6])      # 3 Polygon, 6 MultiPolygon
    simp[revert] = src[revert]
    st['n_reverted'] = int(revert.sum())
    a1 = shapely.area(simp)
    st['area_change_pct'] = float((a1.sum() - a0.sum()) / a0.sum() * 100) if a0.sum() > 0 else 0.0
    st['max_feature_change_pct'] = float(np.max(np.abs(a1[poly] - a0[poly]) / a0[poly]) * 100) if poly.any() else 0.0
    return simp, st


def text_fix(g: pd.DataFrame) -> dict[str, int]:
    """Текстовые поля: NULL -> '', обрезка до 254 байт UTF-8; возвращает число обрезанных значений по полю."""
    cut = {}
    for c in g.columns:
        if c == 'geometry' or g[c].dtype != object:
            continue
        v = g[c].where(g[c].notna(), '').astype(str)
        b = v.str.encode('utf-8')
        long = b.str.len() > DBF_TEXT_MAX
        if long.any():
            v[long] = b[long].map(lambda x: x[:DBF_TEXT_MAX].decode('utf-8', 'ignore'))
            cut[c] = int(long.sum())
        g[c] = v
    return cut


def write_layer(g: gpd.GeoDataFrame, name: str, out: Path) -> dict:
    """Шейпфайл UTF-8 и ZIP; размеры частей."""
    d = out / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    shp = d / f'{name}.shp'
    pyogrio.write_dataframe(g, shp, driver='ESRI Shapefile', encoding='UTF-8', layer_options={'RESIZE': 'YES'})
    parts = sorted(p for p in d.iterdir() if p.stem == name)
    zp = out / f'{name}.zip'
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in parts:
            z.write(p, p.name)
    size = {p.suffix: p.stat().st_size for p in parts}
    return {'shp_mb': size.get('.shp', 0) / 2 ** 20, 'dbf_mb': size.get('.dbf', 0) / 2 ** 20,
            'zip_mb': zp.stat().st_size / 2 ** 20, 'parts': ','.join(sorted(size)),
            'size_ok': size.get('.shp', 0) < FILE_MAX and size.get('.dbf', 0) < FILE_MAX}


def aoi_bounds_4326() -> tuple[float, float, float, float]:
    a = gpd.read_file(ROOT / 'exports' / 'final' / 'aoi' / 'baresand_aoi_v2.shp').to_crs(OUT_CRS)
    x0, y0, x1, y1 = a.total_bounds
    return x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 0.5


def process_vector(name: str, sp: VectorSpec, a: argparse.Namespace) -> dict | None:
    """Чтение, поля, упрощение, проверки, запись одного слоя."""
    if not sp.src.exists():
        msg = f'{name}: нет файла {sp.src}'
        if sp.optional:
            log('ПРЕДУПРЕЖДЕНИЕ ' + msg)
            return {'layer': name, 'status': 'missing'}
        raise FileNotFoundError(msg)
    if sp.layer is not None and sp.layer not in [x[0] for x in pyogrio.list_layers(sp.src)]:
        msg = f'{name}: в {sp.src.name} нет слоя {sp.layer} (кадастровые слои появятся после перестройки скриптом 133)'
        if sp.optional:
            log('ПРЕДУПРЕЖДЕНИЕ ' + msg)
            return {'layer': name, 'status': 'missing'}
        raise ValueError(msg)
    info = pyogrio.read_info(sp.src, layer=sp.layer, encoding=sp.encoding)
    src_crs = sp.crs_override or info['crs']
    cols = list(info['fields']) if sp.fields is None else list(dict.fromkeys(list(sp.fields) + sp.read_fields))
    cols = [c for c in cols if c not in DROP_FIELDS]
    if sp.read_fields and sp.fields is None:
        cols = [c for c in sp.read_fields if c in info['fields']]
    bbox = a.bbox
    if bbox is None and sp.clip_aoi:
        bbox = aoi_bounds_4326()
    t0 = time.time()
    g = pyogrio.read_dataframe(sp.src, layer=sp.layer, columns=cols, encoding=sp.encoding,
                               bbox=bbox_in_crs(bbox, src_crs), max_features=a.max_features)
    if sp.crs_override:
        g = g.set_crs(sp.crs_override, allow_override=True)
    n_in = len(g)
    log(f'{name}: прочитано {n_in} объектов ({info["features"]} в источнике) за {time.time() - t0:.0f} с')
    if n_in == 0:
        log(f'ПРЕДУПРЕЖДЕНИЕ {name}: в охвате нет объектов, слой не записан')
        return {'layer': name, 'status': 'empty', 'n_src': info['features']}
    if sp.derive is not None:
        g = sp.derive(g)
    if sp.fields is not None:
        keep = {k: v for k, v in sp.fields.items() if k in g.columns}
        extra = [c for c in g.columns if c not in sp.fields and c != 'geometry' and c not in sp.read_fields]
        g = g[list(keep) + extra + ['geometry']].rename(columns=keep)
    elif sp.read_fields:   # genesis_v7: поля из GENESIS_FIELDS + производные
        g = g.rename(columns=GENESIS_FIELDS)
        first = list(GENESIS_FIELDS.values())
        g = g[[c for c in first if c in g.columns] + [c for c in g.columns if c not in first and c != 'geometry'] + ['geometry']]
    ren = short_names([c for c in g.columns if c != 'geometry'])
    g = g.rename(columns=ren)
    # числа: округление площадей до 4 знаков (0,0001 га = 1 м2), чтобы не раздувать dbf
    for c in g.columns:
        if c != 'geometry' and pd.api.types.is_float_dtype(g[c]):
            g[c] = g[c].round(4)
        elif c != 'geometry' and pd.api.types.is_bool_dtype(g[c]):
            g[c] = g[c].astype('int64')     # логический тип в dbf: 0/1 надёжнее
    tol = sp.tol if a.tol is None or sp.tol == 0 else a.tol
    geom = g.to_crs(WORK_CRS).geometry.to_numpy() if tol > 0 else g.geometry.to_numpy()
    geom, st = simplify(np.asarray(geom, dtype=object), tol, a.max_area_change)
    g = gpd.GeoDataFrame(g.drop(columns='geometry'), geometry=geom, crs=WORK_CRS if tol > 0 else g.crs).to_crs(OUT_CRS)
    nv = shapely.get_num_coordinates(g.geometry.to_numpy())
    cut = text_fix(g)
    n_empty = int(shapely.is_empty(g.geometry.to_numpy()).sum())
    sz = write_layer(g, name, a.out)
    rec = {'layer': name, 'status': 'ok', 'n_src': info['features'], 'n_in': n_in, 'n_out': len(g), 'tol_m': tol,
           'n_invalid_src': st['n_invalid_src'], 'n_fixed': st['n_fixed'], 'n_reverted': st['n_reverted'],
           'area_change_pct': round(st.get('area_change_pct', 0.0), 4),
           'max_feature_change_pct': round(st.get('max_feature_change_pct', 0.0), 2),
           'vertices': int(nv.sum()), 'max_vertices': int(nv.max()), 'n_over_max_vertices': int((nv > a.max_vertices).sum()),
           'n_empty': n_empty, 'text_cut': ';'.join(f'{k}:{v}' for k, v in cut.items()),
           'fields': ','.join(c for c in g.columns if c != 'geometry'), **sz}
    errs = []
    if rec['n_out'] != n_in:
        errs.append('число объектов изменилось')
    if n_empty:
        errs.append('пустые геометрии')
    if not sz['size_ok']:
        errs.append('.shp или .dbf больше 2 ГБ: разбейте слой (--max-features или по классам)')
    rec['check'] = 'OK' if not errs else 'FAIL: ' + '; '.join(errs)
    log(f'{name}: {rec["n_out"]} объектов, вершин {rec["vertices"]} (макс. {rec["max_vertices"]}), площадь '
        f'{rec["area_change_pct"]:+.4f} % (макс. по объекту {rec["max_feature_change_pct"]} %), откатов {rec["n_reverted"]}, '
        f'zip {sz["zip_mb"]:.1f} МБ (.shp {sz["shp_mb"]:.1f}, .dbf {sz["dbf_mb"]:.1f}) -> {rec["check"]}')
    if name == 'genesis_v7':
        log('  rule_step: ' + str(g['rule_step'].value_counts().sort_index().to_dict()))
    return rec


def process_rasters(a: argparse.Namespace) -> list[dict]:
    """Растры плотности 145: копия в COG (или перепроецирование), проверка суммы."""
    import rasterio
    from rasterio.warp import Resampling, calculate_default_transform, reproject
    recs = []
    areas = {'aeolian': 2729.7, 'anthropogenic': 1876.2}   # км², exports/final/README.md (v7)
    for src in sorted((ROOT / 'exports' / 'figures').glob('density_*_centroid_*.tif')):
        if 'v8draft' in src.stem:
            continue
        dst = a.out / f'{src.stem}.tif'
        with rasterio.open(src) as r:
            arr = r.read(1)
            cell_km2 = abs(r.transform.a * r.transform.e) / 1e6
            total = float(arr[arr > 0].sum() * cell_km2 / 100)
            prof = dict(driver='COG', dtype='float32', count=1, nodata=0, compress='LZW')
            if a.density_epsg:
                tr, w, h = calculate_default_transform(r.crs, f'EPSG:{a.density_epsg}', r.width, r.height, *r.bounds,
                                                       resolution=r.res)
                out = np.zeros((h, w), dtype='float32')
                reproject(arr, out, src_transform=r.transform, src_crs=r.crs, dst_transform=tr,
                          dst_crs=f'EPSG:{a.density_epsg}', src_nodata=0, dst_nodata=0, resampling=Resampling.nearest)
                prof.update(crs=f'EPSG:{a.density_epsg}', transform=tr, width=w, height=h)
                arr_out = out
            else:
                prof.update(crs=r.crs, transform=r.transform, width=r.width, height=r.height)
                arr_out = arr
        with rasterio.open(dst, 'w', **prof) as w:
            w.write(arr_out.astype('float32'), 1)
        cls = 'aeolian' if 'aeolian' in src.stem else 'anthropogenic'
        ok = abs(total - areas[cls]) < 0.1
        # сумма в записанном растре: при перепроецировании ближайшим соседом ячейки дублируются и выпадают
        t_out = prof['transform']
        total_out = float(arr_out[arr_out > 0].sum() * abs(t_out.a * t_out.e) / 1e6 / 100)
        recs.append({'layer': dst.stem, 'status': 'ok', 'n_in': int((arr > 0).sum()), 'zip_mb': dst.stat().st_size / 2 ** 20,
                     'check': 'OK' if ok else f'FAIL: сумма {total:.1f} км² != {areas[cls]}',
                     'fields': f'b1 га/км², ячейка {cell_km2:g} км², сумма {total:.1f} км², в файле {total_out:.1f} км²'})
        log(f'{dst.name}: ячеек с песком {recs[-1]["n_in"]}, сумма {total:.1f} км² (класс {areas[cls]}; в записанном '
            f'растре {total_out:.1f}), {recs[-1]["zip_mb"]:.1f} МБ -> {recs[-1]["check"]}')
    return recs


def scenes_js(out: Path) -> Path:
    """Фрагмент JS: тайл -> сцена реестра 126 и кандидаты по следу ассета (если есть сверка _test/scene_registry_check.csv)."""
    sc = pd.read_csv(ROOT / 'exports' / 'aux' / 'tile_scenes.csv')
    chk_path = APP_DIR / '_test' / 'scene_registry_check.csv'
    chk = pd.read_csv(chk_path).set_index('tile') if chk_path.exists() else None
    lines = ['// Сцены Sentinel-2 по тайлам: s = сцена реестра 126 (exports/aux/tile_scenes.csv),',
             '// v = статус сверки по охвату следа ассета тайла (repo/gee_app/_test/scene_registry_check.csv):',
             "//   'ok' сцена 126 совпала по охвату и облачности, 'fp' только по охвату, 'alt' не совпала (есть кандидаты),",
             "//   'no' не совпала и кандидатов нет, 'na' сверка невозможна (след ассета не ограничен);",
             '// c = сцены-кандидаты, совпавшие с охватом следа ассета и его облачностью (cloud_score).',
             'var SCENES = [']
    for r in sc.itertuples():
        v, c = 'na', []
        if chk is not None and r.tile in chk.index:
            q = chk.loc[r.tile]
            c = [x for x in str(q['scene_fp']).split(';') if x and x != 'nan']
            if q['status'] == 'asset_unbounded':
                v = 'na'
            elif r.scene_id in c:
                v = 'ok'
            elif bool(q['scene_126_in_fp']):
                v = 'fp'      # охват совпал, облачность нет
            else:
                v = 'alt' if c else 'no'
        lines.append(f"  {{t: '{r.tile}', s: '{r.scene_id}', v: '{v}', c: [{', '.join(repr(x) for x in c)}]}},")
    lines[-1] = lines[-1].rstrip(',')
    lines.append('];')
    p = out / 'scenes_snippet.js'
    p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    log(f'фрагмент сцен: {len(sc)} тайлов -> {p}')
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--out', type=Path, default=APP_DIR / 'upload', help='папка результата')
    ap.add_argument('--only', default='', help='слои через запятую (по умолчанию все)')
    ap.add_argument('--bbox', type=float, nargs=4, default=None, metavar=('LON0', 'LAT0', 'LON1', 'LAT1'),
                    help='подмножество по охвату в градусах')
    ap.add_argument('--max-features', type=int, default=None, help='не больше N объектов на слой (проверка)')
    ap.add_argument('--tol', type=float, default=None, help='допуск упрощения, м (по умолчанию у каждого слоя свой)')
    ap.add_argument('--max-area-change', type=float, default=0.05, help='откат упрощения, если площадь изменилась больше доли')
    ap.add_argument('--max-vertices', type=int, default=100_000, help='порог «тяжёлого» объекта (предупреждение)')
    ap.add_argument('--skip-rasters', action='store_true')
    ap.add_argument('--density-epsg', type=int, default=None, help='перепроецировать растры плотности (например 3576)')
    ap.add_argument('--scenes-js', action='store_true', help='только фрагмент JS со сценами')
    a = ap.parse_args()
    a.out = a.out if a.out.is_absolute() else ROOT / a.out
    a.out.mkdir(parents=True, exist_ok=True)
    if a.scenes_js:
        scenes_js(a.out)
        return 0
    try:
        import cpu_limit
        cpu_limit.apply()   # пониженный приоритет, четверть ядер (просьба владельца)
    except Exception as e:  # не критично для подготовки файлов
        log(f'cpu_limit не применён: {e!r}')
    only = {x.strip() for x in a.only.split(',') if x.strip()}
    recs = []
    failed = False
    for name, sp in specs().items():
        if only and name not in only:
            continue
        try:
            r = process_vector(name, sp, a)
        except Exception:
            traceback.print_exc()
            r = {'layer': name, 'status': 'error', 'check': 'FAIL: исключение (traceback выше)'}
        if r:
            recs.append(r)
            failed |= str(r.get('check', '')).startswith('FAIL')
    if not a.skip_rasters and (not only or 'density' in only):
        try:
            rr = process_rasters(a)
            recs += rr
            failed |= any(str(r['check']).startswith('FAIL') for r in rr)
        except Exception:
            traceback.print_exc()
            failed = True
    m = pd.DataFrame(recs)
    m.to_csv(a.out / 'manifest.csv', index=False, encoding='utf-8')
    show = [c for c in ['layer', 'status', 'n_in', 'n_out', 'vertices', 'max_vertices', 'area_change_pct', 'zip_mb', 'check']
            if c in m.columns]
    print(m[show].to_string(index=False))
    log(f'манифест: {a.out / "manifest.csv"}; ошибки проверок: {"есть" if failed else "нет"}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
