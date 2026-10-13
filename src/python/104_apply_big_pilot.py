"""
104_apply_big_pilot.py - шаг 6: перенос проверенного пилота по крупнейшим undefined в продукт (v3e -> v4), 2026-09-26.

Что переносится:
  * принятые моделью 102 контуры (accept = 1) с независимой меткой, совпавшей с предложением (103: 119 из 119);
    класс not_sand в продукте не ведётся (как в 94: not_sand -> undefined), такие контуры остаются undefined с not_sand_suspect = 1;
  * вердикты владельца по морским барам (exports/qc/lake/big/expert_big.csv) -> shoal.
Поля: genesis_v3e (прежний класс), step6_rule ('v4_big_nb' | 'v4_expert'). Исходный v3e не меняется.
Выход: exports/baresand_genesis_step6_v4.gpkg (+ .qml от v3e). Запись через временный файл.
Запуск: PYTHONIOENCODING=utf-8 python -u python/104_apply_big_pilot.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

ROOT = Path(r'D:\test\baresand_zapsib')
SRC = ROOT / 'exports' / 'baresand_genesis_step5_v3e.gpkg'
DST = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
BIG = ROOT / 'exports' / 'qc' / 'lake' / 'big'
APPLY_CLEAR_ANTHRO = True   # False откатывает правило рубок (v4_clear_anthro) при следующей сборке
APPLY_DISPUTED = True       # False возвращает спорные (v4_disputed) в undefined
APPLY_TRANSFER = True       # False откатывает перенос меток моделью (v4_transfer)


def main() -> None:
    lab = pd.read_csv(BIG / 'big_labels.csv')
    acc = lab[(lab['accept'].astype(str).str.lower().isin(['true', '1'])) & (lab['final'] == lab['class_nb'])]
    ex = pd.read_csv(BIG / 'expert_big.csv')
    # эталон владельца из окна проверки (105/107): класс -> genesis, not_sand -> флаг, mixed/unresolved -> только пометка
    gold_p = ROOT / 'exports' / 'qc' / 'owner_click' / 'owner_gold.csv'
    if gold_p.exists():
        ru = {'lake_shoal': 'озёрная отмель', 'river_shoal': 'речная отмель', 'shoal': 'морская отмель', 'aeolian': 'эоловый',
              'anthropogenic': 'техноген', 'not_sand': 'не песок', 'mixed': 'смешанный', 'unresolved': 'не понять', 'disputed': 'спорный'}
        gd = pd.read_csv(gold_p)
        gd = gd.assign(verdict=gd['label'].where(~gd['label'].isin(['mixed', 'unresolved', 'disputed']), 'pending'),
                       owner_text=gd['label'].map(ru) + gd['note'].fillna('').map(lambda s: f' ({s})' if s else ''),
                       source='owner_click', date=gd['batch'])
        ex = pd.concat([ex[~ex['id'].isin(gd['id'])], gd[['id', 'verdict', 'owner_text', 'source', 'date']]], ignore_index=True)
        print(f'эталон окна проверки: {len(gd)} меток')
    print(f'к переносу: модель {len(acc)} контуров, эксперт {len(ex)}')
    g = pyogrio.read_dataframe(SRC, layer='genesis')
    before = g.groupby('genesis')['area_ha'].sum() / 100
    g['genesis_v3e'] = g['genesis']
    g['step6_rule'] = None
    und = g['genesis'] == 'undefined'
    cls = dict(zip(acc['id'], acc['class_nb']))
    newcls = g['id'].map(cls)
    m = und & newcls.notna()
    is_ns = m & (newcls == 'not_sand')
    g.loc[m & ~is_ns, 'genesis'] = newcls[m & ~is_ns]
    g.loc[m, 'step6_rule'] = 'v4_big_nb'
    g.loc[is_ns, 'not_sand_suspect'] = 1
    # правило плеча «лес был, лес пропал, пожара по MODIS нет» -> техноген (108, burn_pop.csv, arm_clear).
    # Решение владельца 2026-09-26 «на рубках можно везде техноген писать»; предрегистрированную планку правило не прошло
    # (O2: 35/40 = 0.88 по числу, 0.83 по площади), поэтому отдельная пометка v4_clear_anthro для отката одним флагом.
    burn_pop = ROOT / 'exports' / 'qc' / 'owner_click' / 'burn_pop.csv'
    if APPLY_CLEAR_ANTHRO and burn_pop.exists():
        arms = pd.read_csv(burn_pop)
        clear_ids = set(arms.loc[arms['arm'] == 'arm_clear', 'id'])
        mc = g['id'].isin(clear_ids) & g['genesis'].eq('undefined') & g['step6_rule'].isna()
        g.loc[mc, 'genesis'] = 'anthropogenic'
        g.loc[mc, 'step6_rule'] = 'v4_clear_anthro'
        print(f'правило «рубки без пожара -> техноген»: {int(mc.sum())} контуров, {g.loc[mc, "area_ha"].sum() / 100:.2f} км2')
    # перенос меток на хвост моделью (114, замороженные предсказания): только единицы, прошедшие проверку владельцем
    # (exports/qc/alphaearth/transfer_accepted.json пишется после приёма партии, правило в O4/O5 prereg.md)
    acc_p = ROOT / 'exports' / 'qc' / 'alphaearth' / 'transfer_accepted.json'
    if APPLY_TRANSFER and acc_p.exists():
        # правила по порядку; каждое берёт только ещё не решённые контуры (undefined без step6_rule)
        for rule in json.loads(acc_p.read_text(encoding='utf-8'))['rules']:
            tp = pd.read_csv(ROOT / 'exports' / 'qc' / 'alphaearth' / rule['pred_csv'])
            tp = tp[(tp['pmax'] >= rule['min_p']) & (tp['area_ha'] >= rule.get('min_area_ha', 0))
                    & (tp['area_ha'] < rule.get('max_area_ha', np.inf)) & tp['final'].isin(rule['classes'])]
            mt = g['id'].isin(set(tp['id'])) & g['genesis'].eq('undefined') & g['step6_rule'].isna()
            g.loc[mt, 'genesis'] = g.loc[mt, 'id'].map(dict(zip(tp['id'], tp['final'])))
            g.loc[mt, 'step6_rule'] = 'v4_transfer'
            print(f'перенос моделью {rule["model"]}: {int(mt.sum())} контуров, {g.loc[mt, "area_ha"].sum() / 100:.2f} км2 '
                  f'({rule["classes"]}, p >= {rule["min_p"]}, площадь {rule.get("min_area_ha", 0)}-{rule.get("max_area_ha", "")} га)')
    # вердикты владельца: класс -> genesis; not_sand -> остаётся undefined с флагом; pending -> только пометка (решение не принято)
    ev = dict(zip(ex['id'], ex['verdict']))
    exv = g['id'].map(ev)
    cls_e = exv.notna() & ~exv.isin(['not_sand', 'pending'])
    ns_e = exv.eq('not_sand')
    g.loc[cls_e, 'genesis'] = exv[cls_e]
    g.loc[ns_e, 'genesis'] = 'undefined'
    g.loc[ns_e, 'not_sand_suspect'] = 1
    g.loc[cls_e | ns_e, 'step6_rule'] = 'v4_expert'
    g.loc[cls_e, 'not_sand_suspect'] = 0   # владелец подтвердил песок
    # флаг not_sand_suspect по определению (95) только у aeolian/undefined: у переведённых шагом 6 в другие классы снять
    moved = g['step6_rule'].notna() & ~g['genesis'].isin(['aeolian', 'undefined'])
    g.loc[moved, 'not_sand_suspect'] = 0
    if 'owner_text' in ex:
        g['expert_note'] = g['id'].map(dict(zip(ex['id'], ex['owner_text'])))
    print(f'эксперт: класс {int(cls_e.sum())}, не песок (флаг) {int(ns_e.sum())}, ждут решения {int(exv.eq("pending").sum())}')
    # класс «спорный» (disputed, просьба владельца 2026-09-26; список 110_disputed_class.py, действующее определение
    # в disputed_current.csv, с 2026-09-27 v2): только для оставшихся undefined;
    # у контуров с классом причина спорности пишется в поле dispute_reason без смены класса
    disp_p = ROOT / 'exports' / 'qc' / 'disputed' / 'disputed_current.csv'
    if APPLY_DISPUTED and disp_p.exists():
        dp = pd.read_csv(disp_p)
        g['dispute_reason'] = g['id'].map(dict(zip(dp['id'], dp['reason'])))
        md = g['dispute_reason'].notna() & g['genesis'].eq('undefined')
        g.loc[md, 'genesis'] = 'disputed'
        g.loc[md, 'step6_rule'] = 'v4_disputed'
        print(f'спорный: {int(md.sum())} контуров, {g.loc[md, "area_ha"].sum() / 100:.2f} км2 '
              f'(ещё {int((g["dispute_reason"].notna() & ~md).sum())} с классом получили только пометку)')
    # основной класс и тип отмели (решение владельца 2026-09-27; DNA раздел 2: «отмель» один класс генезиса,
    # код alluvial_littoral из контракта CLAUDE.md). Тип отмели второстепенный оценочный атрибут; источник типа:
    # owner (метка владельца), model (перенос или модель пилота), rule (правила каскада, шаги 1-2)
    shoal_t = {'lake_shoal': 'lake', 'river_shoal': 'river', 'shoal': 'sea'}
    g['genesis_main'] = g['genesis'].where(~g['genesis'].isin(list(shoal_t)), 'alluvial_littoral')
    g['shoal_type'] = g['genesis'].map(shoal_t)
    src = np.select([g['step6_rule'].eq('v4_expert'), g['step6_rule'].isin(['v4_transfer', 'v4_big_nb'])], ['owner', 'model'], 'rule')
    g['shoal_type_src'] = pd.Series(src, index=g.index).where(g['shoal_type'].notna())
    main_km2 = (g.groupby('genesis_main')['area_ha'].sum() / 100).round(2)
    print('основной класс, км2: ' + ', '.join(f'{k} {v}' for k, v in main_km2.items()))
    print('тип отмели по источнику, км2:\n' + (g.groupby(['shoal_type', 'shoal_type_src'])['area_ha'].sum() / 100).round(2).unstack(fill_value=0).to_string())
    after = g.groupby('genesis')['area_ha'].sum() / 100
    t = pd.DataFrame({'v3e_km2': before, 'v4_km2': after}).fillna(0).round(2)
    t['delta'] = (t['v4_km2'] - t['v3e_km2']).round(2)
    print(t.to_string())
    print(f'изменено контуров: {int((g["genesis"] != g["genesis_v3e"]).sum())}; помечено step6_rule: {int(g["step6_rule"].notna().sum())}')
    tmp = DST.with_name(DST.stem + '_tmp.gpkg')
    if tmp.exists():
        tmp.unlink()
    pyogrio.write_dataframe(g, tmp, layer='genesis', driver='GPKG')
    os.replace(tmp, DST)
    qml = SRC.with_suffix('.qml')
    if qml.exists():
        # стиль v3e + категория «спорный» (почти чёрная заливка, жёлтая обводка) и уточнённая подпись undefined
        s = qml.read_text(encoding='utf-8')
        s = s.replace('label="неопределённый (шаг 4)"/>',
                      'label="неопределённый (нет решения)"/>\n'
                      '      <category render="true" symbol="7" value="disputed" label="спорный (просмотрен, генезис неоднозначен)"/>')
        s = s.replace('    </symbols>',
                      '      <symbol clip_to_extent="1" type="fill" name="7" alpha="1"><layer class="SimpleFill" enabled="1" pass="0">'
                      '<prop k="color" v="30,30,30,230"/><prop k="outline_color" v="255,230,0,255"/><prop k="outline_width" v="0.4"/>'
                      '<prop k="style" v="solid"/></layer></symbol>\n    </symbols>')
        DST.with_suffix('.qml').write_text(s, encoding='utf-8')
        # второй стиль: основной класс (genesis_main), отмели одним цветом; подключать в QGIS вручную
        reps = [('attr="genesis"', 'attr="genesis_main"'),
                ('      <category render="true" symbol="0" value="shoal" label="морская отмель (шаг 1)"/>\n', ''),
                ('<category render="true" symbol="1" value="river_shoal" label="речная отмель (шаг 2)"/>',
                 '<category render="true" symbol="1" value="alluvial_littoral" label="отмель (речная, озёрная, морская)"/>'),
                ('      <category render="true" symbol="2" value="lake_shoal" label="озёрная отмель (шаг 2)"/>\n', '')]
        m = s
        for old, new in reps:
            if old not in m:
                raise ValueError(f'стиль основного класса: не найден фрагмент {old[:60]!r}')
            m = m.replace(old, new)
        DST.with_name(DST.stem + '_main.qml').write_text(m, encoding='utf-8')
    print(f'-> {DST} ({len(g)} контуров)')


if __name__ == '__main__':
    main()
