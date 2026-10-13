/**
 * BareSand — Метод 5: AlphaEarth Foundation Model Embeddings (трек D)
 *
 * 4 эксперимента:
 *   5a. Similarity search (косинусное сходство с эталоном)
 *   5b. RF на 64 эмбеддингах
 *   5c. K-Means на эмбеддингах
 *   5d. Change detection 2017 → 2024
 *
 * Ассет: GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL (64 bands A00-A63, 10м)
 * Geometry Imports: sand, lichen, vegetation, water, fire
 */

// ============================================================================
// ДАННЫЕ
// ============================================================================

// AlphaEarth годовые эмбеддинги 2024
var emb = ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
  .filterDate('2024-01-01', '2025-01-01').first();

// Имена bands
var embBands = emb.bandNames();

// Обучающая выборка из Geometry Imports
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

print('═══ AlphaEarth Embeddings (трек D) ═══');
print('Bands:', embBands.size(), '(A00–A63)');

// ============================================================================
// 5a. SIMILARITY SEARCH
// ============================================================================

print('');
print('── 5a. Similarity Search ──');

// Средний эмбеддинг песка
var sandGeom = sandFC.geometry();
var sandMeanDict = emb.reduceRegion({
  reducer: ee.Reducer.mean(), geometry: sandGeom, scale: 10, maxPixels: 1e8
});
var sandMeanImage = emb.multiply(0).add(ee.Image.constant(sandMeanDict.values(embBands)));

// Средний эмбеддинг лишайника
var lichenGeom = lichenFC.geometry();
var lichenMeanDict = emb.reduceRegion({
  reducer: ee.Reducer.mean(), geometry: lichenGeom, scale: 10, maxPixels: 1e8
});

// Косинусное сходство каждого пикселя с эталоном песка
var dotProduct = emb.multiply(sandMeanImage).reduce(ee.Reducer.sum());
var normPixel = emb.pow(2).reduce(ee.Reducer.sum()).sqrt();
var normRef = sandMeanImage.pow(2).reduce(ee.Reducer.sum()).sqrt();
var similarity = dotProduct.divide(normPixel).divide(normRef).rename('similarity');

// КРИТИЧЕСКИЙ ТЕСТ: similarity песок-лишайник
var lichenMeanImage = emb.multiply(0).add(ee.Image.constant(lichenMeanDict.values(embBands)));
var dotSL = ee.Array(sandMeanDict.values(embBands))
  .dotProduct(ee.Array(lichenMeanDict.values(embBands)));
var normS = ee.Array(sandMeanDict.values(embBands)).dotProduct(
  ee.Array(sandMeanDict.values(embBands))).sqrt();
var normL = ee.Array(lichenMeanDict.values(embBands)).dotProduct(
  ee.Array(lichenMeanDict.values(embBands))).sqrt();
var simSandLichen = dotSL.divide(normS).divide(normL);

print('*** SIMILARITY ПЕСОК-ЛИШАЙНИК:', simSandLichen, '***');
print('   < 0.70 → модель различает → similarity search работает');
print('   0.70–0.85 → серая зона → нужен RF');
print('   > 0.85 → не различает → similarity бесполезен');

// Маска по similarity
var sandEmbSimilarity = similarity.gt(0.85).rename('sand_emb_similarity');

// Площадь
var simArea = sandEmbSimilarity.multiply(ee.Image.pixelArea()).reduceRegion({
  reducer: ee.Reducer.sum(), geometry: emb.geometry(), scale: 10, maxPixels: 1e9
});
print('Площадь (similarity > 0.85):', ee.Number(simArea.get('sand_emb_similarity')).divide(1e6), 'км²');

// ============================================================================
// 5b. RF НА ЭМБЕДДИНГАХ
// ============================================================================

print('');
print('── 5b. RF на эмбеддингах ──');

var embTraining = emb.sampleRegions({
  collection: allTraining, properties: ['class'], scale: 10
});

var embClassifier = ee.Classifier.smileRandomForest({
  numberOfTrees: 200, seed: 42
}).train({features: embTraining, classProperty: 'class', inputProperties: embBands});

var embClassified = emb.classify(embClassifier).rename('emb_classification');
var sandEmbRF = embClassified.eq(0).rename('sand_emb_rf');

// Variable importance
print('Variable Importance (топ dims):');
var embImportance = ee.Dictionary(embClassifier.explain().get('importance'));
print(embImportance);

// Площадь (scale 30 + bestEffort чтобы обойти timeout при классификации on-the-fly)
var rfArea = sandEmbRF.multiply(ee.Image.pixelArea()).reduceRegion({
  reducer: ee.Reducer.sum(), geometry: emb.geometry(), scale: 30,
  maxPixels: 1e9, bestEffort: true, tileScale: 4
});
print('Площадь (RF эмбеддинги):', ee.Number(rfArea.get('sand_emb_rf')).divide(1e6), 'км²');

// ============================================================================
// 5c. КЛАСТЕРИЗАЦИЯ ЭМБЕДДИНГОВ
// ============================================================================

print('');
print('── 5c. K-Means на эмбеддингах ──');

var embSample = emb.sample({
  region: emb.geometry(), scale: 20, numPixels: 30000, seed: 42
});
var embClusterer = ee.Clusterer.wekaKMeans(15).train(embSample);
var embClustered = emb.cluster(embClusterer).rename('emb_cluster');

// Авто-маска: кластеры с similarity > 0.85
var sandEmbClustering = similarity.gt(0.85).rename('sand_emb_clustering');

print('Кластеризация: 15 кластеров на 64 dims');

// ============================================================================
// 5d. CHANGE DETECTION 2017 → 2024
// ============================================================================

print('');
print('── 5d. Change Detection 2017 → 2024 ──');

var emb2017 = ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
  .filterDate('2017-01-01', '2018-01-01').first();
var emb2024 = emb;  // уже загружен

var change = emb2024.subtract(emb2017).pow(2).reduce(ee.Reducer.sum()).sqrt()
  .rename('emb_change');

// Статистика change на песке vs всей сцене
var changeSand = change.reduceRegion({
  reducer: ee.Reducer.mean(), geometry: sandGeom, scale: 10, maxPixels: 1e8
});
var changeAll = change.reduceRegion({
  reducer: ee.Reducer.mean(), geometry: emb.geometry(), scale: 60,
  maxPixels: 1e9, bestEffort: true
});
print('Change на песке (среднее):', changeSand.get('emb_change'));
print('Change на всей сцене (среднее):', changeAll.get('emb_change'));
print('Если песок стабилен → change на песке < среднего');

// ============================================================================
// ВИЗУАЛИЗАЦИЯ
// ============================================================================

Map.setOptions('SATELLITE');
Map.centerObject(ee.Geometry.Point([73.31, 65.45]), 13);

// Базовый слой — Sentinel-2 true color для контекста
var scene = ee.Image('COPERNICUS/S2_SR_HARMONIZED/20240711T064629_20240711T064625_T42WXT');
var scl = scene.select('SCL');
var cloudMask = scl.eq(8).or(scl.eq(9)).or(scl.eq(10)).or(scl.eq(3)).or(scl.eq(11)).not();
Map.addLayer(scene.updateMask(cloudMask), {bands: ['B4','B3','B2'], min: 0, max: 3000}, 'S2 True Color');

// Similarity map
Map.addLayer(similarity, {min: 0.6, max: 0.95,
  palette: ['0000FF', '00FFFF', 'FFFFFF', 'FFFF00', 'FF0000']
}, 'Similarity с песком');

// Маска по similarity
Map.addLayer(sandEmbSimilarity.selfMask(), {palette: ['FFD700']},
  'ПЕСОК (similarity > 0.85)', false, 0.7);

// RF на эмбеддингах
var CLASS_PALETTE = ['FFD700','C8C878','A0522D','4A2800','FF00FF','228B22','0000FF','FFFFFF'];
Map.addLayer(embClassified, {min: 0, max: 7, palette: CLASS_PALETTE},
  'RF эмбеддинги (8 классов)', false);
Map.addLayer(sandEmbRF.selfMask(), {palette: ['FFD700']},
  'ПЕСОК (RF эмбеддинги)', true, 0.7);

// Кластеры эмбеддингов
var palette15 = ['FF0000','00FF00','0000FF','FFFF00','FF00FF',
  '00FFFF','FF8800','88FF00','0088FF','FF0088',
  '88FF88','8888FF','FF8888','888888','FFFFFF'];
Map.addLayer(embClustered, {min: 0, max: 14, palette: palette15},
  'Кластеры эмбеддингов', false);

// Change detection
Map.addLayer(change, {min: 0, max: 5,
  palette: ['00FF00', 'FFFF00', 'FF0000']
}, 'Change 2017→2024', false);

print('');
print('✓ AlphaEarth завершён');
print('ГЛАВНАЯ ЦИФРА: similarity песок-лишайник (см. выше)');
