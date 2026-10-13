/**
 * BareSand — Метод 3: Random Forest
 *
 * Supervised classification. Временная выборка из Inspector.
 * Variable importance — научный результат.
 */

// ============================================================================
// КОНФИГУРАЦИЯ
// ============================================================================

var SCENE_ID = 'COPERNICUS/S2_SR_HARMONIZED/20240711T064629_20240711T064625_T42WXT';
var RF_TREES = 200;
var RF_MIN_LEAF = 5;
var RF_SEED = 42;

// Палитра классов
var CLASS_PALETTE = [
  'FFD700',  // 0 sand
  'C8C878',  // 1 lichen
  'A0522D',  // 2 gravel
  '4A2800',  // 3 peat
  'FF00FF',  // 4 anthro
  '228B22',  // 5 vegetation
  '0000FF',  // 6 water
  'FFFFFF'   // 7 snow
];

// ============================================================================
// ЗАГРУЗКА И ПОДГОТОВКА
// ============================================================================

var scene = ee.Image(SCENE_ID);
var scl = scene.select('SCL');
var cloudMask = scl.eq(8).or(scl.eq(9)).or(scl.eq(10)).or(scl.eq(3)).or(scl.eq(11)).not();
var masked = scene.updateMask(cloudMask);

// Стек признаков (трек C)
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
// ВРЕМЕННАЯ ОБУЧАЮЩАЯ ВЫБОРКА (замените GeoJSON от эксперта)
// Координаты из Inspector на сцене 20240711 T42WXT
// ============================================================================

var tempTraining = ee.FeatureCollection([
  // Sand — открытые раздувы Надымских песков
  ee.Feature(ee.Geometry.Point([73.3137, 65.4428]), {class: 0}),
  ee.Feature(ee.Geometry.Point([73.3200, 65.4400]), {class: 0}),
  ee.Feature(ee.Geometry.Point([73.3050, 65.4450]), {class: 0}),
  ee.Feature(ee.Geometry.Point([73.2900, 65.4470]), {class: 0}),
  ee.Feature(ee.Geometry.Point([73.3300, 65.4380]), {class: 0}),
  ee.Feature(ee.Geometry.Point([73.3100, 65.4500]), {class: 0}),
  ee.Feature(ee.Geometry.Point([73.2800, 65.4420]), {class: 0}),

  // Lichen — лишайниковая пустошь рядом с песками
  ee.Feature(ee.Geometry.Point([73.3167, 65.4507]), {class: 1}),
  ee.Feature(ee.Geometry.Point([73.3400, 65.4600]), {class: 1}),
  ee.Feature(ee.Geometry.Point([73.2700, 65.4550]), {class: 1}),
  ee.Feature(ee.Geometry.Point([73.3500, 65.4500]), {class: 1}),
  ee.Feature(ee.Geometry.Point([73.2600, 65.4600]), {class: 1}),
  ee.Feature(ee.Geometry.Point([73.3600, 65.4650]), {class: 1}),

  // Vegetation — тундра, кустарник
  ee.Feature(ee.Geometry.Point([73.2000, 65.4600]), {class: 5}),
  ee.Feature(ee.Geometry.Point([73.1500, 65.4700]), {class: 5}),
  ee.Feature(ee.Geometry.Point([73.1800, 65.4800]), {class: 5}),
  ee.Feature(ee.Geometry.Point([73.2200, 65.4900]), {class: 5}),
  ee.Feature(ee.Geometry.Point([73.1000, 65.4500]), {class: 5}),

  // Water — озёра
  ee.Feature(ee.Geometry.Point([73.4000, 65.4300]), {class: 6}),
  ee.Feature(ee.Geometry.Point([73.5000, 65.4200]), {class: 6}),
  ee.Feature(ee.Geometry.Point([73.1500, 65.4200]), {class: 6}),
  ee.Feature(ee.Geometry.Point([73.3000, 65.4100]), {class: 6})
]);

// ============================================================================
// ОБУЧЕНИЕ RF
// ============================================================================

print('═══════════════════════════════════════');
print('Метод 3: Random Forest (трек C)');
print('═══════════════════════════════════════');

// Извлечь значения стека на обучающих точках
var training = stack.sampleRegions({
  collection: tempTraining,
  properties: ['class'],
  scale: 10
});

print('Обучающих точек:', training.size());
print('Распределение по классам:', training.aggregate_histogram('class'));

// Обучение
var classifier = ee.Classifier.smileRandomForest({
  numberOfTrees: RF_TREES,
  minLeafPopulation: RF_MIN_LEAF,
  seed: RF_SEED
}).train({
  features: training,
  classProperty: 'class',
  inputProperties: bandNames
});

// Классификация
var classified = stack.classify(classifier).rename('classification');

// Бинарная маска песка
var sandRF = classified.eq(0).rename('sand_rf');

// ============================================================================
// VARIABLE IMPORTANCE (научный результат)
// ============================================================================

print('');
print('── Variable Importance (топ-18) ──');
var importance = ee.Dictionary(classifier.explain().get('importance'));
print(importance);

// Отсортировать для удобства
var keys = importance.keys();
var values = importance.values();
print('Признаки:', keys);
print('Важность:', values);

// ============================================================================
// СТАТИСТИКА
// ============================================================================

var sandArea = sandRF.multiply(ee.Image.pixelArea()).reduceRegion({
  reducer: ee.Reducer.sum(),
  geometry: scene.geometry(),
  scale: 10,
  maxPixels: 1e9
});
print('');
print('Площадь песка (RF):', ee.Number(sandArea.get('sand_rf')).divide(1e6), 'км²');

// ============================================================================
// ВИЗУАЛИЗАЦИЯ
// ============================================================================

Map.setOptions('SATELLITE');
Map.centerObject(ee.Geometry.Point([73.31, 65.45]), 13);

Map.addLayer(masked, {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000}, 'True Color');
Map.addLayer(classified, {min: 0, max: 7, palette: CLASS_PALETTE}, 'RF классификация (8 классов)');
Map.addLayer(sandRF.selfMask(), {palette: ['FFD700']}, 'ПЕСОК (RF)', true, 0.7);

// Обучающие точки
Map.addLayer(tempTraining.filter(ee.Filter.eq('class', 0)), {color: 'red'}, 'Train: sand', false);
Map.addLayer(tempTraining.filter(ee.Filter.eq('class', 1)), {color: 'orange'}, 'Train: lichen', false);
Map.addLayer(tempTraining.filter(ee.Filter.eq('class', 5)), {color: 'green'}, 'Train: veg', false);
Map.addLayer(tempTraining.filter(ee.Filter.eq('class', 6)), {color: 'blue'}, 'Train: water', false);

print('');
print('✓ Метод 3 завершён');
print('ПРОВЕРЬТЕ: Variable Importance — NDRE и B12 в топ-5?');

exports.sandRF = sandRF;
exports.classified = classified;
exports.classifier = classifier;
