/**
 * BareSand — Инвентаризация тайлов AOI (Фаза 2)
 *
 * Запускается ОДИН РАЗ. Находит все MGRS-тайлы, покрывающие AOI,
 * и лучшую сцену (мин. облачность) для каждого.
 *
 * Результат: словарь TILE_SCENES для копирования в 21_production_classify.js
 */

// ════════════════════════════════════════════════════════════════════════════
// AOI
// ════════════════════════════════════════════════════════════════════════════

var AOI_ASSET = 'projects/nodal-thunder-481307-u1/assets/baresand_aoi';
var aoi = ee.FeatureCollection(AOI_ASSET).geometry();

// ════════════════════════════════════════════════════════════════════════════
// ПАРАМЕТРЫ ПОИСКА
// ════════════════════════════════════════════════════════════════════════════

// Пик бесснежного сезона 2024–2025
var DATE_RANGES = [
  ['2024-07-10', '2024-09-10'],
  ['2025-07-10', '2025-09-10']
];

// Максимальная облачность
var CLOUD_MAX_SEARCH = 5;

// Морские тайлы отфильтруются вручную при просмотре списка

// ════════════════════════════════════════════════════════════════════════════
// СБОР КОЛЛЕКЦИИ S2
// ════════════════════════════════════════════════════════════════════════════

print('═══════════════════════════════════════');
print('ИНВЕНТАРИЗАЦИЯ ТАЙЛОВ AOI');
print('═══════════════════════════════════════');

// Объединение сезонов
var s2 = ee.ImageCollection([]);
DATE_RANGES.forEach(function(range) {
  var season = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(aoi)
    .filterDate(range[0], range[1])
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', CLOUD_MAX_SEARCH));
  s2 = s2.merge(season);
});

print('Всего сцен (облачность <' + CLOUD_MAX_SEARCH + '%):', s2.size());

// ════════════════════════════════════════════════════════════════════════════
// УНИКАЛЬНЫЕ ТАЙЛЫ + ЛУЧШАЯ СЦЕНА
// ════════════════════════════════════════════════════════════════════════════

// Получить все тайлы
var allTiles = s2.aggregate_array('MGRS_TILE').distinct().sort();
print('Уникальных MGRS-тайлов:', allTiles.size());

// Для каждого тайла: найти лучшую сцену (мин. облачность, предпочтение июль–август)
var tileInfo = allTiles.map(function(tile) {
  tile = ee.String(tile);

  // Все сцены этого тайла, лучшая = мин. облачность
  var tileScenes = s2.filter(ee.Filter.eq('MGRS_TILE', tile));
  var best = tileScenes.sort('CLOUDY_PIXEL_PERCENTAGE').first();

  var sceneId = best.get('system:index');
  var cloudPct = best.get('CLOUDY_PIXEL_PERCENTAGE');
  var dateStr = best.date().format('YYYY-MM-dd');
  var month = best.date().get('month');

  // Центроид тайла для оценки сложности
  var centroid = best.geometry().centroid(100);
  var lat = centroid.coordinates().get(1);

  // Оценка сложности по широте
  var complexity = ee.Algorithms.If(ee.Number(lat).gt(67), 'simple',
    ee.Algorithms.If(ee.Number(lat).gt(64), 'medium', 'complex'));

  return ee.Feature(centroid, {
    tile: tile,
    scene_id: sceneId,
    cloud_pct: cloudPct,
    date: dateStr,
    month: month,
    latitude: lat,
    complexity: complexity
  });
});

var landTiles = ee.FeatureCollection(tileInfo);

print('');
print('Тайлов:', landTiles.size());

// ════════════════════════════════════════════════════════════════════════════
// СТАТИСТИКА
// ════════════════════════════════════════════════════════════════════════════

print('');
print('── Распределение по сложности ──');
print(landTiles.aggregate_histogram('complexity'));

print('');
print('── Распределение по облачности ──');
var cloudStats = landTiles.aggregate_stats('cloud_pct');
print('Мин:', ee.Number(cloudStats.get('min')).format('%.1f'), '%');
print('Макс:', ee.Number(cloudStats.get('max')).format('%.1f'), '%');
print('Средняя:', ee.Number(cloudStats.get('mean')).format('%.1f'), '%');

print('');
print('── Распределение по месяцам ──');
print(landTiles.aggregate_histogram('month'));

// ════════════════════════════════════════════════════════════════════════════
// ТАБЛИЦА ТАЙЛОВ
// ════════════════════════════════════════════════════════════════════════════

print('');
print('══════════════════════════════════════════════════════════════');
print('ТАБЛИЦА ТАЙЛОВ (скопировать scene_id для 21_production_classify.js)');
print('══════════════════════════════════════════════════════════════');

// Сортировка по тайлу
var sorted = landTiles.sort('tile');
print(sorted);

// ════════════════════════════════════════════════════════════════════════════
// СЛОВАРЬ ДЛЯ КОПИРОВАНИЯ (формат для 21_production_classify.js)
// ════════════════════════════════════════════════════════════════════════════

// Печать в формате JS-словаря
// К сожалению, GEE не поддерживает серверный string concatenation в цикле,
// поэтому пользователь должен скопировать данные из таблицы выше.
// Ниже — evaluate для клиентского вывода (может быть медленным).

print('');
print('── TILE_SCENES (для копирования) ──');
print('Раскрой таблицу выше — для каждого тайла скопируй tile и scene_id');
print('Формат:');
print("  'TILE_ID': 'COPERNICUS/S2_SR_HARMONIZED/SCENE_ID',");

// Оценка трудозатрат
var numSimple = landTiles.filter(ee.Filter.eq('complexity', 'simple')).size();
var numMedium = landTiles.filter(ee.Filter.eq('complexity', 'medium')).size();
var numComplex = landTiles.filter(ee.Filter.eq('complexity', 'complex')).size();

print('');
print('── Оценка трудозатрат ──');
print('Простых (тундра, ~3 мин):', numSimple);
print('Средних (~5 мин):', numMedium);
print('Сложных (лес, ~8 мин):', numComplex);
// Оценка: simple*3 + medium*5 + complex*8
var totalMinutes = numSimple.multiply(3).add(numMedium.multiply(5)).add(numComplex.multiply(8));
var totalHours = totalMinutes.divide(60);
print('Ориентировочно:', totalMinutes, 'мин =', totalHours.format('%.1f'), 'часов');

// ════════════════════════════════════════════════════════════════════════════
// ВИЗУАЛИЗАЦИЯ
// ════════════════════════════════════════════════════════════════════════════

Map.setOptions('SATELLITE');
Map.centerObject(aoi, 5);

// AOI контур
Map.addLayer(ee.Image().paint(ee.FeatureCollection([ee.Feature(aoi)]), 0, 2),
  {palette: ['FF0000']}, 'AOI', true, 0.8);

// Тайлы по сложности
var simpleTiles = landTiles.filter(ee.Filter.eq('complexity', 'simple'));
var mediumTiles = landTiles.filter(ee.Filter.eq('complexity', 'medium'));
var complexTiles = landTiles.filter(ee.Filter.eq('complexity', 'complex'));

Map.addLayer(simpleTiles, {color: '00FF00'}, 'Простые (тундра)', true);
Map.addLayer(mediumTiles, {color: 'FFAA00'}, 'Средние', true);
Map.addLayer(complexTiles, {color: 'FF0000'}, 'Сложные (лес)', true);

print('');
print('✓ Инвентаризация завершена');
print('Зелёные = простые, оранжевые = средние, красные = сложные');
