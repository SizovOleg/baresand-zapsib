/**
 * BareSand — Сравнение 5 методов на Надымской калибровочной сцене
 *
 * Методы:
 *   1. Пороговый (NDVI + BSI + NDRE + Brightness)
 *   2. K-Means (кластеры привязаны к точкам песка)
 *   3. RF на спектральных индексах (8 классов)
 *   4. Комбинированный (threshold pre-filter → binary RF + MMU)
 *   5. RF на AlphaEarth эмбеддингах (64 dims)
 *
 * Выход: попиксельное сравнение + agreement map (0–5) + площади.
 *
 * Geometry Imports (общие для всех методов):
 *   sand, lichen, vegetation, water, fire
 */

// ============================================================================
// КОНФИГУРАЦИЯ
// ============================================================================

var SCENE_ID = 'COPERNICUS/S2_SR_HARMONIZED/20240711T064629_20240711T064625_T42WXT';
var RF_TREES = 200;
var RF_SEED = 42;
var CENTER = ee.Geometry.Point([73.31, 65.45]);

// Калибровочные пороги (из 10_method_threshold.js после калибровки)
var TH = {
  NDVI_MAX: 0.15,
  BSI_MIN: 0.04,
  NDRE_MAX: 0.05,
  BRIGHTNESS_MIN: 1400,
  MNDWI_MAX: 0
};

// ============================================================================
// ЗАГРУЗКА СЦЕНЫ + МАСКА ОБЛАКОВ
// ============================================================================

var scene = ee.Image(SCENE_ID);
var scl = scene.select('SCL');
var cloudMask = scl.eq(8).or(scl.eq(9)).or(scl.eq(10)).or(scl.eq(3)).or(scl.eq(11)).not();
var masked = scene.updateMask(cloudMask);

// ============================================================================
// СПЕКТРАЛЬНЫЙ СТЕК (индексы)
// ============================================================================

var B2 = masked.select('B2'),  B3 = masked.select('B3'),  B4 = masked.select('B4');
var B5 = masked.select('B5'),  B6 = masked.select('B6'),  B7 = masked.select('B7');
var B8 = masked.select('B8'),  B8A = masked.select('B8A');
var B11 = masked.select('B11'), B12 = masked.select('B12');

var NDVI = B8.subtract(B4).divide(B8.add(B4)).rename('NDVI');
var BSI = B11.add(B4).subtract(B8.add(B2)).divide(B11.add(B4).add(B8).add(B2)).rename('BSI');
var DBSI = B11.subtract(B3).divide(B11.add(B3)).subtract(NDVI).rename('DBSI');
var MBI = B11.subtract(B12).subtract(B8).divide(B11.add(B12).add(B8)).add(0.5).rename('MBI');
var MNDWI = B3.subtract(B11).divide(B3.add(B11)).rename('MNDWI');
var NDRE = B8A.subtract(B5).divide(B8A.add(B5)).rename('NDRE');
var NDMI = B8.subtract(B11).divide(B8.add(B11)).rename('NDMI');
var Brightness = B2.add(B3).add(B4).add(B8).divide(4).rename('Brightness');

var stack = masked.select(['B2','B3','B4','B5','B6','B7','B8','B8A','B11','B12'])
  .addBands(NDVI).addBands(BSI).addBands(DBSI).addBands(MBI)
  .addBands(MNDWI).addBands(NDRE).addBands(NDMI).addBands(Brightness);
var stackBands = stack.bandNames();

// ============================================================================
// AlphaEarth ЭМБЕДДИНГИ (для метода 5)
// ============================================================================

var emb = ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
  .filterDate('2024-01-01', '2025-01-01')
  .filterBounds(CENTER)
  .first();
var embBands = emb.bandNames();

// ============================================================================
// ОБУЧАЮЩАЯ ВЫБОРКА (из Geometry Imports — общая для всех методов)
// ============================================================================

var sandFC = ee.FeatureCollection(sand.coordinates().map(function(c) {
  return ee.Feature(ee.Geometry.Point(c), {class: 0});
}));
var lichenFC = ee.FeatureCollection(lichen.coordinates().map(function(c) {
  return ee.Feature(ee.Geometry.Point(c), {class: 1});
}));
var fireFC = ee.FeatureCollection(fire.coordinates().map(function(c) {
  return ee.Feature(ee.Geometry.Point(c), {class: 3});
}));
var vegFC = ee.FeatureCollection(vegetation.coordinates().map(function(c) {
  return ee.Feature(ee.Geometry.Point(c), {class: 5});
}));
var waterFC = ee.FeatureCollection(water.coordinates().map(function(c) {
  return ee.Feature(ee.Geometry.Point(c), {class: 6});
}));

var allTraining = sandFC.merge(lichenFC).merge(fireFC).merge(vegFC).merge(waterFC);

print('═══════════════════════════════════════');
print('Сравнение 5 методов на Надымской сцене');
print('═══════════════════════════════════════');
print('Training points:', allTraining.size());
print('  sand:', sandFC.size(), 'lichen:', lichenFC.size(),
      'fire:', fireFC.size(), 'vegetation:', vegFC.size(), 'water:', waterFC.size());

// ============================================================================
// МЕТОД 1: ПОРОГОВЫЙ
// ============================================================================

var sandThreshold = NDVI.lt(TH.NDVI_MAX)
  .and(BSI.gt(TH.BSI_MIN))
  .and(NDRE.lt(TH.NDRE_MAX))
  .and(Brightness.gt(TH.BRIGHTNESS_MIN))
  .and(MNDWI.lte(TH.MNDWI_MAX))
  .focal_mode({radius: 1, kernelType: 'square'})
  .rename('sand_threshold');

// ============================================================================
// МЕТОД 2: K-MEANS (привязка кластеров к точкам песка)
// ============================================================================

var clusterTraining = stack.sample({
  region: scene.geometry(), scale: 20, numPixels: 30000, seed: RF_SEED
});
var clusterer = ee.Clusterer.wekaKMeans(15).train(clusterTraining);
var clustered = stack.cluster(clusterer).rename('cluster');

// Находим какие кластеры содержат sand-точки
var sandClusterIds = clustered.sampleRegions({
  collection: sandFC, scale: 10
}).aggregate_array('cluster').distinct();

// Маска = пиксели в этих кластерах
var sandClustering = clustered.remap(
  sandClusterIds, ee.List.repeat(1, sandClusterIds.size()), 0
).rename('sand_clustering');

// ============================================================================
// МЕТОД 3: RF НА СПЕКТРАЛЬНОМ СТЕКЕ (8 классов)
// ============================================================================

var rfTraining = stack.sampleRegions({
  collection: allTraining, properties: ['class'], scale: 10
});
var rfClassifier = ee.Classifier.smileRandomForest({numberOfTrees: RF_TREES, seed: RF_SEED})
  .train({features: rfTraining, classProperty: 'class', inputProperties: stackBands});
var sandRF = stack.classify(rfClassifier).eq(0).rename('sand_rf');

// ============================================================================
// МЕТОД 4: КОМБИНИРОВАННЫЙ (threshold → binary RF + MMU)
// ============================================================================

// Stage 1: грубая bare-маска (убираем воду, растительность, снег)
var bareMask = MNDWI.lte(TH.MNDWI_MAX)
  .and(NDVI.lte(0.25))
  .and(scl.neq(11));
var bareCandidates = stack.updateMask(bareMask);

// Stage 2: binary RF — обучаем на ВСЁМ стеке с полной выборкой,
// классифицируем только bareCandidates
var binaryRF = ee.Classifier.smileRandomForest({numberOfTrees: RF_TREES, seed: RF_SEED})
  .train({features: rfTraining, classProperty: 'class', inputProperties: stackBands});

// Stage 3: применяем только к bare-кандидатам + MMU + focal_mode
var sandCombined = bareCandidates.classify(binaryRF).eq(0)
  .updateMask(bareMask)
  .selfMask().connectedPixelCount(16, true).gte(9)
  .focal_mode({radius: 1, kernelType: 'square'})
  .unmask(0)
  .rename('sand_combined');

// ============================================================================
// МЕТОД 5: RF НА AlphaEarth ЭМБЕДДИНГАХ
// ============================================================================

var embTraining = emb.sampleRegions({
  collection: allTraining, properties: ['class'], scale: 10
});
var embClassifier = ee.Classifier.smileRandomForest({numberOfTrees: RF_TREES, seed: RF_SEED})
  .train({features: embTraining, classProperty: 'class', inputProperties: embBands});
var sandEmbRF = emb.classify(embClassifier).eq(0).rename('sand_emb_rf');

// ============================================================================
// AGREEMENT MAP (0–5)
// ============================================================================

var agreement = sandThreshold.unmask(0)
  .add(sandClustering.unmask(0))
  .add(sandRF.unmask(0))
  .add(sandCombined.unmask(0))
  .add(sandEmbRF.unmask(0))
  .rename('sand_agreement');

// ============================================================================
// ПЛОЩАДИ
// ============================================================================

function getArea(mask, name, scale) {
  var area = mask.unmask(0).multiply(ee.Image.pixelArea()).reduceRegion({
    reducer: ee.Reducer.sum(),
    geometry: scene.geometry(),
    scale: scale || 10,
    maxPixels: 1e9,
    bestEffort: true,
    tileScale: 4
  });
  var km2 = ee.Number(area.get(mask.bandNames().get(0))).divide(1e6);
  print(name + ':', km2, 'км²');
  return km2;
}

print('');
print('── Площади по методам ──');
getArea(sandThreshold, '1. Пороговый', 10);
getArea(sandClustering, '2. K-Means', 20);
getArea(sandRF, '3. RF спектр', 10);
getArea(sandCombined, '4. Комбинированный', 10);
getArea(sandEmbRF, '5. RF эмбеддинги', 30);

// ============================================================================
// AGREEMENT СТАТИСТИКА
// ============================================================================

print('');
print('── Agreement map (0–5) ──');
print('0 = ни один метод; 5 = все согласны');
var agreementHist = agreement.reduceRegion({
  reducer: ee.Reducer.frequencyHistogram(),
  geometry: scene.geometry(),
  scale: 20,
  maxPixels: 1e9,
  bestEffort: true,
  tileScale: 4
});
print('Распределение:', agreementHist.get('sand_agreement'));

// Площадь ядра консенсуса (3+ методов согласны)
var consensusCore = agreement.gte(3).rename('consensus_core');
getArea(consensusCore, 'Ядро консенсуса (≥3 методов)', 20);

// ============================================================================
// ВИЗУАЛИЗАЦИЯ
// ============================================================================

Map.setOptions('SATELLITE');
Map.centerObject(CENTER, 13);

// True Color подложка
Map.addLayer(masked, {bands: ['B4','B3','B2'], min: 0, max: 3000}, 'S2 True Color');

// Отдельные маски (выключены по умолчанию)
Map.addLayer(sandThreshold.selfMask(), {palette: ['FF4444']},
  '1. Пороговый', false, 0.7);
Map.addLayer(sandClustering.selfMask(), {palette: ['44FF44']},
  '2. K-Means', false, 0.7);
Map.addLayer(sandRF.selfMask(), {palette: ['4444FF']},
  '3. RF спектр', false, 0.7);
Map.addLayer(sandCombined.selfMask(), {palette: ['FF44FF']},
  '4. Комбинированный', false, 0.7);
Map.addLayer(sandEmbRF.selfMask(), {palette: ['FFAA00']},
  '5. RF эмбеддинги', false, 0.7);

// Agreement map — главный продукт
Map.addLayer(agreement.selfMask(), {
  min: 1, max: 5,
  palette: ['FFFFCC', 'FED976', 'FD8D3C', 'E31A1C', '800026']
}, 'AGREEMENT (1–5 методов)', true, 0.75);

// Эталонные точки
Map.addLayer(sandFC, {color: 'FFD700'}, 'Sand points', false);
Map.addLayer(lichenFC, {color: 'C8C878'}, 'Lichen points', false);
Map.addLayer(fireFC, {color: 'A0522D'}, 'Fire points', false);
Map.addLayer(vegFC, {color: '228B22'}, 'Vegetation points', false);
Map.addLayer(waterFC, {color: '0000FF'}, 'Water points', false);

print('');
print('✓ Сравнение завершено');
print('Палитра agreement: светло-жёлтый → тёмно-красный');
print('  1 метод → 2 → 3 → 4 → 5 согласны');
print('');
print('Интерпретация для статьи:');
print('  - Ядро консенсуса (≥3) → референс "точно песок"');
print('  - Разница методов → обсуждение overclassification vs edges');
