"""
97_lake_sample.py — выборка НАСТРОЙКИ (fit) для озёрного прохода, редакция 2 (2026-09-18, по разбору Астры).

Две совокупности из exports/qc/lake/lake_evidence_v2.csv (96):
  undef_lake — undefined у озёр (20 797 контуров, 96.6 км²); страты регион × размер × контакт с водой → 12 страт, 80 контуров;
  river_lake — river_shoal у озёрных компонент (51 168 контуров, 592.9 км²); страты происхождение (шаг 5 / шаг 2) × регион → 6 страт,
               36 контуров. Здесь измеряем, сколько озёрного песка сидит в речном классе (в holdout это ОДИН контур 288142).
Регионы (владелец, 2026-09-18): север — широта ≥ 67.5°; Ямал — север западнее 72.5° в. д., Гыдан/Таз — восточнее; материк — южнее.
Размер: S < 1 га, L ≥ 1 га. Контакт: c30 ≥ 0.05 (доля кольца 30 м, занятая водой GSW ≥ 50 %) → touch, иначе apart.

Отделение аудита: контуры настройки берутся с взаимным зазором ≥ 1.2 км; будущая аудиторская выборка (99) исключает всё
в 1.2 км от контуров настройки и всё у тех же водных компонент (near_comp) — озёрные системы не делятся между наборами.
Слепые таблицы агентам: только id, area_ha, lat, lon. Снимки без оверлея классов; для < 1 га — приближенные 0.8 км.

Выход: exports/qc/lake/lake_fit.csv (полные поля), strata_lake_fit.csv, lake_fit.json (сектора), lake_fit_geoms.gpkg,
       agents/sector_L<n>.csv, thumbs_fit/, thumbs_fit_zoom/.
Запуск: python -u python/97_lake_sample.py --n-undef 80 --n-river 36 --sectors 8 --render
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import subprocess
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

ROOT = Path(r'D:\test\baresand_zapsib')
EXPORTS = ROOT / 'exports'
PRODUCT = EXPORTS / 'baresand_genesis_step5_v3e.gpkg'
QCL = EXPORTS / 'qc' / 'lake'
QCF = EXPORTS / 'qc' / 'final'
DRIVER = ROOT / 'python' / 'qc_render_parallel.py'
SEED = 20260918
GAP_M = 1200.0
LAT_NORTH, LON_OB = 67.5, 72.5
SIZE_L_HA = 1.0
TOUCH_C30 = 0.05
BLIND = ['id', 'area_ha', 'lat', 'lon']


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def region(lat: pd.Series, lon: pd.Series) -> pd.Series:
    north = lat >= LAT_NORTH
    return pd.Series(np.where(~north, 'mainland', np.where(lon < LON_OB, 'yamal', 'gydan')), index=lat.index)


def already_labelled() -> set:
    ex = set(pd.read_csv(QCF / 'validation_sample.csv', usecols=['id'])['id'])
    ex |= set(pd.read_csv(EXPORTS / 'qc' / 'target' / 'target_sample.csv', usecols=['id'])['id'])
    for s in ('step2', 'step3', 'step4'):
        f = EXPORTS / 'qc' / s / f'regression_{s}.csv'
        if f.exists():
            ex |= set(pd.read_csv(f, usecols=['id'])['id'])
    return ex


def allocate(strata: pd.DataFrame, total: int, base: int) -> pd.Series:
    """base контуров каждой страте, остаток — пропорционально площади страты; не больше N_conts."""
    n = pd.Series(base, index=strata.index).clip(upper=strata['N_conts'])
    rest = total - int(n.sum())
    if rest > 0:
        share = strata['A_km2'] / strata['A_km2'].sum()
        extra = np.floor(share * rest).astype(int)
        n = (n + extra).clip(upper=strata['N_conts'])
        for i in share.sort_values(ascending=False).index:
            if n.sum() >= total:
                break
            if n[i] < strata.loc[i, 'N_conts']:
                n[i] += 1
    return n.astype(int)


def pick_with_gap(pop: pd.DataFrame, plan: pd.Series, rng: np.random.Generator) -> pd.DataFrame:
    """Отбор по стратам с взаимным зазором ≥ GAP_M между всеми отобранными (по центроидам в EPSG:3576)."""
    picked_xy: list[tuple[float, float]] = []
    picked_idx: list = []
    for st in rng.permutation(plan.index):
        want = int(plan[st])
        cand = pop[pop['stratum'] == st].sample(frac=1, random_state=int(rng.integers(0, 2**31)))
        got = 0
        for idx, r in cand.iterrows():
            if got >= want:
                break
            if picked_xy:
                arr = np.asarray(picked_xy)
                if np.min(np.hypot(arr[:, 0] - r['x'], arr[:, 1] - r['y'])) < GAP_M:
                    continue
            picked_xy.append((r['x'], r['y']))
            picked_idx.append(idx)
            got += 1
        if got < want:
            log(f'  страта {st}: хотели {want}, набрали с зазором {got}')
    return pop.loc[picked_idx].copy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n-undef', type=int, default=80)
    ap.add_argument('--n-river', type=int, default=36)
    ap.add_argument('--base-undef', type=int, default=5)
    ap.add_argument('--base-river', type=int, default=6)
    ap.add_argument('--sectors', type=int, default=8)
    ap.add_argument('--render', action='store_true')
    ap.add_argument('--evidence', default=str(QCL / 'lake_evidence_v2.csv'), help='файл улик (для пробы — промежуточный merge)')
    a = ap.parse_args()
    t0 = time.time()
    (QCL / 'agents').mkdir(parents=True, exist_ok=True)

    ev = pd.read_csv(a.evidence)
    n0 = len(ev)
    ev = ev[ev['c30'].notna() & ev['lat'].notna()].copy()
    log(f'улики: {n0} контуров, с измерениями {len(ev)}')
    ex = already_labelled()
    ev = ev[~ev['id'].isin(ex)].copy()
    log(f'после исключения уже размеченных: {len(ev)}')

    ev['region'] = region(ev['lat'], ev['lon'])
    ev['size'] = np.where(ev['area_ha'] >= SIZE_L_HA, 'L', 'S')
    ev['touch'] = np.where(ev['c30'].fillna(0) >= TOUCH_C30, 'touch', 'apart')
    ev['origin'] = np.where(ev['step2_rule'].fillna('').astype(str).str.strip() == '', 'st5', 'ch')
    u = ev['pop'] == 'undef_lake'
    ev['stratum'] = ''
    ev.loc[u, 'stratum'] = 'U_' + ev.loc[u, ['region', 'size', 'touch']].agg('_'.join, axis=1)
    ev.loc[~u, 'stratum'] = 'R_' + ev.loc[~u, ['origin', 'region']].agg('_'.join, axis=1)

    strata = ev.groupby(['pop', 'stratum']).agg(N_conts=('id', 'size'), A_km2=('area_ha', lambda x: x.sum() / 100)).reset_index()
    strata = strata.set_index('stratum')
    plan = pd.concat([allocate(strata[strata['pop'] == 'undef_lake'], a.n_undef, a.base_undef),
                      allocate(strata[strata['pop'] == 'river_lake'], a.n_river, a.base_river)])
    strata['n_plan'] = plan
    rng = np.random.default_rng(SEED)
    sample = pick_with_gap(ev, plan, rng)
    strata['n_fit'] = sample.groupby('stratum').size()
    strata['n_fit'] = strata['n_fit'].fillna(0).astype(int)
    strata['pi'] = strata['n_fit'] / strata['N_conts']
    strata.reset_index().to_csv(QCL / 'strata_lake_fit.csv', index=False, encoding='utf-8')
    print(strata[['pop', 'N_conts', 'A_km2', 'n_plan', 'n_fit']].round(1).to_string())

    # сектора: кластеры по положению, затем равные порции — агенту достаётся компактный участок
    km = KMeans(n_clusters=min(a.sectors, len(sample)), random_state=SEED, n_init=10).fit(sample[['x', 'y']])
    sample['cluster'] = km.labels_
    sample = sample.sort_values(['cluster', 'x']).reset_index(drop=True)
    sample['sector'] = (np.arange(len(sample)) * a.sectors // len(sample)) + 1
    sample['split'] = 'fit'
    sample.to_csv(QCL / 'lake_fit.csv', index=False, encoding='utf-8')

    g = gpd.read_file(PRODUCT, layer='genesis', columns=['id'], where=f"id IN ({','.join(map(str, sample['id']))})")
    g = g.merge(sample[['id', 'pop', 'stratum', 'area_ha']], on='id')
    bad = ~g.geometry.is_valid
    if bad.any():
        g.loc[bad, 'geometry'] = g.loc[bad, 'geometry'].make_valid()
    g.to_file(QCL / 'lake_fit_geoms.gpkg', layer='sample', driver='GPKG')

    sectors = {}
    for s in sorted(sample['sector'].unique()):
        ss = sample[sample['sector'] == s].sort_values('id')
        sectors[str(s)] = {'name': f'L{s}', 'n': int(len(ss)), 'ids': [int(i) for i in ss['id']]}
        ss[BLIND].round({'area_ha': 2, 'lat': 4, 'lon': 4}).to_csv(QCL / 'agents' / f'sector_L{s}.csv', index=False, encoding='utf-8')
    (QCL / 'lake_fit.json').write_text(json.dumps(sectors, ensure_ascii=False, indent=1), encoding='utf-8')
    log(f'выборка настройки {len(sample)} (undef {int((sample["pop"] == "undef_lake").sum())}, river {int((sample["pop"] == "river_lake").sum())}), '
        f'секторов {len(sectors)}: {[v["n"] for v in sectors.values()]}')
    print(pd.crosstab(sample['pop'], sample['region']).to_string())

    if a.render:
        base = [sys.executable, '-u', str(DRIVER), '--workers', '6', '--batch', '12', '--samples', str(QCL / 'lake_fit.json'),
                '--overlay', str(QCF / 'overlay_none.gpkg'), '--field', 'genesis', '--sample', str(QCL / 'lake_fit_geoms.gpkg')]
        subprocess.run(base + ['--out', str(QCL / 'thumbs_fit')], check=False)
        small = [int(i) for i, ar in zip(sample['id'], sample['area_ha']) if ar < 1]
        (QCL / '_zoom_fit.json').write_text(json.dumps({'1': {'name': 'zoom', 'ids': small}}), encoding='utf-8')
        zoom = [str(QCL / '_zoom_fit.json') if x == str(QCL / 'lake_fit.json') else x for x in base]
        subprocess.run(zoom + ['--out', str(QCL / 'thumbs_fit_zoom'), '--km', '0.8'], check=False)
        log(f'миниатюр: {len(list((QCL / "thumbs_fit").glob("*_esri.png")))} обзорных, '
            f'{len(list((QCL / "thumbs_fit_zoom").glob("*_esri.png")))} приближенных (нужно {len(small)})')
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
