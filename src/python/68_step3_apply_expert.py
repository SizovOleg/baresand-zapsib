"""
68_step3_apply_expert.py — внести вердикты и разрезы эксперта в результат шага 3.

Правило (62) не воспроизводит ручные разрезы смешанных массивов «раздув + зона освоения» и часть точечных вердиктов;
работа эксперта — истина по определению, она должна быть в продукте. Скрипт:
  1. целые контуры с вердиктом эксперта → genesis по вердикту (anthropogenic / unassigned), step3_rule = expert_override;
     вердикт «отмель» (хасырей, осушка) → unassigned с пометкой expert_shoal (класс шага 2, сюда не переносим);
  2. разрезанные контуры → исходный контур удаляется, части вставляются как отдельные объекты
     (id = PART_ID_BASE + n, parent_id = исходный, genesis по вердикту части, step3_rule = expert_split, улики родителя NaN).
Вход:  exports/baresand_genesis_step3_<tag>.gpkg, exports/qc/step3/expert_verdicts_step3*.gpkg (65: Antropogen, Mixed; поздний слой
       перекрывает ранний по тем же id).
Выход: exports/baresand_genesis_step3_<tag>e.gpkg — результат шага 3 с учётом эксперта; сводка изменений.
Запуск: python -u python/68_step3_apply_expert.py --tag v3
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import argparse
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC3 = EXPORTS / 'qc' / 'step3'
EA_CRS = 'EPSG:3576'
PART_ID_BASE = 800_000              # части разрезов эксперта в продукте (маска ≤ 574 544, части шага 2 — 700 000+)
LAYERS = ('expert_verdicts_step3.gpkg', 'expert_verdicts_step3_mixed.gpkg', 'expert_verdicts_step3_nspd.gpkg',
          'expert_verdicts_step3_nspd_fin.gpkg')   # порядок: поздний перекрывает ранний


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='v3')
    a = ap.parse_args()
    src = EXPORTS / f'baresand_genesis_step3_{a.tag}.gpkg'
    out = EXPORTS / f'baresand_genesis_step3_{a.tag}e.gpkg'

    vs = []
    for name in LAYERS:
        p = QC3 / name
        if p.exists():
            v = gpd.read_file(p).to_crs(EA_CRS)
            v['layer'] = name
            vs.append(v)
    v = pd.concat(vs, ignore_index=True)
    v = v[v['expected_genesis'].notna()]
    # поздний слой перекрывает ранний по id
    last_layer = v.groupby('id')['layer'].transform('last')
    v = v[v['layer'] == last_layer].copy()
    whole = v[~v['is_part']]
    parts = v[v['is_part']]
    log(f'вердиктов: целых {whole.id.nunique()}, разрезано {parts.id.nunique()} контуров на {len(parts)} частей')

    log(f'читаю {src.name}...')
    g = gpd.read_file(src).to_crs(EA_CRS)
    n0, a0 = (g['genesis'] == 'anthropogenic').sum(), g.loc[g['genesis'] == 'anthropogenic', 'area_km2'].sum()

    # 1. целые контуры
    exp_map = whole.set_index('id')['expected_genesis']
    tag_map = whole.set_index('id')['tag']
    hit = g['id'].isin(exp_map.index)
    before = g.loc[hit, 'genesis'].copy()
    g.loc[hit, 'genesis'] = g.loc[hit, 'id'].map(exp_map)
    g.loc[hit, 'step3_rule'] = np.where(g.loc[hit, 'id'].map(tag_map) == 'shoal', 'expert_shoal', 'expert_override')
    changed = (before != g.loc[hit, 'genesis']).sum()
    log(f'целые: {int(hit.sum())} контуров получили вердикт эксперта, класс изменился у {int(changed)}')

    # 2. разрезы
    cut_ids = set(parts['id'].unique())
    orig = g[g['id'].isin(cut_ids)]
    log(f'разрезы: удаляю {len(orig)} исходных контуров ({orig.area_km2.sum():.1f} км²), вставляю {len(parts)} частей')
    g = g[~g['id'].isin(cut_ids)]
    rows = []
    for k, (_, p) in enumerate(parts.iterrows()):
        rows.append(dict(id=PART_ID_BASE + k, parent_id=int(p['id']), genesis=p['expected_genesis'], step3_rule='expert_split',
                         genesis_step2='unassigned', area_ha=round(p.geometry.area / 1e4, 3), area_km2=p.geometry.area / 1e6,
                         geometry=p.geometry))
    pg = gpd.GeoDataFrame(rows, geometry='geometry', crs=EA_CRS)
    res = gpd.GeoDataFrame(pd.concat([g, pg], ignore_index=True), geometry='geometry', crs=EA_CRS)
    for c in ('anthro_adjacent', 'new_since_1985', 'new_far', 'net_unsupported', 'burn_suspect', 'old_sand_2000', 'mixed_suspect',
              'hansen_covered', 'absent_s2', 'present_s2', 'anthro_suspect', 'khasyrei_suspect', 'split_n'):
        if c in res.columns:
            res[c] = res[c].fillna(0).astype('int16')
    res.loc[res['parent_id'].isin(cut_ids) & (res['step3_rule'] == 'expert_split'), 'mixed_suspect'] = 0

    n1, a1 = (res['genesis'] == 'anthropogenic').sum(), res.loc[res['genesis'] == 'anthropogenic', 'area_km2'].sum()
    L = [f'anthropogenic: {n0:,} конт / {a0:.1f} км² → {n1:,} конт / {a1:.1f} км² (эксперт: {int(hit.sum())} целых вердиктов, '
         f'{len(cut_ids)} разрезов → {len(parts)} частей: техноген {int((parts.expected_genesis == "anthropogenic").sum())} / '
         f'{parts.loc[parts.expected_genesis == "anthropogenic", "geometry"].area.sum() / 1e6:.1f} км², природный '
         f'{int((parts.expected_genesis != "anthropogenic").sum())} / {parts.loc[parts.expected_genesis != "anthropogenic", "geometry"].area.sum() / 1e6:.1f} км²)']
    for cls in ('shoal', 'river_shoal', 'lake_shoal', 'anthropogenic', 'unassigned'):
        s = res[res['genesis'] == cls]
        L.append(f'  {cls:13s}: {len(s):7,} конт | {s.area_km2.sum():7.1f} км²')
    print('\n'.join(L))
    res.to_file(out, layer='genesis', driver='GPKG')
    (QC3 / f'step3_expert_applied_{a.tag}.txt').write_text('\n'.join(L), encoding='utf-8')
    log(f'сохранено {out}')


if __name__ == '__main__':
    main()
