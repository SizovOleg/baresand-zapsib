/**
 * BareSand — Спектральные индексы и стек признаков
 *
 * Расчёт всех индексов, GLCM-текстур, сборка стека для RF.
 * Формулы из DNA / CLAUDE.md — не менять.
 *
 * Использование:
 *   var si = require('users/USERNAME/baresand:gee_scripts/03_spectral_indices');
 *   var withIndices = si.addSpectralIndices(maskedScene);
 *   var stack = si.buildFeatureStack(maskedScene, 'C');
 */

// ============================================================================
// СПЕКТРАЛЬНЫЕ ИНДЕКСЫ
// ============================================================================

/**
 * Рассчитать все спектральные индексы для сцены.
 * @param {ee.Image} image — сцена S2 (после облачной маски)
 * @return {ee.Image} — исходные каналы + все индексы как дополнительные bands
 */
function addSpectralIndices(image) {
  // Базовые каналы
  var B2  = image.select('B2');   // Blue
  var B3  = image.select('B3');   // Green
  var B4  = image.select('B4');   // Red
  var B8  = image.select('B8');   // NIR

  // --- Индексы для всех треков (A, B, C) ---
  var NDVI = B8.subtract(B4).divide(B8.add(B4)).rename('NDVI');
  var NDWI = B3.subtract(B8).divide(B3.add(B8)).rename('NDWI');
  var Brightness = B2.add(B3).add(B4).add(B8).divide(4).rename('Brightness');

  // Трек A: дополнительные индексы из 4 каналов
  var MNDSI = B4.subtract(B2).divide(B4.add(B2)).rename('MNDSI');
  var B4_B3 = B4.divide(B3).rename('B4_B3');

  var result = image
    .addBands(NDVI)
    .addBands(NDWI)
    .addBands(Brightness)
    .addBands(MNDSI)
    .addBands(B4_B3);

  // --- Индексы для треков B и C (требуют SWIR: B11, B12) ---
  var bandNames = image.bandNames();
  var hasSWIR = bandNames.contains('B11');

  // Серверная проверка наличия SWIR каналов
  result = ee.Image(ee.Algorithms.If(hasSWIR,
    _addSWIRIndices(result),
    result
  ));

  // --- Индексы для трека C (требуют Red Edge: B5, B8A) ---
  var hasRedEdge = bandNames.contains('B5');

  result = ee.Image(ee.Algorithms.If(hasRedEdge,
    _addRedEdgeIndices(result),
    result
  ));

  return result;
}

/**
 * Добавить SWIR-индексы (BSI, DBSI, MBI, MNDWI, NDMI).
 * Вызывается только при наличии B11, B12.
 */
function _addSWIRIndices(image) {
  var B2  = image.select('B2');
  var B3  = image.select('B3');
  var B4  = image.select('B4');
  var B8  = image.select('B8');
  var B11 = image.select('B11');
  var B12 = image.select('B12');
  var NDVI = image.select('NDVI');

  // BSI = ((B11 + B4) - (B8 + B2)) / ((B11 + B4) + (B8 + B2))
  var BSI = B11.add(B4).subtract(B8.add(B2))
    .divide(B11.add(B4).add(B8).add(B2))
    .rename('BSI');

  // DBSI = (B11 - B3) / (B11 + B3) - NDVI
  var DBSI = B11.subtract(B3).divide(B11.add(B3))
    .subtract(NDVI)
    .rename('DBSI');

  // MBI = (B11 - B12 - B8) / (B11 + B12 + B8) + 0.5
  var MBI = B11.subtract(B12).subtract(B8)
    .divide(B11.add(B12).add(B8))
    .add(0.5)
    .rename('MBI');

  // MNDWI = (B3 - B11) / (B3 + B11)
  var MNDWI = B3.subtract(B11).divide(B3.add(B11)).rename('MNDWI');

  // NDMI = (B8 - B11) / (B8 + B11)
  var NDMI = B8.subtract(B11).divide(B8.add(B11)).rename('NDMI');

  return image
    .addBands(BSI)
    .addBands(DBSI)
    .addBands(MBI)
    .addBands(MNDWI)
    .addBands(NDMI);
}

/**
 * Добавить Red Edge индексы (NDRE).
 * Вызывается только при наличии B5, B8A.
 */
function _addRedEdgeIndices(image) {
  var B5  = image.select('B5');   // Red Edge 1 (705 нм)
  var B8A = image.select('B8A');  // Red Edge 4 (865 нм)

  // NDRE = (B8A - B5) / (B8A + B5)
  // Ключевой дискриминатор: лишайник > 0.05, песок ≈ 0
  var NDRE = B8A.subtract(B5).divide(B8A.add(B5)).rename('NDRE');

  return image.addBands(NDRE);
}

// ============================================================================
// GLCM ТЕКСТУРЫ
// ============================================================================

/**
 * Рассчитать GLCM текстуры по B11 (SWIR1).
 * GLCM в GEE работает только с integer bands.
 * @param {ee.Image} image — сцена S2 (должна содержать B11)
 * @param {Number} size — размер окна GLCM (5 для 5×5). По умолчанию 5.
 * @return {ee.Image} — с добавленными bands: B11_ent, B11_idm, B11_contrast
 */
function addGLCMTextures(image, size) {
  size = size || 5;

  // Перевод B11 в integer (× 10000 уже в SR, но нужен Int для GLCM)
  var B11int = image.select('B11').toInt();

  // GLCM
  var glcm = B11int.glcmTexture({size: size});

  // Извлечение нужных текстур
  // GEE именует: B11_ent (entropy), B11_idm (homogeneity), B11_contrast
  var entropy    = glcm.select('B11_ent').rename('B11_ent');
  var homogeneity = glcm.select('B11_idm').rename('B11_idm');
  var contrast   = glcm.select('B11_contrast').rename('B11_contrast');

  return image
    .addBands(entropy)
    .addBands(homogeneity)
    .addBands(contrast);
}

// ============================================================================
// СБОРКА СТЕКА ПРИЗНАКОВ
// ============================================================================

/**
 * Собрать полный стек признаков для классификации.
 * @param {ee.Image} image — сцена S2 (после маски)
 * @param {String} track — 'A', 'B', или 'C'
 * @return {ee.Image} — стек: каналы + индексы + текстуры
 */
function buildFeatureStack(image, track) {
  track = track || 'C';

  // Определяем набор каналов по треку
  var bands;
  if (track === 'A') {
    bands = ['B2', 'B3', 'B4', 'B8'];
  } else if (track === 'B') {
    bands = ['B2', 'B3', 'B4', 'B8', 'B11', 'B12'];
  } else {
    // Трек C — полный набор
    bands = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'];
  }

  // Выбрать каналы
  var selected = image.select(bands);

  // Рассчитать индексы
  var withIndices = addSpectralIndices(selected);

  // Добавить GLCM текстуры (только для треков B и C — нужен B11)
  if (track !== 'A') {
    withIndices = addGLCMTextures(withIndices, 5);
  }

  // Формируем финальный стек по треку
  var stackBands;
  if (track === 'A') {
    // 9 bands
    stackBands = ['B2', 'B3', 'B4', 'B8',
                  'NDVI', 'NDWI', 'Brightness', 'MNDSI', 'B4_B3'];
  } else if (track === 'B') {
    // 17 bands
    stackBands = ['B2', 'B3', 'B4', 'B8', 'B11', 'B12',
                  'NDVI', 'NDWI', 'Brightness', 'MNDSI', 'B4_B3',
                  'BSI', 'DBSI', 'MBI', 'MNDWI', 'NDMI',
                  'B11_ent'];
  } else {
    // Трек C: 20 bands
    stackBands = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12',
                  'NDVI', 'NDWI', 'Brightness', 'MNDSI', 'B4_B3',
                  'BSI', 'DBSI', 'MBI', 'MNDWI', 'NDMI', 'NDRE',
                  'B11_ent', 'B11_idm', 'B11_contrast'];
  }

  return withIndices.select(stackBands);
}

// Экспорт
exports.addSpectralIndices = addSpectralIndices;
exports.addGLCMTextures = addGLCMTextures;
exports.buildFeatureStack = buildFeatureStack;

// ============================================================================
// ТЕСТ: калибровочная сцена Надымских песков
// ============================================================================

print('═══════════════════════════════════════');
print('Тест спектральных индексов — Надымские пески');
print('═══════════════════════════════════════');

// Загрузить и замаскировать сцену
var sceneId = 'COPERNICUS/S2_SR_HARMONIZED/20250810T064641_20250810T064704_T42WXT';
var scene = ee.Image(sceneId);

// Облачная маска (inline — из 02_cloud_mask.js)
var scl = scene.select('SCL');
var cloudMask = scl.eq(8).or(scl.eq(9)).or(scl.eq(10)).or(scl.eq(3)).or(scl.eq(11)).not();
var masked = scene.updateMask(cloudMask);

// Рассчитать индексы
var withIndices = addSpectralIndices(masked);
var withTextures = addGLCMTextures(withIndices, 5);

// Собрать стеки для каждого трека
var stackA = buildFeatureStack(masked, 'A');
var stackB = buildFeatureStack(masked, 'B');
var stackC = buildFeatureStack(masked, 'C');

print('');
print('── Band names по трекам ──');
print('Трек A (' + stackA.bandNames().size().getInfo() + ' bands):', stackA.bandNames());
print('Трек B (' + stackB.bandNames().size().getInfo() + ' bands):', stackB.bandNames());
print('Трек C (' + stackC.bandNames().size().getInfo() + ' bands):', stackC.bandNames());

// ============================================================================
// ВИЗУАЛИЗАЦИЯ
// ============================================================================

var sandPoint = ee.Geometry.Point([72.5, 65.5]);
Map.centerObject(sandPoint, 12);

// True Color
Map.addLayer(masked, {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000}, 'True Color');

// NDVI
Map.addLayer(withIndices.select('NDVI'), {
  min: -0.1, max: 0.5,
  palette: ['#d73027', '#fc8d59', '#fee08b', '#d9ef8b', '#1a9850']
}, 'NDVI (красный < 0.15)');

// BSI
Map.addLayer(withIndices.select('BSI'), {
  min: -0.2, max: 0.2,
  palette: ['#2166ac', '#f7f7f7', '#b2182b']
}, 'BSI (красный = голый грунт)');

// NDRE — ключ к различению песок/лишайник
Map.addLayer(withIndices.select('NDRE'), {
  min: -0.05, max: 0.25,
  palette: ['#2166ac', '#f7f7f7', '#1a9850']
}, 'NDRE (зелёный = лишайник/растительность)');

// Brightness
Map.addLayer(withIndices.select('Brightness'), {
  min: 500, max: 3000,
  palette: ['black', 'white']
}, 'Brightness', false);

// Контрольные точки
Map.addLayer(sandPoint, {color: 'red'}, 'Точка: песок (72.5, 65.5)', false);

// ============================================================================
// INSPECTOR: значения на контрольных точках
// ============================================================================

print('');
print('── Значения индексов на точке песка (72.5°E, 65.5°N) ──');
var sandValues = withTextures.reduceRegion({
  reducer: ee.Reducer.first(),
  geometry: sandPoint,
  scale: 10
});
print(sandValues);

print('');
print('── Ожидаемые значения для песка ──');
print('NDVI < 0.15, BSI > 0, NDRE ≈ 0, Brightness > 1500');
print('');
print('── Ожидаемые значения для лишайника ──');
print('NDVI 0.10–0.30, BSI ≈ 0, NDRE > 0.05, B11_ent > чем у песка');
print('');
print('Кликните Inspector по карте на лишайниковой тундре рядом с песком');
print('и сравните NDRE — это ключевое различие (DNA §6.4.1)');

print('');
print('✓ Тест завершён');
