"""
118_validation_v4_pop.py - совокупность для итоговой независимой проверки продукта v4 по основным классам (2026-09-27).

Страты: основной класс карты (genesis_main: alluvial_littoral, aeolian, anthropogenic, undefined; disputed не берётся,
5 контуров) x размер (S < 1 га, M 1-20 га, L >= 20 га). В файл пишутся ВСЕ контуры страты (веса N_h и A_h считаются по
всей карте); отбор делает 105 (--arms, простая случайная выборка внутри страты, без ранее размеченных контуров).
Объёмы (ALLOC) записаны в V1/prereg.md до разметки.
Выход: exports/qc/owner_click/validation_v4_pop.csv. Запуск: PYTHONIOENCODING=utf-8 python -u python/118_validation_v4_pop.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

ROOT = Path(r'D:\test\baresand_zapsib')
PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
OUT = ROOT / 'exports' / 'qc' / 'owner_click' / 'validation_v4_pop.csv'
SHORT = {'alluvial_littoral': 'shoal', 'aeolian': 'aeolian', 'anthropogenic': 'anthro', 'undefined': 'undef'}
ALLOC = {'v_aeolian_S': 17, 'v_aeolian_M': 23, 'v_aeolian_L': 10,
         'v_shoal_S': 10, 'v_shoal_M': 20, 'v_shoal_L': 20,
         'v_anthro_S': 10, 'v_anthro_M': 20, 'v_anthro_L': 20,
         'v_undef_S': 14, 'v_undef_M': 8, 'v_undef_L': 4}


def main() -> None:
    # совокупность заморожена на момент отбора V1 (27.09): по ней считает 119; пересборка по текущему продукту
    # (v4 после правок или v5) меняет страты и ломает оценку, поэтому перезапись только с явным --force
    if OUT.exists() and '--force' not in sys.argv:
        raise SystemExit(f'{OUT} заморожен (совокупность V1); перезапись только с --force')
    g = pyogrio.read_dataframe(PRODUCT, layer='genesis', read_geometry=False,
                               columns=['id', 'genesis', 'genesis_main', 'step6_rule', 'area_ha'])
    g = g[g['genesis_main'].isin(list(SHORT))].copy()
    size = np.select([g['area_ha'] < 1, g['area_ha'] < 20], ['S', 'M'], 'L')
    g['arm'] = 'v_' + g['genesis_main'].map(SHORT) + '_' + size
    g['final'] = g['genesis']
    g[['id', 'area_ha', 'arm', 'genesis_main', 'final', 'step6_rule']].to_csv(OUT, index=False, encoding='utf-8')
    t = g.groupby('arm').agg(N=('id', 'size'), km2=('area_ha', lambda s: round(s.sum() / 100, 2)))
    t['n'] = t.index.map(ALLOC)
    print(t.to_string())
    print(f'-> {OUT}; выборка {int(t["n"].sum())}; --arms ' + ','.join(f'{k}:{v}' for k, v in ALLOC.items()))


if __name__ == '__main__':
    main()
