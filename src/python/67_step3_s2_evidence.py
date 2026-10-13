"""
67_step3_s2_evidence.py — темпоральная улика шага 3 по подложке Sentinel-2 10 м за 2017–2019 (I:/Hansen/S2/Middle + S2/North):
«был ли голый песок в 2017–2019» — третий временной срез после Landsat-1985 и Hansen-2000; покрывает ВСЮ AOI (в т.ч. север
Ямала/Гыдана, где нет Hansen). Объекты маски 2020–2025, отсутствующие на подложке, — появились недавно.

Подложка: 48 тайлов (Middle 32 + North 16), EPSG:32643, 10 м, uint16 (отражение × 10 000), каналы B2, B3, B4, B8; 0 = нет данных.
Калибровка «голый песок» (red = B4 ≥ RED_MIN ∧ NDVI < NDVI_MAX): дюны Надыма — 93 % пикселей; массив у Обской губы 63 %;
промкомплекс Уренгоя 64 %; площадки Ямбурга 45 %; свежий техноген по агентам (125001, 214487, 444880, 700340) — 3–20 %.
Каверза: сеть Бованенково (2008–2012, гравий/тёмная отсыпка) — 18 %: «не голый в 2017–19» ≠ «не существовал».

По каждому контуру остатка (порядок как в step3_evidence.csv):
  bare_s2_frac — доля площади, голой в 2017–2019; red_s2_mean, ndvi_s2_mean; s2_cov — доля контура с данными подложки.
Тайлы Middle/North перекрываются по широте (~118 км) — пиксели зоны перекрытия считаются дважды в числителе и знаменателе, доля не искажается.
Выход: колонки добавляются в exports/qc/step3/step3_evidence.csv; чекпоинт накопителей step3_s2_partial.npz каждые CKPT тайлов.
Запуск: python -u python/67_step3_s2_evidence.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import glob
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from scipy import ndimage

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC3 = EXPORTS / 'qc' / 'step3'
SRC = EXPORTS / 'baresand_genesis_step2_v3_split.gpkg'
EVID = QC3 / 'step3_evidence.csv'
CKPT = QC3 / 'step3_s2_partial.npz'
S2_DIRS = [Path(r'I:\Hansen\S2\Middle'), Path(r'I:\Hansen\S2\North')]
S2_CRS = 'EPSG:32643'
RED_MIN = 1500
NDVI_MAX = 0.20
CKPT_EVERY = 8


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def main() -> None:
    t0 = time.time()
    ev = pd.read_csv(EVID, low_memory=False)
    log('читаю остаток маски...')
    g = gpd.read_file(SRC, where="genesis = 'unassigned'", columns=['id']).to_crs(S2_CRS)
    g = g.set_index('id').loc[ev['id'].values].reset_index()
    n = len(g)
    tiles = sorted(f for d in S2_DIRS for f in glob.glob(str(d / '*.tif')))
    acc = {k: np.zeros(n) for k in ('px', 'bare', 'red', 'ndvi')}
    done = set()
    if CKPT.exists():
        z = np.load(CKPT, allow_pickle=True)
        for k in acc:
            acc[k] = z[k]
        done = set(z['done'].tolist())
        log(f'чекпоинт: {len(done)} тайлов уже посчитано')
    idx_all = np.arange(1, n + 1, dtype='uint32')
    for ti, f in enumerate(tiles, start=1):
        if f in done:
            continue
        with rasterio.open(f) as src:
            tr, shape, b = src.transform, (src.height, src.width), src.bounds
            sub = g.cx[b.left:b.right, b.bottom:b.top]
            if len(sub) == 0:
                done.add(f)
                continue
            red = src.read(3).astype('float32')
            nir = src.read(4).astype('float32')
        valid = red > 0
        ndvi = np.where(valid, (nir - red) / np.maximum(nir + red, 1), 0).astype('float32')
        del nir
        bare = (valid & (red >= RED_MIN) & (ndvi < NDVI_MAX)).astype('uint8')
        lab = rasterize(((geom, i + 1) for i, geom in zip(sub.index, sub.geometry)), out_shape=shape, transform=tr,
                        fill=0, all_touched=True, dtype='uint32')
        idx = idx_all[sub.index.values]
        acc['px'][sub.index] += ndimage.sum(valid.astype('uint8'), lab, index=idx)
        acc['bare'][sub.index] += ndimage.sum(bare, lab, index=idx)
        acc['red'][sub.index] += ndimage.sum(np.where(valid, red, 0), lab, index=idx)
        acc['ndvi'][sub.index] += ndimage.sum(ndvi, lab, index=idx)
        del red, ndvi, bare, valid, lab
        done.add(f)
        log(f'  тайл {ti}/{len(tiles)} {Path(f).name}: контуров {len(sub):,} | {(time.time() - t0) / 60:.1f} мин')
        if ti % CKPT_EVERY == 0:
            np.savez(CKPT, done=np.array(sorted(done)), **acc)

    px = acc['px']
    ok = px > 0
    ev['bare_s2_frac'] = np.where(ok, acc['bare'] / np.maximum(px, 1), np.nan).round(3)
    ev['red_s2_mean'] = np.where(ok, acc['red'] / np.maximum(px, 1), np.nan).round(0)
    ev['ndvi_s2_mean'] = np.where(ok, acc['ndvi'] / np.maximum(px, 1), np.nan).round(3)
    ev['s2_cov'] = np.minimum(px * 100.0 / np.maximum(ev['area_ha'].values * 1e4, 1), 1.0).round(2)
    ev.loc[~ok, 's2_cov'] = 0.0
    ev.to_csv(EVID, index=False, encoding='utf-8')
    if CKPT.exists():
        CKPT.unlink()
    log(f'сохранено {EVID.name}: с данными подложки {int(ok.sum()):,} из {n:,} | bare_s2 ≥ 0.5: {(ev.bare_s2_frac >= 0.5).sum():,} | '
        f'< 0.15: {(ev.bare_s2_frac < 0.15).sum():,} | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
