"""
BareSand — Скачивание вспомогательных слоёв из GEE для локальной атрибуции генезиса.

Слои (все в EPSG:4326, 30м):
  1. hnd_AOI.tif         — height above nearest drainage (MERIT, 90м→30м)
  2. upa_AOI.tif         — upstream drainage area (MERIT, 90м→30м)
  3. gsw_occurrence_AOI.tif    — частота воды (JRC GSW, 30м)
  4. gsw_seasonality_AOI.tif   — сезонность воды (JRC GSW, 30м)
  5. landsat_1985_brightness.tif — для антропогена (LT05, 30м)
  6. aoi_boundary.tif    — растеризованная граница AOI (30м)

После запуска:
  - 6 задач уйдёт в GEE Tasks
  - Подождать завершения (~20-40 мин)
  - Файлы появятся на Google Drive в папке baresand_exports/
  - Скачать вручную в D:\\test\\baresand_zapsib\\exports\\
"""

import ee
import time

ee.Initialize(project='nodal-thunder-481307-u1')

# ════════════════════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ════════════════════════════════════════════════════════════════════════════

PROJECT = 'projects/nodal-thunder-481307-u1/assets/ZapSib_baresands'
AOI = ee.FeatureCollection(PROJECT + '/baresand_aoi_v2').geometry()
DRIVE_FOLDER = 'baresand_exports'

# Разрешения по слоям (нативные где возможно, 10м для слоёв нужных в полной детальности)
SCALE_MERIT = 90      # HND, UPA — нативное MERIT
SCALE_GSW = 30        # GSW — нативное JRC
SCALE_LANDSAT = 30    # Landsat — нативное
SCALE_BOUNDARY = 10   # граница AOI — для точного совпадения с маской песка 10м

tasks = []

# ════════════════════════════════════════════════════════════════════════════
# 1. HND — height above nearest drainage (MERIT Hydro)
# ════════════════════════════════════════════════════════════════════════════

print('1. HND (MERIT Hydro)...')
hnd = ee.Image('MERIT/Hydro/v1_0_1').select('hnd').clip(AOI)

t1 = ee.batch.Export.image.toDrive(
    image=hnd.toFloat(),
    description='hnd_AOI',
    folder=DRIVE_FOLDER,
    fileNamePrefix='hnd_AOI',
    region=AOI,
    scale=SCALE_MERIT,
    maxPixels=int(1e12),
    crs='EPSG:4326',
    formatOptions={'cloudOptimized': True}
)
t1.start()
tasks.append(('hnd', t1))
print(f'   → запущено')

# ════════════════════════════════════════════════════════════════════════════
# 2. UPA — upstream drainage area (MERIT Hydro)
# ════════════════════════════════════════════════════════════════════════════

print('2. UPA (MERIT Hydro)...')
upa = ee.Image('MERIT/Hydro/v1_0_1').select('upa').clip(AOI)

t2 = ee.batch.Export.image.toDrive(
    image=upa.toFloat(),
    description='upa_AOI',
    folder=DRIVE_FOLDER,
    fileNamePrefix='upa_AOI',
    region=AOI,
    scale=SCALE_MERIT,
    maxPixels=int(1e12),
    crs='EPSG:4326',
    formatOptions={'cloudOptimized': True}
)
t2.start()
tasks.append(('upa', t2))
print(f'   → запущено')

# ════════════════════════════════════════════════════════════════════════════
# 3. GSW occurrence
# ════════════════════════════════════════════════════════════════════════════

print('3. GSW occurrence...')
gsw_occ = ee.Image('JRC/GSW1_4/GlobalSurfaceWater').select('occurrence').clip(AOI)

t3 = ee.batch.Export.image.toDrive(
    image=gsw_occ.toByte(),
    description='gsw_occurrence_AOI',
    folder=DRIVE_FOLDER,
    fileNamePrefix='gsw_occurrence_AOI',
    region=AOI,
    scale=SCALE_GSW,
    maxPixels=int(1e12),
    crs='EPSG:4326',
    formatOptions={'cloudOptimized': True}
)
t3.start()
tasks.append(('gsw_occurrence', t3))
print(f'   → запущено')

# ════════════════════════════════════════════════════════════════════════════
# 4. GSW seasonality
# ════════════════════════════════════════════════════════════════════════════

print('4. GSW seasonality...')
gsw_sea = ee.Image('JRC/GSW1_4/GlobalSurfaceWater').select('seasonality').clip(AOI)

t4 = ee.batch.Export.image.toDrive(
    image=gsw_sea.toByte(),
    description='gsw_seasonality_AOI',
    folder=DRIVE_FOLDER,
    fileNamePrefix='gsw_seasonality_AOI',
    region=AOI,
    scale=SCALE_GSW,
    maxPixels=int(1e12),
    crs='EPSG:4326',
    formatOptions={'cloudOptimized': True}
)
t4.start()
tasks.append(('gsw_seasonality', t4))
print(f'   → запущено')

# ════════════════════════════════════════════════════════════════════════════
# 5. Landsat 5 медиана 1984-1995 (яркость для антропогена)
# ════════════════════════════════════════════════════════════════════════════

print('5. Landsat 1984-1995 brightness...')
landsat = (ee.ImageCollection('LANDSAT/LT05/C02/T1_L2')
    .filterBounds(AOI)
    .filterDate('1984-06-01', '1995-09-30')
    .filter(ee.Filter.calendarRange(7, 9, 'month'))
    .map(lambda img: img.select(['SR_B1','SR_B2','SR_B3','SR_B4'])
         .multiply(0.0000275).add(-0.2).multiply(10000))
)
landsat_median = landsat.median().clip(AOI)
brightness_old = (landsat_median.select('SR_B1')
    .add(landsat_median.select('SR_B2'))
    .add(landsat_median.select('SR_B3'))
    .add(landsat_median.select('SR_B4'))
    .divide(4).rename('brightness_1985'))

t5 = ee.batch.Export.image.toDrive(
    image=brightness_old.toFloat(),
    description='landsat_1985_brightness',
    folder=DRIVE_FOLDER,
    fileNamePrefix='landsat_1985_brightness',
    region=AOI,
    scale=SCALE_LANDSAT,
    maxPixels=int(1e12),
    crs='EPSG:4326',
    formatOptions={'cloudOptimized': True}
)
t5.start()
tasks.append(('landsat_1985', t5))
print(f'   → запущено')

# ════════════════════════════════════════════════════════════════════════════
# 6. Граница AOI как растр (для литорали)
# ════════════════════════════════════════════════════════════════════════════

print('6. AOI boundary raster...')
aoi_fc = ee.FeatureCollection(PROJECT + '/baresand_aoi_v2')
# Линия границы → паинтинг на растр
aoi_boundary = (ee.Image()
    .byte()
    .paint(aoi_fc, 0, 1)  # ширина линии = 1 пиксель
    .clip(AOI)
    .unmask(0)
    .rename('boundary'))

t6 = ee.batch.Export.image.toDrive(
    image=aoi_boundary.toByte(),
    description='aoi_boundary',
    folder=DRIVE_FOLDER,
    fileNamePrefix='aoi_boundary',
    region=AOI,
    scale=SCALE_BOUNDARY,
    maxPixels=int(1e12),
    crs='EPSG:4326',
    formatOptions={'cloudOptimized': True}
)
t6.start()
tasks.append(('aoi_boundary', t6))
print(f'   → запущено')

# ════════════════════════════════════════════════════════════════════════════
# Статусы задач
# ════════════════════════════════════════════════════════════════════════════

print(f'\nЗапущено {len(tasks)} задач в GEE.')
print('Мониторинг (Ctrl+C для прерывания)...')
print()

while True:
    all_done = True
    for name, t in tasks:
        s = t.status()['state']
        if s in ('READY', 'RUNNING'):
            all_done = False
        print(f'  {name:25s} {s}')
    if all_done:
        break
    print('  ─' * 15)
    time.sleep(30)

print('\nВсе задачи завершены!')
print(f'Файлы на Google Drive: {DRIVE_FOLDER}/')
print('Скачай в D:\\test\\baresand_zapsib\\exports\\')
