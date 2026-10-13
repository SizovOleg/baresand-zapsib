/**
 * BareSand — Облачная / теневая / снежная маска для Sentinel-2
 *
 * КРИТИЧЕСКИЙ ИНВАРИАНТ (DNA §3.1):
 *   SCL==5 (bare soil) НЕ маскируется — это потенциальный целевой класс.
 *
 * Логика маски:
 *   Облака: SCL in {8, 9, 10} ИЛИ Cloud Probability > порог
 *   Тени:   SCL == 3
 *   Снег:   SCL == 11
 *   Валидно: всё остальное (SCL 4, 5, 6, 7 и прочее)
 *
 * Использование:
 *   var cm = require('users/USERNAME/baresand:gee_scripts/02_cloud_mask');
 *   var masked = cm.maskCloudsSnow(image);
 *   var withBand = cm.addClearMask(image);
 */

// ============================================================================
// КОНФИГУРАЦИЯ (копия порогов из 00_config.js)
// ============================================================================

var CLOUD_PROB_THRESHOLD = 40;  // из CONFIG.CLOUD_PROB_THRESHOLD
var S2_CLOUD_PROB_COLLECTION = 'COPERNICUS/S2_CLOUD_PROBABILITY';

// ============================================================================
// ФУНКЦИИ
// ============================================================================

/**
 * Получить бинарную маску валидных (чистых) пикселей.
 * 1 = чистый, 0 = облако/тень/снег.
 * SCL==5 (bare soil) СОХРАНЯЕТСЯ (DNA §3.1).
 */
function _getClearMask(image) {
  var scl = image.select('SCL');

  // SCL классы для маскирования
  var isCloud = scl.eq(8)     // Cloud medium probability
    .or(scl.eq(9))            // Cloud high probability
    .or(scl.eq(10));          // Thin cirrus

  var isShadow = scl.eq(3);   // Cloud shadow

  var isSnow = scl.eq(11);    // Snow / ice

  // Cloud Probability (отдельная коллекция, join по system:index)
  var cloudProb = ee.ImageCollection(S2_CLOUD_PROB_COLLECTION)
    .filter(ee.Filter.eq('system:index', image.get('system:index')))
    .first();

  // Если Cloud Probability найдена — добавляем к маске
  var isCloudProb = ee.Algorithms.If(
    cloudProb,
    ee.Image(cloudProb).select('probability').gt(CLOUD_PROB_THRESHOLD),
    ee.Image.constant(0)  // если не найдена — не маскируем по вероятности
  );
  isCloudProb = ee.Image(isCloudProb);

  // Итоговая маска: пиксель чистый, если НЕ (облако ИЛИ тень ИЛИ снег ИЛИ высокая prob)
  var bad = isCloud.or(isShadow).or(isSnow).or(isCloudProb);
  var clearMask = bad.not().rename('clear_mask');

  return clearMask;
}

/**
 * Замаскировать облака, тени и снег на сцене S2.
 * SCL==5 (bare soil) сохраняется.
 * @param {ee.Image} image — сцена S2_SR_HARMONIZED
 * @return {ee.Image} — сцена с маской (замаскированные пиксели = transparent)
 */
function maskCloudsSnow(image) {
  var clearMask = _getClearMask(image);
  return image.updateMask(clearMask);
}

/**
 * Добавить бинарный band 'clear_mask' без маскирования пикселей.
 * Для подсчёта clear observations в мультитемпоральном стеке.
 * @param {ee.Image} image — сцена S2
 * @return {ee.Image} — с добавленным band 'clear_mask' (1=clear, 0=masked)
 */
function addClearMask(image) {
  var clearMask = _getClearMask(image);
  return image.addBands(clearMask);
}

// Экспорт
exports.maskCloudsSnow = maskCloudsSnow;
exports.addClearMask = addClearMask;

// ============================================================================
// ТЕСТ: калибровочная сцена Надымских песков
// ============================================================================

// Калибровочная сцена (из CONFIG.CALIBRATION_SCENES.nadym_dunes)
var sceneId = 'COPERNICUS/S2_SR_HARMONIZED/20250810T064641_20250810T064704_T42WXT';
var scene = ee.Image(sceneId);

print('═══════════════════════════════════════');
print('Тест облачной маски — Надымские пески');
print('═══════════════════════════════════════');
print('Сцена:', sceneId);

// ДО маски
Map.addLayer(
  scene,
  {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000},
  'ДО маски — True Color'
);

// ПОСЛЕ маски
var masked = maskCloudsSnow(scene);
Map.addLayer(
  masked,
  {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000},
  'ПОСЛЕ маски — True Color'
);

// Маска как отдельный слой (чёрный = замаскировано, белый = чисто)
var clearMask = _getClearMask(scene);
Map.addLayer(clearMask, {min: 0, max: 1, palette: ['black', 'white']}, 'Clear mask', false);

// Центр на Надымских песках
var sandPoint = ee.Geometry.Point([72.5, 65.5]);
Map.centerObject(sandPoint, 11);
Map.addLayer(sandPoint, {color: 'red'}, 'Контрольная точка (песок)', false);

// Проверка: пиксель песка не замаскирован
var pixelBefore = scene.select(['B4', 'B3', 'B2', 'SCL'])
  .reduceRegion({reducer: ee.Reducer.first(), geometry: sandPoint, scale: 10});
var pixelAfter = masked.select(['B4', 'B3', 'B2'])
  .reduceRegion({reducer: ee.Reducer.first(), geometry: sandPoint, scale: 10});

print('');
print('── Контрольная точка (72.5°E, 65.5°N) ──');
print('ДО маски (B4, B3, B2, SCL):', pixelBefore);
print('ПОСЛЕ маски (B4, B3, B2):', pixelAfter);
print('Если ПОСЛЕ = null → ОШИБКА: песок замаскирован!');

// Процент замаскированных пикселей (в области 50×50 км вокруг точки)
var areaBox = sandPoint.buffer(25000).bounds();
var totalPixels = ee.Image.constant(1).reduceRegion({
  reducer: ee.Reducer.count(), geometry: areaBox, scale: 10, maxPixels: 1e8
}).get('constant');
var clearPixels = clearMask.reduceRegion({
  reducer: ee.Reducer.sum(), geometry: areaBox, scale: 10, maxPixels: 1e8
}).get('clear_mask');
var maskedPercent = ee.Number(1).subtract(
  ee.Number(clearPixels).divide(ee.Number(totalPixels))
).multiply(100);

print('');
print('── Статистика маски (50×50 км вокруг Надыма) ──');
print('Всего пикселей:', totalPixels);
print('Чистых пикселей:', clearPixels);
print('Замаскировано (%):', maskedPercent);
print('Ожидаем < 5% для сцены с облачностью ~0.7%');

// SCL распределение на сцене
var sclHist = scene.select('SCL').reduceRegion({
  reducer: ee.Reducer.frequencyHistogram(),
  geometry: areaBox, scale: 20, maxPixels: 1e8
}).get('SCL');
print('');
print('── Распределение SCL (50×50 км) ──');
print('SCL histogram:', sclHist);
print('Ключ: 3=shadow, 4=veg, 5=bare_soil(!), 6=water, 7=unclass, 8-10=cloud, 11=snow');

print('');
print('✓ Тест завершён');
print('ПРОВЕРЬТЕ: значения ПОСЛЕ маски НЕ null → песок сохранён');
