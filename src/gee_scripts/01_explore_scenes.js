/**
 * BareSand — Инвентаризация сцен Sentinel-2
 *
 * Назначение: обзор доступных сцен в AOI, выбор калибровочных.
 * Фаза 1 (эксперимент). Запускать в GEE Code Editor.
 *
 * Что делает:
 * 1. Загружает коллекцию S2 по AOI, дате, облачности
 * 2. Выводит статистику: число сцен, распределение по месяцам/облачности
 * 3. Для каждого эталонного участка: доступные сцены и лучшие даты
 * 4. Визуализирует AOI и лучшие сцены на карте
 *
 * Ограничения:
 * - НЕ фильтрует по SCL (на этом этапе не маскируем)
 * - НЕ создаёт мозаику/композит
 * - Только COPERNICUS/S2_SR_HARMONIZED
 */

// ============================================================================
// КОНФИГУРАЦИЯ
// Вариант 1: require (если скрипт в GEE-репозитории)
//   var CONFIG = require('users/USERNAME/baresand:gee_scripts/00_config').CONFIG;
//
// Вариант 2: скопируйте блок CONFIG из 00_config.js сюда.
//
// Ниже — inline-копия для автономного запуска:
// ============================================================================

var YAMAL_NAME = 'Yamalo-nenetskiy Okrug';

var gaul = ee.FeatureCollection('FAO/GAUL/2015/level1');
var russia = gaul.filter(ee.Filter.eq('ADM0_NAME', 'Russian Federation'));
var yamalFeature = russia.filter(ee.Filter.eq('ADM1_NAME', YAMAL_NAME));

// Проверка: если ЯНАО не найден — вывести все регионы для поиска
var yamalSize = yamalFeature.size();
if (yamalSize.getInfo() === 0) {
  print('⚠ ЯНАО не найден по имени: "' + YAMAL_NAME + '"');
  print('Все регионы РФ в FAO/GAUL (ищите ЯНАО):');
  print(russia.aggregate_array('ADM1_NAME').sort());
  throw new Error('Обновите YAMAL_NAME — правильное имя см. в списке выше');
}

var yamalGeom = yamalFeature.geometry();

// Восточное расширение: строго по Енисею + Гыданский полуостров
// Восточная граница трассирована по правому (западному) берегу Енисея
// Координаты верифицированы по Wikipedia, geographic.org, mapcarta.com
// Правый берег = западный при течении на север
var eastExtension = ee.Geometry.Polygon([
  [75.0, 61.5],   // ЮЗ — перекрытие с ЯНАО
  // --- Енисей: правый (западный) берег, юг → север ---
  [90.0, 61.5],   // Енисей у ~61.5°N — устье Подкаменной Тунгуски (61.59°N 90.13°E)
  [89.5, 62.0],   // Енисей ~62°N — река идёт на СЗ от устья Подкаменной Тунгуски
  [88.5, 62.5],   // Енисей ~62.5°N — правый берег, перегиб на запад
  [88.0, 63.0],   // Енисей ~63°N — р-н Бакланихи
  [87.5, 63.5],   // Енисей ~63.5°N — Сургутиха напротив (63.85°N 87.33°E)
  [87.4, 64.0],   // Енисей ~64°N — р-н Верещагино (64.16°N 87.39°E, правый берег)
  [87.5, 64.5],   // Енисей ~64.5°N — излучина к востоку
  [87.6, 65.0],   // Енисей ~65°N — р-н Фарково
  [87.8, 65.5],   // Енисей ~65.5°N — излучина перед Туруханском
  [87.9, 65.8],   // Туруханск (65.80°N 87.97°E) — устье Нижней Тунгуски
  [87.5, 66.2],   // Ниже Туруханска — река поворачивает на СЗ
  [87.2, 66.5],   // Курейка (66.47°N 87.17°E) — правый берег
  [86.8, 67.0],   // Енисей ~67°N — правый берег, р. Курейка
  [86.5, 67.5],   // Игарка напротив (67.47°N 86.58°E, вост. берег) — зап. берег ~86.5°E
  [86.4, 68.0],   // Енисей ~68°N — правый берег
  [86.3, 68.5],   // Потапово (68.68°N 86.28°E, правый берег)
  [86.2, 69.0],   // Дудинка (69.41°N 86.18°E, западный берег)
  [84.5, 69.5],   // Усть-Порт (69.67°N 84.43°E) — река резко расширяется
  // --- Енисейский залив: западный берег (Гыданская сторона) ---
  [83.5, 70.0],   // Вход в Енисейский залив — Бреховские о-ва (70.5°N 82.75°E)
  [82.5, 70.5],   // Западный берег залива ~70.5°N
  [81.5, 71.0],   // Залив ~71°N — ширина ~50 км, зап. берег ~81.5°E
  [80.5, 71.5],   // Залив ~71.5°N — Гыданский берег
  [80.0, 72.0],   // Залив ~72°N — сужение к северу
  [79.5, 72.5],   // Залив ~72.5°N — р-н о. Крестовский (72.4°N 80.8°E) — зап. берег
  [78.5, 73.0],   // Северный выход Енисейского залива
  [77.5, 73.2],   // СВ Гыдана
  [76.5, 73.4],   // Северный берег
  [75.5, 73.5],   // Мыс — северная оконечность
  [75.0, 73.3],   // СЗ склон
  [75.0, 61.5]    // Замыкание
]);

var aoi = yamalGeom.union(eastExtension);

// Конфигурация (минимальная копия из 00_config.js)
var CONFIG = {
  AOI: aoi,
  DATE_RANGES: [
    ['2024-06-20', '2024-10-11'],
    ['2025-06-10', '2025-10-11']
  ],
  S2_COLLECTION: 'COPERNICUS/S2_SR_HARMONIZED',
  CLOUD_MAX_PERCENT: 5,
  BANDS_C: ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'],
  SITES: {
    nadym_dunes: {
      point: ee.Geometry.Point([72.5, 65.5]),
      name: 'Надымские пески'
    },
    ob_salekhard: {
      point: ee.Geometry.Point([66.6, 66.5]),
      name: 'Обь у Салехарда'
    },
    taz_gulf: {
      point: ee.Geometry.Point([73.5, 67.5]),
      name: 'Тазовская губа'
    },
    noyabrsk: {
      point: ee.Geometry.Point([75.5, 63.2]),
      name: 'Ноябрьск'
    },
    taz_terrace: {
      point: ee.Geometry.Point([74.0, 65.0]),
      name: 'Терраса р. Таз'
    }
  },
  VIS_TRUE_COLOR: {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000},
  VIS_FALSE_COLOR: {bands: ['B8', 'B4', 'B3'], min: 0, max: 4000}
};

// ============================================================================
// 1. ЗАГРУЗКА КОЛЛЕКЦИИ S2
// ============================================================================

print('═══════════════════════════════════════');
print('BareSand — Инвентаризация сцен S2');
print('═══════════════════════════════════════');

// Сбор коллекции по сезонным окнам
var s2Collection = ee.ImageCollection([]);
CONFIG.DATE_RANGES.forEach(function(range) {
  var seasonal = ee.ImageCollection(CONFIG.S2_COLLECTION)
    .filterBounds(CONFIG.AOI)
    .filterDate(range[0], range[1])
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', CONFIG.CLOUD_MAX_PERCENT));
  s2Collection = s2Collection.merge(seasonal);
});

var sceneCount = s2Collection.size();
print('Всего сцен (cloud <' + CONFIG.CLOUD_MAX_PERCENT + '%):', sceneCount);
CONFIG.DATE_RANGES.forEach(function(range) {
  print('  ' + range[0] + ' \u2014 ' + range[1]);
});

// ============================================================================
// 2. РАСПРЕДЕЛЕНИЕ ПО МЕСЯЦАМ
// ============================================================================

/**
 * Подсчёт сцен по месяцам.
 * Показывает, в какие месяцы больше всего безоблачных сцен.
 */
var months = ee.List.sequence(1, 12);
var monthNames = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн',
                  'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'];

var monthlyCounts = months.map(function(m) {
  var count = s2Collection
    .filter(ee.Filter.calendarRange(m, m, 'month'))
    .size();
  return ee.Feature(null, {
    month: ee.List(monthNames).get(ee.Number(m).subtract(1)),
    month_num: m,
    count: count
  });
});

var monthlyFC = ee.FeatureCollection(monthlyCounts);
print('');
print('── Распределение по месяцам ──');
print(monthlyFC);

// ============================================================================
// 3. РАСПРЕДЕЛЕНИЕ ПО ОБЛАЧНОСТИ
// ============================================================================

/**
 * Гистограмма облачности: сколько сцен в каждом 5%-ном бине.
 * Помогает оценить качество данных.
 */
var cloudBins = ee.List.sequence(0, 25, 5);  // 0, 5, 10, 15, 20, 25%
var cloudDistribution = cloudBins.map(function(binStart) {
  var binEnd = ee.Number(binStart).add(5);
  var count = s2Collection
    .filter(ee.Filter.and(
      ee.Filter.gte('CLOUDY_PIXEL_PERCENTAGE', binStart),
      ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', binEnd)
    ))
    .size();
  return ee.Feature(null, {
    cloud_range: ee.String(ee.Number(binStart).format('%d'))
      .cat('–')
      .cat(ee.Number(binEnd).format('%d'))
      .cat('%'),
    count: count
  });
});

print('');
print('── Распределение по облачности ──');
print(ee.FeatureCollection(cloudDistribution));

// ============================================================================
// 4. РАСПРЕДЕЛЕНИЕ ПО ГОДАМ
// ============================================================================

[2024, 2025].forEach(function(year) {
  var yearCount = s2Collection
    .filterDate(year + '-01-01', year + '-12-31')
    .size();
  print('Сцен за ' + year + ':', yearCount);
});

// ============================================================================
// 5. ЭТАЛОННЫЕ УЧАСТКИ — ДОСТУПНЫЕ СЦЕНЫ
// ============================================================================

print('');
print('═══════════════════════════════════════');
print('Эталонные участки — доступные сцены');
print('═══════════════════════════════════════');

/**
 * Для каждого эталонного участка:
 * - число доступных сцен
 * - 10 лучших по минимальной облачности (с ID и датой)
 */
var siteKeys = Object.keys(CONFIG.SITES);

siteKeys.forEach(function(key) {
  var site = CONFIG.SITES[key];

  // Фильтрация сцен, покрывающих данный участок
  var siteColl = s2Collection.filterBounds(site.point);
  var siteCount = siteColl.size();

  print('');
  print('── ' + site.name + ' (' + key + ') ──');
  print('Доступно сцен:', siteCount);

  // Сортировка по облачности, вывод 10 лучших
  var bestScenes = siteColl
    .sort('CLOUDY_PIXEL_PERCENTAGE')
    .limit(10);

  // Список ID и дат лучших сцен
  var sceneInfo = bestScenes.map(function(img) {
    return ee.Feature(null, {
      scene_id: img.get('system:index'),
      date: ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
      cloud_pct: img.get('CLOUDY_PIXEL_PERCENTAGE'),
      mgrs_tile: img.get('MGRS_TILE')
    });
  });

  print('Лучшие 10 сцен (мин. облачность):');
  print(sceneInfo);
});

// ============================================================================
// 6. ПОЛНЫЙ СПИСОК ID СЦЕН ДЛЯ КАЖДОГО УЧАСТКА
// ============================================================================

print('');
print('═══════════════════════════════════════');
print('Полные списки ID сцен (для ручного выбора)');
print('═══════════════════════════════════════');

siteKeys.forEach(function(key) {
  var site = CONFIG.SITES[key];
  var siteColl = s2Collection.filterBounds(site.point);

  // Все ID сцен для участка
  var allIds = siteColl.aggregate_array('system:index');
  print('');
  print(site.name + ' — все ID (' + key + '):');
  print(allIds);
});

// ============================================================================
// 7. ВИЗУАЛИЗАЦИЯ НА КАРТЕ
// ============================================================================

// Центрировать карту на ЯНАО
Map.centerObject(CONFIG.AOI, 5);

// AOI — контур
var aoiOutline = ee.Image().byte().paint({
  featureCollection: ee.FeatureCollection([ee.Feature(CONFIG.AOI)]),
  color: 1,
  width: 2
});
Map.addLayer(aoiOutline, {palette: ['red']}, 'AOI — контур');

// ЯНАО — заливка полупрозрачная
var yamalOutline = ee.Image().byte().paint({
  featureCollection: yamalFeature,
  color: 1,
  width: 1
});
Map.addLayer(yamalOutline, {palette: ['blue']}, 'ЯНАО (GAUL)', false);

// Эталонные точки
siteKeys.forEach(function(key) {
  var site = CONFIG.SITES[key];
  Map.addLayer(site.point, {color: 'yellow'}, site.name, false);
});

// ============================================================================
// 8. ЛУЧШАЯ СЦЕНА НА НАДЫМСКИХ ПЕСКАХ
// ============================================================================

print('');
print('═══════════════════════════════════════');
print('Визуализация — Надымские пески');
print('═══════════════════════════════════════');

var nadymColl = s2Collection
  .filterBounds(CONFIG.SITES.nadym_dunes.point)
  .sort('CLOUDY_PIXEL_PERCENTAGE')
  .limit(1);

var bestNadym = ee.Image(nadymColl.first());
var bestNadymDate = ee.Date(bestNadym.get('system:time_start')).format('YYYY-MM-dd');
var bestNadymId = bestNadym.get('system:index');
var bestNadymCloud = bestNadym.get('CLOUDY_PIXEL_PERCENTAGE');

print('Лучшая сцена (Надым):', bestNadymId);
print('Дата:', bestNadymDate);
print('Облачность:', bestNadymCloud, '%');

// True Color (B4/B3/B2) — естественные цвета
Map.addLayer(
  bestNadym,
  CONFIG.VIS_TRUE_COLOR,
  'Надым — True Color (лучшая сцена)'
);

// False Color (B8/B4/B3) — песок выделяется на фоне растительности
Map.addLayer(
  bestNadym,
  CONFIG.VIS_FALSE_COLOR,
  'Надым — False Color NIR (лучшая сцена)',
  false  // выключен по умолчанию
);

// Приблизить к Надымским пескам
Map.centerObject(CONFIG.SITES.nadym_dunes.point, 11);

// ============================================================================
// 9. СВОДКА
// ============================================================================

print('');
print('═══════════════════════════════════════');
print('✓ Инвентаризация завершена');
print('═══════════════════════════════════════');
print('Следующий шаг: выбрать 3–5 калибровочных сцен из списков выше');
print('и перейти к 02_cloud_mask.js');
