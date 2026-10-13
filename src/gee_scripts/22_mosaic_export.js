/**
 * BareSand — Сшивка масок AOI (Фаза 2, финал)
 *
 * Запускается ПОСЛЕ обработки всех тайлов через 21_production_classify.js.
 * Собирает тайловые маски из Assets → мозаика → растровый экспорт.
 * Векторизация — локально через python/30_vectorize_local.py.
 *
 * ПРЕД-РЕКВИЗИТ: запустить python/22_check_mosaic_assets.py.
 *   - сверяет список PROCESSED_TILES с реально существующими ассетами
 *   - если хоть один ассет отсутствует → ImageCollection.fromImages
 *     ломается на reduce. Скрипт печатает MISSING и актуальный список.
 *
 * Логика мозаики (без quality-эвристик)
 * ──────────────────────────────────────
 * 1. В тайлах после 21_production_classify.js значения 0/1 (после .unmask(0)).
 *    Применяем .selfMask() на каждый тайл → 0 становится masked, остаются
 *    только пиксели песка (=1).
 * 2. Все тайлы репроецируются в единую проекцию EPSG:3576 (LAEA, North Pole)
 *    — equal-area, оптимальна для арктики, без артефактов на стыках UTM-зон
 *    41–45 N. Та же проекция используется в python/30_vectorize_local.py.
 * 3. .mosaic() тривиально берёт 1 там, где она есть хоть в одном тайле.
 *    В зоне перекрытия двух тайлов: оба = 1 → результат 1. Один = 1, второй
 *    masked → 1. Оба masked → masked.
 *
 * Семантика: финальная маска показывает «песок ≥ хотя бы в одном наблюдении».
 * Это смещает результат к полноте (Producer's accuracy) — приоритет DNA §4.1.
 */

// ════════════════════════════════════════════════════════════════════════════
// КОНФИГУРАЦИЯ
// ════════════════════════════════════════════════════════════════════════════

var PROJECT = 'projects/nodal-thunder-481307-u1/assets/ZapSib_baresands';
var AOI_ASSET = PROJECT + '/baresand_aoi_v2';
var aoi = ee.FeatureCollection(AOI_ASSET).geometry();

var VERSION = 'v2';

// Единая проекция мозаики: LAEA North Pole — equal-area для арктики,
// без артефактов на стыках UTM-зон 41–45N. Та же CRS в python/30_vectorize_local.py.
var TARGET_CRS = 'EPSG:3576';
var TARGET_SCALE = 10;

// 128 масок (финальные, с _ суффиксом)
var PROCESSED_TILES = [
  '41VPK_','41VPL_',
  '41WPQ_','41WPR_','41WPT_','41WPU_','41WPV_','41XPA_',
  '42VUQ_','42VUR_',
  '42VVP_','42VVQ_','42VVR_',
  '42VWP_','42VWQ_','42VWR_',
  '42VXP_','42VXQ_','42VXR_',
  '42WVA_','42WVB_','42WVC__','42WVD_','42WVE_',  // 42WVC__ — реальное имя ассета (двойное _ при экспорте)
  '42WVS_','42WVT_','42WVU_','42WVV_',
  '42WWA_','42WWB_','42WWC_','42WWD_','42WWE_',
  '42WWS_','42WWT_','42WWU_','42WWV_',
  '42WXA_','42WXB_','42WXC_','42WXD_','42WXE_',
  '42WXS_','42WXT_','42WXU_','42WXV_',
  '42XVF_','42XWF_','42XWG_','42XXF_',
  '43VCJ_','43VCK_','43VCL_','43VDJ_','43VDK_','43VDL_',
  '43VEJ_','43VEK_','43VEL_',
  '43VFJ_','43VFK_','43VFL_',
  '43WDM_','43WDN_','43WDP_','43WDQ_','43WDR_','43WDS_','43WDT_','43WDU_','43WDV_',
  '43WEM_','43WEN_','43WEP_','43WEQ_','43WER_','43WES_','43WET_','43WEU_','43WEV_',
  '43WFM_','43WFN_','43WFP_','43WFQ_','43WFR_','43WFS_','43WFT_','43WFU_','43WFV_',
  '43XDA_','43XEA_','43XFA_',
  '44VLP_','44VLQ_','44VLR_','44VMP_','44VMQ_','44VMR_',
  '44VNP_','44VNQ_','44VNR_',
  '44VPP_','44VPQ_','44VPR_',
  '44WMA_','44WMB_','44WMC_','44WMD_','44WME_','44WMS_','44WMT_','44WMU_','44WMV_',
  '44WNA_','44WNB_','44WNC_','44WND_','44WNE_','44WNS_','44WNT_','44WNU_','44WNV_',
  '44WPA_','44WPB_','44WPC_','44WPS_',
  '45WVQ_','45WVR_'
];

// ════════════════════════════════════════════════════════════════════════════
// ЗАГРУЗКА МАСОК
// ════════════════════════════════════════════════════════════════════════════

print('═══════════════════════════════════════');
print('СШИВКА МАСОК AOI');
print('═══════════════════════════════════════');
print('Тайлов к сшивке:', PROCESSED_TILES.length);
print('CRS мозаики:', TARGET_CRS, '(LAEA North Pole)');

// ════════════════════════════════════════════════════════════════════════════
// ЗАГРУЗКА + НОРМАЛИЗАЦИЯ
// ════════════════════════════════════════════════════════════════════════════

// Каждый тайл: оставить только sand_mask, .selfMask() убирает «0 = не-песок»
// (включая псевдо-0 от облаков), .reproject() приводит к единой LAEA.
var maskList = PROCESSED_TILES.map(function(tile) {
  return ee.Image(PROJECT + '/baresand_mask_' + tile)
    .select('sand_mask')
    .selfMask()
    .reproject({crs: TARGET_CRS, scale: TARGET_SCALE});
});

var maskCollection = ee.ImageCollection.fromImages(maskList);
print('Загружено масок:', maskCollection.size());

// ════════════════════════════════════════════════════════════════════════════
// МОЗАИКА
// ════════════════════════════════════════════════════════════════════════════

// Тривиально: 1 если песок в любом тайле, masked иначе.
// В зоне перекрытия двух тайлов оба = 1 → 1. Один = masked → берём 1 соседа.
var mosaic = maskCollection.mosaic();
var mosaicClipped = mosaic.clip(aoi);

print('✓ Мозаика собрана (selfMask + mosaic, без quality-эвристик)');

// ════════════════════════════════════════════════════════════════════════════
// ПЛОЩАДЬ (sanity check)
// ════════════════════════════════════════════════════════════════════════════
//
// Считаем на scale=10 (родное разрешение S2 + маски). bestEffort убран:
// на 750 000 км² результат должен быть честным, не огрублённым.
// При нехватке памяти GEE — увеличить tileScale до 8/16, не включать bestEffort.

// pixelArea вычисляется в той же LAEA — equal-area, без полярных искажений.
var totalArea = mosaicClipped.multiply(ee.Image.pixelArea()).reduceRegion({
  reducer: ee.Reducer.sum(),
  geometry: aoi,
  scale: TARGET_SCALE,
  crs: TARGET_CRS,
  maxPixels: 1e13,
  tileScale: 8
});
var totalKm2 = ee.Number(totalArea.get('sand_mask')).divide(1e6);

print('');
print('══════════════════════════════════');
print('ОБЩАЯ ПЛОЩАДЬ ПЕСКА AOI:', totalKm2, 'км² (LAEA, scale=10)');
print('══════════════════════════════════');

// Векторизация вынесена в python/30_vectorize_local.py:
//   - reduceToVectors с bestEffort на 750 000 км² автоматически огрубляет
//     результат под maxPixels — мелкие контуры теряются
//   - локальная векторизация поверх GeoTIFF через rasterio.features.shapes
//     + unary_union на швах окон — точнее и воспроизводимо

// ════════════════════════════════════════════════════════════════════════════
// ЭКСПОРТ (только растр; векторизация — в python/30_vectorize_local.py)
// ════════════════════════════════════════════════════════════════════════════

print('');
print('── Экспорт (зарегистрировано в Tasks) ──');

// Финальный экспорт: байтовая 1/0 (selfMask → unmask(0) для GeoTIFF-совместимости),
// в EPSG:3576, scale=10. Тот же CRS для Asset и Drive — единообразие с векторизацией.

var mosaicExport = mosaicClipped.unmask(0).toByte();

// 1. Растровая мозаика → Asset
Export.image.toAsset({
  image: mosaicExport,
  description: 'baresand_mask_AOI_' + VERSION,
  assetId: PROJECT + '/baresand_mask_AOI_' + VERSION,
  region: aoi,
  scale: TARGET_SCALE,
  crs: TARGET_CRS,
  maxPixels: 1e13
});
print('  1. Asset: baresand_mask_AOI_' + VERSION + ' (' + TARGET_CRS + ')');

// 2. Растровая мозаика → GeoTIFF на Drive (вход для python/30_vectorize_local.py)
Export.image.toDrive({
  image: mosaicExport,
  description: 'baresand_mask_AOI_tiff_' + VERSION,
  folder: 'baresand_exports',
  fileNamePrefix: 'baresand_mask_AOI_' + VERSION,
  region: aoi,
  scale: TARGET_SCALE,
  crs: TARGET_CRS,
  maxPixels: 1e13,
  formatOptions: {cloudOptimized: true}
});
print('  2. GeoTIFF → Drive/baresand_exports/ (' + TARGET_CRS + ')');

// ════════════════════════════════════════════════════════════════════════════
// ВИЗУАЛИЗАЦИЯ
// ════════════════════════════════════════════════════════════════════════════

Map.setOptions('SATELLITE');
Map.centerObject(aoi, 5);

Map.addLayer(ee.Image().paint(ee.FeatureCollection([ee.Feature(aoi)]), 0, 2),
  {palette: ['FF0000']}, 'AOI', true, 0.5);
Map.addLayer(mosaicClipped, {palette: ['FFD700']},
  'ПЕСОК (мозаика)', true, 0.7);

print('');
print('✓ Сшивка завершена');
print('→ Tasks tab → Run обоих экспортов');
print('→ После загрузки GeoTIFF: python python/30_vectorize_local.py');
