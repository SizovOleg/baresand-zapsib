/**
 * BareSand — Метод 4: Комбинированный (порог + бинарный RF)
 *
 * Двухэтапный: сначала порог убирает воду/растительность/снег,
 * потом бинарный RF разделяет sand vs not-sand-bare.
 * Ожидается лучшим по DNA.
 */

// ============================================================================
// КОНФИГУРАЦИЯ
// ============================================================================

var SCENE_ID = 'COPERNICUS/S2_SR_HARMONIZED/20240711T064629_20240711T064625_T42WXT';
var RF_TREES = 200;
var RF_SEED = 42;

// ============================================================================
// ЗАГРУЗКА И ПОДГОТОВКА
// ============================================================================

var scene = ee.Image(SCENE_ID);
var scl = scene.select('SCL');
var cloudMask = scl.eq(8).or(scl.eq(9)).or(scl.eq(10)).or(scl.eq(3)).or(scl.eq(11)).not();
var masked = scene.updateMask(cloudMask);

var B2 = masked.select('B2'), B3 = masked.select('B3'), B4 = masked.select('B4');
var B5 = masked.select('B5'), B6 = masked.select('B6'), B7 = masked.select('B7');
var B8 = masked.select('B8'), B8A = masked.select('B8A');
var B11 = masked.select('B11'), B12 = masked.select('B12');

var NDVI = B8.subtract(B4).divide(B8.add(B4)).rename('NDVI');
var BSI = B11.add(B4).subtract(B8.add(B2)).divide(B11.add(B4).add(B8).add(B2)).rename('BSI');
var DBSI = B11.subtract(B3).divide(B11.add(B3)).subtract(NDVI).rename('DBSI');
var MBI = B11.subtract(B12).subtract(B8).divide(B11.add(B12).add(B8)).add(0.5).rename('MBI');
var MNDWI = B3.subtract(B11).divide(B3.add(B11)).rename('MNDWI');
var NDRE = B8A.subtract(B5).divide(B8A.add(B5)).rename('NDRE');
var NDMI = B8.subtract(B11).divide(B8.add(B11)).rename('NDMI');
var Brightness = B2.add(B3).add(B4).add(B8).divide(4).rename('Brightness');

var stack = masked.select(['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'])
  .addBands(NDVI).addBands(BSI).addBands(DBSI).addBands(MBI)
  .addBands(MNDWI).addBands(NDRE).addBands(NDMI).addBands(Brightness);

var bandNames = stack.bandNames();

// ============================================================================
// ЭТАП 1: КОНСЕРВАТИВНЫЙ ПОРОГОВЫЙ ФИЛЬТР
// ============================================================================

print('═══════════════════════════════════════');
print('Метод 4: Комбинированный (порог + RF)');
print('═══════════════════════════════════════');

// Убрать заведомо не-bare: вода, густая растительность, снег
var bareCandidateMask = MNDWI.lte(0)                // не вода
  .and(NDVI.lte(0.25))                               // не густая растительность
  .and(scl.neq(11));                                  // не снег

var bareCandidates = stack.updateMask(bareCandidateMask);

var barePixels = bareCandidateMask.reduceRegion({
  reducer: ee.Reducer.sum(), geometry: scene.geometry(), scale: 20, maxPixels: 1e8
});
print('Этап 1: bare-кандидатов (пикселей):', barePixels);

// ============================================================================
// ЭТАП 2: БИНАРНЫЙ RF (sand vs not-sand-bare)
// ============================================================================

// Обучающая выборка: бинарная (0 = sand, 1 = not-sand-bare)
var binaryTraining = ee.FeatureCollection([
  // Sand (class 0)
  ee.Feature(ee.Geometry.Point([73.3137, 65.4428]), {class: 0}),
  ee.Feature(ee.Geometry.Point([73.3200, 65.4400]), {class: 0}),
  ee.Feature(ee.Geometry.Point([73.3050, 65.4450]), {class: 0}),
  ee.Feature(ee.Geometry.Point([73.2900, 65.4470]), {class: 0}),
  ee.Feature(ee.Geometry.Point([73.3300, 65.4380]), {class: 0}),
  ee.Feature(ee.Geometry.Point([73.3100, 65.4500]), {class: 0}),
  ee.Feature(ee.Geometry.Point([73.2800, 65.4420]), {class: 0}),

  // Not-sand-bare: лишайник + тундра низкая (class 1)
  ee.Feature(ee.Geometry.Point([73.3167, 65.4507]), {class: 1}),
  ee.Feature(ee.Geometry.Point([73.3400, 65.4600]), {class: 1}),
  ee.Feature(ee.Geometry.Point([73.2700, 65.4550]), {class: 1}),
  ee.Feature(ee.Geometry.Point([73.3500, 65.4500]), {class: 1}),
  ee.Feature(ee.Geometry.Point([73.2600, 65.4600]), {class: 1}),
  ee.Feature(ee.Geometry.Point([73.3600, 65.4650]), {class: 1}),
  ee.Feature(ee.Geometry.Point([73.2000, 65.4600]), {class: 1}),
  ee.Feature(ee.Geometry.Point([73.1800, 65.4800]), {class: 1})
]);

// Сэмплирование на bare-кандидатах
var training = bareCandidates.sampleRegions({
  collection: binaryTraining,
  properties: ['class'],
  scale: 10
});

print('Этап 2: обучающих точек:', training.size());

// Бинарный RF
var binaryRF = ee.Classifier.smileRandomForest({
  numberOfTrees: RF_TREES,
  seed: RF_SEED
}).train({
  features: training,
  classProperty: 'class',
  inputProperties: bandNames
});

// Классификация bare-кандидатов
var binaryClassified = bareCandidates.classify(binaryRF);

// Бинарная маска: 0 = sand
var sandCombined = binaryClassified.eq(0)
  .updateMask(bareCandidateMask)
  .rename('sand_combined');

// ============================================================================
// ЭТАП 3: ПОСТФИЛЬТР
// ============================================================================

// Убрать мелкие объекты (< 9 пикселей = 900 м²)
var connected = sandCombined.selfMask().connectedPixelCount(16, true);
var sandClean = sandCombined.updateMask(connected.gte(9));

// Сглаживание
var sandFinal = sandClean.focal_mode({radius: 1, kernelType: 'square'})
  .rename('sand_combined');

// Variable importance
print('');
print('── Variable Importance (бинарный RF) ──');
print(ee.Dictionary(binaryRF.explain().get('importance')));

// Площадь
var sandArea = sandFinal.multiply(ee.Image.pixelArea()).reduceRegion({
  reducer: ee.Reducer.sum(), geometry: scene.geometry(), scale: 10, maxPixels: 1e9
});
print('Площадь песка (комбинированный):', ee.Number(sandArea.get('sand_combined')).divide(1e6), 'км²');

// ============================================================================
// ВИЗУАЛИЗАЦИЯ
// ============================================================================

Map.setOptions('SATELLITE');
Map.centerObject(ee.Geometry.Point([73.31, 65.45]), 13);

Map.addLayer(masked, {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000}, 'True Color');
Map.addLayer(bareCandidateMask.selfMask(), {palette: ['FF4444']}, 'Этап 1: bare-кандидаты', false, 0.3);
Map.addLayer(sandFinal.selfMask(), {palette: ['FFD700']}, 'ПЕСОК (комбинированный)', true, 0.7);

print('');
print('✓ Метод 4 завершён');

exports.sandCombined = sandFinal;
