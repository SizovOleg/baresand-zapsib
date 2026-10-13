"""
108_burn_signature_modis.py - плечи подписи «лес был, лес пропал» по пожарам MODIS (2026-09-26).

Совокупность: undefined в v4 с tc2000_mean >= 10 и loss_frac >= 0.3 (2 007 контуров, 10.1 км2).
Метки владельца O1 (40 контуров) показали: при пожаре по MODIS MCD64A1 (любая дата 2000-2024, буфер 250 м) владелец видит
«не песок» (11 из 11 его «не песок» горели), без пожара чаще техноген (19 из 22). Гипотезы для проверки в O2
(заданы до отбора, подобраны на O1, поэтому только проверка на новой выборке решает):
  arm_burn  -> not_sand (флаг, класс не меняется);
  arm_clear -> anthropogenic.
Выход: exports/qc/owner_click/burn_pop.csv (id, area_ha, modis_burn, arm).
Запуск: PYTHONIOENCODING=utf-8 python -u python/108_burn_signature_modis.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
OUT = ROOT / 'exports' / 'qc' / 'owner_click' / 'burn_pop.csv'
BUF_M = 250
CHUNK = 400


def main() -> None:
    import ee
    try:
        ee.Initialize()
    except Exception:
        ee.Initialize(project='ee-ntcomz18')
    t0 = time.time()
    g = gpd.read_file(PRODUCT, layer='genesis', columns=['id', 'genesis', 'area_ha', 'tc2000_mean', 'loss_frac'],
                      where="genesis = 'undefined'")
    g = g[(g['tc2000_mean'].fillna(0) >= 10) & (g['loss_frac'].fillna(0) >= 0.3)].copy()
    g['geometry'] = g.geometry.simplify(5)
    gw = g.to_crs(4326)
    burned = ee.ImageCollection('MODIS/061/MCD64A1').select('BurnDate').map(lambda im: im.gt(0).unmask(0)).max().rename('b')
    rows = []
    for i0 in range(0, len(gw), CHUNK):
        part = gw.iloc[i0:i0 + CHUNK]
        fc = ee.FeatureCollection([ee.Feature(ee.Geometry(json.loads(gpd.GeoSeries([gm]).to_json())['features'][0]['geometry']),
                                              {'id': int(i)}).buffer(BUF_M) for i, gm in zip(part['id'], part.geometry)])
        st = burned.reduceRegions(collection=fc, reducer=ee.Reducer.max(), scale=250).getInfo()
        rows += [{'id': f['properties']['id'], 'modis_burn': f['properties'].get('max')} for f in st['features']]
        print(f'  {min(i0 + CHUNK, len(gw))}/{len(gw)}', flush=True)
    m = pd.DataFrame(rows)
    d = g.drop(columns='geometry').merge(m, on='id', how='left')
    d['arm'] = np.where(d['modis_burn'].fillna(0) >= 1, 'arm_burn', 'arm_clear')
    d.to_csv(OUT, index=False, encoding='utf-8')
    print(d.groupby('arm').agg(n=('id', 'size'), km2=('area_ha', lambda x: round(x.sum() / 100, 2))).to_string())
    print(f'-> {OUT} | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
