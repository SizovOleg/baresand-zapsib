"""
BareSand — Фаза 3, Шаг 1: атрибуция «отмель vs не-отмель».

DNA §6.5.3 (W0–W3):
  W0 — пересечение с зоной JRC GSW occurrence > 0 (главный критерий)
  W1 — речные отмели: HND_min < 8м И UPA_max > 50 км²
  W2 — озёрные пляжи: GSW_occ_max > 40% И GSW_seas_max ≥ 6 мес
  W3 — морские отмели: контур в буфере 2 км от границы AOI (береговая линия)

Стратегия (быстрая): растеризация контуров в общую grid с aux растрами +
scipy.ndimage.labeled_comprehension. Требует RAM ~30–60 GB для всех слоёв.

Вход:
  - exports/baresand_contours_v2.gpkg  (574k контуров, EPSG:3576)
  - exports/gsw_occurrence_AOI*.tif    (JRC GSW, EPSG:4326, 30м, uint8)
  - exports/gsw_seasonality_AOI*.tif   (uint8)
  - exports/hnd_AOI*.tif               (MERIT, EPSG:4326, ~90м, float32)
  - exports/upa_AOI*.tif               (float32)
  - exports/aoi_v2.geojson

Выход:
  - exports/baresand_littoral_v2.gpkg
"""

import sys
import time
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import reproject, Resampling, calculate_default_transform
from scipy import ndimage

warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')

# ════════════════════════════════════════════════════════════════════════════
# ПУТИ И ПОРОГИ
# ════════════════════════════════════════════════════════════════════════════

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
CONTOURS = EXPORTS / 'baresand_contours_v2.gpkg'
AOI_GEOJSON = EXPORTS / 'aoi_v2.geojson'
OUTPUT = EXPORTS / 'baresand_littoral_v2.gpkg'

HND_FLOODPLAIN_MAX = 8       # W1: < 8 м над ближайшим водотоком
UPA_RIVER_MIN = 50           # W1: > 50 км² водосбор
GSW_FLOOD_MIN = 10           # W0: mean occ > 10%
GSW_LAKE_OCC = 40            # W2: max occ > 40%
GSW_LAKE_SEAS = 6            # W2: max seasonality ≥ 6 мес
COAST_BUFFER_M = 2000        # W3: < 2 км от границы AOI

GDAL_DTYPE = {
    'uint8': 'Byte', 'int8': 'Int8', 'uint16': 'UInt16', 'int16': 'Int16',
    'uint32': 'UInt32', 'int32': 'Int32', 'float32': 'Float32', 'float64': 'Float64',
}


def build_vrt(prefix: str) -> Path | None:
    """Собрать VRT из тайлов {prefix}*.tif."""
    tiles = sorted(t for t in EXPORTS.rglob(prefix + '*.tif'))
    if not tiles:
        return None
    if len(tiles) == 1:
        return tiles[0]
    meta = []
    for t in tiles:
        with rasterio.open(t) as src:
            meta.append({'path': t.relative_to(EXPORTS).as_posix(),
                         'bounds': src.bounds, 'transform': src.transform,
                         'width': src.width, 'height': src.height, 'crs': src.crs,
                         'dtype': src.dtypes[0]})
    res_x = abs(meta[0]['transform'].a)
    res_y = meta[0]['transform'].e
    x_min = min(m['bounds'].left for m in meta)
    x_max = max(m['bounds'].right for m in meta)
    y_max = max(m['bounds'].top for m in meta)
    y_min = min(m['bounds'].bottom for m in meta)
    vw = int(round((x_max - x_min) / res_x))
    vh = int(round((y_max - y_min) / abs(res_y)))
    gdt = GDAL_DTYPE.get(meta[0]['dtype'], 'Float32')

    lines = [f'<VRTDataset rasterXSize="{vw}" rasterYSize="{vh}">',
             f'  <SRS>{meta[0]["crs"].to_wkt()}</SRS>',
             f'  <GeoTransform>{x_min}, {res_x}, 0.0, {y_max}, 0.0, {res_y}</GeoTransform>',
             f'  <VRTRasterBand dataType="{gdt}" band="1">']
    for m in meta:
        xo = int(round((m['bounds'].left - x_min) / res_x))
        yo = int(round((y_max - m['bounds'].top) / abs(res_y)))
        lines += [f'    <SimpleSource>',
                  f'      <SourceFilename relativeToVRT="1">{m["path"]}</SourceFilename>',
                  f'      <SourceBand>1</SourceBand>',
                  f'      <SrcRect xOff="0" yOff="0" xSize="{m["width"]}" ySize="{m["height"]}"/>',
                  f'      <DstRect xOff="{xo}" yOff="{yo}" xSize="{m["width"]}" ySize="{m["height"]}"/>',
                  f'    </SimpleSource>']
    lines += ['  </VRTRasterBand>', '</VRTDataset>']
    vrt = EXPORTS / (prefix.rstrip('-_') + '.vrt')
    vrt.write_text('\n'.join(lines), encoding='utf-8')
    return vrt


def load_raster(path: Path) -> tuple[np.ndarray, rasterio.transform.Affine, rasterio.crs.CRS]:
    """Загрузить растр в память целиком."""
    with rasterio.open(path) as src:
        return src.read(1), src.transform, src.crs


def reproject_to_grid(src_data: np.ndarray, src_transform, src_crs,
                      dst_shape, dst_transform, dst_crs, resampling=Resampling.average):
    """Перепроецировать растр в общую grid."""
    dst = np.zeros(dst_shape, dtype=src_data.dtype)
    reproject(
        source=src_data, destination=dst,
        src_transform=src_transform, src_crs=src_crs,
        dst_transform=dst_transform, dst_crs=dst_crs,
        resampling=resampling,
    )
    return dst


def main() -> None:
    t0 = time.time()
    print('═══════════════════════════════════════')
    print('ШАГ 1: АТРИБУЦИЯ ОТМЕЛЕЙ (W0–W3)')
    print('═══════════════════════════════════════')

    gsw_occ_p = build_vrt('gsw_occurrence_AOI')
    gsw_seas_p = build_vrt('gsw_seasonality_AOI')
    hnd_p = build_vrt('hnd_AOI')
    upa_p = build_vrt('upa_AOI')
    for k, v in [('gsw_occ', gsw_occ_p), ('gsw_seas', gsw_seas_p),
                 ('hnd', hnd_p), ('upa', upa_p)]:
        if v is None:
            print(f'!!! Отсутствует {k}')
            sys.exit(1)
        print(f'  {k:10s} {v.name}')

    # ── Загрузка контуров ──
    print(f'\n[{(time.time()-t0):.0f}s] Загружаю контуры: {CONTOURS.name}')
    gdf = gpd.read_file(CONTOURS)
    print(f'  Контуров: {len(gdf):,} | CRS: {gdf.crs}')

    # ── Загрузка GSW occurrence как опорной grid (30м, EPSG:4326) ──
    print(f'\n[{(time.time()-t0):.0f}s] Загружаю GSW occurrence...')
    gsw_occ, gsw_tr, gsw_crs = load_raster(gsw_occ_p)
    print(f'  shape: {gsw_occ.shape}, dtype: {gsw_occ.dtype}, '
          f'~{gsw_occ.nbytes / 1e9:.1f} GB')

    # ── Растеризация контуров в GSW grid ──
    # gdf в EPSG:3576, грид в EPSG:4326 → репроецируем контуры
    print(f'\n[{(time.time()-t0):.0f}s] Растеризую контуры в GSW grid (uint32)...')
    gdf_wgs = gdf.to_crs(gsw_crs)
    # Каждый контур получит свой ID = index+1 (0 = no contour)
    shapes = [(geom, idx + 1) for idx, geom in enumerate(gdf_wgs.geometry)]
    labels = rasterize(
        shapes, out_shape=gsw_occ.shape, transform=gsw_tr,
        fill=0, all_touched=True, dtype=np.uint32,
    )
    print(f'  labels shape: {labels.shape}, ненулевых: {(labels > 0).sum():,}')

    valid_index = np.arange(1, len(gdf) + 1, dtype=np.uint32)

    # ── Зональная статистика на GSW сетке (30м) ──
    print(f'\n[{(time.time()-t0):.0f}s] GSW occ: mean + max...')
    gsw_occ_mean = ndimage.mean(gsw_occ, labels=labels, index=valid_index)
    gsw_occ_max = ndimage.maximum(gsw_occ, labels=labels, index=valid_index)
    gdf['gsw_occ_mean'] = gsw_occ_mean
    gdf['gsw_occ_max'] = gsw_occ_max
    del gsw_occ

    print(f'[{(time.time()-t0):.0f}s] GSW seas: max...')
    gsw_seas, gsw_seas_tr, gsw_seas_crs = load_raster(gsw_seas_p)
    if gsw_seas.shape != labels.shape:
        gsw_seas = reproject_to_grid(gsw_seas, gsw_seas_tr, gsw_seas_crs,
                                      labels.shape, gsw_tr, gsw_crs)
    gdf['gsw_seas_max'] = ndimage.maximum(gsw_seas, labels=labels, index=valid_index)
    del gsw_seas

    # ── HND/UPA: ресэмпл на GSW grid (~30м) из 90м ──
    print(f'[{(time.time()-t0):.0f}s] HND: min...')
    hnd, hnd_tr, hnd_crs = load_raster(hnd_p)
    hnd_on_grid = reproject_to_grid(hnd, hnd_tr, hnd_crs,
                                     labels.shape, gsw_tr, gsw_crs,
                                     resampling=Resampling.bilinear)
    del hnd
    gdf['hnd_min'] = ndimage.minimum(hnd_on_grid, labels=labels, index=valid_index)
    del hnd_on_grid

    print(f'[{(time.time()-t0):.0f}s] UPA: max...')
    upa, upa_tr, upa_crs = load_raster(upa_p)
    upa_on_grid = reproject_to_grid(upa, upa_tr, upa_crs,
                                     labels.shape, gsw_tr, gsw_crs,
                                     resampling=Resampling.max)
    del upa
    gdf['upa_max'] = ndimage.maximum(upa_on_grid, labels=labels, index=valid_index)
    del upa_on_grid
    del labels

    print(f'  → зональные стат завершены за {(time.time()-t0)/60:.1f} мин')

    # ── W3: близость к границе AOI (в EPSG:3576) ──
    print(f'\n[{(time.time()-t0):.0f}s] W3: расстояние до границы AOI...')
    aoi = gpd.read_file(AOI_GEOJSON).to_crs('EPSG:3576')
    aoi_geom = aoi.geometry.iloc[0] if len(aoi) > 0 else aoi.unary_union
    aoi_boundary = aoi_geom.boundary
    gdf['dist_aoi_boundary_m'] = gdf.geometry.distance(aoi_boundary)

    # ── Правила W0/W1/W2/W3 ──
    print(f'\n[{(time.time()-t0):.0f}s] Применение правил...')
    is_river_floodplain = (gdf['hnd_min'] < HND_FLOODPLAIN_MAX) & \
                          (gdf['upa_max'] > UPA_RIVER_MIN)
    is_flooded = gdf['gsw_occ_mean'] > GSW_FLOOD_MIN
    is_lake_shore = (gdf['gsw_occ_max'] > GSW_LAKE_OCC) & \
                    (gdf['gsw_seas_max'] >= GSW_LAKE_SEAS)
    is_marine = gdf['dist_aoi_boundary_m'] < COAST_BUFFER_M

    gdf['littoral_rule'] = 'none'
    gdf['is_littoral'] = 0
    gdf.loc[is_flooded, ['littoral_rule', 'is_littoral']] = ['W0_flooded', 1]
    gdf.loc[is_lake_shore, ['littoral_rule', 'is_littoral']] = ['W2_lake', 1]
    gdf.loc[is_river_floodplain, ['littoral_rule', 'is_littoral']] = ['W1_river', 1]
    gdf.loc[is_marine, ['littoral_rule', 'is_littoral']] = ['W3_marine', 1]

    # ── Сводка ──
    print('')
    print('═══════════════════════════════════════')
    print('РЕЗУЛЬТАТ')
    print('═══════════════════════════════════════')
    total_km2 = gdf['area_km2'].sum()
    for rule in ['W3_marine', 'W1_river', 'W2_lake', 'W0_flooded', 'none']:
        sub = gdf[gdf['littoral_rule'] == rule]
        if len(sub) == 0:
            continue
        a = sub['area_km2'].sum()
        pct = 100 * a / total_km2 if total_km2 > 0 else 0
        label = 'не-отмель (эоловый/антропоген)' if rule == 'none' else rule
        print(f'  {label:30s}: {len(sub):7,} конт. | {a:8.1f} км² | {pct:5.1f}%')

    print(f'\n  ИТОГО:                          {len(gdf):7,} конт. | {total_km2:8.1f} км²')

    n_lit = int(gdf['is_littoral'].sum())
    a_lit = gdf.loc[gdf['is_littoral'] == 1, 'area_km2'].sum()
    print(f'\n  ОТМЕЛЬ (W0+W1+W2+W3): {n_lit:,} конт. | {a_lit:.1f} км² '
          f'({100 * a_lit / total_km2:.1f}%)')

    gdf.to_file(OUTPUT, driver='GPKG', layer='littoral')
    print(f'\nСохранено: {OUTPUT}')
    print(f'Время: {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
