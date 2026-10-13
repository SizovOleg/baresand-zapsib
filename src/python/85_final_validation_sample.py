"""
85_final_validation_sample.py — независимая (holdout) выборка для итоговой валидации всего каскада генезиса.

Зачем: пороги правил шагов 2–4 подбирались перебором на эталонах этих же шагов, поэтому заявленная там точность оптимистична.
Эта выборка набирается ПОСЛЕ фиксации всех порогов, исключает все контуры, уже попавшие в любой эталон, и даёт:
  * непредвзятую оценку точности итогового продукта;
  * матрицу ошибок 6×6 по итоговым классам (морская / речная / озёрная отмель, антропоген, эоловый, неопределённый);
  * оценку площади каждого класса с доверительными интервалами (стратифицированная отношенческая оценка, 86).

Дизайн: страты = класс карты × размер контура (<1 га, 1–20 га, ≥20 га). Внутри страты — простая случайная выборка
(seed фиксирован). Веса страт (число и площадь генеральной совокупности) сохраняются в strata.csv — они нужны 86 для оценок.
Единица наблюдения — контур целиком: агент определяет ИСТИННЫЙ класс из тех же шести.

Вход:  exports/baresand_genesis_step4_v2e.gpkg; эталоны exports/qc/step*/regression_step*.csv (для исключения).
Выход: exports/qc/final/validation_sample.csv/.json, validation_geoms.gpkg (слой sample), strata.csv, overlay_final.gpkg,
       thumbs_final/<id>_esri.png (при --render); агенты пишут в exports/qc/final/agents/.
Запуск: python -u python/85_final_validation_sample.py --per-class 50 --render
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
QCF = EXPORTS / 'qc' / 'final'
DRIVER = ROOT / 'python' / 'qc_render_parallel.py'
PRODUCT = EXPORTS / 'baresand_genesis_step4_v2e.gpkg'
ETALONS = [EXPORTS / 'qc' / 'step2' / 'regression_step2.csv', EXPORTS / 'qc' / 'step3' / 'regression_step3.csv',
           EXPORTS / 'qc' / 'step4' / 'regression_step4.csv']
EA_CRS = 'EPSG:3576'
SEED = 20260908
CLASSES = ('shoal', 'river_shoal', 'lake_shoal', 'anthropogenic', 'aeolian', 'undefined')
SIZE_BINS = [(0.0, 1.0, 'S'), (1.0, 20.0, 'M'), (20.0, 1e9, 'L')]
MIN_PER_STRATUM = 8
EV_COLS = ['id', 'sector', 'stratum', 'genesis', 'size_class', 'area_ha', 'step2_rule', 'step3_rule', 'step4_rule', 'genesis_confidence',
           'dist_water_m', 'dist_channel_m', 'flood_frac0', 'd_road_built', 'd_industrial', 'nspd_parcel_ind_frac', 'nspd_struct_frac',
           'bare2000_frac', 'loss_frac', 'bare_s2_frac', 'ndvi_s2_mean', 'n_nb_2km', 'e_score', 'anthro_late_suspect', 'lat', 'lon']


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--per-class', type=int, default=50)
    ap.add_argument('--sectors', type=int, default=10)
    ap.add_argument('--render', action='store_true')
    a = ap.parse_args()
    t0 = time.time()
    QCF.mkdir(parents=True, exist_ok=True)

    log('читаю итоговый продукт...')
    g = gpd.read_file(PRODUCT).to_crs(EA_CRS)
    log(f'  {len(g):,} контуров / {g.area_km2.sum():,.1f} км²')

    used = set()
    for p in ETALONS:
        if p.exists():
            used |= set(pd.read_csv(p)['id'].astype(int))
    log(f'исключаю контуры прежних эталонов: {len(used):,} id')
    pool = g[~g['id'].isin(used)].copy()

    sz = np.full(len(pool), '', dtype=object)
    for lo, hi, name in SIZE_BINS:
        sz[(pool['area_ha'].values >= lo) & (pool['area_ha'].values < hi)] = name
    pool['size_class'] = sz
    pool['stratum'] = pool['genesis'] + '_' + pool['size_class']

    # веса страт считаем по ГЕНЕРАЛЬНОЙ совокупности (весь продукт), а не по пулу — пул лишь исключает уже виденное
    all_sz = np.full(len(g), '', dtype=object)
    for lo, hi, name in SIZE_BINS:
        all_sz[(g['area_ha'].values >= lo) & (g['area_ha'].values < hi)] = name
    g['size_class'] = all_sz
    g['stratum'] = g['genesis'] + '_' + g['size_class']
    strata = g.groupby('stratum').agg(N_conts=('id', 'size'), A_km2=('area_km2', 'sum'), mean_ha=('area_ha', 'mean')).reset_index()
    strata['genesis'] = strata['stratum'].str.rsplit('_', n=1).str[0]
    strata['size_class'] = strata['stratum'].str.rsplit('_', n=1).str[1]

    rng = np.random.default_rng(SEED)
    picks = []
    for cls in CLASSES:
        sub = strata[strata['genesis'] == cls]
        if not len(sub):
            continue
        w = sub['A_km2'].values / max(sub['A_km2'].sum(), 1e-9)          # доля площади подстраты внутри класса
        n = np.maximum(np.round(w * a.per_class).astype(int), MIN_PER_STRATUM)
        for (_, row), ni in zip(sub.iterrows(), n):
            cand = pool[pool['stratum'] == row['stratum']]
            if not len(cand):
                log(f'  страта {row["stratum"]}: в пуле пусто, пропуск')
                continue
            take = min(ni, len(cand))
            picks.append(cand.sample(n=take, random_state=int(rng.integers(1e9))))
    sample = pd.concat(picks).drop_duplicates('id').copy()
    ll = sample.geometry.centroid.to_crs('EPSG:4326')
    sample['lat'], sample['lon'] = ll.y.round(4).values, ll.x.round(4).values

    km = KMeans(n_clusters=a.sectors, random_state=SEED, n_init=10).fit(np.c_[sample.geometry.centroid.x, sample.geometry.centroid.y])
    sample['cl'] = km.labels_
    order = sample.groupby('cl').apply(lambda d: d.geometry.centroid.x.mean(), include_groups=False).sort_values().index.tolist()
    sample['sector'] = sample['cl'].map({c: i + 1 for i, c in enumerate(order)})

    n_h = sample.groupby('stratum').size().rename('n_sample')
    strata = strata.merge(n_h, on='stratum', how='left').fillna({'n_sample': 0})
    strata.to_csv(QCF / 'strata.csv', index=False, encoding='utf-8')

    ev = [c for c in EV_COLS if c in sample.columns]
    sample[ev].sort_values(['sector', 'stratum', 'area_ha'], ascending=[True, True, False]).to_csv(QCF / 'validation_sample.csv', index=False, encoding='utf-8')
    sg = gpd.GeoDataFrame(sample[['id', 'genesis', 'stratum', 'size_class', 'area_ha', 'geometry']], geometry='geometry', crs=EA_CRS)
    bad = ~sg.geometry.is_valid
    if bad.any():
        sg.loc[bad, 'geometry'] = sg.loc[bad, 'geometry'].make_valid()
    sg.to_file(QCF / 'validation_geoms.gpkg', layer='sample', driver='GPKG')

    sectors = {}
    for s in range(1, a.sectors + 1):
        ss = sample[sample['sector'] == s]
        if not len(ss):
            continue
        sectors[str(s)] = {'name': f'F{s}', 'center_lat': round(float(ss['lat'].mean()), 3), 'center_lon': round(float(ss['lon'].mean()), 3),
                           'lat_range': [round(float(ss['lat'].min()), 2), round(float(ss['lat'].max()), 2)],
                           'lon_range': [round(float(ss['lon'].min()), 2), round(float(ss['lon'].max()), 2)],
                           'n': int(len(ss)), 'by_stratum': ss['stratum'].value_counts().to_dict(), 'ids': [int(i) for i in ss['id'].tolist()]}
    (QCF / 'validation_sample.json').write_text(json.dumps(sectors, ensure_ascii=False, indent=1), encoding='utf-8')

    log(f'выборка: {len(sample)} контуров в {len(sectors)} секторах')
    print(sample.groupby(['genesis', 'size_class']).size().unstack(fill_value=0).to_string())
    print('\nвеса страт (генеральная совокупность):')
    print(strata[['stratum', 'N_conts', 'A_km2', 'n_sample']].sort_values('A_km2', ascending=False).head(20).to_string(index=False))

    (QCF / 'agents').mkdir(exist_ok=True)
    for s, d in sectors.items():
        sample[sample['id'].isin(d['ids'])][ev].to_csv(QCF / 'agents' / f'sector_F{s}.csv', index=False, encoding='utf-8')

    if a.render:
        ov = QCF / 'overlay_final.gpkg'
        g[['id', 'genesis', 'geometry']].to_file(ov, layer='overlay', driver='GPKG')
        cmd = [sys.executable, str(DRIVER), '--workers', '6', '--batch', '12', '--samples', str(QCF / 'validation_sample.json'),
               '--out', str(QCF / 'thumbs_final'), '--overlay', str(ov), '--field', 'genesis',
               '--sample', str(QCF / 'validation_geoms.gpkg'), '--evidence', str(QCF / 'validation_sample.csv')]
        log('рендер: ' + ' '.join(cmd[1:]))
        subprocess.run(cmd, check=False)
        log(f'миниатюр: {len(list((QCF / "thumbs_final").glob("*_esri.png")))}')
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
