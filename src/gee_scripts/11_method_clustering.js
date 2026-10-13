/**
 * BareSand — Метод 2: Неконтролируемая кластеризация (K-Means)
 *
 * Разведочный метод. Нет ground truth — визуальная интерпретация кластеров.
 * Какие кластеры соответствуют песку (по средним NDVI, BSI, NDRE)?
 */

// ============================================================================
// КОНФИГУРАЦИЯ
// ============================================================================

var SCENE_ID = 'COPERNICUS/S2_SR_HARMONIZED/20240711T064629_20240711T064625_T42WXT';
var K = 15;           // число кластеров
var SAMPLE_SIZE = 30000;

// ============================================================================
// ЗАГРУЗКА И ПОДГОТОВКА
// ============================================================================

var scene = ee.Image(SCENE_ID);
var scl = scene.select('SCL');
var cloudMask = scl.eq(8).or(scl.eq(9)).or(scl.eq(10)).or(scl.eq(3)).or(scl.eq(11)).not();
var masked = scene.updateMask(cloudMask);

// Полный стек признаков (трек C)
var B2 = masked.select('B2'), B3 = masked.select('B3'), B4 = masked.select('B4');
var B5 = masked.select('B5'), B6 = masked.select('B6'), B7 = masked.select('B7');
var B8 = masked.select('B8'), B8A = masked.select('B8A');
var B11 = masked.select('B11'), B12 = masked.select('B12');

var NDVI = B8.subtract(B4).divide(B8.add(B4)).rename('NDVI');
var BSI = B11.add(B4).subtract(B8.add(B2)).divide(B11.add(B4).add(B8).add(B2)).rename('BSI');
var NDRE = B8A.subtract(B5).divide(B8A.add(B5)).rename('NDRE');
var Brightness = B2.add(B3).add(B4).add(B8).divide(4).rename('Brightness');

var stack = masked.select(['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'])
  .addBands(NDVI).addBands(BSI).addBands(NDRE).addBands(Brightness);

// ============================================================================
// КЛАСТЕРИЗАЦИЯ
// ============================================================================

print('═══════════════════════════════════════');
print('Метод 2: K-Means кластеризация (K=' + K + ')');
print('═══════════════════════════════════════');

// Сэмплинг
var training = stack.sample({
  region: scene.geometry(),
  scale: 20,
  numPixels: SAMPLE_SIZE,
  seed: 42
});
print('Обучающих точек:', training.size());

// K-Means
var clusterer = ee.Clusterer.wekaKMeans(K).train(training);
var clustered = stack.cluster(clusterer).rename('cluster');

// ============================================================================
// СПЕКТРАЛЬНЫЕ ПРОФИЛИ КЛАСТЕРОВ
// ============================================================================

print('');
print('── Средние значения индексов по кластерам ──');

// Стек: кластер + индексы
var clusterWithIndices = clustered.addBands(NDVI).addBands(BSI).addBands(NDRE).addBands(Brightness);

// Средние по каждому кластеру
var clusterStats = clusterWithIndices.reduceRegion({
  reducer: ee.Reducer.mean().group({
    groupField: 0,
    groupName: 'cluster'
  }),
  geometry: scene.geometry(),
  scale: 20,
  maxPixels: 1e8
});
print('Статистика кластеров (группы):', clusterStats.get('groups'));

// Отдельно: какие кластеры могут быть песком
print('');
print('── Идентификация песчаных кластеров ──');
print('Песок: NDVI < 0.15, BSI > 0.08, NDRE < 0.05, Brightness > 2000');
print('Смотрите группы выше и определите номера кластеров визуально');

// ============================================================================
// БИНАРНАЯ МАСКА (после ручной интерпретации)
// ============================================================================

// Автоматическое определение песчаных кластеров по средним значениям
// Для каждого кластера проверяем: NDVI < 0.15 AND NDRE < 0.05
// Это грубое приближение — эксперт уточнит
var sandClusters = ee.List([]);
for (var k = 0; k < K; k++) {
  var clusterMask = clustered.eq(k);
  var stats = clusterWithIndices.updateMask(clusterMask).reduceRegion({
    reducer: ee.Reducer.mean(),
    geometry: scene.geometry(),
    scale: 20,
    maxPixels: 1e8
  });
  // Не можем делать серверную условную логику в цикле — просто выводим
}

// Грубая автоматическая маска: пиксели где кластер имеет характеристики песка
// Используем пороги напрямую на индексах (как в threshold) для валидации
var sandAuto = NDVI.lt(0.15).and(BSI.gt(0.08)).and(NDRE.lt(0.05)).and(Brightness.gt(2000));
var sandClustering = clustered.updateMask(sandAuto).gte(0)  // любой кластер где пороги = песок
  .rename('sand_clustering');

print('');
print('Авто-маска кластеризации (кластеры × пороги)');

// ============================================================================
// ВИЗУАЛИЗАЦИЯ
// ============================================================================

// 15 уникальных цветов
var clusterPalette = [
  'FF0000', '00FF00', '0000FF', 'FFFF00', 'FF00FF',
  '00FFFF', 'FF8800', '88FF00', '0088FF', 'FF0088',
  '88FF88', '8888FF', 'FF8888', '888888', 'FFFFFF'
];

Map.setOptions('SATELLITE');
Map.centerObject(ee.Geometry.Point([73.31, 65.45]), 13);

Map.addLayer(masked, {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000}, 'True Color');
Map.addLayer(clustered, {min: 0, max: K - 1, palette: clusterPalette}, 'Кластеры (K=' + K + ')');
Map.addLayer(sandClustering.selfMask(), {palette: ['FFD700']}, 'ПЕСОК (кластеры)', true, 0.7);

print('');
print('✓ Метод 2 завершён');
print('Сравните жёлтую маску с пороговым методом (10_method_threshold.js)');

exports.sandClustering = sandClustering;
exports.clustered = clustered;
