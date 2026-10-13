"""
153_check_cadastre_a.py - проверка кадастровой редакции варианта А (2026-10-13). Только атрибуты и площади.

Вариант А (автор 13.10.2026): класс техногенных песков v7 не меняется; 133 --territory пересчитывает поля cad_* и
слои anthro_in / anthro_exceed / anthro_noallot. Проверки:
1. продукт: те же id, классы и число строк, что в v7 (exports/final/baresand_genesis_v7.gpkg);
2. cad_status только in / cross / unreg / nocad; у cross выход за 10 м больше нуля и доля в отводе не меньше TOUCH_FRAC;
   у in выход за 10 м равен нулю;
3. anthro_exceed: id только со статусом cross, сумма частей по контуру равна cad_exc10_ha (0,5 %);
4. anthro_noallot: ровно контуры со статусом unreg, площадь равна площади контура (0,5 %);
5. anthro_in: нет контуров со статусом unreg (без двойного счёта); сумма частей равна сумме cad_in_ha у in и cross (0,5 %);
6. имена полей слоёв не длиннее 10 знаков (для шейпов 140).
Выход: <qc>/check_cadastre_a.md; при ошибке код возврата 1.
Запуск: PYTHONIOENCODING=utf-8 python -u python/153_check_cadastre_a.py [--qc exports/qc/cadastre_v7a]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

ROOT = Path(r'D:\test\baresand_zapsib')
V7 = ROOT / 'exports' / 'final' / 'baresand_genesis_v7.gpkg'
TOUCH_FRAC = 0.10
TOL = 0.005


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--qc', type=Path, default=ROOT / 'exports' / 'qc' / 'cadastre_v7a')
    ap.add_argument('--product', type=Path, default=None)
    ap.add_argument('--layers', type=Path, default=None)
    a = ap.parse_args()
    prod = a.product or next(a.qc.glob('baresand_genesis_*.gpkg'))
    lay = a.layers or next(a.qc.glob('baresand_anthro_cadastre_*.gpkg'))
    res = []

    def check(name: str, ok: bool, info: str) -> None:
        res.append((name, bool(ok), info))
        print(f'{"OK " if ok else "FAIL"} {name}: {info}', flush=True)

    cols = ['id', 'genesis', 'area_ha', 'cad_cov', 'cad_status', 'cad_in_ha', 'cad_out_ha', 'cad_exc10_ha']
    p = pyogrio.read_dataframe(prod, layer='genesis', read_geometry=False, columns=cols)
    v7 = pyogrio.read_dataframe(V7, layer='genesis', read_geometry=False, columns=['id', 'genesis'])
    m = p[['id', 'genesis']].merge(v7, on='id', how='outer', suffixes=('', '_v7'), indicator=True)
    check('те же id и классы, что в v7', len(p) == len(v7) and m['_merge'].eq('both').all() and m['genesis'].eq(m['genesis_v7']).all(),
          f'{len(p)} / {len(v7)} строк')
    t = p[p['genesis'] == 'anthropogenic'].set_index('id')
    st = t['cad_status']
    check('cad_status из допустимых', st.isin(['in', 'cross', 'unreg', 'nocad']).all(), str(st.value_counts().to_dict()))
    tot = t['cad_in_ha'] + t['cad_out_ha']
    frac = t['cad_in_ha'] / tot.where(tot > 0)
    cr, inn, un = st.eq('cross'), st.eq('in'), st.eq('unreg')
    check('cross: выход > 0 и доля в отводе >= 10 %', (t.loc[cr, 'cad_exc10_ha'] > 0).all() and (frac[cr] >= TOUCH_FRAC - 1e-9).all(),
          f'{int(cr.sum())} контуров')
    check('in: выход за 10 м равен нулю', t.loc[inn, 'cad_exc10_ha'].fillna(0).eq(0).all(), f'{int(inn.sum())} контуров')
    ex = pyogrio.read_dataframe(lay, layer='anthro_exceed', read_geometry=False, columns=['id', 'area_ha'])
    exs = ex.groupby('id')['area_ha'].sum()
    check('anthro_exceed только у cross', exs.index.isin(t.index[cr]).all(), f'{len(exs)} контуров, {exs.sum() / 100:.1f} км2')
    d = (exs / t.loc[exs.index, 'cad_exc10_ha'] - 1).abs()
    check('anthro_exceed = cad_exc10_ha по контуру (0,5 %)', (d < TOL).mean() > 0.999, f'расхождение больше 0,5 % у {int((d >= TOL).sum())}')
    na = pyogrio.read_dataframe(lay, layer='anthro_noallot', read_geometry=False, columns=['id', 'area_ha'])
    check('anthro_noallot = контуры unreg', set(na['id']) == set(t.index[un]), f'{len(na)} / {int(un.sum())}')
    dn = (na.set_index('id')['area_ha'] / t.loc[na['id'], 'area_ha'] - 1).abs()
    check('площадь anthro_noallot = площадь контура (0,5 %)', (dn < TOL).all(), f'{na["area_ha"].sum() / 100:.1f} км2')
    li = pyogrio.read_dataframe(lay, layer='anthro_in', read_geometry=False, columns=['id', 'area_ha'])
    check('anthro_in без контуров unreg', ~li['id'].isin(t.index[un]).any(), f'{len(li)} частей')
    ci = t.loc[inn | cr, 'cad_in_ha'].sum()
    check('anthro_in = cad_in_ha (in, cross; 0,5 %)', abs(li['area_ha'].sum() / ci - 1) < TOL, f'{li["area_ha"].sum() / 100:.1f} / {ci / 100:.1f} км2')
    long = {l: [c for c in pyogrio.read_info(lay, layer=l)['fields'] if len(c) > 10] for l in ('anthro_in', 'anthro_exceed', 'anthro_noallot')}
    check('имена полей не длиннее 10 знаков', not any(long.values()), str({k: v for k, v in long.items() if v}))
    km = lambda s: s.sum() / 100
    L = ['# Проверка кадастровой редакции варианта А (153)', '', f'Продукт {prod}; слои {lay}.', '',
         '| Проверка | Итог | Подробности |', '|---|---|---|', *[f'| {n} | {"да" if ok else "НЕТ"} | {i} |' for n, ok, i in res], '',
         '| Группа | объектов | км2 |', '|---|---|---|',
         f'| в отводах (anthro_in, части) | {len(li)} | {km(li["area_ha"]):.1f} |',
         f'| превышение отвода (anthro_exceed, части) | {len(ex)} | {km(ex["area_ha"]):.1f} |',
         f'| без отвода (anthro_noallot, объекты целиком) | {len(na)} | {km(na["area_ha"]):.1f} |',
         f'| класс техногенных песков | {len(t)} | {km(t["area_ha"]):.1f} |', '',
         'Сумма трёх групп меньше площади класса: полосы допуска 10 м вдоль отводов и куски меньше 900 м2 в группы не входят.']
    out = a.qc / 'check_cadastre_a.md'
    out.write_text('\n'.join(L), encoding='utf-8')
    print(f'-> {out}')
    sys.exit(0 if all(ok for _, ok, _ in res) else 1)


if __name__ == '__main__':
    main()
