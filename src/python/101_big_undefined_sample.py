"""
101_big_undefined_sample.py - пилот «описание по снимку -> вероятность класса» на крупнейших контурах undefined (2026-09-26).

Зачем: локальный разбор (exports/qc/jev/baseline_report.md) показал, что генезис остатка предсказывают 8 полей наблюдений
по снимку (AUC 0.95-0.97), а численные улики не дают чистоты 0.90. Пилот: один слепой дешифровщик описывает снимок,
модель на 296 размеченных контурах переводит описание в вероятности классов.
Выборка: N крупнейших контуров undefined в v3e, не размеченных ранее (holdout, целевая, озёрные fit и audit).
Все они крупнее 4 га, поэтому только обзорный снимок. Слепые таблицы: id, area_ha, lat, lon.

Выход: exports/qc/lake/big/big_sample.csv, big.json, big_geoms.gpkg, agents/sector_B<n>.csv, thumbs_big/.
Запуск: python -u python/101_big_undefined_sample.py --n 180 --sectors 12 --render
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
OUT = QCL / 'big'
QCF = EXPORTS / 'qc' / 'final'
DRIVER = ROOT / 'python' / 'qc_render_parallel.py'
SEED = 20260926
BLIND = ['id', 'area_ha', 'lat', 'lon']


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def labelled() -> set:
    ids: set = set()
    for p in (QCF / 'validation_sample.csv', EXPORTS / 'qc' / 'target' / 'target_sample.csv',
              QCL / 'lake_fit.csv', QCL / 'lake_audit.csv'):
        ids |= set(pd.read_csv(p, usecols=['id'])['id'])
    return ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=180)
    ap.add_argument('--sectors', type=int, default=12)
    ap.add_argument('--render', action='store_true')
    a = ap.parse_args()
    t0 = time.time()
    (OUT / 'agents').mkdir(parents=True, exist_ok=True)
    g = gpd.read_file(PRODUCT, layer='genesis', columns=['id', 'genesis', 'area_ha', 'nearest_type'], where="genesis = 'undefined'")
    g = g[~g['id'].isin(labelled())].sort_values('area_ha', ascending=False).head(a.n).copy()
    c = g.geometry.centroid
    w = gpd.GeoSeries(c, crs=g.crs).to_crs(4326)
    g['x'], g['y'], g['lon'], g['lat'] = c.x, c.y, w.x.round(5), w.y.round(5)
    km = KMeans(n_clusters=a.sectors, random_state=SEED, n_init=10).fit(g[['x', 'y']])
    g['cluster'] = km.labels_
    g = g.sort_values(['cluster', 'x']).reset_index(drop=True)
    g['sector'] = (np.arange(len(g)) * a.sectors // len(g)) + 1
    pd.DataFrame(g.drop(columns='geometry')).to_csv(OUT / 'big_sample.csv', index=False, encoding='utf-8')
    gg = g[['id', 'area_ha', 'geometry']].copy()
    bad = ~gg.geometry.is_valid
    if bad.any():
        gg.loc[bad, 'geometry'] = gg.loc[bad, 'geometry'].make_valid()
    gg.to_file(OUT / 'big_geoms.gpkg', layer='sample', driver='GPKG')
    sectors = {}
    for s in sorted(g['sector'].unique()):
        ss = g[g['sector'] == s].sort_values('id')
        sectors[str(s)] = {'name': f'B{s}', 'n': int(len(ss)), 'ids': [int(i) for i in ss['id']]}
        ss[BLIND].round({'area_ha': 2, 'lat': 4, 'lon': 4}).to_csv(OUT / 'agents' / f'sector_B{s}.csv', index=False, encoding='utf-8')
    (OUT / 'big.json').write_text(json.dumps(sectors, ensure_ascii=False, indent=1), encoding='utf-8')
    log(f'выборка {len(g)} контуров, {g["area_ha"].sum() / 100:.1f} км2, мин. {g["area_ha"].min():.2f} га; секторов {len(sectors)}: '
        f'{[v["n"] for v in sectors.values()]}')
    if a.render:
        cmd = [sys.executable, '-u', str(DRIVER), '--workers', '8', '--batch', '12', '--samples', str(OUT / 'big.json'),
               '--overlay', str(QCF / 'overlay_none.gpkg'), '--field', 'genesis', '--sample', str(OUT / 'big_geoms.gpkg'),
               '--out', str(OUT / 'thumbs_big')]
        subprocess.run(cmd, check=False)
        log(f'миниатюр: {len(list((OUT / "thumbs_big").glob("*_esri.png")))} из {len(g)}')
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
