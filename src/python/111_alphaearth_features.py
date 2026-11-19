"""
111_alphaearth_features.py - эмбеддинги AlphaEarth по контурам хвоста и размеченным контурам (2026-09-27).

Зачем: проверка, можно ли переносить метки владельца на похожие непросмотренные контуры (просьба владельца: «можно сразу
искать похожее - отмели и техноген - и сразу по ним снимать вопросы»). Это только признаки; модель и проверка в 112.
Совокупность: все undefined и disputed в v4 (хвост) + все размеченные контуры (владелец: owner_gold, expert_big, owner30,
undef_review aeolian18/river18; агенты: озёрный проход fit/audit, пилот big).
Признаки: GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL за год YEAR (64 канала, 10 м), среднее внутри контура (ai_00..ai_63) и в
кольце RING_M м снаружи (ar_00..ar_63: окружение). Геометрия упрощается на 5 м (как в 108).
Выход: exports/qc/alphaearth/ae_<YEAR>.csv; дописывается по частям, повторный запуск продолжает с места остановки.
Запуск: PYTHONIOENCODING=utf-8 python -u python/111_alphaearth_features.py [--year 2024]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
QC = ROOT / 'exports' / 'qc'
OUT_DIR = QC / 'alphaearth'
RING_M = 30
CHUNK = 250
WORKERS = 6


def labeled_ids() -> set[int]:
    """Все контуры с меткой владельца или агентов."""
    ids: set[int] = set()
    ids |= set(pd.read_csv(QC / 'owner_click' / 'owner_gold.csv')['id'])
    ids |= set(pd.read_csv(QC / 'lake' / 'big' / 'expert_big.csv')['id'])
    ids |= set(pd.read_csv(QC / 'lake' / 'owner30' / 'owner30_compare.csv')['id'])
    ids |= set(pd.read_csv(QC / 'disputed' / 'multireader.csv')['id'])
    for p in ('undef_review/aeolian18/dem.shp', 'undef_review/river18/river18.shp'):
        ids |= set(gpd.read_file(QC / p, ignore_geometry=True)['id'])
    return {int(i) for i in ids}


def geo(gm) -> dict:
    return json.loads(gpd.GeoSeries([gm]).to_json())['features'][0]['geometry']


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, default=2024)
    a = ap.parse_args()
    import ee
    try:
        ee.Initialize()
    except Exception:
        ee.Initialize(project='ee-author-project')
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f'ae_{a.year}.csv'
    lab = labeled_ids()
    g = gpd.read_file(PRODUCT, layer='genesis', columns=['id', 'genesis'])
    g = g[g['genesis'].isin(['undefined', 'disputed']) | g['id'].isin(lab)].copy()
    done = set(pd.read_csv(out, usecols=['id'])['id']) if out.exists() else set()
    g = g[~g['id'].isin(done)]
    print(f'контуров к расчёту: {len(g)} (уже есть {len(done)}), размеченных всего {len(lab)}', flush=True)
    if not len(g):
        return
    inner = g.geometry.simplify(5)
    ring = g.geometry.buffer(RING_M).difference(g.geometry).simplify(5)
    gi = gpd.GeoSeries(inner, crs=g.crs).to_crs(4326)
    gr = gpd.GeoSeries(ring, crs=g.crs).to_crs(4326)
    img = (ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
           .filterDate(f'{a.year}-01-01', f'{a.year + 1}-01-01').mosaic())
    bands = [f'A{i:02d}' for i in range(64)]
    ids = g['id'].to_numpy()
    lock = threading.Lock()
    header = not out.exists()

    def run(i0: int) -> int:
        sl = slice(i0, i0 + CHUNK)
        feats = []
        for i, gm_i, gm_r in zip(ids[sl], gi.iloc[sl], gr.iloc[sl]):
            if gm_i is not None and not gm_i.is_empty:
                feats.append(ee.Feature(ee.Geometry(geo(gm_i)), {'id': int(i), 'part': 'i'}))
            if gm_r is not None and not gm_r.is_empty:
                feats.append(ee.Feature(ee.Geometry(geo(gm_r)), {'id': int(i), 'part': 'r'}))
        for attempt in range(4):
            try:
                st = img.reduceRegions(collection=ee.FeatureCollection(feats), reducer=ee.Reducer.mean(),
                                       scale=10, tileScale=2).getInfo()
                break
            except Exception as e:
                if attempt == 3:
                    raise
                print(f'  повтор части {i0}: {str(e)[:120]}', flush=True)
                time.sleep(10 * (attempt + 1))
        rows: dict[int, dict] = {}
        for f in st['features']:
            p = f['properties']
            pre = 'ai' if p['part'] == 'i' else 'ar'
            r = rows.setdefault(p['id'], {'id': p['id']})
            for k, b in enumerate(bands):
                r[f'{pre}_{k:02d}'] = p.get(b)
        df = pd.DataFrame(list(rows.values()))
        cols = ['id'] + [f'ai_{k:02d}' for k in range(64)] + [f'ar_{k:02d}' for k in range(64)]
        df = df.reindex(columns=cols)
        nonlocal header
        with lock:
            df.to_csv(out, mode='a', header=header, index=False, encoding='utf-8')
            header = False
        return len(df)

    n_done = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(run, i0) for i0 in range(0, len(ids), CHUNK)]
        for k, fu in enumerate(as_completed(futs)):
            n_done += fu.result()
            if k % 10 == 0 or k == len(futs) - 1:
                print(f'  {n_done}/{len(ids)} | {(time.time() - t0) / 60:.1f} мин', flush=True)
    print(f'-> {out} | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
