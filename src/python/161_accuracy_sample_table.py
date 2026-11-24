"""
161_accuracy_sample_table.py - таблица выборки оценки точности для дополнительных материалов (S6, табл. S06_sample.csv).

Выборка V1 + V1b + V1c (276 контуров) в том виде, в каком она входит в расчёт 119_validation_v4.py
(--batches V1,V1b,V1c --split-ha 100, веса страт по домену U): страта (класс карты x размер), площадь и число контуров
страты в домене U, класс карты на момент отбора, площадь контура, метка эксперта и эталонная категория, координаты точки
контура (WGS 84). Заметки эксперта в таблицу не входят.

Проверка: матрица площадей, общая точность и каппа, рассчитанные только по таблице (формула S6.1), должны совпасть с
расчётом 119 на тех же данных; число верно атрибутированных единиц без весов 233 из 276 (S6).

Запуск: PYTHONIOENCODING=utf-8 python -u python/161_accuracy_sample_table.py [--out PATH]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import importlib.util
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
OC = ROOT / 'exports' / 'qc' / 'owner_click'
OUT = ROOT / 'repo' / 'supplement' / 'tables' / 'S06_sample.csv'
BATCHES = ('V1', 'V1b', 'V1c')
SPLIT_HA = 100.0                      # граница страт «20-100 га» и «не менее 100 га» (119 --split-ha 100)
EXPECT_N, EXPECT_OK = 276, 233        # объём выборки и число верных без весов (S6)
# классы карты и эталонные категории в таблице (коды 119 -> названия таблицы)
MAP_NAME = {'shoal': 'shoal', 'aeolian': 'aeolian', 'anthro': 'anthropogenic', 'undef': 'undefined'}
REF_NAME = {'shoal': 'shoal', 'aeolian': 'aeolian', 'anthro': 'anthropogenic', 'not_sand': 'not_sand', 'mixed': 'mixed'}
SIZE_NAME = {'S': '<1', 'M': '1-20', 'L1': '20-100', 'XL': '>=100'}


def load_119() -> ModuleType:
    """Модуль 119 (словари классов, матрица площадей и показатели берутся оттуда, без копирования)."""
    spec = importlib.util.spec_from_file_location('validation_v4', Path(__file__).resolve().parent / '119_validation_v4.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def split_strata(t: pd.DataFrame) -> pd.DataFrame:
    """Деление страт крупных контуров (L) на 20-100 га (L1) и не менее 100 га (XL), как в 119 --split-ha."""
    t = t.copy()
    m = t['stratum'].str.endswith('_L')
    t.loc[m, 'stratum'] = np.where(t.loc[m, 'area_ha'] >= SPLIT_HA, t.loc[m, 'stratum'].str.replace('_L', '_XL'),
                                   t.loc[m, 'stratum'].str.replace('_L', '_L1'))
    return t


def domain_u(b: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Площадь (км²) и число контуров страт в домене U: совокупность без контуров, размеченных до V1 (как в 119)."""
    pop = split_strata(pd.read_csv(OC / 'validation_v4_pop.csv').rename(columns={'arm': 'stratum'}))
    qc = ROOT / 'exports' / 'qc'
    E: set[int] = set()
    for p in (qc / 'final' / 'validation_sample.csv', qc / 'target' / 'target_sample.csv', qc / 'lake' / 'lake_fit.csv',
              qc / 'lake' / 'lake_audit.csv', qc / 'lake' / 'big' / 'big_sample.csv'):
        E |= set(pd.read_csv(p, usecols=['id'])['id'])
    gold = pd.read_csv(OC / 'owner_gold.csv')
    E |= set(gold.loc[gold['batch'].astype(str).str.match(r'^O\d+$'), 'id'])
    u = pop[~(pop['id'].isin(E) & ~pop['id'].isin(b['id']))]
    return u.groupby('stratum')['area_ha'].sum() / 100, u.groupby('stratum').size()


def build(v: ModuleType) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Таблица для публикации, рабочая таблица в кодах 119 и площади страт домена U."""
    b = pd.concat([pd.read_csv(OC / n / 'batch.csv').assign(batch=n) for n in BATCHES], ignore_index=True)
    if b['id'].duplicated().any():
        raise SystemExit('контур попал в две партии выборки')
    b = split_strata(b)
    A_U, N_U = domain_u(b)
    gold = pd.read_csv(OC / 'owner_gold.csv')
    lab = gold[gold['batch'].isin(BATCHES)][['id', 'label']]
    if lab['id'].duplicated().any():
        raise SystemExit('у контура выборки несколько меток эксперта')
    d = b.merge(lab, on='id', how='left')
    if d['label'].isna().any():
        raise SystemExit(f'нет метки эксперта: {sorted(d.loc[d["label"].isna(), "id"])}')
    d['map'] = d['genesis_main'].map(v.MAP)
    d['ref'] = d['label'].map(v.REF)
    if d[['map', 'ref']].isna().any().any():
        raise SystemExit('класс карты или метка вне словарей 119')
    st = d['stratum'].str.extract(r'^v_(\w+?)_(S|M|L1|XL)$')
    if st.isna().any().any():
        raise SystemExit(f'неожиданные страты: {sorted(d["stratum"].unique())}')
    if (st[0] != d['map']).any():
        raise SystemExit('класс карты не совпадает с классом страты')
    t = pd.DataFrame({
        'id': d['id'].astype(int),
        'batch': d['batch'],
        'stratum_class': st[0].map(MAP_NAME),
        'stratum_size_ha': st[1].map(SIZE_NAME),
        'stratum_area_km2': d['stratum'].map(A_U).round(4),
        'stratum_n_contours': d['stratum'].map(N_U).astype(int),
        'map_class': d['map'].map(MAP_NAME),
        'map_genesis': d['final'],
        'area_ha': d['area_ha'].round(4),
        'ref_label': d['label'],
        'ref_class': d['ref'].map(REF_NAME),
        'lon': d['lon'].round(5),
        'lat': d['lat'].round(5),
    })
    # неопределённых контуров не менее 100 га в совокупности нет: страта крупных называется «не менее 20 га» (табл. S6.1)
    if 'v_undef_XL' not in A_U.index:
        t.loc[(t['stratum_class'] == 'undefined') & (t['stratum_size_ha'] == '20-100'), 'stratum_size_ha'] = '>=20'
    order = {c: i for i, c in enumerate(MAP_NAME.values())}
    size = {s: i for i, s in enumerate(SIZE_NAME.values())} | {'>=20': 2}
    t = t.assign(_c=t['stratum_class'].map(order), _s=t['stratum_size_ha'].map(size)) \
         .sort_values(['_c', '_s', 'id']).drop(columns=['_c', '_s']).reset_index(drop=True)
    return t, d, A_U


def matrix_from_table(t: pd.DataFrame, rows: list[str], cols: list[str]) -> np.ndarray:
    """Матрица площадей по формуле S6.1 только из столбцов опубликованной таблицы (независимо от 119)."""
    M = np.zeros((len(rows), len(cols)))
    t = t.assign(h=t['stratum_class'] + '|' + t['stratum_size_ha'])
    for _, x in t.groupby('h'):
        A_h = x['stratum_area_km2'].iloc[0]
        a = x['area_ha'].to_numpy(dtype=float)
        for (k, j), y in x.assign(a=a).groupby(['map_class', 'ref_class']):
            M[rows.index(k), cols.index(j)] += A_h * y['a'].sum() / a.sum()
    return M


def main() -> None:
    ap = argparse.ArgumentParser(description='Таблица выборки оценки точности (S6).')
    ap.add_argument('--out', default=str(OUT), help='путь CSV (по умолчанию repo/supplement/tables/S06_sample.csv)')
    a = ap.parse_args()
    v = load_119()
    t, d, A_U = build(v)
    if len(t) != EXPECT_N:
        raise SystemExit(f'в выборке {len(t)} единиц, ожидалось {EXPECT_N}')
    ok = int((d['map'] == d['ref']).sum())
    if ok != EXPECT_OK:
        raise SystemExit(f'верных без весов {ok}, ожидалось {EXPECT_OK}')
    M119 = v.area_matrix(d, A_U)
    rows = [MAP_NAME[r] for r in v.ROWS]
    cols = [REF_NAME[c] for c in v.COLS]
    Mt = matrix_from_table(t, rows, cols)
    if not np.allclose(M119, Mt, atol=0.01, rtol=0):
        raise SystemExit(f'матрица по таблице не равна расчёту 119:\n{M119.round(2)}\n{Mt.round(2)}')
    S = v.stats(Mt)
    Mdf = pd.DataFrame(Mt, index=rows, columns=cols).round(1)
    Mdf['map_total'] = Mdf.sum(axis=1)
    print(Mdf.to_string())
    print(f'по столбцам: {Mdf.sum().round(1).to_dict()}')
    print(f'OA3 {S["OA3"]:.4f}; OA4 {S["OA4"]:.4f}; kappa {S["kappa"]:.4f}; UA/PA эоловых {S["UA_aeolian"]:.4f} / '
          f'{S["PA_aeolian"]:.4f}; верно без весов {ok} из {len(t)}')
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    t.to_csv(out, index=False, encoding='utf-8', lineterminator='\n')
    print(f'записано: {out} ({len(t)} строк)')


if __name__ == '__main__':
    main()
