/**
 * BareSand — Метод 1: Пороговая классификация
 *
 * Простейший метод. Если F1 >= 0.80 — RF не нужен (DNA §4.3).
 * Пороги калиброваны по Inspector (сцена 20240711, Надымские пески).
 */

// ============================================================================
// КОНФИГУРАЦИЯ
// ============================================================================

var AOI_ASSET = 'projects/nodal-thunder-481307-u1/assets/baresand_aoi';
var SCENE_ID = 'COPERNICUS/S2_SR_HARMONIZED/20240711T064629_20240711T064625_T42WXT';

// Пороги (из CONFIG, калиброваны по Inspector)
var NDVI_SAND_MAX = 0.15;
var BSI_SAND_MIN = 0.08;
var NDRE_SAND_MAX = 0.05;
var BRIGHTNESS_MIN = 2000;
var NDVI_VEG_THRESHOLD = 0.25;

// ============================================================================
// ЗАГРУЗКА И ПОДГОТОВКА
// ============================================================================

var scene = ee.Image(SCENE_ID);

// Облачная маска (DNA §3.1: SCL==5 НЕ маскируется)
var scl = scene.select('SCL');
var cloudMask = scl.eq(8).or(scl.eq(9)).or(scl.eq(10)).or(scl.eq(3)).or(scl.eq(11)).not();
var masked = scene.updateMask(cloudMask);

// Индексы
var B2 = masked.select('B2'), B3 = masked.select('B3'), B4 = masked.select('B4');
var B5 = masked.select('B5'), B8 = masked.select('B8'), B8A = masked.select('B8A');
var B11 = masked.select('B11'), B12 = masked.select('B12');

var NDVI = B8.subtract(B4).divide(B8.add(B4)).rename('NDVI');
var BSI = B11.add(B4).subtract(B8.add(B2)).divide(B11.add(B4).add(B8).add(B2)).rename('BSI');
var NDRE = B8A.subtract(B5).divide(B8A.add(B5)).rename('NDRE');
var MNDWI = B3.subtract(B11).divide(B3.add(B11)).rename('MNDWI');
var Brightness = B2.add(B3).add(B4).add(B8).divide(4).rename('Brightness');

// ============================================================================
// ПОРОГОВАЯ КЛАССИФИКАЦИЯ
// ============================================================================

print('═══════════════════════════════════════');
print('Метод 1: Пороговая классификация');
print('═══════════════════════════════════════');

// Шаг 1: убрать заведомо не-песок
var waterMask = MNDWI.lte(0);        // вода: MNDWI > 0
var vegMask = NDVI.lte(NDVI_VEG_THRESHOLD);  // густая растительность

// Шаг 2: правило для песка (трек C)
var sandMask = NDVI.lt(NDVI_SAND_MAX)
  .and(BSI.gt(BSI_SAND_MIN))
  .and(NDRE.lt(NDRE_SAND_MAX))
  .and(Brightness.gt(BRIGHTNESS_MIN))
  .and(waterMask)
  .and(vegMask)
  .rename('sand_threshold');

// Шаг 3: постфильтр — focal_mode 3×3 (убрать изолированные пиксели)
var sandFiltered = sandMask.focal_mode({radius: 1, kernelType: 'square'})
  .rename('sand_threshold');

// ============================================================================
// СТАТИСТИКА
// ============================================================================

// Площадь песка
var aoi = ee.FeatureCollection(AOI_ASSET).geometry();
var sandArea = sandFiltered.multiply(ee.Image.pixelArea())
  .reduceRegion({
    reducer: ee.Reducer.sum(),
    geometry: scene.geometry(),
    scale: 10,
    maxPixels: 1e9
  });
var sandKm2 = ee.Number(sandArea.get('sand_threshold')).divide(1e6);
print('Площадь песка:', sandKm2, 'км²');

// Число пикселей
var sandPixels = sandFiltered.reduceRegion({
  reducer: ee.Reducer.sum(),
  geometry: scene.geometry(),
  scale: 10,
  maxPixels: 1e9
});
print('Пикселей песка:', sandPixels.get('sand_threshold'));

print('');
print('Пороги:');
print('  NDVI <', NDVI_SAND_MAX);
print('  BSI >', BSI_SAND_MIN);
print('  NDRE <', NDRE_SAND_MAX);
print('  Brightness >', BRIGHTNESS_MIN);

// ============================================================================
// ВИЗУАЛИЗАЦИЯ
// ============================================================================

Map.setOptions('SATELLITE');
Map.centerObject(ee.Geometry.Point([73.31, 65.45]), 13);

// True Color
Map.addLayer(masked, {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000}, 'True Color');

// SWIR Composite
Map.addLayer(masked, {bands: ['B12', 'B11', 'B4'], min: 0, max: 4000}, 'SWIR Composite', false);

// Маска песка поверх true color
Map.addLayer(sandFiltered.selfMask(), {palette: ['FFD700']}, 'ПЕСОК (пороговый)', true, 0.7);

// Маска песка (без фильтра) для сравнения
Map.addLayer(sandMask.selfMask(), {palette: ['FF6600']}, 'ПЕСОК (до фильтра)', false, 0.7);

// Контрольные точки
Map.addLayer(ee.Geometry.Point([73.3137, 65.4428]), {color: 'red'}, 'Песок (ctrl)', false);
Map.addLayer(ee.Geometry.Point([73.3167, 65.4507]), {color: 'orange'}, 'Лишайник (ctrl)', false);

print('');
print('✓ Метод 1 завершён');
print('Визуальная проверка: жёлтые пятна = песок. Совпадают с яркими на true color?');

// Экспорт маски
exports.sandThreshold = sandFiltered;
exports.masked = masked;
exports.indices = {NDVI: NDVI, BSI: BSI, NDRE: NDRE, MNDWI: MNDWI, Brightness: Brightness};
