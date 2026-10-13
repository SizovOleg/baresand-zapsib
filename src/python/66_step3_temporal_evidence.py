"""
66_step3_temporal_evidence.py — темпоральные улики шага 3 по мозаикам Hansen GFC (I:/Hansen): «был ли песок в 2000» (DNA A0)
и потери леса 2001–2019 (гари/вырубки).

Данные (все 30 м, EPSG:4326, тайлы 70N_060E / 070E / 080E — покрытие 60–70° с.ш., север Ямала и Гыдана НЕ покрыт):
  I:/Hansen/First2000/Hansen_GFC-2019-v1.7_first_<tile>.tif   — композит ~2000, 4 канала uint8: red, NIR, SWIR1, SWIR2 (масштаб 0–255)
  I:/Hansen/Lossyear/Hansen_GFC-2019-v1.7_lossyear_<tile>.tif — год потери лесного покрова (1..19 = 2001..2019, 0 = нет)
  I:/Hansen/Treecover2000/Hansen_GFC-2019-v1.7_treecover2000_<tile>.tif — % древесного покрова в 2000
Калибровка «песок в 2000» (по контурам с известным генезисом): дюны Надыма — red p50 120, NDVI −0.18, доля red ≥ 60 = 0.96;
природные массивы 0.81–0.96; площадки Ямбурга, построенные после 2000, — red 32, NDVI 0.22, доля 0.10; гари/вырубки в борах —
red 27–44, доля 0.00, lossyear > 0 у 55–99 % пикселей. Порог: bare2000 = red ≥ RED_MIN ∧ NDVI < NDVI_MAX.

По каждому контуру остатка (тот же набор и порядок, что в step3_evidence.csv):
  bare2000_frac — доля площади, бывшей ярким голым песком в 2000 (NaN вне покрытия)
  red2000_mean  — средняя яркость red 2000 (масштаб 0–255)
  loss_frac     — доля площади с потерей леса 2001–2019 (гарь/вырубка)
  tc2000_mean   — средний древесный покров 2000, %
  hansen_cov    — доля площади контура в покрытии тайлов (1 = полностью)
Выход: колонки добавляются в exports/qc/step3/step3_evidence.csv. По тайлам: чтение каналов целиком (1.6 ГБ/канал),
растеризация контуров тайла (uint32), ndimage.sum.
Запуск: python -u python/66_step3_temporal_evidence.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
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
HANSEN = Path(r'I:\Hansen')
TILES = ('70N_060E', '70N_070E', '70N_080E')
RED_MIN = 60
NDVI_MAX = 0.15


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def main() -> None:
    t0 = time.time()
    ev = pd.read_csv(EVID, low_memory=False)
    log('читаю остаток маски...')
    g = gpd.read_file(SRC, where="genesis = 'unassigned'", columns=['id']).to_crs('EPSG:4326')
    g = g.set_index('id').loc[ev['id'].values].reset_index()
    n = len(g)
    acc = {k: np.zeros(n) for k in ('px', 'bare', 'red', 'loss', 'tc')}
    area_px_total = np.zeros(n)
    for tile in TILES:
        first = HANSEN / 'First2000' / f'Hansen_GFC-2019-v1.7_first_{tile}.tif'
        with rasterio.open(first) as src:
            tr, shape, bounds = src.transform, (src.height, src.width), src.bounds
            sub = g.cx[bounds.left:bounds.right, bounds.bottom:bounds.top]
            if len(sub) == 0:
                continue
            log(f'{tile}: контуров в тайле {len(sub):,}; читаю red/NIR...')
            red = src.read(1)
            nir = src.read(2)
        ndvi = (nir.astype('float32') - red) / np.maximum(nir.astype('float32') + red, 1)
        del nir
        bare = ((red >= RED_MIN) & (ndvi < NDVI_MAX)).astype('uint8')
        del ndvi
        log(f'{tile}: растеризация...')
        lab = rasterize(((geom, i + 1) for i, geom in zip(sub.index, sub.geometry)), out_shape=shape, transform=tr,
                        fill=0, all_touched=True, dtype='uint32')
        idx = np.arange(1, n + 1, dtype='uint32')
        idx_sub = idx[sub.index.values]
        px = ndimage.sum(np.ones(shape, dtype='uint8'), lab, index=idx_sub)
        acc['px'][sub.index] += px
        acc['bare'][sub.index] += ndimage.sum(bare, lab, index=idx_sub)
        acc['red'][sub.index] += ndimage.sum(red, lab, index=idx_sub)
        del bare, red
        with rasterio.open(HANSEN / 'Lossyear' / f'Hansen_GFC-2019-v1.7_lossyear_{tile}.tif') as s:
            loss = (s.read(1) > 0).astype('uint8')
        acc['loss'][sub.index] += ndimage.sum(loss, lab, index=idx_sub)
        del loss
        with rasterio.open(HANSEN / 'Treecover2000' / f'Hansen_GFC-2019-v1.7_treecover2000_{tile}.tif') as s:
            tc = s.read(1)
        acc['tc'][sub.index] += ndimage.sum(tc, lab, index=idx_sub)
        del tc, lab
        log(f'{tile}: готово ({(time.time() - t0) / 60:.1f} мин)')

    px = acc['px']
    ok = px > 0
    ev['bare2000_frac'] = np.where(ok, acc['bare'] / np.maximum(px, 1), np.nan).round(3)
    ev['red2000_mean'] = np.where(ok, acc['red'] / np.maximum(px, 1), np.nan).round(0)
    ev['loss_frac'] = np.where(ok, acc['loss'] / np.maximum(px, 1), np.nan).round(3)
    ev['tc2000_mean'] = np.where(ok, acc['tc'] / np.maximum(px, 1), np.nan).round(0)
    # покрытие: пиксели 30 м × 900 м² относительно площади контура (all_touched завышает у мелких — режем до 1)
    ev['hansen_cov'] = np.minimum(px * 900.0 / np.maximum(ev['area_ha'].values * 1e4, 1), 1.0).round(2)
    ev.loc[~ok, 'hansen_cov'] = 0.0
    ev.to_csv(EVID, index=False, encoding='utf-8')
    cov = ev['hansen_cov'] > 0
    log(f'сохранено {EVID.name}: в покрытии {int(cov.sum()):,} из {n:,} контуров | bare2000 ≥ 0.7: {(ev.bare2000_frac >= 0.7).sum():,} | '
        f'< 0.2: {(ev.bare2000_frac < 0.2).sum():,} | loss ≥ 0.5: {(ev.loss_frac >= 0.5).sum():,} | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
