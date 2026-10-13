"""
BareSand — Проверка ассетов перед запуском мозаики.

Список тайлов в gee_scripts/22_mosaic_export.js — синхронен с реальными
экспортами или нет? Если хоть один из 128 ассетов отсутствует,
ImageCollection.fromImages(...).qualityMosaic(...) упадёт на reduce.

Скрипт:
  1. Получить реальный список ассетов в PROJECT через ee.data.listAssets
  2. Сравнить с PROCESSED_TILES (захардкожен ниже, должен совпадать с JS)
  3. Распечатать: MISSING (нет ассета), EXTRA (есть ассет, нет в JS-списке)
  4. (опц.) Сгенерировать актуальный JS-блок для копи-пейста в 22_mosaic_export.js

Запуск:
  python python/22_check_mosaic_assets.py
"""

import sys
import ee

# Windows cp1251 → UTF-8 для box-символов
sys.stdout.reconfigure(encoding='utf-8')

PROJECT = 'projects/nodal-thunder-481307-u1/assets/ZapSib_baresands'

# Список из gee_scripts/22_mosaic_export.js — синхронизировать с JS
PROCESSED_TILES = [
    '41VPK_', '41VPL_',
    '41WPQ_', '41WPR_', '41WPT_', '41WPU_', '41WPV_', '41XPA_',
    '42VUQ_', '42VUR_',
    '42VVP_', '42VVQ_', '42VVR_',
    '42VWP_', '42VWQ_', '42VWR_',
    '42VXP_', '42VXQ_', '42VXR_',
    '42WVA_', '42WVB_', '42WVC__', '42WVD_', '42WVE_',  # 42WVC__: имя ассета с двойным _
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

ASSET_PREFIX = 'baresand_mask_'


def main() -> None:
    ee.Initialize()

    print('═══════════════════════════════════════')
    print('ПРОВЕРКА АССЕТОВ МОЗАИКИ')
    print('═══════════════════════════════════════')
    print(f'PROJECT: {PROJECT}')
    print(f'Ожидается тайлов в JS: {len(PROCESSED_TILES)}')

    # Реальный список ассетов в проекте
    try:
        result = ee.data.listAssets({'parent': PROJECT})
    except Exception as e:
        print(f'\n!!! Ошибка ee.data.listAssets: {e}')
        return

    assets = result.get('assets', [])
    # Обработка пагинации
    while 'nextPageToken' in result:
        result = ee.data.listAssets({
            'parent': PROJECT,
            'pageToken': result['nextPageToken']
        })
        assets.extend(result.get('assets', []))

    # Имена только baresand_mask_*
    real_names = set()
    for a in assets:
        short = a['id'].split('/')[-1]
        if short.startswith(ASSET_PREFIX):
            tile = short[len(ASSET_PREFIX):]
            real_names.add(tile)

    print(f'Найдено в проекте: {len(real_names)} ассетов с префиксом {ASSET_PREFIX}')

    expected = set(PROCESSED_TILES)
    missing = sorted(expected - real_names)   # есть в JS, нет в проекте → ПАДЕНИЕ
    extra = sorted(real_names - expected)     # есть в проекте, нет в JS → потерянные данные

    print('')
    if missing:
        print(f'!!! MISSING ({len(missing)}) — мозаика упадёт:')
        for t in missing:
            print(f'    {ASSET_PREFIX}{t}')
    else:
        print('✓ Нет MISSING — все 128 ассетов на месте')

    print('')
    if extra:
        print(f'⚠ EXTRA ({len(extra)}) — ассет есть, но не используется в мозаике:')
        for t in extra:
            print(f'    {ASSET_PREFIX}{t}')
    else:
        print('✓ Нет EXTRA — список синхронен')

    # Готовый JS-блок: только реально существующие тайлы из PROCESSED_TILES
    actual = sorted(expected & real_names)
    print('')
    print('═══════════════════════════════════════')
    print(f'АКТУАЛЬНЫЙ СПИСОК ДЛЯ JS ({len(actual)} тайлов):')
    print('═══════════════════════════════════════')
    quoted = [f"'{t}'" for t in actual]
    # По 5 на строку, как в JS-файле
    for i in range(0, len(quoted), 5):
        print('  ' + ', '.join(quoted[i:i + 5]) + ',')


if __name__ == '__main__':
    main()
