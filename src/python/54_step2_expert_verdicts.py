"""
54_step2_expert_verdicts.py — перенос финальных вердиктов эксперта по шагу 2 в эталон.

Вход:  exports/qc/step2/Rivers.shp — слой final_check_step2 после правки экспертом:
       колонка expert (речная отмель / озёрная отмель / не отмель / город / карьер у реки / антропоген / раздув /
       морская отмель / «раздув с отмелью, разрезать» / «раздув и речная отмель»), часть контуров разрезана на части
       (несколько строк с одним id).
Выход: exports/qc/step2/regression_step2.csv           — эталон (вердикт эксперта перекрывает агентов);
       exports/qc/step2/visual_sample_geoms_step2.gpkg — геометрии для оценки по геометрии (добавлены части разрезов,
                                                          синтетические id = PART_ID_BASE + id*10 + k);
       exports/qc/step2/expert_verdicts_step2.csv/.gpkg — все вердикты с разбором;
       exports/qc/step2/split_targets_step2.csv        — смешанные контуры «разрезать» (проверка скрипта 55);
       exports/qc/expert_overrides.csv                 — точечные вердикты, которых правило не выводит (морская отмель 574532),
                                                          применяются в 51_step2_rule.py.
Запуск: python -u python/54_step2_expert_verdicts.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

import geopandas as gpd
import pandas as pd

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC = EXPORTS / 'qc'
QC2 = QC / 'step2'
EXPERT_SHP = QC2 / 'Rivers.shp'
FINAL_CHECK = QC2 / 'final_check_step2.gpkg'
REGRESSION = QC2 / 'regression_step2.csv'
SAMPLE_GEOMS = QC2 / 'visual_sample_geoms_step2.gpkg'
VERDICTS_CSV = QC2 / 'visual_qc_step2_verdicts.csv'
OUT_CSV = QC2 / 'expert_verdicts_step2.csv'
OUT_GPKG = QC2 / 'expert_verdicts_step2.gpkg'
SPLIT_TARGETS = QC2 / 'split_targets_step2.csv'
OVERRIDES = QC / 'expert_overrides.csv'
EA_CRS = 'EPSG:3576'

PART_ID_BASE = 900_000_000     # синтетические id частей разрезов эксперта
SLIVER_HA = 0.01               # артефакты разреза (доли квадратного метра) — отбрасываем

# текст эксперта → (класс для регрессии шага 2, тег генезиса)
EXPERT_MAP = {
    'речная отмель': ('river_shoal', 'river'),
    'озёрная отмель': ('lake_shoal', 'lake'),
    'не отмель': ('unassigned', 'not_shoal'),
    'раздув': ('unassigned', 'aeolian'),
    'город': ('unassigned', 'anthropogenic'),
    'карьер у реки': ('unassigned', 'anthropogenic'),
    'антропоген': ('unassigned', 'anthropogenic'),
    'морская отмель': ('unassigned', 'marine'),      # для шага 2 — не речная/озёрная; для итога — shoal (override)
    'раздув с отмелью, разрезать': (None, 'mixed'),
    'раздув и речная отмель': (None, 'mixed'),
}
AGENT_MAP = {'речная отмель': 'river_shoal', 'озёрная отмель': 'lake_shoal', 'не отмель': 'unassigned', 'сомнение': None}


def main() -> None:
    ex = gpd.read_file(EXPERT_SHP).to_crs(EA_CRS)
    fc = gpd.read_file(FINAL_CHECK).to_crs(EA_CRS).set_index('id')
    ex['expert'] = ex['expert'].str.strip()
    unknown = sorted(set(ex['expert']) - set(EXPERT_MAP))
    if unknown:
        sys.exit(f'Неизвестные формулировки эксперта: {unknown} — добавь в EXPERT_MAP')
    ex['geom_ha'] = ex.geometry.area / 1e4
    ex = ex[ex['geom_ha'] >= SLIVER_HA].copy()

    sectors = pd.read_csv(VERDICTS_CSV)[['id', 'sector']].drop_duplicates('id').set_index('id')['sector']
    rows = []
    for cid, grp in ex.groupby('id'):
        orig = fc.geometry.loc[cid]
        is_split = len(grp) > 1
        for k, (_, r) in enumerate(grp.sort_values('geom_ha', ascending=False).iterrows(), start=1):
            expected, tag = EXPERT_MAP[r['expert']]
            iou = orig.intersection(r.geometry).area / orig.union(r.geometry).area
            rows.append(dict(
                id=cid, part_id=(PART_ID_BASE + cid * 10 + k) if is_split else cid, is_part=is_split,
                agents=r['agents'], expert=r['expert'], expected_genesis=expected, tag=tag,
                stratum=r['stratum'], sector=int(sectors.get(cid, -1)), area_ha=round(r['geom_ha'], 3),
                part_frac=round(r.geometry.area / orig.area, 4), iou=round(iou, 4), geometry=r.geometry))
    v = gpd.GeoDataFrame(rows, geometry='geometry', crs=EA_CRS)
    v.drop(columns='geometry').to_csv(OUT_CSV, index=False, encoding='utf-8')
    v.to_file(OUT_GPKG, driver='GPKG')

    # ── сравнение агенты / эксперт ──
    whole = v[~v['is_part']]
    ctrl = whole[whole['agents'] != 'сомнение']
    ctrl_ok = ctrl.apply(lambda r: AGENT_MAP[r['agents']] == r['expected_genesis'] or r['tag'] == 'mixed', axis=1)
    print(f'Контроль (агенты уверены): {len(ctrl)} целых + {v[v.is_part].id.nunique()} разрезанных; '
          f'совпало по классу шага 2: {int(ctrl_ok.sum())}/{len(ctrl)}')
    for _, r in ctrl[~ctrl_ok].iterrows():
        print(f'  расхождение {r.id}: агенты «{r.agents}» → эксперт «{r.expert}»')
    doubt = whole[whole['agents'] == 'сомнение']
    print(f'Сомнения агентов, решено экспертом: {len(doubt)} целых')
    for _, r in doubt.iterrows():
        print(f'  {r.id:7d} {r.area_ha:8.2f} га → {r.expert}')
    for cid, grp in v[v.is_part].groupby('id'):
        print(f'  {cid} разрезан экспертом на {len(grp)}: ' + '; '.join(f'{p.area_ha:.1f} га → {p.expert}' for _, p in grp.iterrows()))

    # ── регрессия: вердикт эксперта перекрывает агентов ──
    reg = pd.read_csv(REGRESSION)
    scored = v[v['expected_genesis'].notna()]
    reg = reg[~reg['id'].isin(v['id'])]                          # убрать строки агентов по этим id (и целые разрезанных)
    reg = reg[~reg['id'].isin(scored['part_id'])]                # идемпотентность
    add = scored[['part_id', 'expected_genesis', 'stratum', 'sector']].rename(columns={'part_id': 'id'})
    add['stratum'] = add['stratum'].where(~scored['is_part'].values, 'expert_part')
    reg = pd.concat([reg, add], ignore_index=True).sort_values(['sector', 'id'])
    reg.to_csv(REGRESSION, index=False, encoding='utf-8')
    print(f'\nРегрессия: {len(reg)} строк (добавлено/обновлено {len(add)}, из них частей разрезов {int(scored.is_part.sum())})')
    print(reg['expected_genesis'].value_counts().to_string())

    # ── геометрии частей для оценки по геометрии ──
    sg = gpd.read_file(SAMPLE_GEOMS, layer='sample').to_crs(EA_CRS)
    parts = scored[scored['is_part']]
    sg = sg[~sg['id'].isin(parts['part_id'])]
    add_g = gpd.GeoDataFrame({'id': parts['part_id'].values, 'genesis': parts['expected_genesis'].values,
                              'stratum': 'expert_part', 'area_ha': parts['area_ha'].values},
                             geometry=parts.geometry.values, crs=EA_CRS)
    sg = pd.concat([sg, add_g], ignore_index=True)
    sg.to_file(SAMPLE_GEOMS, layer='sample', driver='GPKG')
    print(f'Геометрии выборки: {len(sg)} (добавлено частей: {len(add_g)})')

    # ── смешанные «разрезать» — цели для скрипта разреза ──
    mixed = v[v['tag'] == 'mixed'][['id', 'expert', 'area_ha', 'stratum']]
    mixed.to_csv(SPLIT_TARGETS, index=False, encoding='utf-8')
    print(f'Смешанные контуры для разреза (55_step2_split_mixed.py): {len(mixed)} → {SPLIT_TARGETS.name}')

    # ── точечные вердикты, которых правило не выводит ──
    ov_new = v[v['tag'] == 'marine'][['id']].assign(genesis='shoal', source='expert_step2',
                                                    note='морская отмель по вердикту эксперта (Rivers.shp)')
    if OVERRIDES.exists():
        ov = pd.read_csv(OVERRIDES)
        ov = pd.concat([ov[~ov['id'].isin(ov_new['id'])], ov_new], ignore_index=True)
    else:
        ov = ov_new
    ov.to_csv(OVERRIDES, index=False, encoding='utf-8')
    print(f'Overrides: {len(ov)} → {OVERRIDES}')

    anthro = v[v['tag'] == 'anthropogenic']
    print(f'Техноген по вердиктам эксперта (сид для шага 3): {len(anthro)} частей, {anthro.area_ha.sum():.0f} га')


if __name__ == '__main__':
    main()
