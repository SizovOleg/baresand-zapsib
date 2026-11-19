"""
150_gee_upload.py - загрузка слоёв в ассеты Earth Engine для мини-приложения (2026-10-13, по решению автора).

GCS у проекта нет, поэтому таблица отправляется частями: каждая часть строится как клиентская FeatureCollection
(GeoJSON до CHUNK_MB) и выгружается Export.table.toAsset в <FOLDER>/<слой>_pNNN; затем --merge склеивает части в один
ассет <FOLDER>/<слой> на стороне EE (flatten + Export.table.toAsset), --cleanup удаляет части после склейки.
Геометрия упрощается на SIMPLIFY_M (один пиксель маски 10 м: ступенчатые контуры), координаты округляются до 1e-5°
(около 1 м); для показа на карте этого достаточно, точные слои в облаке автора.
Слои: genesis (итоговый v7: id, g = класс генезиса, a = площадь га, r = step6_rule), fields (месторождения), roads (OSM
trunk/primary), rivers (крупные реки OSM, 146), density_aeolian / density_anthropogenic (ячейки 10 км, 145: v = га/км²),
cadastre (классы техногена после перестройки 133: путь задаётся --src).
Дополнено 2026-11-19: districts (районы со статистикой 155), infra_lines (дороги основные, прочие и грунтовые, железные
дороги, трубопроводы, ЛЭП OSM: поле kind, winter), infra_areas (промышленные площадки и карьеры OSM: поле kind);
allotments (обобщённая маска отводов под объекты, 156, без атрибутов);
--density-grid M: растры плотности по центроидам контуров генезиса с ячейкой M метров (EPSG:3576) для эоловых, отмелей
(всех типов) и техногенных: density_<класс>_<км>km, га/км².
Ассеты приватные (права меняет автор). Журнал задач: exports/qc/gee_upload/<слой>_tasks.json.
Запуск: PYTHONIOENCODING=utf-8 python -u python/150_gee_upload.py --layer genesis [--dry-run] | --merge genesis [--cleanup]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import time
from pathlib import Path

import ee
import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

ROOT = Path(r'D:\test\baresand_zapsib')
PROJECT = 'nodal-thunder-481307-u1'
FOLDER = f'projects/{PROJECT}/assets/ZapSib_baresands/app'
LOG = ROOT / 'exports' / 'qc' / 'gee_upload'
CHUNK_MB = 3.0            # сериализация FeatureCollection почти удваивает объём; лимит запроса EE 10 МБ
SIMPLIFY_M = 10.0
PREC = 1e-5
FIGS = ROOT / 'exports' / 'figures'
GCODE = {'aeolian': 1, 'river_shoal': 2, 'lake_shoal': 3, 'shoal': 4, 'anthropogenic': 5, 'undefined': 6}   # как в приложении
RIVERS_MAJOR = ['Обь', 'Малая Обь', 'Енисей', 'Таз', 'Пур', 'Пякупур', 'Айваседапур', 'Надым', 'Полуй', 'Казым',
                'Мессояха', 'Юрибей', 'Щучья', 'Танама', 'Турухан', 'Вах', 'Аган', 'Тромъёган']


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


INFRA = ROOT / 'exports' / 'osm' / 'osm_infra_AOI.gpkg'


def load(layer: str, src: Path | None) -> gpd.GeoDataFrame:
    """Слой для загрузки с короткими именами полей."""
    if layer == 'allotments':
        # обобщённая маска отводов под объекты (156): только геометрия и указание источника
        g = gpd.read_file(ROOT / 'exports' / 'final' / 'allotments_generalized_v7b.gpkg', layer='allotments')
        return g[['src', 'geometry']]
    if layer == 'districts':
        g = gpd.read_file(ROOT / 'exports' / 'qc' / 'app_stats' / 'districts.gpkg', layer='districts')
        return g[['name', 'label', 'sand_km2', 'aeolian', 'anthropogenic', 'n', 'geometry']]
    if layer == 'infra_lines':
        r = pyogrio.read_dataframe(INFRA, layer='roads', columns=['cls', 'winter'],
                                   where="cls IN ('major', 'minor', 'track')")
        r['kind'] = 'road_' + r['cls']
        r['winter'] = pd.to_numeric(r['winter'], errors='coerce').fillna(0).astype(int)
        rl = pyogrio.read_dataframe(INFRA, layer='rail', columns=['railway'],
                                    where="railway IN ('rail', 'disused', 'abandoned')")
        rl['kind'] = np.where(rl['railway'] == 'rail', 'rail', 'rail_old')
        rl['winter'] = 0
        ln = pyogrio.read_dataframe(INFRA, layer='linear', columns=['kind'], where="kind IN ('pipeline', 'power')")
        ln['winter'] = 0
        g = pd.concat([x[['kind', 'winter', 'geometry']].to_crs(4326) for x in (r, rl, ln)], ignore_index=True)
        return gpd.GeoDataFrame(g, geometry='geometry', crs=4326)
    if layer == 'infra_areas':
        g = pyogrio.read_dataframe(INFRA, layer='industrial', columns=['kind'])
        keep = ['industrial', 'quarry', 'storage_tank', 'construction', 'brownfield', 'works', 'substation', 'gasometer',
                'helipad']
        return g[g['kind'].isin(keep)][['kind', 'geometry']]
    if layer == 'genesis':
        g = pyogrio.read_dataframe(ROOT / 'exports' / 'final' / 'baresand_genesis_v7.gpkg', layer='genesis',
                                   columns=['id', 'genesis', 'area_ha', 'step6_rule'])
        return g.rename(columns={'genesis': 'g', 'area_ha': 'a', 'step6_rule': 'r'})
    if layer == 'fields':
        g = gpd.read_file(ROOT / 'oilfields' / 'Efield_region.shp', encoding='cp1251').set_crs(4326, allow_override=True)
        g['geometry'] = shapely.make_valid(g.geometry.values)
        aoi = gpd.read_file(ROOT / 'exports' / 'final' / 'aoi' / 'baresand_aoi_v2.shp').to_crs(4326)
        g = g[g.intersects(aoi.union_all().buffer(0.5))]
        return g[['NUMBER_1', 'TYPE_1', 'STAGES_1', 'geometry']].rename(columns={'NUMBER_1': 'name', 'TYPE_1': 'type', 'STAGES_1': 'stage'})
    if layer == 'roads':
        # поля приложения: cls (major), winter (1 = зимник); только основные дороги (объём)
        g = pyogrio.read_dataframe(ROOT / 'exports' / 'osm' / 'osm_infra_AOI.gpkg', layer='roads',
                                   columns=['highway', 'cls', 'winter', 'name'], where="cls = 'major'")
        g['winter'] = pd.to_numeric(g['winter'], errors='coerce').fillna(0).astype(int)
        return g
    if layer == 'rivers':
        g = gpd.read_file(ROOT / 'exports' / 'osm' / 'osm_rivers_AOI.gpkg', layer='rivers')
        return g[g['name'].isin(RIVERS_MAJOR)][['name', 'geometry']]
    if layer.startswith('density_'):
        cls = layer.split('_', 1)[1]
        c = pd.read_csv(FIGS / f'distr_{cls}_centroid_10000m_cells.csv')
        crs = '+proj=aea +lat_0=66 +lon_0=75 +lat_1=63 +lat_2=70 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs'
        geom = [shapely.box(x * 1e4, y * 1e4, (x + 1) * 1e4, (y + 1) * 1e4) for x, y in zip(c['ix'], c['iy'])]
        return gpd.GeoDataFrame({'v': c['ha_per_km2'].round(4), 'km2': c['km2'].round(4)}, geometry=geom, crs=crs)
    if layer in ('anthro_in', 'anthro_exceed', 'anthro_noallot'):
        if src is None:
            raise SystemExit(f'для {layer} нужен --src (gpkg слоёв 133)')
        keep = {'anthro_in': ['id', 'grp', 'area_ha', 'age2000'],
                'anthro_exceed': ['id', 'area_ha', 'in_pct', 'age2000'],
                'anthro_noallot': ['id', 'area_ha', 'kind', 'in_pct', 'under', 'age2000']}[layer]
        d = pyogrio.read_dataframe(src, layer=layer, columns=keep)
        return d[d.geometry.area >= 900] if layer == 'anthro_in' else d
    if layer == 'contours':
        # первичный вектор маски до атрибуции генезиса (30_vectorize_local.py)
        g = pyogrio.read_dataframe(ROOT / 'exports' / 'baresand_contours_v2.gpkg')
        keep = [c for c in ('id', 'tile', 'area_m2') if c in g.columns]
        return g[keep + ['geometry']]
    if layer == 'coverage':
        return gpd.read_file(ROOT / 'exports' / 'final' / 'aoi' / 'mask_coverage_128tiles.shp')[['geometry']].assign(name='coverage')
    if layer == 'tiles':
        g = gpd.read_file(ROOT / 'exports' / 'aux' / 'coverage_tiles.gpkg')
        keep = [c for c in g.columns if c in ('tile', 'name', 'Name', 'scene', 'date')]
        return g[keep + ['geometry']]
    raise SystemExit(f'неизвестный слой {layer}')


def to_features(g: gpd.GeoDataFrame, simplify: float) -> list[dict]:
    """GeoJSON-объекты в EPSG:4326 после упрощения и округления."""
    geom = gpd.GeoSeries(shapely.make_valid(g.geometry.values), crs=g.crs, index=g.index)
    if simplify > 0 and geom.crs and not geom.crs.is_geographic:
        geom = geom.simplify(simplify)
    geom = geom.to_crs(4326)
    try:
        geom = shapely.set_precision(geom.values, PREC)
    except shapely.errors.GEOSException:
        # редкие топологические ошибки: по одной, с исправлением геометрии; при неудаче без округления
        def one(x):
            for f in (lambda y: y, lambda y: shapely.make_valid(y).buffer(0)):
                try:
                    return shapely.set_precision(f(x), PREC)
                except shapely.errors.GEOSException:
                    continue
            return x
        geom = np.array([one(x) for x in geom.values], dtype=object)
    props = g.drop(columns='geometry')
    feats = []
    for x, row in zip(geom, props.to_dict('records')):
        if x is None or x.is_empty:
            continue
        clean = {k: (None if (isinstance(v, float) and np.isnan(v)) else (v.item() if hasattr(v, 'item') else v)) for k, v in row.items()}
        feats.append({'type': 'Feature', 'geometry': shapely.geometry.mapping(x), 'properties': clean})
    return feats


def chunks(feats: list[dict], max_bytes: float) -> list[list[dict]]:
    out, cur, size = [], [], 0
    for f in feats:
        s = len(json.dumps(f, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))
        if cur and size + s > max_bytes:
            out.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += s
    if cur:
        out.append(cur)
    return out


def ensure_folder(path: str) -> None:
    try:
        ee.data.getAsset(path)
    except ee.EEException:
        ee.data.createAsset({'type': 'FOLDER'}, path)
        log(f'создана папка {path}')


def exists(asset: str) -> bool:
    try:
        ee.data.getAsset(asset)
        return True
    except ee.EEException:
        return False


def upload(layer: str, src: Path | None, dry: bool) -> None:
    g = load(layer, src)
    simplify = SIMPLIFY_M if layer in ('genesis', 'contours', 'anthro_in', 'anthro_exceed', 'anthro_noallot', 'fields') else 0.0
    feats = to_features(g, simplify)
    parts = chunks(feats, CHUNK_MB * 1e6)
    log(f'{layer}: {len(feats)} объектов, {len(parts)} частей')
    if dry:
        return
    ensure_folder(FOLDER)
    LOG.mkdir(parents=True, exist_ok=True)
    jl = LOG / f'{layer}_tasks.json'
    rec = json.loads(jl.read_text(encoding='utf-8')) if jl.exists() else {}
    for k, p in enumerate(parts):
        asset = f'{FOLDER}/{layer}_p{k:03d}'
        if exists(asset) or asset in rec:
            continue
        fc = ee.FeatureCollection({'type': 'FeatureCollection', 'features': p})
        t = ee.batch.Export.table.toAsset(collection=fc, description=f'baresand_{layer}_p{k:03d}', assetId=asset)
        t.start()
        rec[asset] = {'task': t.id, 'n': len(p)}
        jl.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
        log(f'  {asset}: {len(p)} объектов, задача {t.id}')
    rec['_parts'] = len(parts)
    jl.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')


def merge(layer: str, cleanup: bool) -> None:
    jl = LOG / f'{layer}_tasks.json'
    rec = json.loads(jl.read_text(encoding='utf-8'))
    n = rec['_parts']
    assets = [f'{FOLDER}/{layer}_p{k:03d}' for k in range(n)]
    miss = [x for x in assets if not exists(x)]
    if miss:
        raise SystemExit(f'не готовы части: {len(miss)} из {n} (например {miss[:3]})')
    target = f'{FOLDER}/{layer}'
    if exists(target):
        log(f'{target} уже есть')
    else:
        fc = ee.FeatureCollection([ee.FeatureCollection(x) for x in assets]).flatten()
        if layer == 'genesis':
            # имена полей приложения (repo/gee_app/baresand_app.js): genesis, area_ha, step6_rule и код класса gcode
            codes = ee.Dictionary(GCODE)
            fc = fc.map(lambda f: ee.Feature(f.geometry(), {
                'id': f.get('id'), 'genesis': f.get('g'), 'area_ha': f.get('a'), 'step6_rule': f.get('r'),
                'gcode': codes.get(f.get('g'), 0)}))
        t = ee.batch.Export.table.toAsset(collection=fc, description=f'baresand_{layer}_merge', assetId=target)
        t.start()
        rec['_merge'] = t.id
        jl.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
        log(f'склейка {target}: задача {t.id}')
        return
    if cleanup:
        for x in assets:
            ee.data.deleteAsset(x)
        log(f'удалено частей: {len(assets)}')


def raster(layer: str) -> None:
    """Растр плотности из таблицы ячеек 10 км (поле v, га/км²) на стороне EE: <FOLDER>/<слой>_r."""
    src = f'{FOLDER}/{layer}_p000'
    target = f'{FOLDER}/{layer}_r'
    if exists(target):
        log(f'{target} уже есть')
        return
    fc = ee.FeatureCollection(src)
    img = fc.reduceToImage(['v'], ee.Reducer.first()).rename('density').toFloat()
    region = fc.geometry().bounds(1000)
    t = ee.batch.Export.image.toAsset(image=img, description=f'baresand_{layer}_r', assetId=target, region=region,
                                      crs='EPSG:3576', scale=1000, maxPixels=1e10)
    t.start()
    log(f'растр {target}: задача {t.id}')


def class_raster(scale: float = 50.0) -> None:
    """Обзорный растр классов gcode из склеенного genesis на стороне EE: <FOLDER>/genesis_r50 (пирамиды по моде)."""
    src, target = f'{FOLDER}/genesis', f'{FOLDER}/genesis_r{int(scale)}'
    if not exists(src):
        raise SystemExit(f'нет {src}: сначала --merge genesis')
    if exists(target):
        log(f'{target} уже есть')
        return
    fc = ee.FeatureCollection(src)
    img = fc.reduceToImage(['gcode'], ee.Reducer.first()).rename('gcode').toByte()
    region = ee.FeatureCollection(f'projects/{PROJECT}/assets/ZapSib_baresands/baresand_aoi_v2').geometry().bounds(1000)
    t = ee.batch.Export.image.toAsset(image=img, description='baresand_genesis_r50', assetId=target, region=region,
                                      crs='EPSG:3576', scale=scale, maxPixels=1e11,
                                      pyramidingPolicy={'gcode': 'mode'})
    t.start()
    log(f'растр классов {target}: задача {t.id}')


def density_grid(cell_m: float) -> None:
    """Растры плотности (га/км²) по центроидам контуров склеенного genesis: сумма площадей контуров, центроид которых
    лежит в ячейке, делённая на площадь ячейки (тот же способ, что 145). Сетка EPSG:3576 с шагом cell_m."""
    src = f'{FOLDER}/genesis'
    if not exists(src):
        raise SystemExit(f'нет {src}')
    region = ee.FeatureCollection(f'projects/{PROJECT}/assets/ZapSib_baresands/baresand_aoi_v2').geometry().bounds(1000)
    cell_km2 = (cell_m / 1000.0) ** 2
    km = f'{cell_m / 1000:g}'
    for cls, codes in (('aeolian', [1]), ('shoal', [2, 3, 4]), ('anthropogenic', [5])):
        target = f'{FOLDER}/density_{cls}_{km}km'
        if exists(target):
            log(f'{target} уже есть')
            continue
        pts = ee.FeatureCollection(src).filter(ee.Filter.inList('gcode', codes)).map(
            lambda f: ee.Feature(f.geometry().centroid(1), {'a': f.get('area_ha')}))
        img = pts.reduceToImage(['a'], ee.Reducer.sum()).divide(cell_km2).rename('density').toFloat()
        t = ee.batch.Export.image.toAsset(image=img, description=f'baresand_density_{cls}_{km}km', assetId=target,
                                          region=region, crs='EPSG:3576', scale=cell_m, maxPixels=1e10)
        t.start()
        log(f'плотность {target}: задача {t.id}')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--layer')
    ap.add_argument('--src', type=Path, default=None)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--merge')
    ap.add_argument('--cleanup', action='store_true')
    ap.add_argument('--raster')
    ap.add_argument('--class-raster', action='store_true')
    ap.add_argument('--density-grid', type=float, default=None, help='шаг сетки плотности, м (например 2000)')
    a = ap.parse_args()
    ee.Initialize(project=PROJECT)
    if a.density_grid:
        density_grid(a.density_grid)
    elif a.class_raster:
        class_raster()
    elif a.raster:
        raster(a.raster)
    elif a.merge:
        merge(a.merge, a.cleanup)
    elif a.layer:
        upload(a.layer, a.src, a.dry_run)


if __name__ == '__main__':
    main()
