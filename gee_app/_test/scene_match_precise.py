# Уточнение сцен тайлов по точной облачности из ассета маски (только чтение GEE). Запуск (около 10 мин):
# PYTHONIOENCODING=utf-8 python repo/gee_app/_test/scene_match_precise.py
# Отличие от scene_registry_check.py: облачность берётся не из реестра 126 (там она округлена, у многих тайлов 0,0),
# а из канала cloud_score самого ассета (float32 с CLOUDY_PIXEL_PERCENTAGE исходной сцены, 21_production_classify.js).
# Совпадение: IoU охватов следов >= 0.98 и облачность сцены равна cloud_score с точностью float32. У ассетов с
# неограниченным следом (41WPQ, 41WPR) охват не сравнивается, только облачность.
import math
from pathlib import Path

import ee
import pandas as pd

ee.Initialize(project='nodal-thunder-481307-u1')
P = 'projects/nodal-thunder-481307-u1/assets/ZapSib_baresands'
HERE = Path(__file__).parent
REG = pd.read_csv(r'D:\test\baresand_zapsib\exports\aux\tile_scenes.csv')
OUT = HERE / 'scene_match_precise.csv'


def ar(q: tuple[float, float, float, float]) -> float:
    return max(0.0, q[2] - q[0]) * max(0.0, q[3] - q[1])


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    i = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    u = ar(a) + ar(b) - ar(i)
    return ar(i) / u if u > 0 else 0.0


def same_cloud(c: float, cs: float) -> bool:
    # cloud_score хранится во float32: относительная ошибка около 6e-8
    return abs(c - cs) <= 1e-6 + 1e-6 * abs(cs)


def main() -> None:
    rows = []
    for k, r in enumerate(REG.itertuples()):
        asset = f"{P}/baresand_mask_{r.tile}{'__' if r.tile == '42WVC' else '_'}"
        meta = ee.data.getAsset(asset)
        g = meta['geometry']
        xs = [float(c[0]) for c in g['coordinates'][0]]
        ys = [float(c[1]) for c in g['coordinates'][0]]
        a = (min(xs), min(ys), max(xs), max(ys))
        bounded = all(math.isfinite(v) for v in a)
        img = ee.Image(asset)
        # точка внутри ассета: центр следа; при неограниченном следе центр сцены реестра того же тайла
        pt = img.geometry().centroid(1) if bounded else \
            ee.Image('COPERNICUS/S2_SR_HARMONIZED/' + r.scene_id).geometry().centroid(1)
        cs = img.select('cloud_score').reduceRegion(ee.Reducer.first(), pt, 10).get('cloud_score').getInfo()
        col = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filter(ee.Filter.eq('MGRS_TILE', r.tile))
               .filterDate('2020-06-01', '2025-10-01').filter(ee.Filter.calendarRange(7, 9, 'month'))
               .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 15)))
        fe = col.map(lambda im: ee.Feature(im.geometry().bounds(ee.ErrorMargin(1)),
                                           {'id': im.get('system:index'),
                                            'c': im.get('CLOUDY_PIXEL_PERCENTAGE')})).getInfo()['features']
        cand = []
        for f in fe:
            q = f['geometry']['coordinates'][0]
            b = (min(c[0] for c in q), min(c[1] for c in q), max(c[0] for c in q), max(c[1] for c in q))
            cand.append((f['properties']['id'], float(f['properties']['c']), iou(a, b) if bounded else float('nan'),
                         ar(b)))
        fp = [c for c in cand if bounded and c[2] >= 0.98]
        if cs is None:
            match = []
        elif bounded:
            match = [c for c in fp if same_cloud(c[1], cs)]
        else:
            # без охвата: облачность совпала, крупный след первым
            match = sorted([c for c in cand if same_cloud(c[1], cs)], key=lambda c: -c[3])
        # запасной вариант для показа: наименее облачная сцена, совпавшая по охвату
        fp_best = min(fp, key=lambda c: c[1])[0] if fp else ''
        rows.append({'tile': r.tile, 'scene_126': r.scene_id, 'cloud_score': cs, 'bounded': bounded,
                     'n_cand': len(cand), 'n_fp': len(fp), 'n_match': len(match),
                     'scenes_match': ';'.join(c[0] for c in match), 'scene_fp_least_cloud': fp_best,
                     'scene_126_matches': any(c[0] == r.scene_id for c in match),
                     'status': 'unique' if len(match) == 1 else 'ambiguous' if len(match) > 1 else 'none'})
        if (k + 1) % 16 == 0:
            print(k + 1, flush=True)
    o = pd.DataFrame(rows)
    o.to_csv(OUT, index=False)
    print(o.status.value_counts(dropna=False).to_dict())
    print('сцена реестра совпала:', int(o.scene_126_matches.sum()), 'из', len(o))
    print('число совпавших сцен:', o.n_match.value_counts().sort_index().to_dict())


if __name__ == '__main__':
    main()
