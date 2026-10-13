/**
 * BareSand — Production: классификация одного тайла (Фаза 2)
 *
 * Workflow:
 *   1. Установить TILE_KEY → Run → лучшая сцена загрузится
 *   2. Создать sand (15–20) + lichen (10–15) → Run
 *   3. Визуальная проверка маски
 *   4. Tasks → Run export
 *   5. Save As → 21_{tile_id}
 */

// ════════════════════════════════════════════════════════════════════════════
// НАСТРОЙКИ — МЕНЯТЬ ЗДЕСЬ
// ════════════════════════════════════════════════════════════════════════════

var TILE_KEY = '43WDP';  // ← менять для каждого тайла

// ════════════════════════════════════════════════════════════════════════════
// ПАРАМЕТРЫ (НЕ менять между тайлами)
// ════════════════════════════════════════════════════════════════════════════

var PROJECT = 'projects/nodal-thunder-481307-u1/assets';
var RF_TREES = 200;
var RF_MIN_LEAF = 5;
var RF_BAG_FRACTION = 0.5;
var RF_SEED = 42;
var MMU_PIXELS = 9;
var NDVI_VEG_MAX = 0.40;
var MNDWI_WATER_MAX = 0;

// ════════════════════════════════════════════════════════════════════════════
// АВТОПОИСК ЛУЧШЕЙ СЦЕНЫ
// ════════════════════════════════════════════════════════════════════════════

// Широкий поиск: 2020–2025, июнь–октябрь, <15%. Берёт лучшую по облачности.
var scene = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filter(ee.Filter.eq('MGRS_TILE', TILE_KEY))
  .filterDate('2020-06-01', '2025-10-01')
  .filter(ee.Filter.calendarRange(7, 9, 'month'))
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 15))
  .sort('CLOUDY_PIXEL_PERCENTAGE')
  .first();

print('═══════════════════════════════════════');
print('ТАЙЛ: ' + TILE_KEY);
print('Сцена:', scene.get('system:index'));
print('Дата:', scene.date().format('YYYY-MM-dd'));
print('Облачность:', scene.get('CLOUDY_PIXEL_PERCENTAGE'), '%');
print('═══════════════════════════════════════');

var scl = scene.select('SCL');
// SCL==11 (снег) НЕ маскируем — на >67°N SCL путает яркий песок со снегом
var cloudMask = scl.eq(8).or(scl.eq(9)).or(scl.eq(10)).or(scl.eq(3)).not();
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
// ПОДЛОЖКА
// ════════════════════════════════════════════════════════════════════════════

Map.setOptions('SATELLITE');
Map.centerObject(scene.geometry(), 11);
Map.addLayer(masked, {bands: ['B8','B4','B3'], min: 180, max: 4950}, 'False Color');
Map.addLayer(masked, {bands: ['B4','B3','B2'], min: 0, max: 3000}, 'True Color', false);
Map.addLayer(masked, {bands: ['B12','B11','B4'], min: 0, max: 4000}, 'SWIR', false);

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
  print('Создай: sand (15-20 pts) + lichen (10-15 pts) → Run');

} else {

  var sandFC = importToFC(sand, 0);
  var lichenFC = importToFC(lichen, 1);
  var allTraining = sandFC.merge(lichenFC);

  // Опционально:
  // var fireFC = importToFC(fire, 8); allTraining = allTraining.merge(fireFC);
  // var vegFC = importToFC(vegetation, 5); allTraining = allTraining.merge(vegFC);
  // var anthropogenicFC = importToFC(anthropogenic, 4); allTraining = allTraining.merge(anthropogenicFC);

  print('Training:', allTraining.size(), '(sand:', sandFC.size(), ', lichen:', lichenFC.size(), ')');

  // ── COMBINED ──

  var bareMask = MNDWI.lte(MNDWI_WATER_MAX).and(NDVI.lte(NDVI_VEG_MAX));
  var bareCandidates = stack.updateMask(bareMask);

  var training = stack.sampleRegions({collection: allTraining, properties: ['class'], scale: 10});

  var rfClassifier = ee.Classifier.smileRandomForest({
    numberOfTrees: RF_TREES, minLeafPopulation: RF_MIN_LEAF,
    bagFraction: RF_BAG_FRACTION, seed: RF_SEED
  }).train({features: training, classProperty: 'class', inputProperties: stackBands});

  var classified = bareCandidates.classify(rfClassifier);

  var sandMask = classified.eq(0)
    .updateMask(bareMask).selfMask()
    .connectedPixelCount(16, true).gte(MMU_PIXELS)
    .focal_mode({radius: 1, kernelType: 'square'})
    .unmask(0).rename('sand_combined');

  // ── ПЛОЩАДЬ ──

  var areaKm2 = ee.Number(sandMask.multiply(ee.Image.pixelArea()).reduceRegion({
    reducer: ee.Reducer.sum(), geometry: scene.geometry(),
    scale: 10, maxPixels: 1e9, bestEffort: true, tileScale: 4
  }).get('sand_combined')).divide(1e6);

  print('');
  print('Площадь:', areaKm2, 'км²');

  // ── ЭКСПОРТ ──

  var cloudPct = ee.Number(scene.get('CLOUDY_PIXEL_PERCENTAGE'));
  Export.image.toAsset({
    image: sandMask.toByte().rename('sand_mask')
      .addBands(ee.Image.constant(cloudPct).float().rename('cloud_score')),
    description: 'baresand_' + TILE_KEY,
    assetId: PROJECT + '/baresand_mask_' + TILE_KEY,
    region: scene.geometry(), scale: 10,
    maxPixels: 1e10
  });

  print('✓ Export: baresand_mask_' + TILE_KEY + ' → Tasks → Run');

  // ── КАРТА ──

  Map.addLayer(sandMask.selfMask(), {palette: ['FFD700']}, 'ПЕСОК', true, 0.7);
  Map.addLayer(sandFC, {color: 'FFD700'}, 'sand', false);
  Map.addLayer(lichenFC, {color: 'C8C878'}, 'lichen', false);

  print('Save As → 21_' + TILE_KEY);

}
