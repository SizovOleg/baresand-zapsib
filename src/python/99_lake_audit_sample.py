"""
99_lake_audit_sample.py — аудиторская выборка для ЗАМОРОЖЕННЫХ правил озёрного прохода (2026-09-18, план §6).

Совокупность аудита: контуры lake_evidence_v2.csv с измерениями, не размеченные ранее, не из выборки настройки, дальше
GAP_M = 1.2 км от любого контура настройки и не у тех же водных компонент (near_comp) — озёрные системы не делятся.
Правила берутся из exports/qc/lake/rules_frozen.json (98 --freeze) и применяются функцией rule_mask из 98 — один источник истины.
Отбор: --n-hit срабатываний (страты правило × регион × размер) и --n-miss несрабатываний (undef_lake: регион × размер;
river_lake: регион). Агенты не знают, что сработало: сектора A<n> перемешивают всё по положению.
Слепые таблицы: id, area_ha, lat, lon. Снимки без оверлея; < 1 га — плюс окно 0.8 км. Промпты для аудита создаются из
промптов настройки заменой путей (thumbs_fit → thumbs_audit, L{N} → A{N}).

Выход: lake_audit.csv, strata_lake_audit.csv, lake_audit.json, lake_audit_geoms.gpkg, agents/sector_A<n>.csv,
       thumbs_audit/, thumbs_audit_zoom/, PROMPT_review_audit.md, PROMPT_verify_audit.md, audit_population.csv (все срабатывания).
Запуск: python -u python/99_lake_audit_sample.py --n-hit 100 --n-miss 80 --sectors 14 --render
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import importlib
import json
import subprocess
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.cluster import KMeans

ROOT = Path(r'D:\test\baresand_zapsib')
EXPORTS = ROOT / 'exports'
PRODUCT = EXPORTS / 'baresand_genesis_step5_v3e.gpkg'
QCL = EXPORTS / 'qc' / 'lake'
QCF = EXPORTS / 'qc' / 'final'
DRIVER = ROOT / 'python' / 'qc_render_parallel.py'
SEED = 20260919
GAP_M = 1200.0
LAT_NORTH, LON_OB = 67.5, 72.5
SIZE_L_HA = 1.0
BLIND = ['id', 'area_ha', 'lat', 'lon']

sys.path.insert(0, str(ROOT / 'python'))
m98 = importlib.import_module('98_lake_verdicts')
m97 = importlib.import_module('97_lake_sample')


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n-hit', type=int, default=100)
    ap.add_argument('--n-miss', type=int, default=80)
    ap.add_argument('--miss-river-share', type=float, default=0.25)
    ap.add_argument('--sectors', type=int, default=14)
    ap.add_argument('--render', action='store_true')
    a = ap.parse_args()
    t0 = time.time()
    frozen = json.loads((QCL / 'rules_frozen.json').read_text(encoding='utf-8'))
    log('правила: ' + '; '.join(f'{k}: {v["family"]} {v["params"]}' for k, v in frozen['rules'].items()))

    ev = pd.read_csv(QCL / 'lake_evidence_v2.csv')
    ev = ev[ev['c30'].notna() & ev['lat'].notna()].copy()
    fit = pd.read_csv(QCL / 'lake_fit.csv')
    ex = m97.already_labelled() | set(fit['id'])
    ev = ev[~ev['id'].isin(ex)].copy()
    tree = cKDTree(fit[['x', 'y']].to_numpy())
    dist, _ = tree.query(ev[['x', 'y']].to_numpy(), k=1)
    ev['d_fit_m'] = dist
    ev = ev[(ev['d_fit_m'] >= GAP_M) & ~ev['near_comp'].isin(set(fit['near_comp'].dropna()))].copy()
    log(f'совокупность аудита: {len(ev)} контуров, {ev["area_ha"].sum() / 100:.1f} км² (исключено по зазору и компонентам)')

    ev['region'] = m97.region(ev['lat'], ev['lon'])
    ev['size'] = np.where(ev['area_ha'] >= SIZE_L_HA, 'L', 'S')
    ev['fired'] = ''
    for key, r in frozen['rules'].items():
        m = m98.rule_mask(ev, r['family'], r['params'])
        ev.loc[m, 'fired'] = key
    hits = ev[ev['fired'] != '']
    log('срабатываний в совокупности аудита: ' + ', '.join(f'{k}: {int((hits["fired"] == k).sum())} конт. / {hits.loc[hits["fired"] == k, "area_ha"].sum() / 100:.1f} км²'
                                                      for k in frozen['rules']))
    ev.to_csv(QCL / 'audit_population.csv', index=False, encoding='utf-8')

    ev['stratum'] = ''
    h = ev['fired'] != ''
    ev.loc[h, 'stratum'] = 'H_' + ev.loc[h, ['fired', 'region', 'size']].agg('_'.join, axis=1)
    mu = ~h & (ev['pop'] == 'undef_lake')
    ev.loc[mu, 'stratum'] = 'MU_' + ev.loc[mu, ['region', 'size']].agg('_'.join, axis=1)
    mr = ~h & (ev['pop'] == 'river_lake')
    ev.loc[mr, 'stratum'] = 'MR_' + ev.loc[mr, 'region']
    strata = ev.groupby(['pop', 'stratum']).agg(N_conts=('id', 'size'), A_km2=('area_ha', lambda x: x.sum() / 100)).reset_index().set_index('stratum')
    strata['kind'] = np.where(strata.index.str.startswith('H_'), 'hit', np.where(strata.index.str.startswith('MU_'), 'miss_undef', 'miss_river'))
    n_mr = int(round(a.n_miss * a.miss_river_share))
    plan = pd.concat([m97.allocate(strata[strata['kind'] == 'hit'], a.n_hit, 4),
                      m97.allocate(strata[strata['kind'] == 'miss_undef'], a.n_miss - n_mr, 4),
                      m97.allocate(strata[strata['kind'] == 'miss_river'], n_mr, 3)])
    strata['n_plan'] = plan
    rng = np.random.default_rng(SEED)
    sample = m97.pick_with_gap(ev, plan, rng)
    strata['n_audit'] = sample.groupby('stratum').size()
    strata['n_audit'] = strata['n_audit'].fillna(0).astype(int)
    strata['pi'] = strata['n_audit'] / strata['N_conts']
    strata.reset_index().to_csv(QCL / 'strata_lake_audit.csv', index=False, encoding='utf-8')
    print(strata[['pop', 'kind', 'N_conts', 'A_km2', 'n_plan', 'n_audit']].round(1).to_string())

    km = KMeans(n_clusters=min(a.sectors, len(sample)), random_state=SEED, n_init=10).fit(sample[['x', 'y']])
    sample['cluster'] = km.labels_
    sample = sample.sort_values(['cluster', 'x']).reset_index(drop=True)
    sample['sector'] = (np.arange(len(sample)) * a.sectors // len(sample)) + 1
    sample['split'] = 'audit'
    sample.to_csv(QCL / 'lake_audit.csv', index=False, encoding='utf-8')

    g = gpd.read_file(PRODUCT, layer='genesis', columns=['id'], where=f"id IN ({','.join(map(str, sample['id']))})")
    g = g.merge(sample[['id', 'pop', 'stratum', 'area_ha']], on='id')
    bad = ~g.geometry.is_valid
    if bad.any():
        g.loc[bad, 'geometry'] = g.loc[bad, 'geometry'].make_valid()
    g.to_file(QCL / 'lake_audit_geoms.gpkg', layer='sample', driver='GPKG')

    sectors = {}
    for s in sorted(sample['sector'].unique()):
        ss = sample[sample['sector'] == s].sort_values('id')
        sectors[str(s)] = {'name': f'A{s}', 'n': int(len(ss)), 'ids': [int(i) for i in ss['id']]}
        ss[BLIND].round({'area_ha': 2, 'lat': 4, 'lon': 4}).to_csv(QCL / 'agents' / f'sector_A{s}.csv', index=False, encoding='utf-8')
    (QCL / 'lake_audit.json').write_text(json.dumps(sectors, ensure_ascii=False, indent=1), encoding='utf-8')
    log(f'аудиторская выборка {len(sample)} (срабатываний {int((sample["fired"] != "").sum())}, несрабатываний {int((sample["fired"] == "").sum())}), '
        f'секторов {len(sectors)}: {[v["n"] for v in sectors.values()]}')

    for kind in ('review', 'verify'):
        txt = (QCL / f'PROMPT_{kind}_lake.md').read_text(encoding='utf-8')
        txt = txt.replace('thumbs_fit', 'thumbs_audit').replace('L{N}', 'A{N}').replace('редакция 2', 'редакция 2, аудит')
        (QCL / f'PROMPT_{kind}_audit.md').write_text(txt, encoding='utf-8')

    if a.render:
        base = [sys.executable, '-u', str(DRIVER), '--workers', '6', '--batch', '12', '--samples', str(QCL / 'lake_audit.json'),
                '--overlay', str(QCF / 'overlay_none.gpkg'), '--field', 'genesis', '--sample', str(QCL / 'lake_audit_geoms.gpkg')]
        subprocess.run(base + ['--out', str(QCL / 'thumbs_audit')], check=False)
        small = [int(i) for i, ar in zip(sample['id'], sample['area_ha']) if ar < 1]
        (QCL / '_zoom_audit.json').write_text(json.dumps({'1': {'name': 'zoom', 'ids': small}}), encoding='utf-8')
        zoom = [str(QCL / '_zoom_audit.json') if x == str(QCL / 'lake_audit.json') else x for x in base]
        subprocess.run(zoom + ['--out', str(QCL / 'thumbs_audit_zoom'), '--km', '0.8'], check=False)
        log(f'миниатюр: {len(list((QCL / "thumbs_audit").glob("*_esri.png")))} обзорных, '
            f'{len(list((QCL / "thumbs_audit_zoom").glob("*_esri.png")))} приближенных (нужно {len(small)})')
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
