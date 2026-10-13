"""
94_step5_apply_expert.py — перенос вердиктов эксперта по спорным контурам целевой выборки (шаг 5) в продукт.

Спорные контуры (дешифровщик и скептик разошлись) в подбор порогов не входили; вердикт эксперта по ним — истина, которая
перекрывает и агентов, и правило. Как на шагах 2–4: целый вердикт → genesis эксперта, step5_rule = expert_override;
разрезанный контур (несколько объектов с одним id) → исходный контур удаляется, части входят с новыми id (продолжая ряд 800000+),
parent_id = исходный, step5_rule = expert_split. Невалидные после разреза геометрии чинятся (make_valid).

Вход:  exports/qc/target/<layer> (Check14.shp; поле expert, по-русски), exports/baresand_genesis_step5_<tag>.gpkg.
Выход: exports/baresand_genesis_step5_<tag>e.gpkg (+ .qml), exports/qc/target/expert_verdicts_step5.csv.
Запуск: python -u python/94_step5_apply_expert.py --tag v3 --layer Check14.shp
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import shutil
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QCT = EXPORTS / 'qc' / 'target'
EA_CRS = 'EPSG:3576'
SLIVER_HA = 0.02
RUS2EN = {'морская отмель': 'shoal', 'речная отмель': 'river_shoal', 'отмель речная': 'river_shoal', 'озёрная отмель': 'lake_shoal',
          'озерная отмель': 'lake_shoal', 'отмель озерная': 'lake_shoal', 'хасырей': 'lake_shoal',
          'техноген': 'anthropogenic', 'антропоген': 'anthropogenic', 'антропогенный': 'anthropogenic', 'техногенный': 'anthropogenic',
          'эоловый': 'aeolian', 'эоловое': 'aeolian', 'эоловая': 'aeolian', 'раздув': 'aeolian',
          'не песок': 'not_sand', 'не_песок': 'not_sand', 'лишайник': 'not_sand', 'снег': 'not_sand', 'гарь': 'not_sand',
          'торф': 'not_sand', 'вода': 'not_sand', 'неопределённый': 'undefined', 'неопределенный': 'undefined'}
# «не песок» на карте классом не является: такие контуры эксперт снимает с генезиса → undefined (контракт данных не меняется)
MAP_CLASS = {'not_sand': 'undefined'}


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def classify(text: str) -> str | None:
    t = str(text or '').strip().lower()
    if t in RUS2EN:
        return RUS2EN[t]
    for k, v in RUS2EN.items():
        if k in t:
            return v
    return t if t in ('shoal', 'river_shoal', 'lake_shoal', 'anthropogenic', 'aeolian', 'undefined') else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='v3')
    ap.add_argument('--layer', default='Check14.shp')
    a = ap.parse_args()
    t0 = time.time()
    src = EXPORTS / f'baresand_genesis_step5_{a.tag}.gpkg'
    out = EXPORTS / f'baresand_genesis_step5_{a.tag}e.gpkg'

    ex = gpd.read_file(QCT / a.layer).to_crs(EA_CRS)
    fld = 'expert' if 'expert' in ex.columns else 'verdict'
    bad = ~ex.geometry.is_valid
    if bad.any():
        ex.loc[bad, 'geometry'] = ex.loc[bad, 'geometry'].make_valid()
        log(f'починено невалидных геометрий: {int(bad.sum())}')
    ex['cls'] = [classify(t) for t in ex[fld]]
    ex['geom_ha'] = ex.geometry.area / 1e4
    unk = ex[ex['cls'].isna()]
    if len(unk):
        log(f'НЕ РАСПОЗНАНО: {unk[["id", fld]].to_dict("records")}')
    ex = ex[ex['cls'].notna() & (ex['geom_ha'] >= SLIVER_HA)].copy()
    ex['id'] = ex['id'].astype(int)
    ex['map_cls'] = ex['cls'].map(lambda c: MAP_CLASS.get(c, c))
    counts = ex['id'].value_counts()
    ex['is_part'] = ex['id'].map(counts) > 1
    whole = ex[~ex['is_part']]
    parts = ex[ex['is_part']]
    log(f'вердиктов: целых {len(whole)}, разрезов {parts["id"].nunique()} → {len(parts)} частей')
    ex.drop(columns='geometry').assign(geom_ha=lambda d: d['geom_ha'].round(3)).to_csv(
        QCT / 'expert_verdicts_step5.csv', index=False, encoding='utf-8')

    log(f'читаю {src.name}...')
    g = gpd.read_file(src, layer='genesis').to_crs(EA_CRS)
    before = g.groupby('genesis')['area_ha'].sum() / 100
    wmap = whole.set_index('id')['map_cls']
    m = g['id'].isin(wmap.index)
    g.loc[m, 'genesis'] = g.loc[m, 'id'].map(wmap)
    g.loc[m, 'step5_rule'] = 'expert_override'
    if 'genesis_confidence' in g.columns:
        g.loc[m, 'genesis_confidence'] = 'expert'
    if len(parts):
        next_id = int(max(g['id'].max() + 1, 800000))
        cut_ids = parts['id'].unique()
        parents = g[g['id'].isin(cut_ids)].set_index('id')
        rows = []
        for k, (_, p) in enumerate(parts.iterrows()):
            par = parents.loc[int(p['id'])]
            rows.append(dict(id=next_id + k, parent_id=int(p['id']), genesis=p['map_cls'], genesis_v2e=par.get('genesis_v2e', ''),
                             step5_rule='expert_split', genesis_confidence='expert',
                             area_ha=round(p['geom_ha'], 3), area_km2=round(p['geom_ha'] / 100, 4), geometry=p.geometry))
        add_g = gpd.GeoDataFrame(rows, geometry='geometry', crs=EA_CRS)
        g = gpd.GeoDataFrame(pd.concat([g[~g['id'].isin(cut_ids)], add_g], ignore_index=True), geometry='geometry', crs=EA_CRS)
    after = g.groupby('genesis')['area_ha'].sum() / 100
    L = ['класс: км² до → после']
    for c in ('shoal', 'river_shoal', 'lake_shoal', 'anthropogenic', 'aeolian', 'undefined'):
        L.append(f'  {c:14s} {before.get(c, 0):8.1f} → {after.get(c, 0):8.1f}')
    print('\n'.join(L))
    g.to_file(out, layer='genesis', driver='GPKG')
    qml = EXPORTS / f'baresand_genesis_step5_{a.tag}.qml'
    if qml.exists():
        shutil.copy2(qml, EXPORTS / f'baresand_genesis_step5_{a.tag}e.qml')
    log(f'сохранено {out} ({len(g)} контуров) | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
