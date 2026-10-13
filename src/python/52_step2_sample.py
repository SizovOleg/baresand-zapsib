"""
BareSand — Стратифицированная выборка для визуальной валидации шага 2 (речные/озёрные отмели).

Страты (см. AGENT_PROTOCOL_step2.md):
  river       — правило: river_shoal
  lake        — правило: lake_shoal
  giant       — river/lake ≥ 20 га (needs_split) — целиком (топ по площади, cap)
  near_dry    — ≤ D от воды, но не прошли (сухо/высоко) — проверка защиты террас
  small_river — у реки с UPA < UPA_MIN — не взяты
  small_lake  — у озера < LAKE_MIN км² — не взяты
  border      — D..500 м от воды, влажно/низко — не взяты (пропуски?)
  far         — контроль: > 1 км от воды, unassigned

Секторы: KMeans по центроидам, с запада на восток.
Выход: exports/qc/step2/visual_sample_step2.csv / .json, visual_sample_geoms_step2.gpkg,
       overlay для рендера — сам gpkg шага 2 (genesis).

Запуск: python -u python/52_step2_sample.py [--per-sector 50] [--sectors 6] [--tag v1] [--render]
"""
import sys
import json
import argparse
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from sklearn.cluster import KMeans

sys.stdout.reconfigure(encoding='utf-8')

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC2 = EXPORTS / 'qc' / 'step2'
DRIVER = Path(r'D:\test\baresand_zapsib\python\qc_render_parallel.py')
EA_CRS = 'EPSG:3576'
SEED = 42
D_NEAR, D_BORDER, D_FAR = 200.0, 500.0, 1000.0
UPA_MIN, LAKE_MIN = 50.0, 1.0
CAP_GIANT = 6
WEIGHTS = {'river': 0.28, 'lake': 0.18, 'near_dry': 0.18, 'border': 0.12, 'small_river': 0.08, 'small_lake': 0.06, 'far': 0.10}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--per-sector', type=int, default=50)
    ap.add_argument('--sectors', type=int, default=6)
    ap.add_argument('--tag', default='v1')
    ap.add_argument('--render', action='store_true')
    a = ap.parse_args()
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    src = EXPORTS / f'baresand_genesis_step2_{a.tag}.gpkg'

    g = gpd.read_file(src)
    g = g[g['genesis'] != 'shoal'].copy()                   # морской класс шага 1 не трогаем
    ev = g['dist_water_m'].notna()
    g = g[ev].copy()
    cen = g.geometry.centroid.set_crs(EA_CRS, allow_override=True)
    g['x'], g['y'] = cen.x, cen.y
    wgs = cen.to_crs('EPSG:4326')
    g['lat'], g['lon'] = wgs.y.round(4), wgs.x.round(4)

    wet_low = (g['flood_frac0'] >= 0.2) | (g['hnd_min'] <= 3)
    def stratum(r) -> str:
        if r['genesis'] in ('river_shoal', 'lake_shoal'):
            return 'giant' if r['area_ha'] >= 20 else ('river' if r['genesis'] == 'river_shoal' else 'lake')
        d = r['dist_water_m']
        if d <= D_NEAR:
            if r['nearest_type'] == 'river' and r['comp_upa_km2'] < UPA_MIN:
                return 'small_river'
            if r['nearest_type'] == 'lake' and r['comp_area_km2'] < LAKE_MIN:
                return 'small_lake'
            return 'near_dry'
        if D_NEAR < d <= D_BORDER and ((r['flood_frac0'] >= 0.2) or (r['hnd_min'] <= 3)):
            return 'border'
        if d > D_FAR:
            return 'far'
        return 'other'
    g['stratum'] = g.apply(stratum, axis=1)
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
        full = ps[ps['stratum'] == 'giant'].nlargest(CAP_GIANT, 'area_ha')
        picks.append(full)
        budget = max(a.per_sector - len(full), int(a.per_sector * 0.7))
        for st, w in WEIGHTS.items():
            cand = ps[ps['stratum'] == st]
            n = min(len(cand), max(1, int(round(budget * w)))) if len(cand) else 0
            if n:
                top = cand.nlargest(n // 2, 'area_ha')
                rest = cand.drop(top.index)
                rnd = rest.sample(n=min(len(rest), n - len(top)), random_state=int(rng.integers(1e9))) if len(rest) else rest
                picks.append(pd.concat([top, rnd]))
    sample = pd.concat(picks).drop_duplicates('id')
    cols = ['id', 'sector', 'stratum', 'genesis', 'needs_split', 'area_ha', 'dist_water_m', 'nearest_type',
            'comp_area_km2', 'comp_upa_km2', 'flood_frac0', 'flood_frac10', 'hnd_min', 'gsw_seas_max', 'lat', 'lon']
    cols = [c for c in cols if c in sample.columns]
    sample[cols].sort_values(['sector', 'stratum', 'area_ha'], ascending=[True, True, False]) \
        .to_csv(QC2 / 'visual_sample_step2.csv', index=False, encoding='utf-8')
    gpd.GeoDataFrame(sample[['id', 'genesis', 'stratum', 'area_ha', 'geometry']], geometry='geometry', crs=EA_CRS) \
        .to_file(QC2 / 'visual_sample_geoms_step2.gpkg', layer='sample', driver='GPKG')

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
    (QC2 / 'visual_sample_step2.json').write_text(json.dumps(sectors, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'\nВыборка: {len(sample):,} контуров в {len(sectors)} секторах')
    for s, d in sectors.items():
        print(f"  S{s}: {d['n']:3d} | {d['center_lat']}N {d['center_lon']}E | {d['by_stratum']}")

    if a.render:
        # оверлей — сам слой шага 2 в пределах 3 км от воды (весь файл тяжёлый: режем по evidence)
        ov = g[['id', 'genesis', 'geometry']]
        ov_p = QC2 / 'overlay_step2.gpkg'
        gpd.GeoDataFrame(ov, geometry='geometry', crs=EA_CRS).to_file(ov_p, layer='overlay', driver='GPKG')
        cmd = [sys.executable, str(DRIVER), '--workers', '6', '--batch', '12',
               '--samples', str(QC2 / 'visual_sample_step2.json'), '--out', str(QC2 / 'thumbs'),
               '--overlay', str(ov_p), '--field', 'genesis', '--sample', str(QC2 / 'visual_sample_geoms_step2.gpkg'),
               '--evidence', str(QC2 / 'visual_sample_step2.csv')]
        print('\nРендер:', ' '.join(cmd[1:]), flush=True)
        subprocess.run(cmd, check=False)
    print(f'Время: {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
