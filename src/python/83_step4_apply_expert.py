"""
83_step4_apply_expert.py — перенос вердиктов эксперта по шагу 4 в эталон и в продукт.

Вход:  слой эксперта exports/qc/step4/<layer> (по умолчанию Final.shp — final_check_step4 после правки; поле вердикта expert
       или verdict), исходные геометрии exports/qc/step4/visual_sample_geoms_step4.gpkg (слой sample),
       продукт exports/baresand_genesis_step4_<tag>.gpkg.
Словарь вердиктов эксперта (регистр не важен): «эолов…» → aeolian; «отмель», «техноген», «хасырей», «лишайник», «торф», «гарь»,
       «снег», «щебень», «не песок», «не_песок», «природн…» без уточнения → undefined (для шага 4 всё, что не эоловый).
Если эксперт разрезал контур — части (несколько объектов с одним id) получают синтетические id 900_000_000 + id*10 + k, идут в эталон
как страта expert_part и заменяют исходный контур в продукте (id 800000+, step4_rule = expert_split, parent_id = исходный).
Выход: exports/qc/step4/expert_verdicts_step4[_<tag>].csv/.gpkg, дополненный exports/qc/step4/regression_step4.csv,
       продукт exports/baresand_genesis_step4_<tag>e.gpkg (step4_rule = expert_override у целых вердиктов).
Запуск: python -u python/83_step4_apply_expert.py --tag v2 --layer Final.shp
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
QC4 = EXPORTS / 'qc' / 'step4'
SAMPLE_GEOMS = QC4 / 'visual_sample_geoms_step4.gpkg'
REGRESSION = QC4 / 'regression_step4.csv'
EA_CRS = 'EPSG:3576'
SLIVER_HA = 0.05
PART_ID_BASE = 800000
SYNTH_BASE = 900_000_000
AEOL = ('эолов', 'раздув', 'дюн', 'котловин', 'развеива')
UNDEF = ('отмель', 'техноген', 'хасырей', 'лишайник', 'торф', 'гарь', 'снег', 'щебен', 'не песок', 'не_песок', 'болот', 'вода', 'природн')


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def classify(text: str) -> tuple[str | None, str]:
    """Текст эксперта → (expected_genesis шага 4, тег). Пусто = согласен с правилом (в эталон не идёт)."""
    t = (text or '').strip().lower()
    if not t:
        return None, 'empty'
    if any(t.startswith(w) or w in t for w in AEOL):
        return 'aeolian', 'aeolian'
    for w in UNDEF:
        if w in t:
            return 'undefined', w
    return None, 'unknown:' + t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='v2')
    ap.add_argument('--layer', default='Final.shp')
    ap.add_argument('--field', default=None, help='поле вердикта (по умолчанию expert, иначе verdict)')
    a = ap.parse_args()
    t0 = time.time()
    src = EXPORTS / f'baresand_genesis_step4_{a.tag}.gpkg'
    out = EXPORTS / f'baresand_genesis_step4_{a.tag}e.gpkg'
    layer = QC4 / a.layer
    tag_out = layer.stem.lower()
    out_csv = QC4 / (f'expert_verdicts_step4.csv' if tag_out == 'aeolian' else f'expert_verdicts_step4_{tag_out}.csv')
    out_gpkg = out_csv.with_suffix('.gpkg')

    ex = gpd.read_file(layer).to_crs(EA_CRS)
    field = a.field or ('expert' if 'expert' in ex.columns else 'verdict')
    ex = ex.rename(columns={field: 'expert'})
    # разрез по самокасающейся пиксельной границе даёт Ring Self-intersection → GDAL/QGIS не читают таблицу; чиним на приёме
    bad = ~ex.geometry.is_valid
    if bad.any():
        ex.loc[bad, 'geometry'] = ex.loc[bad, 'geometry'].make_valid()
        ex = ex[~ex.geometry.is_empty]
        log(f'починено невалидных геометрий в слое эксперта: {int(bad.sum())}')
    ex['geom_ha'] = ex.geometry.area / 1e4
    ex = ex[ex['geom_ha'] >= SLIVER_HA].copy()
    parsed = ex['expert'].apply(classify)
    ex['expected_genesis'] = [p[0] for p in parsed]
    ex['tag'] = [p[1] for p in parsed]
    bad = ex[ex['tag'].str.startswith('unknown')]
    if len(bad):
        print('НЕРАЗОБРАННЫЕ вердикты:', bad[['id', 'expert']].to_string(index=False))
    ex = ex[ex['expected_genesis'].notna()].copy()
    ex['n_parts'] = ex.groupby('id')['id'].transform('size')
    orig = gpd.read_file(SAMPLE_GEOMS, layer='sample').to_crs(EA_CRS).set_index('id')
    ex['orig_ha'] = ex['id'].map(orig['area_ha'])
    cut = (ex['n_parts'] > 1) | ((ex['geom_ha'] / ex['orig_ha'] - 1).abs() > 0.05)
    whole, parts = ex[~cut].copy(), ex[cut].copy()
    parts['k'] = parts.groupby('id').cumcount() + 1
    parts['part_id'] = SYNTH_BASE + parts['id'] * 10 + parts['k']
    log(f'вердиктов: целых {len(whole)}, разрезано {parts["id"].nunique()} контуров на {len(parts)} частей; '
        f'{whole["expected_genesis"].value_counts().to_dict()}')

    v = pd.concat([whole.assign(is_part=False, part_id=whole['id']), parts.assign(is_part=True)], ignore_index=True)
    v[['id', 'part_id', 'is_part', 'expert', 'expected_genesis', 'tag', 'geom_ha', 'orig_ha']].to_csv(out_csv, index=False, encoding='utf-8')
    gpd.GeoDataFrame(v, geometry='geometry', crs=EA_CRS).to_file(out_gpkg, driver='GPKG')

    reg = pd.read_csv(REGRESSION) if REGRESSION.exists() else pd.DataFrame(columns=['id', 'expected_genesis', 'stratum', 'sector'])
    stratum = ex.get('stratum', pd.Series('expert', index=ex.index))
    add = pd.DataFrame({'id': v['part_id'].astype(int), 'expected_genesis': v['expected_genesis'],
                        'stratum': np.where(v['is_part'], 'expert_part', 'expert_step4'), 'sector': -1})
    reg = pd.concat([reg[~reg['id'].isin(add['id'])], add], ignore_index=True)      # вердикт эксперта перекрывает агентский
    reg.to_csv(REGRESSION, index=False, encoding='utf-8')
    sg = gpd.read_file(SAMPLE_GEOMS, layer='sample').to_crs(EA_CRS)
    if len(parts):
        pg = gpd.GeoDataFrame({'id': parts['part_id'].astype(int), 'genesis': parts['expected_genesis'],
                               'stratum': 'expert_part', 'area_ha': parts['geom_ha'].round(3)},
                              geometry=parts.geometry.values, crs=EA_CRS)
        sg = pd.concat([sg[~sg['id'].isin(pg['id'])], pg], ignore_index=True)
        gpd.GeoDataFrame(sg, geometry='geometry', crs=EA_CRS).to_file(SAMPLE_GEOMS, layer='sample', driver='GPKG')
    log(f'эталон: {len(reg)} строк (добавлено/обновлено {len(add)})')

    log(f'читаю {src.name}...')
    g = gpd.read_file(src).to_crs(EA_CRS)
    n0, a0 = (g['genesis'] == 'aeolian').sum(), g.loc[g['genesis'] == 'aeolian', 'area_km2'].sum()
    wmap = whole.set_index('id')['expected_genesis']
    m = g['id'].isin(wmap.index)
    g.loc[m, 'genesis'] = g.loc[m, 'id'].map(wmap)
    g.loc[m, 'step4_rule'] = 'expert_override'
    g.loc[m, 'genesis_confidence'] = 'expert'
    if len(parts):
        cut_ids = parts['id'].unique()
        keep = ~g['id'].isin(cut_ids)
        base = g[g['id'].isin(cut_ids)].iloc[0:0]
        rows = []
        for k, (_, p) in enumerate(parts.iterrows(), start=1):
            rows.append(dict(id=PART_ID_BASE + k, parent_id=int(p['id']), genesis=p['expected_genesis'], step4_rule='expert_split',
                             genesis_confidence='expert', area_ha=round(p['geom_ha'], 3), area_km2=round(p['geom_ha'] / 100, 4),
                             geometry=p.geometry))
        add_g = gpd.GeoDataFrame(rows, geometry='geometry', crs=EA_CRS)
        g = pd.concat([g[keep], add_g], ignore_index=True)
        g = gpd.GeoDataFrame(g, geometry='geometry', crs=EA_CRS)
    n1, a1 = (g['genesis'] == 'aeolian').sum(), g.loc[g['genesis'] == 'aeolian', 'area_km2'].sum()
    L = [f'aeolian: {n0:,} конт / {a0:.1f} км² → {n1:,} конт / {a1:.1f} км² (эксперт: {len(whole)} целых вердиктов, '
         f'{parts["id"].nunique() if len(parts) else 0} разрезов → {len(parts)} частей)']
    for cls in ('aeolian', 'undefined'):
        s = g[g['genesis'] == cls]
        L.append(f'  {cls:12s}: {len(s):7,} конт | {s.area_km2.sum():7.1f} км²')
    print('\n'.join(L))
    g.to_file(out, layer='genesis', driver='GPKG')
    (QC4 / f'step4_expert_applied_{a.tag}.txt').write_text('\n'.join(L), encoding='utf-8')
    log(f'сохранено {out} | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
