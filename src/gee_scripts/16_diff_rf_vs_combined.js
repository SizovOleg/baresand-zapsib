/**
 * BareSand — Визуальный diff: RF vs Combined
 *
 * Цель: понять, что именно Combined добавляет к RF (разница ~16 км²).
 *   - Настоящие края раздувов → Combined лучше
 *   - Разрозненный шум → Combined хуже (RF без post-processing)
 *
 * XOR-карта:
 *   1 = только RF (синий)       — RF видит, Combined нет
 *   2 = только Combined (красный) — Combined видит, RF нет
 *   3 = оба (жёлтый)              — согласие
 *
 * Geometry Imports: sand, lichen, vegetation, water, fire
 */

// ============================================================================
// КОНФИГУРАЦИЯ
// ============================================================================

var SCENE_ID = 'COPERNICUS/S2_SR_HARMONIZED/20240711T064629_20240711T064625_T42WXT';
var RF_TREES = 200;
var RF_SEED = 42;
var CENTER = ee.Geometry.Point([73.31, 65.45]);

// ============================================================================
// СЦЕНА + МАСКА ОБЛАКОВ + СТЕК
// ============================================================================

var scene = ee.Image(SCENE_ID);
var scl = scene.select('SCL');
var cloudMask = scl.eq(8).or(scl.eq(9)).or(scl.eq(10)).or(scl.eq(3)).or(scl.eq(11)).not();
var masked = scene.updateMask(cloudMask);

var B2 = masked.select('B2'),  B3 = masked.select('B3'),  B4 = masked.select('B4');
var B5 = masked.select('B5'),  B8 = masked.select('B8'),  B8A = masked.select('B8A');
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
// ОБУЧАЮЩАЯ ВЫБОРКА (та же что в 12/13/14)
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

var training = stack.sampleRegions({
  collection: allTraining, properties: ['class'], scale: 10
});

// ============================================================================
// МЕТОД 3: RF (8 классов, полный стек)
// ============================================================================

var rfClassifier = ee.Classifier.smileRandomForest({numberOfTrees: RF_TREES, seed: RF_SEED})
  .train({features: training, classProperty: 'class', inputProperties: stackBands});
var sandRF = stack.classify(rfClassifier).eq(0).rename('sand_rf');

// ============================================================================
// МЕТОД 4: COMBINED (pre-filter → RF → MMU + focal_mode)
// ============================================================================

var bareMask = MNDWI.lte(0).and(NDVI.lte(0.25)).and(scl.neq(11));
var bareCandidates = stack.updateMask(bareMask);

var sandCombined = bareCandidates.classify(rfClassifier).eq(0)
  .updateMask(bareMask)
  .selfMask().connectedPixelCount(16, true).gte(9)
  .focal_mode({radius: 1, kernelType: 'square'})
  .unmask(0)
  .rename('sand_combined');

// ============================================================================
// XOR-КАРТА
// ============================================================================

// Значения: 0=ни один, 1=только RF, 2=только Combined, 3=оба
var rfBin = sandRF.unmask(0);
var coBin = sandCombined.unmask(0);

var diff = rfBin.add(coBin.multiply(2)).rename('diff');
// 0 = (0,0) ни один
// 1 = (1,0) только RF
// 2 = (0,1) только Combined
// 3 = (1,1) оба

// ============================================================================
// ПЛОЩАДИ КАТЕГОРИЙ
// ============================================================================

print('═══════════════════════════════════════');
print('DIFF: RF vs Combined');
print('═══════════════════════════════════════');

function getArea(img, name) {
  var area = img.multiply(ee.Image.pixelArea()).reduceRegion({
    reducer: ee.Reducer.sum(),
    geometry: scene.geometry(),
    scale: 10, maxPixels: 1e9, bestEffort: true, tileScale: 4
  });
  var km2 = ee.Number(area.get(img.bandNames().get(0))).divide(1e6);
  print(name + ':', km2, 'км²');
  return km2;
}

getArea(rfBin, 'RF всего');
getArea(coBin, 'Combined всего');

var onlyRF = diff.eq(1).rename('only_rf');
var onlyCombined = diff.eq(2).rename('only_combined');
var both = diff.eq(3).rename('both');

print('');
print('── Разложение ──');
getArea(onlyRF, 'Только RF (теряется в Combined)');
getArea(onlyCombined, 'Только Combined (добавляется к RF)');
getArea(both, 'Согласие');

// ============================================================================
// ВИЗУАЛИЗАЦИЯ
// ============================================================================

Map.setOptions('SATELLITE');
Map.centerObject(CENTER, 13);

// Подложка
Map.addLayer(masked, {bands: ['B4','B3','B2'], min: 0, max: 3000}, 'S2 True Color');

// Отдельные слои (выключены)
Map.addLayer(sandRF.selfMask(), {palette: ['4444FF']},
  'RF (весь)', false, 0.6);
Map.addLayer(sandCombined.selfMask(), {palette: ['FF44FF']},
  'Combined (весь)', false, 0.6);

// ГЛАВНАЯ КАРТА — XOR diff
//   1 = только RF        → синий    (что Combined отбрасывает, возможно шум)
//   2 = только Combined  → красный  (что Combined добавляет, возможно края)
//   3 = оба               → жёлтый   (согласие)
Map.addLayer(diff.selfMask(), {
  min: 1, max: 3,
  palette: ['0066FF', 'FF3300', 'FFFF00']
}, 'DIFF: синий=только RF, красный=только Combined, жёлтый=оба', true, 0.75);

// Отдельно компоненты для переключения
Map.addLayer(onlyRF.selfMask(), {palette: ['0066FF']},
  'ТОЛЬКО RF (возможно шум)', false, 0.8);
Map.addLayer(onlyCombined.selfMask(), {palette: ['FF3300']},
  'ТОЛЬКО Combined (возможно края)', false, 0.8);
Map.addLayer(both.selfMask(), {palette: ['FFFF00']},
  'Согласие RF+Combined', false, 0.8);

// Эталонные точки поверх
Map.addLayer(sandFC, {color: 'FFD700'}, 'Sand points', false);
Map.addLayer(lichenFC, {color: 'C8C878'}, 'Lichen points', false);

print('');
print('✓ Diff готов');
print('');
print('── Как смотреть ──');
print('1. Включи "DIFF" (он уже включён)');
print('2. Красные пятна = что добавляет Combined:');
print('   - если по краям жёлтых ядер → настоящие фронты раздувов');
print('   - если разрозненные вдали от ядер → артефакты');
print('3. Синие пятна = что отбрасывает Combined:');
print('   - если разрозненные одиночки → salt-and-pepper шум RF');
print('   - если сплошные области → Combined теряет настоящий сигнал');
print('');
print('Вывод:');
print('  красный=края + синий=шум  → Combined лучше');
print('  красный=шум               → RF лучше');
print('  синий=сигнал              → Combined ломает');
