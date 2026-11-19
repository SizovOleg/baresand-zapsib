# Восстановление исходных сцен тайлов по копиям скрипта 21_<тайл>_.js из репозитория GEE автора
# (users/<автор>/sand_ZapSib, папка rf; итоговые маски «с _ суффиксом», gee_scripts/22_mosaic_export.js).
# Вход: scripts_params.json (параметры, прочитанные из копий в Code Editor 19.11.2026: TILE_KEY, filterDate,
# calendarRange, порог облачности, NUM_SCENES, USE_SCENES). Выбор повторяется так же, как в копии: коллекция
# S2_SR_HARMONIZED тайла, фильтры, сортировка по облачности, первые NUM_SCENES, сцены с номерами USE_SCENES (с 1);
# при нескольких номерах классифицировалась их мозаика. Выход: scenes_from_scripts.csv (тайл, сцены через ;).
# Запуск: PYTHONIOENCODING=utf-8 python repo/gee_app/_test/scenes_from_scripts.py
import json
import re
from pathlib import Path

import ee
import pandas as pd

ee.Initialize(project='nodal-thunder-481307-u1')
HERE = Path(__file__).parent
PARAMS = HERE / 'scripts_params.json'
OUT = HERE / 'scenes_from_scripts.csv'


def quoted(s: str) -> list[str]:
    return re.findall(r"'([^']*)'", s or '')


def scenes_for(p: dict) -> list[str]:
    tile = p['tile']
    col = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filter(ee.Filter.eq('MGRS_TILE', tile))
    d = quoted(p.get('date'))
    if len(d) == 2:
        col = col.filterDate(d[0], d[1])
    if p.get('cal'):
        a = [x.strip() for x in p['cal'].split(',')]
        col = col.filter(ee.Filter.calendarRange(int(a[0]), int(a[1]), a[2].strip("'\"")))
    col = col.filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', float(p.get('cloudlt') or 15)))
    col = col.sort('CLOUDY_PIXEL_PERCENTAGE')
    num = int(p.get('num') or 10)
    ids = col.limit(num).aggregate_array('system:index').getInfo()
    use = json.loads(p['use']) if p.get('use') else [1]
    return [ids[n - 1] for n in use if 0 < n <= len(ids)]


def main() -> None:
    params = json.loads(PARAMS.read_text(encoding='utf-8'))
    rows = []
    for name, p in sorted(params.items()):
        if not name.endswith('_.js') or not p.get('tile'):
            continue
        try:
            sc = scenes_for(p)
            rows.append({'script': name, 'tile': p['tile'], 'use': p.get('use'), 'num': p.get('num'),
                         'date': p.get('date'), 'cal': p.get('cal'), 'region': p.get('region'),
                         'scenes': ';'.join(sc), 'n_scenes': len(sc)})
        except Exception as e:  # ошибка одного тайла пишется в таблицу, остальные считаются
            rows.append({'script': name, 'tile': p.get('tile'), 'error': str(e)[:200]})
    o = pd.DataFrame(rows)
    o.to_csv(OUT, index=False)
    print('скриптов _:', len(o), '| сцен на тайл:', o['n_scenes'].value_counts().to_dict())


if __name__ == '__main__':
    main()
