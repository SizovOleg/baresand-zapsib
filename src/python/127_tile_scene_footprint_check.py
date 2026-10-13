"""
127_tile_scene_footprint_check.py - проверка воспроизведённых сцен тайлов (126) по следу ассета (2026-09-30).

След ассета тайла (system:footprint) совпадает со следом сцены, по которой он экспортирован (region = scene.geometry()).
Облачность сцен почти нулевая, поэтому сверка 126 по облачности слабая; здесь для каждого тайла среди сцен-кандидатов
(июль-сентябрь 2020-2025, облачность < 15 %) ищутся сцены, чей след совпадает со следом ассета (IoU > 0.98), и
проверяется, есть ли среди них воспроизведённая сцена. Совпадение следа определяет орбиту; при нескольких датах одной
орбиты с нулевой облачностью дата остаётся неоднозначной.
Выход: exports/aux/tile_scenes_check.csv. Запуск: PYTHONIOENCODING=utf-8 python -u python/127_tile_scene_footprint_check.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

import pandas as pd
from shapely.geometry import shape

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
PROJECT = 'projects/nodal-thunder-481307-u1/assets/ZapSib_baresands'
IN = ROOT / 'exports' / 'aux' / 'tile_scenes.csv'
OUT = ROOT / 'exports' / 'aux' / 'tile_scenes_check.csv'


def iou(a, b) -> float:
    u = a.union(b).area
    return a.intersection(b).area / u if u else 0.0


def main() -> None:
    cpu_limit.apply()
    import ee
    try:
        ee.Initialize()
    except Exception:
        ee.Initialize(project='ee-ntcomz18')
    t = pd.read_csv(IN)
    rows = []
    for k, r in enumerate(t.itertuples()):
        key = r.tile + ('__' if r.tile == '42WVC' else '_')
        fa = shape(ee.data.getAsset(f'{PROJECT}/baresand_mask_{key}')['geometry'])
        col = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filter(ee.Filter.eq('MGRS_TILE', r.tile))
               .filterDate('2020-06-01', '2025-10-01').filter(ee.Filter.calendarRange(7, 9, 'month'))
               .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 15)).sort('CLOUDY_PIXEL_PERCENTAGE').limit(25))
        feats = col.map(lambda im: ee.Feature(im.geometry(), {'id': im.get('system:index'), 'cloud': im.get('CLOUDY_PIXEL_PERCENTAGE'),
                                                             't': im.get('system:time_start')})).getInfo()['features']
        same = [(f['properties']['id'], f['properties']['cloud'], iou(fa, shape(f['geometry']))) for f in feats]
        cand = [s for s in same if s[2] > 0.98]
        min_cloud = min((s[1] for s in cand), default=None)
        best = [s for s in cand if min_cloud is not None and s[1] - min_cloud < 1e-3]
        rows.append({'tile': r.tile, 'scene_126': r.scene_id, 'footprint_match_126': any(s[0] == r.scene_id for s in cand),
                     'n_same_footprint': len(cand), 'n_same_fp_min_cloud': len(best),
                     'dates_same_fp_min_cloud': ';'.join(s[0][:8] for s in best)})
        if (k + 1) % 16 == 0:
            print(f'  {k + 1}/{len(t)}', flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(OUT, index=False, encoding='utf-8')
    print('след совпал с воспроизведённой сценой:', d['footprint_match_126'].value_counts().to_dict())
    print('однозначно (одна сцена с этим следом и минимальной облачностью):', int((d['n_same_fp_min_cloud'] == 1).sum()), 'из', len(d))
    print(f'-> {OUT}')


if __name__ == '__main__':
    main()
