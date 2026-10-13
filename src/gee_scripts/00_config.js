/**
 * BareSand — Конфигурация проекта
 *
 * Единый источник всех параметров. Все скрипты используют CONFIG из этого файла.
 * Хардкод порогов в других скриптах запрещён (DNA §3.4, RNA §6).
 *
 * Использование в других скриптах GEE Code Editor:
 *   var CONFIG = require('users/USERNAME/baresand:gee_scripts/00_config').CONFIG;
 *
 * Если require не работает — скопируйте блок CONFIG в начало скрипта.
 */

// ============================================================================
// AOI — территория исследования
// ============================================================================

// Северная часть Западно-Сибирской равнины.
// Граница: ЯНАО (GAUL) + восточное расширение до Енисея (LSIB береговая линия).
// Финальный AOI выгружен как SHP → загружен как GEE Asset.
//
// Если Asset загружен — используем его (быстро, без вычислений).
// Если нет — строим на лету из GAUL + LSIB (v12c).

var AOI_ASSET = 'projects/nodal-thunder-481307-u1/assets/baresand_aoi';

// Попытка загрузки из Asset
var aoi;
try {
  aoi = ee.FeatureCollection(AOI_ASSET).geometry();
  print('AOI загружен из Asset:', AOI_ASSET);
} catch(e) {
  // Fallback: строим на лету
  print('Asset не найден, строим AOI на лету (GAUL + LSIB)...');

  var gaul = ee.FeatureCollection('FAO/GAUL/2015/level1');
  var yanao = gaul.filter(ee.Filter.eq('ADM0_NAME', 'Russian Federation'))
    .filter(ee.Filter.eq('ADM1_NAME', 'Yamalo-nenetskiy Okrug'));
  var yanaoGeom = yanao.geometry();

  var russia = ee.FeatureCollection('USDOS/LSIB_SIMPLE/2017')
    .filter(ee.Filter.eq('country_na', 'Russia'));
  var russiaGeom = russia.geometry();

  // Клип: восточная граница по Енисею (юг) и середине залива (север)
  var eastClip = ee.Geometry.Polygon([
    [75.0, 61.5],
    [90.0, 61.5],
    [89.5, 62.0],
    [88.5, 62.5],
    [88.0, 63.0],
    [87.7, 63.5],
    [87.5, 64.0],
    [87.4, 64.5],
    [87.5, 65.0],
    [87.8, 65.5],
    [87.9, 65.8],    // Туруханск
    [87.5, 66.2],
    [87.2, 66.5],    // Курейка
    [86.8, 67.0],
    [86.5, 67.5],    // Игарка
    [86.3, 68.0],
    [86.2, 68.5],
    [86.0, 69.0],    // Дудинка
    [85.5, 69.2],
    [85.0, 69.35],
    [84.5, 69.5],    // Усть-Порт
    // Середина Енисейского залива
    [84.5, 70.0],
    [84.0, 71.0],
    [83.0, 72.0],
    [82.0, 73.0],
    [80.0, 74.0],
    [75.0, 74.0],
    [75.0, 61.5]
  ]);

  var gydanCoast = russiaGeom.intersection(eastClip);
  aoi = yanaoGeom.union(gydanCoast);
}

// ============================================================================
// ПАРАМЕТРЫ ДАННЫХ
// ============================================================================

var CONFIG = {

  // --- Территория ---
  AOI: aoi,
  AOI_YAMAL: yamalGeom,
  AOI_EAST_EXTENSION: eastExtension,

  // --- Временной диапазон (бесснежный сезон) ---
  // Сезонные окна (бесснежный период)
  // 2024: 20 июня — 10 октября, 2025: 10 июня — 10 октября
  DATE_RANGES: [
    ['2024-06-20', '2024-10-11'],
    ['2025-06-10', '2025-10-11']
  ],

  // --- Коллекция Sentinel-2 ---
  S2_COLLECTION: 'COPERNICUS/S2_SR_HARMONIZED',
  S2_CLOUD_PROB_COLLECTION: 'COPERNICUS/S2_CLOUD_PROBABILITY',
  CLOUD_MAX_PERCENT: 5,    // максимальный % облачности сцены

  // --- Наборы каналов ---
  // Трек A: только 10м
  BANDS_A: ['B2', 'B3', 'B4', 'B8'],
  // Трек B: 10м + SWIR 20м
  BANDS_B: ['B2', 'B3', 'B4', 'B8', 'B11', 'B12'],
  // Трек C: полный набор (основной) — 10м + Red Edge + SWIR
  BANDS_C: ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'],

  // --- Параметры Random Forest ---
  RF_TREES: 200,
  RF_MIN_LEAF: 5,
  RF_BAG_FRACTION: 0.5,
  RF_SEED: 42,

  // --- Пороги классификации (калиброваны по сцене 20240711 T42WXT, Надымские пески) ---
  NDVI_VEG_THRESHOLD: 0.40,      // выше — растительность (ослаблено с 0.25: мокрый песок на 68°N имеет NDVI до 0.36 из-за субпиксельного мха)
  NDVI_SAND_MAX: 0.15,           // песок: 0.085, лишайник: 0.293
  BSI_SAND_MIN: 0.04,            // песок: 0.144, лишайник: 0.027 (исходно 0.08, ослаблено)
  NDRE_SAND_MAX: 0.05,           // песок: 0.037, лишайник: 0.217 — КЛЮЧЕВОЙ дискриминатор
  BRIGHTNESS_MIN: 1400,           // песок: 3260, лишайник: 1653 (исходно 2000, ослаблено)
  CLOUD_PROB_THRESHOLD: 40,       // порог Cloud Probability (%)
  MMU_PIXELS: 9,                  // минимальный объект: 3×3 пикселя = 900 м²

  // --- Контрольные точки (верифицированы Inspector 2024-07-11) ---
  CONTROL_POINTS: {
    sand:   {lon: 73.3137, lat: 65.4428, description: 'Открытый раздув, Надымские пески'},
    lichen: {lon: 73.3167, lat: 65.4507, description: 'Лишайниковая пустошь рядом'}
  },

  // --- Калибровочные сцены (выбраны в PROMPT_01) ---
  CALIBRATION_SCENES: {
    nadym_dunes:  '20250810T064641_20250810T064704_T42WXT',
    gydan:        '20240811T070621_20240811T070622_T43WET',
    taz_gulf:     '20240724T065629_20240724T065905_T42WXA',
    noyabrsk:     '20250730T062629_20250730T063043_T43VEL',
    nadym_terrace: '20240718T063629_20240718T063627_T43WDN',
    yaratto:       '20250823T065641_20250823T065640_T42WWA'
  },

  // --- Классы покрова ---
  CLASSES: {
    bare_sand: 0,
    lichen_barren: 1,
    gravel: 2,
    bare_peat: 3,
    anthropogenic: 4,
    vegetation: 5,
    water: 6,
    snow_ice: 7,
    fire: 8
  },

  // Имена классов для вывода
  CLASS_NAMES: [
    'bare_sand',        // 0
    'lichen_barren',    // 1
    'gravel',           // 2
    'bare_peat',        // 3
    'anthropogenic',    // 4
    'vegetation',       // 5
    'water',            // 6
    'snow_ice',         // 7
    'fire'              // 8
  ],

  // --- Генезис песка (постклассификация, Фаза 3) ---
  GENESIS_TYPES: {
    aeolian: 'aeolian',
    alluvial_littoral: 'alluvial_littoral',
    anthropogenic: 'anthropogenic',
    undefined: 'undefined'
  },

  // --- Эталонные участки ---
  SITES: {
    nadym_dunes: {
      point: ee.Geometry.Point([72.5, 65.5]),
      name: 'Надымские пески',
      type: 'aeolian',
      description: 'Дюнное поле, калибровка E-правил'
    },
    gydan: {
      point: ee.Geometry.Point([76.0, 68.5]),
      name: 'Гыданская гряда',
      type: 'aeolian_tundra',
      description: 'Водораздельная тундра, эоловые пески'
    },
    taz_gulf: {
      point: ee.Geometry.Point([73.5, 67.5]),
      name: 'Тазовская губа',
      type: 'alluvial_marine',
      description: 'Морские отмели, калибровка W3'
    },
    noyabrsk: {
      point: ee.Geometry.Point([75.5, 63.2]),
      name: 'Ноябрьск',
      type: 'anthropogenic',
      description: 'Техногенные площадки, калибровка A-правил'
    },
    nadym_terrace: {
      point: ee.Geometry.Point([74.0, 65.0]),
      name: 'Терраса р. Надым',
      type: 'aeolian_near_river',
      description: 'Эоловый у реки, конфликт E/W'
    },
    yaratto: {
      point: ee.Geometry.Point([70.64, 68.11]),
      name: 'Яратто (Южный Ямал)',
      type: 'complex',
      description: 'Озёра + пески + тундра, сложный регион'
    }
  },

  // --- GEE-ассеты для атрибуции генезиса (Фаза 3) ---
  GSW_ASSET: 'JRC/GSW1_4/GlobalSurfaceWater',
  GSW_MONTHLY_ASSET: 'JRC/GSW1_4/MonthlyRecurrence',
  HYDRO_RIVERS_ASSET: 'WWF/HydroSHEDS/v1/FreeFlowingRivers',

  // --- Обучающая выборка ---
  // Пос-сценная: train_{YYYYMMDD}_{TILE}.geojson → GEE Asset
  TRAINING_ASSET_PREFIX: 'users/USERNAME/baresand_train_',
  TRAINING_MIN_SAND: 10,         // мин. полигонов песка на сцену
  TRAINING_MIN_LICHEN: 8,        // мин. полигонов лишайника
  TRAINING_MIN_CLASSES: 5,       // мин. различных классов
  TRAINING_SPLIT_BUFFER_M: 200,  // мин. расстояние между train и test полигонами

  // --- Визуализация ---
  VIS_TRUE_COLOR: {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000},
  VIS_FALSE_COLOR: {bands: ['B8', 'B4', 'B3'], min: 0, max: 4000},
  VIS_SWIR: {bands: ['B12', 'B11', 'B4'], min: 0, max: 4000},
  VIS_SAND_MASK: {min: 0, max: 1, palette: ['black', 'yellow']},
  VIS_CLASSES: {
    min: 0, max: 7,
    palette: [
      '#FFD700',  // 0 bare_sand — золотой
      '#C8E6C9',  // 1 lichen_barren — бледно-зелёный
      '#9E9E9E',  // 2 gravel — серый
      '#795548',  // 3 bare_peat — коричневый
      '#F44336',  // 4 anthropogenic — красный
      '#4CAF50',  // 5 vegetation — зелёный
      '#2196F3',  // 6 water — синий
      '#FFFFFF'   // 7 snow_ice — белый
    ]
  }
};

// ============================================================================
// ЭКСПОРТ
// ============================================================================

exports.CONFIG = CONFIG;

print('✓ CONFIG загружен. AOI:', aoi);
print('ЯНАО найден:', yamalFeature.first().get('ADM1_NAME'));
