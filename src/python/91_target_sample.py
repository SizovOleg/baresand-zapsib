"""
91_target_sample.py — целевая выборка из зоны путаницы для НАСТРОЙКИ порогов по уликам рельефа.

Зачем: пороги по h_local / h_chan нельзя брать ни с эталонов шагов 2–4 (по ним настраивались прежние правила),
ни с отложенной выборки (она — единственная независимая проверка). Нужна третья, своя выборка из тех контуров,
которые правила и будут трогать. Она стратифицирована по величине превышения, чтобы порог было на чём искать.

Два фронта:
  A — весь класс undefined (вернуть раздувы и озёрные отмели, что каскад отложил);
  B — эоловые ближе 400 м к руслу (вычистить побочни, которым каскад дал «эоловый»).

Страты: фронт × бин превышения h_local600 (≤0.5 / 0.5–1.5 / 1.5–3 / >3 м) × тип ближайшей воды (озеро/река) × размер
(<1 / ≥1 га). Плюс добор контуров с признаком «русло пересекает контур» (upa_in_max ≥ 20 км² и русловой коридор
внутри), чтобы правило B было на чём проверять. Веса страт сохраняются — по ним потом считается, сколько площади
переедет между классами.

Слепота агентов: в сектора уходят только плановые признаки без метки карты, без рельефа и без расстояния до русла.
Миниатюры без оверлея классов. Исключены все контуры отложенной выборки и прежних эталонов.

Вход:  exports/baresand_genesis_step4_v2e.gpkg, exports/qc/dem/mass/part_*.csv (улики рельефа, 90).
Выход: exports/qc/target/target_sample.csv (полная таблица), target_sample.json (сектора), target_geoms.gpkg,
       strata_target.csv, agents/sector_T<n>.csv (слепые), thumbs_target/ (при --render).
Запуск: python -u python/91_target_sample.py --per-stratum 8 --sectors 12 --render
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
PRODUCT = EXPORTS / 'baresand_genesis_step4_v2e.gpkg'
MASS = EXPORTS / 'qc' / 'dem' / 'mass'
QCT = EXPORTS / 'qc' / 'target'
QCF = EXPORTS / 'qc' / 'final'
DRIVER = ROOT / 'python' / 'qc_render_parallel.py'
SEED = 20260913
D_CHAN = 400
HBINS = [-np.inf, 0.5, 1.5, 3.0, np.inf]
HLAB = ['h<=0.5', 'h0.5-1.5', 'h1.5-3', 'h>3']
UPA_CROSS = 20.0
# что видят агенты (слепые колонки): без genesis, рельефа, расстояния до русла и служебных полей
BLIND = ['id', 'area_ha', 'lat', 'lon', 'dist_water_m', 'nearest_type', 'flood_frac0', 'n_nb_2km',
         'bare2000_frac', 'bare_s2_frac', 'ndvi_s2_mean', 'd_road_built']


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def excluded_ids() -> set:
    ids = set()
    f = QCF / 'validation_sample.csv'
    if f.exists():
        ids |= set(pd.read_csv(f, usecols=['id'])['id'].astype(int))
    for s in ('step2', 'step3', 'step4'):
        f = EXPORTS / 'qc' / s / f'regression_{s}.csv'
        if f.exists():
            ids |= set(pd.read_csv(f, usecols=['id'])['id'].astype(int))
    return ids


def load_dem() -> pd.DataFrame:
    parts = sorted(MASS.glob('part_*.csv'))
    if not parts:
        raise SystemExit('нет exports/qc/dem/mass/part_*.csv — сначала 90_dem_evidence_mass.py')
    d = pd.concat([pd.read_csv(p) for p in parts], ignore_index=True).drop_duplicates('id')
    d['h_local600'] = d['h_cont'] - d['local600_p5']
    d['h_local1200'] = d['h_cont'] - d['local1200_p5']
    near = d['chan600_n'].fillna(0) >= 3
    d['h_chan'] = np.where(near, d['h_cont'] - d['chan600_p5'], d['h_cont'] - d['chan2500_p5'])
    d.loc[~near & (d['chan2500_n'].fillna(0) < 3), 'h_chan'] = np.nan
    d['crossed'] = (d['upa_in_max'].fillna(0) >= UPA_CROSS) & (d['chan_in_frac'].fillna(0) > 0)
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--per-stratum', type=int, default=8)
    ap.add_argument('--cross-min', type=int, default=30, help='минимум контуров с пересечением русла на фронт')
    ap.add_argument('--sectors', type=int, default=12)
    ap.add_argument('--fronts', default='A,B')
    ap.add_argument('--render', action='store_true')
    ap.add_argument('--append', action='store_true', help='дописать к уже существующей выборке (второй фронт)')
    ap.add_argument('--sector-offset', type=int, default=0, help='нумерация секторов с этого числа + 1')
    a = ap.parse_args()
    t0 = time.time()
    QCT.mkdir(parents=True, exist_ok=True)
    (QCT / 'agents').mkdir(exist_ok=True)

    dem = load_dem()
    log(f'улик рельефа: {len(dem)} контуров')
    cols = ['id', 'genesis', 'area_ha', 'dist_channel_m', 'dist_water_m', 'nearest_type', 'flood_frac0', 'n_nb_2km',
            'bare2000_frac', 'bare_s2_frac', 'ndvi_s2_mean', 'd_road_built', 'loss_frac', 'step4_rule', 'e_score', 'geometry']
    g = gpd.read_file(PRODUCT, layer='genesis', columns=cols[:-1],
                      where=f"id IN ({','.join(map(str, dem['id'].tolist()))})")
    c = g.geometry.centroid.to_crs(4326)
    g['lon'], g['lat'] = c.x, c.y
    pop = g.merge(dem, on='id', how='inner')
    pop = pop[~pop['id'].isin(excluded_ids())]
    prev = pd.read_csv(QCT / 'target_sample.csv') if (a.append and (QCT / 'target_sample.csv').exists()) else None
    if prev is not None:
        pop = pop[~pop['id'].isin(prev['id'])]
    pop['front'] = np.where(pop['genesis'] == 'undefined', 'A',
                            np.where((pop['genesis'] == 'aeolian') & (pop['dist_channel_m'].fillna(9e9) <= D_CHAN), 'B', ''))
    pop = pop[pop['front'].isin(a.fronts.split(','))]
    pop['hbin'] = pd.cut(pop['h_local600'], HBINS, labels=HLAB).astype(str).replace('nan', 'h_na')
    pop['water'] = pop['nearest_type'].fillna('none').replace({'None': 'none'})
    pop.loc[~pop['water'].isin(['lake', 'river']), 'water'] = 'none'
    pop['size'] = np.where(pop['area_ha'] < 1, 'S', 'M')
    pop['stratum'] = pop['front'] + '_' + pop['hbin'] + '_' + pop['water'] + '_' + pop['size']
    log(f'генеральная совокупность: {len(pop)} | по фронтам {pop["front"].value_counts().to_dict()} | '
        f'с пересечением русла {int(pop["crossed"].sum())}')

    rng = np.random.default_rng(SEED)
    picks = []
    for st, s in pop.groupby('stratum'):
        n = min(a.per_stratum, len(s))
        picks.append(s.sample(n, random_state=int(rng.integers(0, 2**31))))
    sample = pd.concat(picks)
    for fr in a.fronts.split(','):
        have = int(sample[(sample['front'] == fr) & sample['crossed']].shape[0])
        pool = pop[(pop['front'] == fr) & pop['crossed'] & ~pop['id'].isin(sample['id'])]
        need = max(0, a.cross_min - have)
        if need and len(pool):
            picks.append(pool.sample(min(need, len(pool)), random_state=SEED + 7))
    sample = pd.concat(picks).drop_duplicates('id').copy()
    sample['crossed'] = sample['crossed'].astype(bool)

    strata = pop.groupby('stratum').agg(N_conts=('id', 'size'), A_km2=('area_ha', lambda x: x.sum() / 100)).reset_index()
    strata = strata.merge(sample.groupby('stratum').size().rename('n_sample').reset_index(), on='stratum', how='left')
    strata['n_sample'] = strata['n_sample'].fillna(0).astype(int)
    if prev is not None and (QCT / 'strata_target.csv').exists():
        strata = pd.concat([pd.read_csv(QCT / 'strata_target.csv'), strata]).drop_duplicates('stratum', keep='last')
    strata.to_csv(QCT / 'strata_target.csv', index=False, encoding='utf-8')

    km = KMeans(n_clusters=min(a.sectors, len(sample)), random_state=SEED, n_init=10).fit(sample[['lat', 'lon']])
    sample['sector'] = km.labels_ + 1 + a.sector_offset
    sample = sample.sort_values(['sector', 'stratum', 'area_ha'], ascending=[True, True, False])
    full_cols = [c for c in sample.columns if c != 'geometry']
    tab = pd.DataFrame(sample[full_cols])
    if prev is not None:
        tab = pd.concat([prev, tab], ignore_index=True).drop_duplicates('id')
    tab.to_csv(QCT / 'target_sample.csv', index=False, encoding='utf-8')

    sg = gpd.GeoDataFrame(sample[['id', 'genesis', 'front', 'stratum', 'area_ha', 'geometry']], geometry='geometry', crs=g.crs)
    bad = ~sg.geometry.is_valid
    if bad.any():
        sg.loc[bad, 'geometry'] = sg.loc[bad, 'geometry'].make_valid()
    if prev is not None and (QCT / 'target_geoms.gpkg').exists():
        sg.to_file(QCT / 'target_geoms.gpkg', layer='sample', driver='GPKG', mode='a')
    else:
        sg.to_file(QCT / 'target_geoms.gpkg', layer='sample', driver='GPKG')

    sectors = {}
    for s in sorted(sample['sector'].unique()):
        ss = sample[sample['sector'] == s]
        sectors[str(s)] = {'name': f'T{s}', 'center_lat': round(float(ss['lat'].mean()), 3),
                           'center_lon': round(float(ss['lon'].mean()), 3),
                           'lat_range': [round(float(ss['lat'].min()), 2), round(float(ss['lat'].max()), 2)],
                           'lon_range': [round(float(ss['lon'].min()), 2), round(float(ss['lon'].max()), 2)],
                           'n': int(len(ss)), 'ids': [int(i) for i in ss['id']]}
        ss[BLIND].to_csv(QCT / 'agents' / f'sector_T{s}.csv', index=False, encoding='utf-8')
    if prev is not None and (QCT / 'target_sample.json').exists():
        old = json.loads((QCT / 'target_sample.json').read_text(encoding='utf-8'))
        old.update(sectors)
        sectors_all = old
    else:
        sectors_all = sectors
    (QCT / 'target_sample.json').write_text(json.dumps(sectors_all, ensure_ascii=False, indent=1), encoding='utf-8')

    log(f'выборка: {len(sample)} контуров, {len(sectors)} секторов; по фронтам {sample["front"].value_counts().to_dict()}; '
        f'с пересечением русла {int(sample["crossed"].sum())}')
    print(sample.groupby(['front', 'hbin', 'water']).size().unstack(fill_value=0).to_string())

    if a.render:
        (QCT / '_render_now.json').write_text(json.dumps(sectors, ensure_ascii=False), encoding='utf-8')
        cmd = [sys.executable, str(DRIVER), '--workers', '6', '--batch', '12', '--samples', str(QCT / '_render_now.json'),
               '--out', str(QCT / 'thumbs_target'), '--overlay', str(QCF / 'overlay_none.gpkg'), '--field', 'genesis',
               '--sample', str(QCT / 'target_geoms.gpkg'), '--evidence', str(QCT / 'target_sample.csv')]
        log('рендер: ' + ' '.join(cmd[1:]))
        subprocess.run(cmd, check=False)
        log(f'миниатюр: {len(list((QCT / "thumbs_target").glob("*_esri.png")))}')
        # второй, приближенный снимок для мелких контуров: положение относительно воды на окне 2.5 км не читается
        small = {k: {**v, 'ids': [i for i in v['ids'] if i in set(sample.loc[sample['area_ha'] < 1, 'id'])]}
                 for k, v in sectors.items()}
        small = {k: v for k, v in small.items() if v['ids']}
        if small:
            (QCT / '_render_zoom.json').write_text(json.dumps(small, ensure_ascii=False), encoding='utf-8')
            cmd_z = [sys.executable, str(DRIVER), '--workers', '6', '--batch', '12', '--samples', str(QCT / '_render_zoom.json'),
                     '--out', str(QCT / 'thumbs_target_zoom'), '--overlay', str(QCF / 'overlay_none.gpkg'), '--field', 'genesis',
                     '--sample', str(QCT / 'target_geoms.gpkg'), '--evidence', str(QCT / 'target_sample.csv'), '--km', '0.8']
            log(f'рендер приближенных (< 1 га): {sum(len(v["ids"]) for v in small.values())} контуров')
            subprocess.run(cmd_z, check=False)
            log(f'приближенных миниатюр: {len(list((QCT / "thumbs_target_zoom").glob("*_esri.png")))}')
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
