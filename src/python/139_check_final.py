"""
139_check_final.py - сверка итоговой версии v7 с v6 (2026-10-06). Только атрибуты, без геометрии.

Проверки:
1. те же id и число строк; genesis_v6 в v7 равен genesis в v6 у всех строк;
2. класс сменился ровно у контуров из decisions_v7.csv (138), только эоловый -> техногенный, step6_rule из решений;
3. у контуров, техногенных и в v6, и в v7, поля cad_* совпадают (кадастр пересчитан тем же способом);
4. у новых техногенных cad_cov заполнен, при cad_cov = 1 сумма cad_in_ha + cad_out_ha равна area_ha (допуск 1 %);
5. у не техногенных cad_* и age2000 пусты; age2000 заполнен у всех техногенных;
6. все поля v6 есть в v7; слои anthro_in и anthro_out: сумма площадей частей равна сумме cad_in_ha и cad_out_ha.
Выход: exports/qc/final_build/check_v7.md; при ошибке код возврата 1.
Запуск: PYTHONIOENCODING=utf-8 python -u python/139_check_final.py [--v7 exports/final/baresand_genesis_v7.gpkg]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

ROOT = Path(r'D:\test\baresand_zapsib')
V6 = ROOT / 'exports' / 'baresand_genesis_step6_v6.gpkg'
V7 = ROOT / 'exports' / 'final' / 'baresand_genesis_v7.gpkg'
LAYERS = ROOT / 'exports' / 'final' / 'baresand_anthro_cadastre_v7.gpkg'
DEC = ROOT / 'exports' / 'qc' / 'final_build' / 'decisions_v7.csv'
OUT = ROOT / 'exports' / 'qc' / 'final_build' / 'check_v7.md'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--v7', default=str(V7))
    ap.add_argument('--layers', default=str(LAYERS))
    ap.add_argument('--v6', default=str(V6), help=r'v6 после переноса лежит в E:\baresand_zapsib_archive\exports')
    a = ap.parse_args()
    v6_path = a.v6
    f6 = list(pyogrio.read_info(v6_path, layer='genesis')['fields'])
    f7 = list(pyogrio.read_info(a.v7, layer='genesis')['fields'])
    cad = [c for c in f6 if c.startswith('cad_')]
    cols = ['id', 'genesis', 'genesis_main', 'step6_rule', 'area_ha'] + cad
    v6 = pyogrio.read_dataframe(v6_path, layer='genesis', read_geometry=False, columns=cols).set_index('id')
    v7 = pyogrio.read_dataframe(a.v7, layer='genesis', read_geometry=False, columns=cols + ['genesis_v6', 'age2000']).set_index('id')
    dec = pd.read_csv(DEC).set_index('id')
    res: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, info: str = '') -> None:
        res.append((name, bool(ok), info))

    check('поля v6 есть в v7', not (set(f6) - set(f7)), str(sorted(set(f6) - set(f7))))
    new_fields = {'genesis_v6', 'age2000', 'cad_status', 'cad_exc10_ha', 'cad_exc20_ha', 'cad_exc10u_ha'}
    check('новые поля v7', set(f7) - set(f6) == new_fields, str(sorted(set(f7) - set(f6))))
    check('те же id', v6.index.equals(v7.index) or set(v6.index) == set(v7.index), f'{len(v6)} / {len(v7)}')
    v7 = v7.reindex(v6.index)
    check('genesis_v6 = класс v6', (v7['genesis_v6'] == v6['genesis']).all(), '')
    ch = v7['genesis'] != v6['genesis']
    check('сменили класс ровно контуры решений', set(v7.index[ch]) == set(dec.index), f'сменили {int(ch.sum())}, решений {len(dec)}')
    check('только эоловый -> техногенный', (v6.loc[ch, 'genesis'].eq('aeolian') & v7.loc[ch, 'genesis'].eq('anthropogenic')).all(), '')
    check('genesis_main = genesis у новых', v7.loc[ch, 'genesis_main'].eq('anthropogenic').all(), '')
    check('step6_rule из решений', (v7.loc[dec.index, 'step6_rule'] == dec['rule']).all(), '')
    # сравниваются контуры с кадастром в v6: участки Красноярского края (133 --kras) законно меняют cad_* у контуров края
    both = v6['genesis'].eq('anthropogenic') & v7['genesis'].eq('anthropogenic') & v6['cad_cov'].eq(1)
    diff = {}
    for c in cad:
        x, y = v6.loc[both, c], v7.loc[both, c]
        if pd.api.types.is_numeric_dtype(x):
            bad = ~(np.isclose(x.astype(float), y.astype(float), rtol=1e-6, atol=1e-6, equal_nan=True))
        else:
            bad = ~((x == y) | (x.isna() & y.isna()))
        if bad.any():
            diff[c] = int(bad.sum())
    check('cad_* у прежних техногенных совпадают с v6', not diff, str(diff))
    new = v7.index[ch]
    check('cad_cov заполнен у новых техногенных', v7.loc[new, 'cad_cov'].notna().all(), '')
    nc = v7.loc[new]
    nc1 = nc[nc['cad_cov'] == 1]
    rel = ((nc1['cad_in_ha'] + nc1['cad_out_ha']) / nc1['area_ha'] - 1).abs()
    check('сумма частей = площадь у новых (1 %)', (rel < 0.01).all(), f'макс. отклонение {rel.max():.4f}' if len(rel) else 'нет контуров с кадастром')
    an = v7['genesis'].eq('anthropogenic')
    check('у не техногенных cad_* и age2000 пусты', v7.loc[~an, cad + ['age2000']].isna().all().all(), '')
    check('age2000 у всех техногенных', v7.loc[an, 'age2000'].notna().all(), str(v7.loc[an, 'age2000'].value_counts().to_dict()))
    st = pyogrio.read_dataframe(a.v7, layer='genesis', read_geometry=False,
                                columns=['id', 'genesis', 'cad_cov', 'cad_status', 'cad_in_ha', 'cad_exc10_ha', 'cad_exc20_ha'])
    sa = st[st['genesis'] == 'anthropogenic']
    ok_st = (sa['cad_status'].notna().all() and sa.loc[sa['cad_cov'] == 0, 'cad_status'].eq('nocad').all()
             # при отводе ближе 10 м выход за 20 м не больше выхода за 10 м; у unreg вариант 20 м может найти отвод в 10-20 м
             and (sa.loc[sa['cad_status'].isin(['in', 'cross']), 'cad_exc20_ha']
                  <= sa.loc[sa['cad_status'].isin(['in', 'cross']), 'cad_exc10_ha'] + 1e-6).all()
             and sa.loc[sa['cad_status'] == 'cross', 'cad_exc10_ha'].gt(0).all()
             and sa.loc[sa['cad_status'].isin(['in', 'unreg']), 'cad_exc10_ha'].eq(0).all())
    check('cad_status согласован с выходом за отвод', ok_st, str(sa['cad_status'].value_counts().to_dict()))
    lay = Path(a.layers)
    if lay.exists():
        s_in = pyogrio.read_dataframe(lay, layer='anthro_in', read_geometry=False, columns=['area_ha'])['area_ha'].sum()
        s_out = pyogrio.read_dataframe(lay, layer='anthro_out', read_geometry=False, columns=['area_ha'])['area_ha'].sum()
        c_in, c_out = v7.loc[an, 'cad_in_ha'].sum(), v7.loc[an, 'cad_out_ha'].sum()
        check('слои = поля (0,5 %)', abs(s_in / c_in - 1) < 0.005 and abs(s_out / c_out - 1) < 0.005,
              f'in {s_in / 100:.1f} / {c_in / 100:.1f} км2, out {s_out / 100:.1f} / {c_out / 100:.1f} км2')
    t = v7.groupby('genesis_main')['area_ha'].agg(['size', 'sum'])
    L = ['# Сверка v7 с v6 (139)', '', f'v7: {a.v7}', '', '| Проверка | Итог | Подробности |', '|---|---|---|',
         *[f'| {n} | {"да" if ok else "НЕТ"} | {i} |' for n, ok, i in res], '',
         'Основные классы v7:', '', '| Класс | Контуров | км2 |', '|---|---|---|',
         *[f'| {k} | {int(r["size"])} | {r["sum"] / 100:.2f} |' for k, r in t.iterrows()],
         f'| всего | {len(v7)} | {v7["area_ha"].sum() / 100:.2f} |']
    OUT.write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))
    sys.exit(0 if all(ok for _, ok, _ in res) else 1)


if __name__ == '__main__':
    main()
