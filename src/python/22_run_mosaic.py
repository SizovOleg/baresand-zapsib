"""
BareSand — Запуск мозаики (Python-вариант gee_scripts/22_mosaic_export.js).

Стартует 2 GEE Task'а:
  1. Asset:  baresand_mask_AOI_v2 в проектную папку
  2. Drive:  baresand_mask_AOI_v2-*.tif в Google Drive/baresand_exports/

Запуск:
  python python/22_run_mosaic.py

После запуска: Tasks работают на сервере GEE (1–3 часа). Проверка статуса:
  python python/22_run_mosaic.py --status
"""

import sys
import argparse
import ee

sys.stdout.reconfigure(encoding='utf-8')

# ════════════════════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ (синхронизирована с gee_scripts/22_mosaic_export.js)
# ════════════════════════════════════════════════════════════════════════════

PROJECT = 'projects/nodal-thunder-481307-u1/assets/ZapSib_baresands'
AOI_ASSET = PROJECT + '/baresand_aoi_v2'

VERSION = 'v2'

# LAEA North Pole — equal-area для арктики, без артефактов на стыках UTM-зон.
TARGET_CRS = 'EPSG:3576'
TARGET_SCALE = 10

PROCESSED_TILES = [
    '41VPK_', '41VPL_',
    '41WPQ_', '41WPR_', '41WPT_', '41WPU_', '41WPV_', '41XPA_',
    '42VUQ_', '42VUR_',
    '42VVP_', '42VVQ_', '42VVR_',
    '42VWP_', '42VWQ_', '42VWR_',
    '42VXP_', '42VXQ_', '42VXR_',
    '42WVA_', '42WVB_', '42WVC__', '42WVD_', '42WVE_',  # 42WVC__: двойное _ в реальном имени
    '42WVS_', '42WVT_', '42WVU_', '42WVV_',
    '42WWA_', '42WWB_', '42WWC_', '42WWD_', '42WWE_',
    '42WWS_', '42WWT_', '42WWU_', '42WWV_',
    '42WXA_', '42WXB_', '42WXC_', '42WXD_', '42WXE_',
    '42WXS_', '42WXT_', '42WXU_', '42WXV_',
    '42XVF_', '42XWF_', '42XWG_', '42XXF_',
    '43VCJ_', '43VCK_', '43VCL_', '43VDJ_', '43VDK_', '43VDL_',
    '43VEJ_', '43VEK_', '43VEL_',
    '43VFJ_', '43VFK_', '43VFL_',
    '43WDM_', '43WDN_', '43WDP_', '43WDQ_', '43WDR_', '43WDS_', '43WDT_', '43WDU_', '43WDV_',
    '43WEM_', '43WEN_', '43WEP_', '43WEQ_', '43WER_', '43WES_', '43WET_', '43WEU_', '43WEV_',
    '43WFM_', '43WFN_', '43WFP_', '43WFQ_', '43WFR_', '43WFS_', '43WFT_', '43WFU_', '43WFV_',
    '43XDA_', '43XEA_', '43XFA_',
    '44VLP_', '44VLQ_', '44VLR_', '44VMP_', '44VMQ_', '44VMR_',
    '44VNP_', '44VNQ_', '44VNR_',
    '44VPP_', '44VPQ_', '44VPR_',
    '44WMA_', '44WMB_', '44WMC_', '44WMD_', '44WME_', '44WMS_', '44WMT_', '44WMU_', '44WMV_',
    '44WNA_', '44WNB_', '44WNC_', '44WND_', '44WNE_', '44WNS_', '44WNT_', '44WNU_', '44WNV_',
    '44WPA_', '44WPB_', '44WPC_', '44WPS_',
    '45WVQ_', '45WVR_',
]

TASK_DESCRIPTIONS = (f'baresand_mask_AOI_{VERSION}', f'baresand_mask_AOI_tiff_{VERSION}')


# ════════════════════════════════════════════════════════════════════════════
# ПОСТРОЕНИЕ МОЗАИКИ
# ════════════════════════════════════════════════════════════════════════════

def build_mosaic() -> tuple[ee.Image, ee.Geometry]:
    """Собрать мозаику. Возвращает (mosaic_export_image, aoi_geometry)."""
    aoi = ee.FeatureCollection(AOI_ASSET).geometry()

    # Каждый тайл: только sand_mask, selfMask (0 → masked), reproject в LAEA
    mask_list = [
        ee.Image(f'{PROJECT}/baresand_mask_{tile}')
        .select('sand_mask')
        .selfMask()
        .reproject(crs=TARGET_CRS, scale=TARGET_SCALE)
        for tile in PROCESSED_TILES
    ]
    mask_collection = ee.ImageCollection.fromImages(mask_list)

    # Тривиальная мозаика: 1 где песок в любом тайле, masked иначе
    mosaic = mask_collection.mosaic().clip(aoi)

    # unmask(0) для GeoTIFF-совместимости
    mosaic_export = mosaic.unmask(0).toByte()
    return mosaic_export, aoi


# ════════════════════════════════════════════════════════════════════════════
# ЗАПУСК ТАСКОВ
# ════════════════════════════════════════════════════════════════════════════

def start_exports() -> None:
    print('═══════════════════════════════════════')
    print('ЗАПУСК МОЗАИКИ (Python)')
    print('═══════════════════════════════════════')
    print(f'PROJECT: {PROJECT}')
    print(f'VERSION: {VERSION}')
    print(f'CRS: {TARGET_CRS} (LAEA North Pole)')
    print(f'Тайлов: {len(PROCESSED_TILES)}')

    mosaic_export, aoi = build_mosaic()

    # 1. Asset
    task_asset = ee.batch.Export.image.toAsset(
        image=mosaic_export,
        description=TASK_DESCRIPTIONS[0],
        assetId=f'{PROJECT}/baresand_mask_AOI_{VERSION}',
        region=aoi,
        scale=TARGET_SCALE,
        crs=TARGET_CRS,
        maxPixels=int(1e13),
    )
    task_asset.start()
    print(f'\n✓ Task запущен: {TASK_DESCRIPTIONS[0]} (id={task_asset.id})')

    # 2. Drive (GeoTIFF)
    task_drive = ee.batch.Export.image.toDrive(
        image=mosaic_export,
        description=TASK_DESCRIPTIONS[1],
        folder='baresand_exports',
        fileNamePrefix=f'baresand_mask_AOI_{VERSION}',
        region=aoi,
        scale=TARGET_SCALE,
        crs=TARGET_CRS,
        maxPixels=int(1e13),
        formatOptions={'cloudOptimized': True},
    )
    task_drive.start()
    print(f'✓ Task запущен: {TASK_DESCRIPTIONS[1]} (id={task_drive.id})')

    print('')
    print('Tasks работают на сервере GEE (обычно 1–3 часа на 750 000 км² × 10м).')
    print('Проверка статуса:  python python/22_run_mosaic.py --status')
    print(f'После завершения: скачать GeoTIFF из Drive/baresand_exports/{VERSION}/')
    print('Затем:            python python/30_vectorize_local.py')


# ════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКА СТАТУСА
# ════════════════════════════════════════════════════════════════════════════

def show_status() -> None:
    print('═══════════════════════════════════════')
    print('СТАТУС TASK\'ОВ')
    print('═══════════════════════════════════════')
    statuses = ee.data.getTaskList()
    relevant = [
        s for s in statuses
        if s.get('description', '') in TASK_DESCRIPTIONS
    ]
    if not relevant:
        print('Не найдено task\'ов с описанием:', TASK_DESCRIPTIONS)
        return

    for s in relevant[:10]:  # обычно последние первые
        desc = s.get('description', '')
        state = s.get('state', '')
        ts_creation = s.get('creation_timestamp_ms', 0) // 1000
        ts_update = s.get('update_timestamp_ms', 0) // 1000
        elapsed = (ts_update - ts_creation) // 60 if ts_creation else 0
        print(f'  {desc}: {state} (elapsed: {elapsed} мин)')


# ════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--status', action='store_true', help='Показать статус task\'ов')
    args = parser.parse_args()

    ee.Initialize()

    if args.status:
        show_status()
    else:
        start_exports()


if __name__ == '__main__':
    main()
