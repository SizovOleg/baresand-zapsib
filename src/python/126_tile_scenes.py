"""
126_tile_scenes.py - даты и идентификаторы сцен Sentinel-2, по которым классифицированы 128 тайлов маски (2026-09-30).

В ассетах тайлов (ZapSib_baresands/baresand_mask_<TILE>) дата сцены не записана, но записана её облачность (канал
cloud_score). Выбор сцены в gee_scripts/21_production_classify.js детерминирован: S2_SR_HARMONIZED, MGRS_TILE, 2020-06-01 -
2025-10-01, июль-сентябрь, CLOUDY_PIXEL_PERCENTAGE < 15, минимальная облачность. Скрипт воспроизводит выбор и сверяет
облачность с ассетом; при несовпадении ищет среди кандидатов сцену с той же облачностью.
Выход: exports/aux/tile_scenes.csv (tile, scene_id, date, cloud_scene, cloud_asset, match). Запуск:
PYTHONIOENCODING=utf-8 python -u python/126_tile_scenes.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import re
from pathlib import Path

import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
PROJECT = 'projects/nodal-thunder-481307-u1/assets/ZapSib_baresands'
OUT = ROOT / 'exports' / 'aux' / 'tile_scenes.csv'


def tiles() -> list[str]:
    s = (ROOT / 'python' / '22_run_mosaic.py').read_text(encoding='utf-8')
    m = re.search(r"PROCESSED_TILES = \[(.*?)\]", s, re.S)
    return re.findall(r"'(\d{2}[A-Z]{3}_+)'", m.group(1))


def main() -> None:
    import ee
    try:
        ee.Initialize()
    except Exception:
        ee.Initialize(project='ee-ntcomz18')
    import geopandas as gpd
    from shapely.geometry import mapping
    foot = gpd.read_file(ROOT / 'exports' / 'aux' / 'coverage_tiles.gpkg', layer='tiles').set_index('tile')   # из 123_coverage.py
    rows = []
    for k, key in enumerate(tiles()):
        t = key.rstrip('_')
        img = ee.Image(f'{PROJECT}/baresand_mask_{key}')
        # облачность из ассета: канал-константа; первое незамаскированное значение в следе тайла (грубый шаг)
        region = ee.Geometry(mapping(foot.loc[t, 'geometry']))
        cloud_asset = img.select('cloud_score').reduceRegion(ee.Reducer.firstNonNull(), region, 2000, bestEffort=True).get('cloud_score')
        col = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filter(ee.Filter.eq('MGRS_TILE', t))
               .filterDate('2020-06-01', '2025-10-01').filter(ee.Filter.calendarRange(7, 9, 'month'))
               .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 15)).sort('CLOUDY_PIXEL_PERCENTAGE'))
        top = col.limit(8)
        info = ee.Dictionary({'cloud_asset': cloud_asset,
                              'ids': top.aggregate_array('system:index'),
                              'clouds': top.aggregate_array('CLOUDY_PIXEL_PERCENTAGE'),
                              'times': top.aggregate_array('system:time_start')}).getInfo()
        ca = info['cloud_asset']
        ids, clouds, times = info['ids'], info['clouds'], info['times']
        pick = 0
        if ca is not None and clouds:
            diffs = [abs(c - ca) for c in clouds]
            pick = diffs.index(min(diffs))
        rec = {'tile': t, 'cloud_asset': ca}
        if ids:
            rec.update(scene_id=ids[pick], date=pd.to_datetime(times[pick], unit='ms').strftime('%Y-%m-%d'),
                       cloud_scene=clouds[pick], rank=pick + 1,
                       match=bool(ca is not None and abs(clouds[pick] - ca) < 1e-3))
        rows.append(rec)
        if (k + 1) % 16 == 0:
            print(f'  {k + 1}/128', flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(OUT, index=False, encoding='utf-8')
    d['year'] = d['date'].str[:4]
    d['month'] = d['date'].str[5:7]
    print(d['match'].value_counts(dropna=False).to_dict(), '| ранг совпавшей сцены:', d['rank'].value_counts().to_dict())
    print('по годам:', d['year'].value_counts().sort_index().to_dict())
    print('по месяцам:', d['month'].value_counts().sort_index().to_dict())
    print('облачность сцен: медиана', round(d['cloud_scene'].median(), 2), 'макс', round(d['cloud_scene'].max(), 2))
    print(f'-> {OUT}')


if __name__ == '__main__':
    main()
