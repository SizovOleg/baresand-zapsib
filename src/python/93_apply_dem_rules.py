"""
93_apply_dem_rules.py — шаг 5 каскада: правила по уликам рельефа → продукт v3.

Каскад не нарушается: правила касаются только контуров, УЖЕ прошедших шаги 1–4 и получивших undefined (фронт A) или
aeolian у русла (фронт B). Порядок A→W→E сохранён, техноген не трогается (признак его не различает, DNA §3.6).

Правила (пороги — из 92_target_verdicts.py по целевой выборке; здесь только применяются, через CLI):
  A1  undefined ∧ h_local600 > T_A ∧ был_голым ∧ loss<0.1 ∧ дорога>500 → aeolian      v3_A1_relief
  A2  undefined ∧ water_in_frac ≥ W ∧ nearest=lake                     → lake_shoal   v3_A2_in_water
  A3  undefined ∧ h_local600 ≤ T_LOW                                    → river_shoal  v3_A3_base_level
  B1  aeolian ∧ crossed ∧ h_chan ≤ T_B                                  → river_shoal  v3_B1_channel_cross
Любое правило можно выключить порогом (--t-a 999 и т.п.). crossed = upa_in_max ≥ 20 ∧ русловой коридор внутри.

Вход:  exports/baresand_genesis_step4_v2e.gpkg, exports/qc/dem/dem_evidence_mass.csv (90 --merge).
Выход: exports/baresand_genesis_step5_<tag>.gpkg (все прежние поля + genesis_v2e, step5_rule, h_local600, h_chan, crossed),
       exports/qc/target/apply_<tag>.md — что переехало, регрессия по эталонам шагов 2–4.
Запуск: python -u python/93_apply_dem_rules.py --tag v3 --t-a 2.0 --w-lake 0.5 --t-low 0.5 --t-b 1.0 [--dry]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
EXPORTS = ROOT / 'exports'
PRODUCT = EXPORTS / 'baresand_genesis_step4_v2e.gpkg'
DEM = EXPORTS / 'qc' / 'dem' / 'dem_evidence_mass.csv'
QCT = EXPORTS / 'qc' / 'target'
UPA_CROSS = 20.0


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def regression(g: pd.DataFrame, L: list) -> None:
    """Сколько контуров прежних эталонов сменили класс и в какую сторону относительно вердикта эксперта."""
    for s in ('step2', 'step3', 'step4'):
        f = EXPORTS / 'qc' / s / f'regression_{s}.csv'
        if not f.exists():
            continue
        r = pd.read_csv(f)[['id', 'expected_genesis']].merge(g[['id', 'genesis_v2e', 'genesis']], on='id', how='inner')
        ch = r[r['genesis_v2e'] != r['genesis']]
        known = ch[~ch['expected_genesis'].isin(['unassigned', 'undefined'])]
        good = int((known['genesis'] == known['expected_genesis']).sum())
        bad = int(((known['genesis_v2e'] == known['expected_genesis']) & (known['genesis'] != known['expected_genesis'])).sum())
        L.append(f'- эталон {s}: контуров {len(r)}, сменили класс {len(ch)}; среди размеченных — стало верно {good}, '
                 f'**было верно и сломано {bad}**')
        if bad:
            L.append('  ' + ', '.join(f'{i}: {a}→{b} (эксперт {e})' for i, a, b, e in known.loc[
                (known['genesis_v2e'] == known['expected_genesis']) & (known['genesis'] != known['expected_genesis']),
                ['id', 'genesis_v2e', 'genesis', 'expected_genesis']].head(12).itertuples(index=False)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='v3')
    ap.add_argument('--t-a', type=float, default=2.0, help='A1: превышение над локальным минимумом, м')
    ap.add_argument('--w-lake', type=float, default=0.5, help='A2: доля постоянной воды GSW внутри контура')
    ap.add_argument('--t-low', type=float, default=0.5, help='A3: контур не выше базиса на столько метров → речная отмель')
    ap.add_argument('--t-b', type=float, default=1.0, help='B1: превышение над тальвегом при пересечении руслом, м')
    ap.add_argument('--t-b2', type=float, default=0.3, help='B2: превышение над локальным базисом без пересечения, м (-99 = выкл.)')
    ap.add_argument('--a1-min-area', type=float, default=0.0, help='A1: не трогать контуры мельче, га')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    t0 = time.time()

    dem = pd.read_csv(DEM)
    dem['crossed'] = (dem['upa_in_max'].fillna(0) >= UPA_CROSS) & (dem['chan_in_frac'].fillna(0) > 0)
    keep = ['id', 'h_local600', 'h_local1200', 'h_chan', 'crossed', 'upa_in_max', 'chan_in_frac', 'water_in_frac']
    dem = dem[keep]
    log(f'улик рельефа: {len(dem)}')

    log('читаю продукт...')
    g = gpd.read_file(PRODUCT, layer='genesis') if not a.dry else \
        gpd.read_file(PRODUCT, layer='genesis', columns=['id', 'genesis', 'area_ha', 'nearest_type', 'dist_water_m', 'dist_channel_m',
                                                         'bare_s2_frac', 'bare2000_frac', 'loss_frac', 'd_road_built'])
    g = g.merge(dem, on='id', how='left')
    g['genesis_v2e'] = g['genesis']
    g['step5_rule'] = ''
    und = g['genesis'] == 'undefined'
    aeo = g['genesis'] == 'aeolian'
    h6 = g['h_local600']
    cr = g['crossed'].fillna(False).astype(bool)

    # рельеф отделяет раздувы от отмелей, но не от снежников/гарей/техногена (те тоже высоко) —
    # их отсекает история поверхности: раздув был голым хоть в одну эпоху, гарь и дорога — отдельными уликами
    ever_bare = (g['bare_s2_frac'].fillna(0) > 0.05) | (g['bare2000_frac'].fillna(0) > 0.05)
    clean = ever_bare & (g['loss_frac'].fillna(0) < 0.1) & (g['d_road_built'].fillna(9e9) > 500)
    a1 = und & (h6 > a.t_a) & clean & (g['area_ha'] >= a.a1_min_area)
    # осушки озёр стоят в воде: DEM там пуст, выдаёт их доля постоянной воды внутри контура
    a2 = und & ~a1 & (g['water_in_frac'].fillna(0) >= a.w_lake) & (g['nearest_type'] == 'lake')
    # контур на уровне базиса — побочень малой реки, которую GSW не видит
    a3 = und & ~a1 & ~a2 & (h6 <= a.t_low)
    # фронт B: эоловый у русла, лежащий на уровне тальвега (B1, при пересечении руслом) или базиса (B2) — побочень
    near_chan = g['dist_channel_m'].fillna(9e9) <= 400
    b1 = aeo & near_chan & cr & (g['h_chan'].fillna(99) <= a.t_b)
    b2 = aeo & near_chan & ~b1 & (h6 <= a.t_b2)
    g.loc[a1, ['genesis', 'step5_rule']] = ['aeolian', f'{a.tag}_A1_relief']
    g.loc[a2, ['genesis', 'step5_rule']] = ['lake_shoal', f'{a.tag}_A2_in_water']
    g.loc[a3, ['genesis', 'step5_rule']] = ['river_shoal', f'{a.tag}_A3_base_level']
    g.loc[b1, ['genesis', 'step5_rule']] = ['river_shoal', f'{a.tag}_B1_channel_cross']
    g.loc[b2, ['genesis', 'step5_rule']] = ['river_shoal', f'{a.tag}_B2_base_level']

    L = [f'# Применение правил рельефа: продукт {a.tag}', '',
         f'Пороги: A1 h_local600 > {a.t_a} м ∧ был голым ∧ loss<0.1 ∧ дорога>500 (площадь ≥ {a.a1_min_area} га); '
         f'A2 water_in_frac ≥ {a.w_lake} ∧ озеро; A3 h_local600 ≤ {a.t_low} м; '
         f'B1 crossed ∧ h_chan ≤ {a.t_b} м; B2 h_local600 ≤ {a.t_b2} м (оба — эоловые ближе 400 м к руслу).', '',
         '## Что переехало', '', '| правило | контуров | км² | из класса | в класс |', '|---|---:|---:|---|---|']
    for nm, m, src, dst in (('A1', a1, 'undefined', 'aeolian'), ('A2', a2, 'undefined', 'lake_shoal'),
                            ('A3', a3, 'undefined', 'river_shoal'), ('B1', b1, 'aeolian', 'river_shoal'),
                            ('B2', b2, 'aeolian', 'river_shoal')):
        L.append(f'| {nm} | {int(m.sum())} | {g.loc[m, "area_ha"].sum() / 100:.1f} | {src} | {dst} |')
    t = g.groupby('genesis')['area_ha'].agg(['count', 'sum'])
    t0_ = g.groupby('genesis_v2e')['area_ha'].agg(['count', 'sum'])
    L += ['', '## Классы до и после, км²', '', '| класс | было контуров | было км² | стало контуров | стало км² |', '|---|---:|---:|---:|---:|']
    for c in ['shoal', 'river_shoal', 'lake_shoal', 'anthropogenic', 'aeolian', 'undefined']:
        L.append(f'| {c} | {int(t0_.loc[c, "count"]) if c in t0_.index else 0} | {t0_.loc[c, "sum"] / 100 if c in t0_.index else 0:.1f} | '
                 f'{int(t.loc[c, "count"]) if c in t.index else 0} | {t.loc[c, "sum"] / 100 if c in t.index else 0:.1f} |')
    L += ['', '## Регрессия по прежним эталонам', '']
    regression(g, L)
    rep = QCT / f'apply_{a.tag}{"_dry" if a.dry else ""}.md'
    rep.write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))
    if a.dry:
        log(f'--dry: продукт не записан | {(time.time() - t0) / 60:.1f} мин')
        return
    out = EXPORTS / f'baresand_genesis_step5_{a.tag}.gpkg'
    log(f'пишу {out} ...')
    g.to_file(out, layer='genesis', driver='GPKG')
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
