"""
BareSand — Локальная векторизация растровой мозаики песка.

Вход: 15 тайлов baresand_mask_AOI_v1-*.tif (с Google Drive)
Выход: baresand_contours_v1.gpkg — полигоны (каждый = связный компонент песка)

Логика:
  1. Собрать VRT из 15 тайлов (один логический растр)
  2. Векторизовать по окнам 0.5° с перекрытием
  3. unary_union → разделить → каждый полигон = связная группа песка
  4. Атрибуты формы + MMU фильтр
  5. GeoPackage
"""

import sys
import rasterio
from rasterio.features import shapes
from rasterio.windows import from_bounds
import geopandas as gpd
import numpy as np
from shapely.geometry import shape
from shapely.ops import unary_union
from pathlib import Path
from tqdm import tqdm
import warnings
warnings.filterwarnings('ignore')

# Windows cp1251 → UTF-8 для box-символов и единиц
sys.stdout.reconfigure(encoding='utf-8')

# ════════════════════════════════════════════════════════════════════════════
# НАСТРОЙКИ
# ════════════════════════════════════════════════════════════════════════════

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
VERSION = 'v2'  # синхронизировано с gee_scripts/22_mosaic_export.js
TILES_DIR = EXPORTS / 'baresand_mask'  # сюда пользователь скачивает тайлы из Drive
TILE_GLOB = f'baresand_mask_AOI_{VERSION}-*.tif'
VRT_PATH = TILES_DIR / f'baresand_mask_AOI_{VERSION}.vrt'  # рядом с тайлами для relativeToVRT
OUTPUT_PATH = EXPORTS / f'baresand_contours_{VERSION}.gpkg'

# Размер окна в МЕТРАХ. 50 км → ~5000×5000 px при 10м.
# Если CRS входа градусный (v1), автоматически переводится в градусы по широте.
WINDOW_M = 50_000
OVERLAP_M = 2_000

# MMU: минимальная площадь контура (м²). 9 пикселей по 100 м² = 900 м²
MMU_M2 = 900

# Equal-area проекция для расчёта площади (North Pole LAEA)
EA_CRS = 'EPSG:3576'

# ════════════════════════════════════════════════════════════════════════════
# ШАГ 1: Сборка VRT из тайлов
# ════════════════════════════════════════════════════════════════════════════

print('═══════════════════════════════════════')
print('ВЕКТОРИЗАЦИЯ МАСКИ ПЕСКА')
print('═══════════════════════════════════════')

tiles = sorted(TILES_DIR.glob(TILE_GLOB))
tiles = [t for t in tiles if t.suffix == '.tif']
if not tiles:
    print(f'\n!!! Не найдены тайлы {TILE_GLOB} в {TILES_DIR}')
    exit(1)

print(f'Тайлов маски: {len(tiles)}')

# Сборка VRT через GDAL XML (без внешних зависимостей)
# Читаем метаданные каждого тайла
tile_meta = []
for t in tiles:
    with rasterio.open(t) as src:
        tile_meta.append({
            'path': t.name,
            'bounds': src.bounds,
            'transform': src.transform,
            'width': src.width,
            'height': src.height,
            'crs': src.crs,
            'dtype': src.dtypes[0],
            'nodata': src.nodata,
        })

crs = tile_meta[0]['crs']
res_x = tile_meta[0]['transform'].a
res_y = tile_meta[0]['transform'].e  # отрицательный

# Общие границы
x_min = min(m['bounds'].left for m in tile_meta)
x_max = max(m['bounds'].right for m in tile_meta)
y_min = min(m['bounds'].bottom for m in tile_meta)
y_max = max(m['bounds'].top for m in tile_meta)

vrt_w = int(round((x_max - x_min) / abs(res_x)))
vrt_h = int(round((y_max - y_min) / abs(res_y)))

# Размер окна в единицах CRS: метры или градусы
is_metric = crs.linear_units in ('metre', 'meter')
if is_metric:
    WINDOW = WINDOW_M
    OVERLAP = OVERLAP_M
    unit = 'м'
else:
    # Градусы: 1° по широте ≈ 111 км
    WINDOW = WINDOW_M / 111_000.0
    OVERLAP = OVERLAP_M / 111_000.0
    unit = '°'

print(f'CRS: {crs} ({unit})')

res_str = f'{abs(res_x):.2f}' if is_metric else f'{abs(res_x):.7f}'
print(f'VRT: {vrt_w} x {vrt_h} px, разрешение {res_str} {unit}')
print(f'Границы: {x_min:.3f}, {y_min:.3f} → {x_max:.3f}, {y_max:.3f}')

# Генерация VRT XML
vrt_lines = [
    f'<VRTDataset rasterXSize="{vrt_w}" rasterYSize="{vrt_h}">',
    f'  <SRS>{crs.to_wkt()}</SRS>',
    f'  <GeoTransform>{x_min}, {abs(res_x)}, 0.0, {y_max}, 0.0, {res_y}</GeoTransform>',
    f'  <VRTRasterBand dataType="Byte" band="1">',
    f'    <NoDataValue>0</NoDataValue>',
]
for m in tile_meta:
    # Смещение тайла в пикселях VRT
    x_off = int(round((m['bounds'].left - x_min) / abs(res_x)))
    y_off = int(round((y_max - m['bounds'].top) / abs(res_y)))
    vrt_lines.append(f'    <SimpleSource>')
    vrt_lines.append(f'      <SourceFilename relativeToVRT="1">{m["path"]}</SourceFilename>')
    vrt_lines.append(f'      <SourceBand>1</SourceBand>')
    vrt_lines.append(f'      <SrcRect xOff="0" yOff="0" xSize="{m["width"]}" ySize="{m["height"]}"/>')
    vrt_lines.append(f'      <DstRect xOff="{x_off}" yOff="{y_off}" xSize="{m["width"]}" ySize="{m["height"]}"/>')
    vrt_lines.append(f'    </SimpleSource>')
vrt_lines.append('  </VRTRasterBand>')
vrt_lines.append('</VRTDataset>')

VRT_PATH.write_text('\n'.join(vrt_lines), encoding='utf-8')
print(f'VRT собран: {VRT_PATH.name}')

# ════════════════════════════════════════════════════════════════════════════
# ШАГ 2: Векторизация по окнам
# ════════════════════════════════════════════════════════════════════════════

x_starts = np.arange(x_min, x_max, WINDOW)
y_starts = np.arange(y_min, y_max, WINDOW)
total_windows = len(x_starts) * len(y_starts)
print(f'\nОкон: {len(x_starts)} x {len(y_starts)} = {total_windows}')
print('Векторизация...')

all_polys = []

with rasterio.open(VRT_PATH) as src:
    for wx in tqdm(x_starts, desc='Столбцы'):
        for wy in y_starts:
            # Окно с перекрытием
            left = max(wx - OVERLAP, x_min)
            bottom = max(wy - OVERLAP, y_min)
            right = min(wx + WINDOW + OVERLAP, x_max)
            top = min(wy + WINDOW + OVERLAP, y_max)

            try:
                window = from_bounds(left, bottom, right, top, src.transform)
                data = src.read(1, window=window)
            except Exception:
                continue

            if data.size == 0 or data.max() == 0:
                continue

            win_transform = src.window_transform(window)
            for geom, val in shapes(data, mask=(data > 0), transform=win_transform):
                if val == 1:
                    all_polys.append(shape(geom))

print(f'Полигонов до объединения: {len(all_polys)}')

# ════════════════════════════════════════════════════════════════════════════
# ШАГ 3: Объединение швов (полигоны через границы окон → один компонент)
# ════════════════════════════════════════════════════════════════════════════

print('Объединение полигонов на швах окон...')
merged = unary_union(all_polys)

# Разделить мультиполигон на отдельные связные компоненты
if merged.geom_type == 'Polygon':
    components = [merged]
else:
    components = list(merged.geoms)

print(f'Связных компонентов: {len(components)}')

# ════════════════════════════════════════════════════════════════════════════
# ШАГ 4: Атрибуты + MMU фильтр
# ════════════════════════════════════════════════════════════════════════════

gdf = gpd.GeoDataFrame(geometry=components, crs=crs)

# Площадь и периметр в equal-area проекции
gdf_ea = gdf.to_crs(EA_CRS)
gdf['area_m2'] = gdf_ea.geometry.area
gdf['perimeter_m'] = gdf_ea.geometry.length

# MMU фильтр
before = len(gdf)
gdf = gdf[gdf['area_m2'] >= MMU_M2].copy()
print(f'MMU фильтр ({MMU_M2} м²): {before} → {len(gdf)}')

# Атрибуты формы
gdf['area_ha'] = gdf['area_m2'] / 1e4
gdf['area_km2'] = gdf['area_m2'] / 1e6
# Компактность: 4πA/P² (1.0 = круг, → 0 вытянутые/изрезанные)
gdf['compactness'] = 4 * np.pi * gdf['area_m2'] / (gdf['perimeter_m'] ** 2)
gdf['compactness'] = gdf['compactness'].clip(0, 1)
gdf['centroid_lon'] = gdf.geometry.centroid.x
gdf['centroid_lat'] = gdf.geometry.centroid.y
gdf['id'] = range(1, len(gdf) + 1)

gdf = gdf[['id', 'area_ha', 'area_km2', 'perimeter_m', 'compactness',
           'centroid_lon', 'centroid_lat', 'geometry']]

# ════════════════════════════════════════════════════════════════════════════
# ШАГ 5: Статистика + экспорт
# ════════════════════════════════════════════════════════════════════════════

total_km2 = gdf['area_km2'].sum()
print('')
print('═══════════════════════════════════════')
print('РЕЗУЛЬТАТ')
print('═══════════════════════════════════════')
print(f'Контуров: {len(gdf)}')
print(f'Общая площадь: {total_km2:.1f} км²')
print(f'Мин: {gdf["area_ha"].min():.2f} га | Макс: {gdf["area_ha"].max():.1f} га '
      f'| Медиана: {gdf["area_ha"].median():.2f} га')

print('\nТоп-15 крупнейших:')
top = gdf.nlargest(15, 'area_ha')[['id', 'area_ha', 'centroid_lon', 'centroid_lat']]
print(top.to_string(index=False))

gdf.to_file(OUTPUT_PATH, driver='GPKG', layer='contours')
print(f'\nСохранено: {OUTPUT_PATH}')
print(f'Размер: {OUTPUT_PATH.stat().st_size / 1e6:.1f} МБ')
print('Готово!')
