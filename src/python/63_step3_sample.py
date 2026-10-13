"""
63_step3_sample.py — стратифицированная выборка для визуальной верификации шага 3 (антропоген) + рендер.

Страты (см. AGENT_PROTOCOL_step3.md):
  net         — правило a_net (сети дорог/площадок из шага 2) — контроль
  osm_on      — a_osm_on: контур в следе OSM-инфраструктуры
  net_adj     — a_net_adj: примыкает к сети (фрагмент той же сети?)
  near_new    — a_near_new: у инфраструктуры, тёмный в 1985 (свежая отсыпка/карьер — или новый раздув у дороги?)
  road_small  — a_road_small: мелочь (≤ 1 га), касающаяся дороги (обочина/резерв — или раздув у дороги?)
  thin_net    — a_thin_net: тонкая сеть ≥ 20 га (ero50 < 0.15), не взятая пре-фильтром шага 2 — сеть дорог/площадок?
  adjacent    — природный (не взят), но ≤ 100 м от инфраструктуры — раздув у дороги или пропущенная отсыпка?
  new_far     — природный, тёмный в 1985, ≥ 5 га, вдали от инфраструктуры — некартированный карьер или новый раздув?
  big_natural — природный ≥ 20 га, ≤ 2 км от инфраструктуры — пропущенный карьер/посёлок?
  far         — контроль: природный, > 3 км от любой инфраструктуры
Секторы: KMeans по центроидам (запад → восток). Гиганты (≥ 50 га) в классе — топ по площади в каждом секторе.
Выход: exports/qc/step3/visual_sample_step3.csv / .json, visual_sample_geoms_step3.gpkg (слой sample),
       overlay_step3.gpkg (классы для рендера), thumbs/ (при --render).
Запуск: python -u python/63_step3_sample.py --tag v1 [--per-sector 45] [--sectors 6] [--render]
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

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC3 = EXPORTS / 'qc' / 'step3'
DRIVER = Path(r'D:\test\baresand_zapsib\python\qc_render_parallel.py')
EA_CRS = 'EPSG:3576'
SEED = 42
D_ADJ, D_BIG, D_FAR = 100.0, 2000.0, 3000.0
BIG_HA, GIANT_HA, CAP_GIANT = 20.0, 50.0, 4
WEIGHTS = {'osm_on': 0.17, 'net_adj': 0.09, 'near_new': 0.15, 'road_small': 0.09, 'thin_net': 0.06, 'net': 0.05,
           'adjacent': 0.14, 'new_far': 0.12, 'big_natural': 0.07, 'far': 0.06}
EV_COLS = ['id', 'sector', 'stratum', 'genesis', 'step3_rule', 'new_far', 'anthro_adjacent', 'area_ha', 'd_road_any', 'd_road_major', 'd_industrial',
           'd_linear', 'd_building', 'd_place', 'place_type', 'osm_overlap', 'd_net', 'rect', 'elong', 'convex', 'ero15',
           'nv_km', 'mrr_long_m', 'l85_mean', 'l85_dark_frac', 'dist_water_m', 'flood_frac0', 'lat', 'lon']


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='v1')
    ap.add_argument('--per-sector', type=int, default=45)
    ap.add_argument('--sectors', type=int, default=6)
    ap.add_argument('--render', action='store_true')
    a = ap.parse_args()
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    src = EXPORTS / f'baresand_genesis_step3_{a.tag}.gpkg'

    g = gpd.read_file(src)
    g = g[g['genesis'].isin(['anthropogenic', 'unassigned']) & g['d_road_any'].notna()].copy()
    cen = g.geometry.centroid.set_crs(EA_CRS, allow_override=True)
    g['x'], g['y'] = cen.x, cen.y
    wgs = cen.to_crs('EPSG:4326')
    g['lat'], g['lon'] = wgs.y.round(4), wgs.x.round(4)
    d_infra = g[['d_road_any', 'd_industrial', 'd_linear', 'd_building']].min(axis=1)

    rule = g['step3_rule'].fillna('').str.replace(f'{a.tag}_', '', regex=False)
    g['stratum'] = 'other'
    for r_name, st in (('a_net', 'net'), ('a_osm_on', 'osm_on'), ('a_net_adj', 'net_adj'), ('a_near_new', 'near_new'),
                       ('a_road_small', 'road_small'), ('a_thin_net', 'thin_net'), ('a_near_shape', 'near_shape'), ('a_shape', 'shape'), ('a_linear', 'linear')):
        g.loc[rule == r_name, 'stratum'] = st
    nat = g['genesis'] == 'unassigned'
    g.loc[nat & (d_infra <= D_ADJ), 'stratum'] = 'adjacent'
    g.loc[nat & (g['new_far'] == 1), 'stratum'] = 'new_far'
    g.loc[nat & (d_infra > D_ADJ) & (d_infra <= D_BIG) & (g['area_ha'] >= BIG_HA), 'stratum'] = 'big_natural'
    g.loc[nat & (d_infra > D_FAR), 'stratum'] = 'far'
    pool = g[g['stratum'] != 'other'].copy()
    print('Пул по стратам:')
    print(pool.groupby('stratum').agg(n=('id', 'size'), km2=('area_km2', 'sum')).round(1).to_string())

    km = KMeans(n_clusters=a.sectors, random_state=SEED, n_init=10).fit(pool[['x', 'y']].values)
    pool['cl'] = km.labels_
    order = pool.groupby('cl')['lon'].mean().sort_values().index.tolist()
    pool['sector'] = pool['cl'].map({cl: i + 1 for i, cl in enumerate(order)})

    picks = []
    for s in range(1, a.sectors + 1):
        ps = pool[pool['sector'] == s]
        giants = ps[(ps['genesis'] == 'anthropogenic') & (ps['area_ha'] >= GIANT_HA)].nlargest(CAP_GIANT, 'area_ha')
        picks.append(giants)
        budget = max(a.per_sector - len(giants), int(a.per_sector * 0.7))
        for st, w in WEIGHTS.items():
            cand = ps[(ps['stratum'] == st) & ~ps['id'].isin(giants['id'])]
            n = min(len(cand), max(1, int(round(budget * w)))) if len(cand) else 0
            if n:
                top = cand.nlargest(n // 2, 'area_ha')
                rest = cand.drop(top.index)
                rnd = rest.sample(n=min(len(rest), n - len(top)), random_state=int(rng.integers(1e9))) if len(rest) else rest
                picks.append(pd.concat([top, rnd]))
    sample = pd.concat(picks).drop_duplicates('id')
    cols = [c for c in EV_COLS if c in sample.columns]
    sample[cols].sort_values(['sector', 'stratum', 'area_ha'], ascending=[True, True, False]) \
        .to_csv(QC3 / 'visual_sample_step3.csv', index=False, encoding='utf-8')
    gpd.GeoDataFrame(sample[['id', 'genesis', 'stratum', 'area_ha', 'geometry']], geometry='geometry', crs=EA_CRS) \
        .to_file(QC3 / 'visual_sample_geoms_step3.gpkg', layer='sample', driver='GPKG')

    sectors = {}
    for s in range(1, a.sectors + 1):
        ss = sample[sample['sector'] == s]
        if len(ss) == 0:
            continue
        sectors[str(s)] = {'name': f'S{s}', 'center_lat': round(float(ss['lat'].mean()), 3),
                           'center_lon': round(float(ss['lon'].mean()), 3),
                           'lat_range': [round(float(ss['lat'].min()), 2), round(float(ss['lat'].max()), 2)],
                           'lon_range': [round(float(ss['lon'].min()), 2), round(float(ss['lon'].max()), 2)],
                           'n': int(len(ss)), 'by_stratum': ss['stratum'].value_counts().to_dict(),
                           'ids': [int(i) for i in ss['id'].tolist()]}
    (QC3 / 'visual_sample_step3.json').write_text(json.dumps(sectors, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'\nВыборка: {len(sample):,} контуров в {len(sectors)} секторах')
    for s, d in sectors.items():
        print(f"  S{s}: {d['n']:3d} | {d['center_lat']}N {d['center_lon']}E | {d['by_stratum']}")

    if a.render:
        ov_p = QC3 / 'overlay_step3.gpkg'
        full = gpd.read_file(src, columns=['id', 'genesis'])
        full[['id', 'genesis', 'geometry']].to_file(ov_p, layer='overlay', driver='GPKG')
        cmd = [sys.executable, str(DRIVER), '--workers', '6', '--batch', '12',
               '--samples', str(QC3 / 'visual_sample_step3.json'), '--out', str(QC3 / 'thumbs'),
               '--overlay', str(ov_p), '--field', 'genesis', '--sample', str(QC3 / 'visual_sample_geoms_step3.gpkg'),
               '--evidence', str(QC3 / 'visual_sample_step3.csv')]
        print('\nРендер:', ' '.join(cmd[1:]), flush=True)
        subprocess.run(cmd, check=False)
    print(f'Время: {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
