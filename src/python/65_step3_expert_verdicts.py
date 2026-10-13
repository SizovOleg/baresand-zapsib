"""
65_step3_expert_verdicts.py — перенос финальных вердиктов эксперта по шагу 3 в эталон.

Вход:  слой эксперта (--layer): exports/qc/step3/Antropogen.shp — final_check_step3 после правки (по умолчанию) или
       exports/qc/step3/Mixed.shp — разрезы смешанных гигантов из mixed_suspect_step3.gpkg (--layer Mixed.shp --orig mixed_suspect_step3.gpkg).
       Колонка expert (техноген / природный / озёрная отмель / «техноген, квадратный, рядом карьеры» …), часть контуров разрезана
       на части (несколько строк с одним id). Повторный разрез того же id заменяет прежние части (синтетические id id*10+k).
Выход: exports/qc/step3/regression_step3.csv           — эталон (вердикт эксперта перекрывает агентов);
       exports/qc/step3/visual_sample_geoms_step3.gpkg — слой sample + части разрезов (синтетические id = PART_ID_BASE + id*10 + k);
       exports/qc/step3/expert_verdicts_step3.csv/.gpkg — все вердикты с разбором;
       exports/qc/step3/expert_split_step3.gpkg        — разрезы эксперта (природный массив vs техноген) — калибровка разреза 66.
Запуск: python -u python/65_step3_expert_verdicts.py [--layer Mixed.shp --orig mixed_suspect_step3.gpkg --stratum expert_mixed]
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC3 = EXPORTS / 'qc' / 'step3'
EXPERT_SHP = QC3 / 'Antropogen.shp'
FINAL_CHECK = QC3 / 'final_check_step3.gpkg'
REGRESSION = QC3 / 'regression_step3.csv'
SAMPLE_GEOMS = QC3 / 'visual_sample_geoms_step3.gpkg'
VERDICTS_CSV = QC3 / 'visual_qc_step3_verdicts.csv'
OUT_CSV = QC3 / 'expert_verdicts_step3.csv'
OUT_GPKG = QC3 / 'expert_verdicts_step3.gpkg'
OUT_SPLIT = QC3 / 'expert_split_step3.gpkg'
EA_CRS = 'EPSG:3576'
PART_ID_BASE = 900_000_000
SLIVER_HA = 0.01


def classify(text: str) -> tuple[str, str]:
    """Текст эксперта → (expected_genesis для шага 3, тег). Техноген → anthropogenic; всё природное → unassigned."""
    t = (text or '').strip().lower()
    if not t:
        return None, 'empty'
    if t.startswith('техноген'):
        return 'anthropogenic', 'anthropogenic'
    if 'отмель' in t:
        return 'unassigned', 'shoal'            # озёрная/речная отмель — класс шага 2, для шага 3 «не техноген»
    if t.startswith('природн'):
        return 'unassigned', 'natural'
    return None, 'unknown:' + t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--layer', default=EXPERT_SHP.name, help='слой эксперта в exports/qc/step3/')
    ap.add_argument('--orig', default=FINAL_CHECK.name, help='слой с исходными геометриями контуров (для доли части)')
    ap.add_argument('--stratum', default=None, help='страта для целых контуров в регрессии (по умолчанию — из слоя)')
    ap.add_argument('--field', default=None, help='поле с вердиктом эксперта (по умолчанию expert, иначе verdict)')
    a = ap.parse_args()
    layer, orig_p = QC3 / a.layer, QC3 / a.orig
    ex = gpd.read_file(layer).to_crs(EA_CRS)
    field = a.field or ('expert' if 'expert' in ex.columns else 'verdict')
    if field != 'expert':
        ex = ex.rename(columns={field: 'expert'})
    # маска векторизована из растра: границы самокасающиеся (углы пикселей), и разрез эксперта через такую точку даёт
    # Ring Self-intersection — GDAL/QGIS потом не читают таблицу («Shape integrity error»). Чиним сразу на приёме.
    bad = ~ex.geometry.is_valid
    if bad.any():
        ex.loc[bad, 'geometry'] = ex.loc[bad, 'geometry'].make_valid()
        ex = ex[~ex.geometry.is_empty]
        print(f'починено невалидных геометрий в слое эксперта: {int(bad.sum())}')
    fc = gpd.read_file(orig_p).to_crs(EA_CRS).set_index('id')
    tag_out = layer.stem.lower()
    global OUT_CSV, OUT_GPKG, OUT_SPLIT
    if tag_out != 'antropogen':
        OUT_CSV = QC3 / f'expert_verdicts_step3_{tag_out}.csv'
        OUT_GPKG = QC3 / f'expert_verdicts_step3_{tag_out}.gpkg'
        OUT_SPLIT = QC3 / f'expert_split_step3_{tag_out}.gpkg'
    for c in ('agents', 'stratum', 'genesis', 'step3_rule'):
        if c not in ex.columns:
            ex[c] = ''
    if a.stratum:
        ex['stratum'] = a.stratum
    ex['geom_ha'] = ex.geometry.area / 1e4
    ex = ex[ex['geom_ha'] >= SLIVER_HA].copy()
    parsed = ex['expert'].apply(classify)
    ex['expected_genesis'] = [p[0] for p in parsed]
    ex['tag'] = [p[1] for p in parsed]
    bad = ex[ex['tag'].str.startswith('unknown')]
    if len(bad):
        sys.exit(f'Неизвестные формулировки эксперта: {bad["expert"].unique().tolist()}')

    sectors = pd.read_csv(VERDICTS_CSV)[['id', 'sector']].drop_duplicates('id').set_index('id')['sector']
    rows = []
    for cid, grp in ex.groupby('id'):
        orig = fc.geometry.loc[cid]
        is_split = len(grp) > 1
        for k, (_, r) in enumerate(grp.sort_values('geom_ha', ascending=False).iterrows(), start=1):
            rows.append(dict(id=cid, part_id=(PART_ID_BASE + cid * 10 + k) if is_split else cid, is_part=is_split,
                             agents=r['agents'], expert=r['expert'], expected_genesis=r['expected_genesis'], tag=r['tag'],
                             stratum=r['stratum'], genesis_rule=r['genesis'], step3_rule=r['step3_rule'],
                             sector=int(sectors.get(cid, -1)), area_ha=round(r['geom_ha'], 3),
                             part_frac=round(r.geometry.area / orig.area, 4), geometry=r.geometry))
    v = gpd.GeoDataFrame(rows, geometry='geometry', crs=EA_CRS)
    v.drop(columns='geometry').to_csv(OUT_CSV, index=False, encoding='utf-8')
    v.to_file(OUT_GPKG, driver='GPKG')

    # ── контроль агентов ──
    whole = v[~v['is_part']]
    ctrl = whole[whole['agents'].isin(['техноген', 'природный'])]
    ag_map = {'техноген': 'anthropogenic', 'природный': 'unassigned'}
    ok = ctrl['agents'].map(ag_map) == ctrl['expected_genesis']
    print(f'Контроль (агенты уверены): {len(ctrl)} целых; совпало: {int(ok.sum())}/{len(ctrl)}')
    for _, r in ctrl[~ok].iterrows():
        print(f'  расхождение {r.id}: агенты «{r.agents}» → эксперт «{r.expert}»')
    doubt = whole[~whole['agents'].isin(['техноген', 'природный'])]
    print(f'Целиком решено экспертом (без уверенного вердикта агентов): {len(doubt)} → ' + ', '.join(f'{r.id}:{r.tag}' for _, r in doubt.iterrows()))
    for cid, grp in v[v.is_part].groupby('id'):
        print(f'  {cid} разрезан на {len(grp)}: ' + '; '.join(f'{p.area_ha:.1f} га → {p.tag}' for _, p in grp.iterrows()))

    # ── регрессия ──
    reg = pd.read_csv(REGRESSION)
    scored = v[v['expected_genesis'].notna()]
    stale = set()
    for cid in v['id'].unique():
        stale.update(range(PART_ID_BASE + int(cid) * 10 + 1, PART_ID_BASE + int(cid) * 10 + 10))
    reg = reg[~reg['id'].isin(v['id']) & ~reg['id'].isin(stale)]
    add = scored[['part_id', 'expected_genesis', 'stratum', 'sector']].rename(columns={'part_id': 'id'})
    add['stratum'] = add['stratum'].where(~scored['is_part'].values, 'expert_part')
    reg = pd.concat([reg, add], ignore_index=True).sort_values(['sector', 'id'])
    reg.to_csv(REGRESSION, index=False, encoding='utf-8')
    print(f'\nРегрессия: {len(reg)} строк (добавлено/обновлено {len(add)}, частей разрезов {int(scored.is_part.sum())})')
    print(reg['expected_genesis'].value_counts().to_string())

    sg = gpd.read_file(SAMPLE_GEOMS, layer='sample').to_crs(EA_CRS)
    parts = scored[scored['is_part']]
    sg = sg[~sg['id'].isin(stale)]
    # целые контуры, которых нет в выборке (разрезы вне final_check) — добавить геометрии для оценки по геометрии
    whole_new = scored[~scored['is_part'] & ~scored['id'].isin(sg['id'])]
    if len(whole_new):
        sg = pd.concat([sg, gpd.GeoDataFrame({'id': whole_new['id'].values, 'genesis': whole_new['expected_genesis'].values,
                                              'stratum': whole_new['stratum'].values, 'area_ha': whole_new['area_ha'].values},
                                             geometry=whole_new.geometry.values, crs=EA_CRS)], ignore_index=True)
    add_g = gpd.GeoDataFrame({'id': parts['part_id'].values, 'genesis': parts['expected_genesis'].values,
                              'stratum': 'expert_part', 'area_ha': parts['area_ha'].values}, geometry=parts.geometry.values, crs=EA_CRS)
    sg = pd.concat([sg, add_g], ignore_index=True)
    sg.to_file(SAMPLE_GEOMS, layer='sample', driver='GPKG')
    print(f'Геометрии выборки: {len(sg)} (добавлено частей: {len(add_g)})')

    # ── разрезы эксперта → калибровка автоматического разреза ──
    parts[['id', 'part_id', 'tag', 'expected_genesis', 'area_ha', 'part_frac', 'geometry']].to_file(OUT_SPLIT, driver='GPKG')
    sp = parts.groupby('id').agg(n=('part_id', 'size'), anthro_ha=('area_ha', lambda s: s[parts.loc[s.index, 'tag'] == 'anthropogenic'].sum()),
                                 natural_ha=('area_ha', lambda s: s[parts.loc[s.index, 'tag'] != 'anthropogenic'].sum()))
    print('\nРазрезы эксперта (техноген / природный, га):'); print(sp.round(1).to_string())
    print(f'сохранено {OUT_SPLIT.name}')


if __name__ == '__main__':
    main()
