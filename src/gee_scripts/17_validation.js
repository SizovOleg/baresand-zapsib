/**
 * BareSand — Валидация Combined на калибровочных сценах (Фаза 1C)
 *
 * Облегчённый режим: только sand + lichen (пре-фильтр убирает воду/растительность).
 * Один скрипт для всех 6 сцен. Переключение через SCENE_KEY.
 *
 * Workflow:
 *   1. Установить SCENE_KEY → Run → сцена на карте
 *   2. Создать Geometry Imports: sand, lichen → расставить точки
 *   3. Run → классификация + маска + площадь
 *   4. Создать: test_sand, test_not_sand → расставить точки
 *   5. Run → F1, OA, Kappa
 *
 * Training:  sand (15–20), lichen (10–15). Опционально: fire, gravel, peat
 * Test:      test_sand (8–10), test_not_sand (15–20)
 */

// ════════════════════════════════════════════════════════════════════════════
// НАСТРОЙКИ — МЕНЯТЬ ЗДЕСЬ
// ════════════════════════════════════════════════════════════════════════════

var SCENE_KEY = 'gydan';
// Варианты: 'nadym_dunes', 'gydan', 'taz_gulf',
//           'noyabrsk', 'nadym_terrace', 'yaratto'

// ════════════════════════════════════════════════════════════════════════════
// КОНФИГУРАЦИЯ (не менять между сценами)
// ════════════════════════════════════════════════════════════════════════════

var SCENES = {
  nadym_dunes:    'COPERNICUS/S2_SR_HARMONIZED/20250810T064641_20250810T064704_T42WXT',
  gydan:          'COPERNICUS/S2_SR_HARMONIZED/20240811T070621_20240811T070622_T43WET',
  taz_gulf:       'COPERNICUS/S2_SR_HARMONIZED/20240724T065629_20240724T065905_T42WXA',
  noyabrsk:       'COPERNICUS/S2_SR_HARMONIZED/20250730T062629_20250730T063043_T43VEL',
  nadym_terrace:  'COPERNICUS/S2_SR_HARMONIZED/20240718T063629_20240718T063627_T43WDN',
  yaratto:        'COPERNICUS/S2_SR_HARMONIZED/20250823T065641_20250823T065640_T42WWA'
};

var SCENE_NAMES = {
  nadym_dunes:   'Надымские пески (эоловый)',
  gydan:         'Гыданская гряда',
  taz_gulf:      'Тазовская губа (морская отмель)',
  noyabrsk:      'Ноябрьск (антропоген)',
  nadym_terrace: 'Терраса р. Надым (эоловый у реки)',
  yaratto:       'Яратто (озёра + пески + тундра)'
};

var RF_TREES = 200;
var RF_MIN_LEAF = 5;
var RF_BAG_FRACTION = 0.5;
var RF_SEED = 42;
var MMU_PIXELS = 9;

var NDVI_VEG_MAX = 0.40;
var MNDWI_WATER_MAX = 0;

// ════════════════════════════════════════════════════════════════════════════
// ЗАГРУЗКА СЦЕНЫ
// ════════════════════════════════════════════════════════════════════════════

var sceneId = SCENES[SCENE_KEY];
var sceneName = SCENE_NAMES[SCENE_KEY];

print('═══════════════════════════════════════');
print('СЦЕНА: ' + sceneName);
print('ID: ' + sceneId);
print('═══════════════════════════════════════');

var scene = ee.Image(sceneId);
var scl = scene.select('SCL');
var cloudMask = scl.eq(8).or(scl.eq(9)).or(scl.eq(10)).or(scl.eq(3)).or(scl.eq(11)).not();
var masked = scene.updateMask(cloudMask);

// ════════════════════════════════════════════════════════════════════════════
// СПЕКТРАЛЬНЫЙ СТЕК
// ════════════════════════════════════════════════════════════════════════════

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

// ════════════════════════════════════════════════════════════════════════════
// ПОДЛОЖКА (всегда первой)
// ════════════════════════════════════════════════════════════════════════════

Map.setOptions('SATELLITE');
Map.centerObject(scene.geometry(), 11);
Map.addLayer(masked, {bands: ['B8','B4','B3'], min: 180, max: 4950}, 'False Color (B8-B4-B3)');
Map.addLayer(masked, {bands: ['B4','B3','B2'], min: 0, max: 3000}, 'True Color', false);
Map.addLayer(masked, {bands: ['B12','B11','B4'], min: 0, max: 4000}, 'SWIR Composite', false);

// ════════════════════════════════════════════════════════════════════════════
// ОБУЧАЮЩАЯ ВЫБОРКА
// ════════════════════════════════════════════════════════════════════════════

var hasTraining = (typeof sand !== 'undefined') && (typeof lichen !== 'undefined');

function importToFC(geom, classCode) {
  return ee.FeatureCollection(geom.coordinates().map(function(c) {
    return ee.Feature(ee.Geometry.Point(c), {class: classCode});
  }));
}

if (!hasTraining) {
  print('');
  print('⚠ Обучающие точки не найдены.');
  print('');
  print('Создай Geometry Imports:');
  print('  1. sand    (15–20 точек) — ядра и края раздувов');
  print('  2. lichen  (10–15 точек) — лишайниковые пустоши рядом');
  print('  Опционально: fire, gravel, peat, anthropogenic');
  print('');
  print('Расставь точки → Run.');

} else {

  var sandFC = importToFC(sand, 0);
  var lichenFC = importToFC(lichen, 1);
  var allTraining = sandFC.merge(lichenFC);

  // Опциональные классы — раскомментируй если Geometry Import создан:
  // var fireFC = importToFC(fire, 8);
  // allTraining = allTraining.merge(fireFC);
  // var vegFC = importToFC(vegetation, 5);
  // allTraining = allTraining.merge(vegFC);
  // var gravelFC = importToFC(gravel, 2);
  // allTraining = allTraining.merge(gravelFC);
  // var peatFC = importToFC(peat, 3);
  // allTraining = allTraining.merge(peatFC);
  // var anthropogenicFC = importToFC(anthropogenic, 4);
  // allTraining = allTraining.merge(anthropogenicFC);

  print('Обучающая выборка:', allTraining.size(), 'точек');
  print('  sand:', sandFC.size(), '  lichen:', lichenFC.size());

  // ════════════════════════════════════════════════════════════════════════
  // КЛАССИФИКАЦИЯ: COMBINED
  // ════════════════════════════════════════════════════════════════════════

  var bareMask = MNDWI.lte(MNDWI_WATER_MAX)
    .and(NDVI.lte(NDVI_VEG_MAX))
    .and(scl.neq(11));
  var bareCandidates = stack.updateMask(bareMask);

  var training = stack.sampleRegions({
    collection: allTraining, properties: ['class'], scale: 10
  });

  var rfClassifier = ee.Classifier.smileRandomForest({
    numberOfTrees: RF_TREES,
    minLeafPopulation: RF_MIN_LEAF,
    bagFraction: RF_BAG_FRACTION,
    seed: RF_SEED
  }).train({
    features: training,
    classProperty: 'class',
    inputProperties: stackBands
  });

  var importance = rfClassifier.explain().get('importance');
  print('');
  print('── Variable Importance ──');
  print(importance);

  var classified = bareCandidates.classify(rfClassifier);

  var sandMask = classified.eq(0)
    .updateMask(bareMask)
    .selfMask()
    .connectedPixelCount(16, true).gte(MMU_PIXELS)
    .focal_mode({radius: 1, kernelType: 'square'})
    .unmask(0)
    .rename('sand_combined');

  // ════════════════════════════════════════════════════════════════════════
  // ПЛОЩАДЬ
  // ════════════════════════════════════════════════════════════════════════

  var areaResult = sandMask.multiply(ee.Image.pixelArea()).reduceRegion({
    reducer: ee.Reducer.sum(),
    geometry: scene.geometry(),
    scale: 10,
    maxPixels: 1e9,
    bestEffort: true,
    tileScale: 4
  });
  var areaKm2 = ee.Number(areaResult.get('sand_combined')).divide(1e6);

  print('');
  print('── Результат Combined ──');
  print('Площадь:', areaKm2, 'км²');

  // ════════════════════════════════════════════════════════════════════════
  // ВАЛИДАЦИЯ
  // ════════════════════════════════════════════════════════════════════════

  var hasTest = (typeof test_sand !== 'undefined') &&
                (typeof test_not_sand !== 'undefined');

  if (hasTest) {
    var testSandFC = importToFC(test_sand, 0).map(function(f) {
      return f.set('binary_class', 1);
    });
    var testNotSandFC = importToFC(test_not_sand, 1).map(function(f) {
      return f.set('binary_class', 0);
    });
    var testAll = testSandFC.merge(testNotSandFC);

    print('');
    print('Контрольные точки:', testAll.size(),
          '(test_sand:', testSandFC.size(), ', test_not_sand:', testNotSandFC.size(), ')');

    var sandMaskForTest = sandMask.rename('predicted');
    var testWithPredicted = sandMaskForTest.sampleRegions({
      collection: testAll,
      properties: ['binary_class'],
      scale: 10
    });

    var errorMatrix = testWithPredicted.errorMatrix('binary_class', 'predicted');
    var oa = errorMatrix.accuracy();
    var kappa = errorMatrix.kappa();
    var producersAcc = errorMatrix.producersAccuracy();
    var consumersAcc = errorMatrix.consumersAccuracy();

    var pa_sand = ee.Number(producersAcc.get([1, 0]));
    var ua_sand = ee.Number(consumersAcc.get([0, 1]));
    var f1_sand = ee.Number(2).multiply(pa_sand).multiply(ua_sand)
      .divide(pa_sand.add(ua_sand));

    print('');
    print('═══════════════════════════════════════');
    print('ACCURACY: ' + sceneName);
    print('═══════════════════════════════════════');
    print('');
    print('Confusion Matrix (binary):');
    print(errorMatrix);
    print('');
    print('OA:       ', oa);
    print('Kappa:    ', kappa);
    print('F1(sand): ', f1_sand);
    print('PA(sand): ', pa_sand, '  (recall)');
    print('UA(sand): ', ua_sand, '  (precision)');
    print('Площадь:  ', areaKm2, 'км²');

    var status = ee.Algorithms.If(
      f1_sand.gte(0.80), '✓ F1 >= 0.80 — ПРОЙДЕН',
      ee.Algorithms.If(
        f1_sand.gte(0.70), '⚠ F1 0.70–0.80 — ДОРАБОТКА',
        '✗ F1 < 0.70 — СТОП'
      )
    );
    print('СТАТУС:', status);

    var errors = testWithPredicted.map(function(f) {
      var ref = ee.Number(f.get('binary_class'));
      var pred = ee.Number(f.get('predicted'));
      var errorType = ee.Algorithms.If(ref.eq(pred), 0,
        ee.Algorithms.If(pred.eq(1), 1, 2));
      return f.set('error_type', errorType);
    });
    Map.addLayer(errors.filter(ee.Filter.eq('error_type', 1)),
      {color: 'FF0000'}, '✗ False Positive', true);
    Map.addLayer(errors.filter(ee.Filter.eq('error_type', 2)),
      {color: '0000FF'}, '✗ False Negative', true);
    Map.addLayer(errors.filter(ee.Filter.eq('error_type', 0)),
      {color: '00FF00'}, '✓ Correct', false);
  } else {
    print('');
    print('⚠ Тестовые точки не найдены.');
    print('Создай: test_sand (8–10), test_not_sand (15–20) → Run');
  }

  Map.addLayer(sandMask.selfMask(), {palette: ['FFD700']},
    'ПЕСОК Combined', true, 0.7);
  Map.addLayer(classified.clip(scene.geometry()), {
    min: 0, max: 8,
    palette: ['#FFD700','#C8E6C9','#9E9E9E','#795548','#F44336',
              '#4CAF50','#2196F3','#FFFFFF','#FF8C00']
  }, 'RF (все классы)', false);

  Map.addLayer(sandFC, {color: 'FFD700'}, 'Train: sand', false);
  Map.addLayer(lichenFC, {color: 'C8C878'}, 'Train: lichen', false);

  print('');
  print('✓ Классификация завершена');

} // конец if(hasTraining)
