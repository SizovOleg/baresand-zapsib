# Уточнение реестра сцен по охвату следа ассета тайла (только чтение GEE). Запуск (около 20 мин):
# PYTHONIOENCODING=utf-8 python -I repo/gee_app/_test/scene_registry_check.py
# Ассет маски экспортирован с region = scene.geometry() (gee_scripts/21_production_classify.js), поэтому охват его следа
# совпадает с охватом следа использованной сцены. Кандидаты: то же правило отбора, что в 21 и 126 (июль-сентябрь
# 2020-2025, облачность < 15 %); совпадение: IoU охватов >= 0.98 и облачность сцены = cloud_score ассета (126).
import math

import ee
import pandas as pd

ee.Initialize()
P = 'projects/nodal-thunder-481307-u1/assets/ZapSib_baresands'
d = pd.read_csv(r'D:\test\baresand_zapsib\exports\aux\tile_scenes.csv')


def ar(q: tuple[float, float, float, float]) -> float:
    return max(0.0, q[2] - q[0]) * max(0.0, q[3] - q[1])


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    i = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    u = ar(a) + ar(b) - ar(i)
    return ar(i) / u if u > 0 else 0.0


rows = []
for k, r in enumerate(d.itertuples()):
    key = r.tile + ('__' if r.tile == '42WVC' else '_')
    g = ee.data.getAsset(f'{P}/baresand_mask_{key}')['geometry']
    xs = [float(c[0]) for c in g['coordinates'][0]]
    ys = [float(c[1]) for c in g['coordinates'][0]]
    a = (min(xs), min(ys), max(xs), max(ys))
    rec = {'tile': r.tile, 'scene_126': r.scene_id, 'cloud_asset': r.cloud_asset}
    if not all(math.isfinite(v) for v in a):
        rec.update(status='asset_unbounded', n_fp=None, n_fp_cloud=None, scene_fp=None)
        rows.append(rec)
        continue
    col = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filter(ee.Filter.eq('MGRS_TILE', r.tile))
           .filterDate('2020-06-01', '2025-10-01').filter(ee.Filter.calendarRange(7, 9, 'month'))
           .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 15)))
    fe = col.map(lambda im: ee.Feature(im.geometry().bounds(ee.ErrorMargin(1)),
                                       {'id': im.get('system:index'), 'c': im.get('CLOUDY_PIXEL_PERCENTAGE')})).getInfo()['features']
    cand = []
    for f in fe:
        cs = f['geometry']['coordinates'][0]
        b = (min(c[0] for c in cs), min(c[1] for c in cs), max(c[0] for c in cs), max(c[1] for c in cs))
        cand.append((f['properties']['id'], f['properties']['c'], iou(a, b)))
    fp = [c for c in cand if c[2] >= 0.98]
    ca = r.cloud_asset
    fpc = [c for c in fp if ca == ca and abs(c[1] - ca) < 1e-3] if ca == ca else []
    best = fpc if fpc else []
    rec.update(n_cand=len(cand), n_fp=len(fp), n_fp_cloud=len(fpc),
               scene_fp=';'.join(c[0] for c in sorted(fpc, key=lambda c: c[0])),
               scene_126_in_fp=any(c[0] == r.scene_id for c in fp),
               status=('unique' if len(fpc) == 1 else 'ambiguous' if len(fpc) > 1 else 'none'))
    rows.append(rec)
    if (k + 1) % 16 == 0:
        print(k + 1, flush=True)
o = pd.DataFrame(rows)
o.to_csv(r'D:\test\baresand_zapsib\repo\gee_app\_test\scene_registry_check.csv', index=False)
print(o.status.value_counts(dropna=False).to_dict())
print('сцена 126 среди совпавших по охвату:', o.scene_126_in_fp.value_counts(dropna=False).to_dict())
print(o.n_fp_cloud.value_counts(dropna=False).sort_index().to_dict())
