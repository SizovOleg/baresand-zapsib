/*
 * BareSand: оголённые пески севера Западной Сибири.
 * Интерактивная карта Google Earth Engine (Code Editor, ui API, JavaScript ES5).
 * Материалы и описание: https://github.com/SizovOleg/baresand-zapsib (gee_app/README.md).
 *
 * Данные: итоговый слой генезиса и группы техногенных песков (docs/DATA.md), маска песка и первичный вектор
 * (src/gee_scripts/22_mosaic_export.js, src/python/30_vectorize_local.py), сцены Sentinel-2 по тайлам (supplement/S07).
 * Загрузка ассетов: src/python/150_gee_upload.py.
 *
 * Что настроить перед запуском: раздел 1 (PROJECT, ASSETS, LINKS). Остальные разделы менять не нужно.
 * Пока путь ассета содержит '<PROJECT>', слой помечается «ассет не задан» и не загружается.
 */

// ============================================================================
// 1. НАСТРОЙКИ: ПУТИ К АССЕТАМ И ССЫЛКИ (заглушки)
// ============================================================================

// Папка ассетов. Ассеты загружены src/python/150_gee_upload.py: таблицы частями <слой>_pNNN, крупные склеены в один
// ассет; геометрия упрощена на 10 м (пиксель маски).
var ROOT_ASSETS = 'projects/nodal-thunder-481307-u1/assets/ZapSib_baresands';
var PROJECT = ROOT_ASSETS + '/app';

var ASSETS = {
  // граница района работ, покрытие маски, следы 128 тайлов
  aoi: ROOT_ASSETS + '/baresand_aoi_v2',
  coverage: PROJECT + '/coverage_p000',
  tiles: PROJECT + '/tiles_p000',
  // первичная маска: растр 10 м по району работ (gee_scripts/22_mosaic_export.js), канал sand_mask
  maskRaster: ROOT_ASSETS + '/baresand_mask_AOI_v2',
  // первичный вектор (src/python/30_vectorize_local.py)
  contours: PROJECT + '/contours',
  // итоговый слой генезиса v7 (поля id, genesis, area_ha, step6_rule, gcode) и обзорный растр классов gcode 50 м
  // (из таблицы на стороне EE, 150 --class-raster): на мелких масштабах контуры меньше ячейки не видны
  genesis: PROJECT + '/genesis',
  genesisRaster: PROJECT + '/genesis_r50',
  // техногенные пески по отношению к кадастровым отводам (133, вариант А 13.10.2026, редакция v7b от 03.11.2026:
  // территория населённых пунктов и части единых землепользований считаются отводом, участки крупнее 1000 га нет;
  // превышение отвода; объекты без отвода, включая касающиеся чужого участка)
  // обобщённая маска отводов под объекты (156): участки ЕГРН ближе 60 м к техногенным пескам, слиты, без атрибутов
  allotments: PROJECT + '/allotments',
  anthroIn: PROJECT + '/anthro_in',
  anthroExceed: PROJECT + '/anthro_exceed',
  anthroNoallot: PROJECT + '/anthro_noallot',
  // плотность: растры density_<класс>_<ячейка>km (150 --density-grid, EPSG:3576), пути строит densityAsset()
  // районы со статистикой (155) для выбора района в правой панели
  districts: PROJECT + '/districts',
  // инфраструктура OSM (150): линии (поле kind: road_major, road_minor, road_track, rail, rail_old, pipeline, power;
  // winter = 1 у зимников) и площадки (kind: industrial, quarry, storage_tank и др.)
  infraLines: PROJECT + '/infra_lines',
  infraAreas: PROJECT + '/infra_areas',
  // дополнительные слои
  // месторождения: в приложении не показываются
  oilfields: ''
};


// FeatureView (необязательно, README, шаг 5): быстрый показ векторов с крупных масштабов. Пусто: векторы рисуются из
// таблиц (ee.Image.paint) начиная с масштаба Z_VECTOR.
var FEATURE_VIEWS = {
  contours: '',
  genesis: '',
  anthroIn: '',
  anthroExceed: '',
  anthroNoallot: ''
};

// Ссылки в панели: пустая строка = ссылка не показывается. Репозиторий открыт 19.11.2026; DOI статьи и адрес выкладки
// полных слоёв вписать, когда появятся.
var LINKS = {
  article: '',
  repo: 'https://github.com/SizovOleg/baresand-zapsib',
  methods: 'https://github.com/SizovOleg/baresand-zapsib/blob/main/docs/INTERPRETATION.md',
  data: ''       // выкладка полных слоёв без упрощения (Zenodo или релиз GitHub)
};

// Наборы каталога GEE (проверены 13.10.2026 через ee.data.getAsset)
var CATALOG = {
  s2: 'COPERNICUS/S2_SR_HARMONIZED',
  dem: 'UMN/PGC/ArcticDEM/V4/2m_mosaic',                 // как в src/python/88-96
  gsw: 'JRC/GSW1_4/GlobalSurfaceWater',                  // как в src/python/31, 88-96
  hansen: 'UMD/hansen/global_forest_change_2019_v1_7'   // версия, использованная в обработке (src/python/66)
};

// Масштабы (уровни масштаба карты), с которых рисуются тяжёлые слои
var Z_VECTOR = 11;   // границы контуров из таблиц (575 тыс. полигонов)
var Z_FILL = 9;      // заливка из таблицы, если нет растра классов
var Z_MASK = 10;     // растр маски (пирамиды MEAN: на мелких масштабах песок исчезает)
var Z_ANTHRO = 8;    // кадастровые классы техногена из таблиц
var Z_TILES = 5;     // следы тайлов

// ============================================================================
// 2. СПРАВОЧНИКИ
// ============================================================================

// Классы генезиса. Площади: supplement/S08 (отмели по типу).
var CLASSES = [
  {code: 1, key: 'aeolian', label: 'эоловые', fill: 'FF9F1A', line: 'C86E00', km2: '2 729,7'},
  {code: 2, key: 'river_shoal', label: 'отмели речные', fill: '0078FF', line: '003CA0', km2: '3 053,7'},
  {code: 3, key: 'lake_shoal', label: 'отмели озёрные', fill: '00DCDC', line: '008C8C', km2: '136,6'},
  {code: 4, key: 'shoal', label: 'отмели морские', fill: 'FFE600', line: 'B49600', km2: '315,8'},
  {code: 5, key: 'anthropogenic', label: 'техногенные', fill: 'C800C8', line: '780078', km2: '1 876,2'},
  {code: 6, key: 'undefined', label: 'неопределённые', fill: 'A0A0A0', line: '5A5A5A', km2: '43,8'}
];
var MAIN_RU = {aeolian: 'эоловые', alluvial_littoral: 'отмели', anthropogenic: 'техногенные', undefined: 'неопределённые'};
var SHOAL_RU = {river: 'речная', lake: 'озёрная', sea: 'морская'};
var SHOAL_SRC_RU = {rule: 'правило каскада', model: 'модель', owner: 'метка автора'};

// Шаги каскада (приложение S3)
var STEP_RU = {
  1: 'шаг 1: морские отмели',
  2: 'шаг 2: речные и озёрные отмели',
  3: 'шаг 3: техногенные',
  4: 'шаг 4: эоловые и неопределённые',
  5: 'шаг 5: уточнение по рельефу',
  6: 'шаг 6: уточнение остатка автором, перенос, исправления'
};

// Правила (коды из полей shoal_rule, step2_rule ... step6_rule; описания по docstring скриптов 45, 51, 55, 62, 81,
// 93, 104, 132, 138 и repo/docs/DATA.md, раздел 4.3)
var RULE_RU = {
  v3_sea_adjacent: 'у морского берега: не далее 400 м, низкое положение (HND)',
  v3_sea_adjacent_split: 'прибрежная часть разрезанного крупного контура',
  v3_split_remainder: 'остаток разрезанного крупного контура',
  v3_rejected_inland_giant: 'крупный внутренний контур снят с морских',
  v3_river: 'затопляемость по GSW у реки',
  v3_river_channel: 'у русла по сети MERIT Hydro',
  v3_lake: 'затопляемость по GSW у озера',
  v3_marine_leak: 'отмель шага 2 у морского берега: отнесена к морским',
  v3sG_split_dry: 'сухая часть, отрезанная от отмели',
  v3sG_whole_dry: 'класс отмели снят целиком (сухой контур)',
  v4_a_osm_on: 'в следе объектов OSM',
  v4_a_nspd_on: 'в сооружениях или промышленных участках ЕГРН',
  v4_a_near_new: 'у инфраструктуры, поверхность новая (тёмная в 1985 г.)',
  v4_a_net: 'сеть дорог и площадок с поддержкой OSM',
  v4_a_net_adj: 'примыкает к сети дорог и площадок',
  v4_a_new_infra: 'новая компактная поверхность в зоне инфраструктуры',
  v4_a_road_small: 'мелкий контур у построенной дороги (обочины, съезды)',
  v4_a_thin_net: 'тонкая сеть у дорог или промзон',
  v2_aeolian_high: 'балл эолового генезиса высокий',
  v2_aeolian_medium: 'балл эолового генезиса средний',
  v2_inherit_aeolian: 'наследование от крупного эолового соседа',
  v2_cluster_small: 'мелкий контур в кластере эоловых',
  v2_undef_burn: 'гарь или вырубка',
  v2_undef_khasyrei: 'днище спущенного озера (хасырей)',
  v2_undef_shoal: 'признаки отмели',
  v2_undef_lin: 'линейная форма',
  v2_undef_veg: 'растительность',
  v2_undef_wet: 'влажная поверхность',
  v2_undef_few: 'мало признаков',
  v2_inherit_undef: 'наследование от неопределённого соседа',
  v2_undef_isolated: 'изолированный контур',
  v3_A1_relief: 'превышение над локальным базисом: неопределённый -> эоловый',
  v3_A2_in_water: 'внутри водного контура: -> озёрная отмель',
  v3_A3_base_level: 'на уровне локального базиса: -> речная отмель',
  v3_B1_channel_cross: 'у русла, низко над тальвегом: эоловый -> речная отмель',
  v3_B2_base_level: 'на уровне локального базиса: эоловый -> речная отмель',
  expert_override: 'вердикт эксперта',
  expert_split: 'разрез эксперта',
  expert_shoal: 'вердикт эксперта: отмель',
  v4_expert: 'метка автора',
  v4_transfer: 'перенос меток автора моделью',
  v4_big_nb: 'крупный контур: описание снимка языковой моделью',
  v4_clear_anthro: 'рубка без пожара отнесена к техногенным',
  v5_mixed_owner: 'смешанный контур, разрезанный автором',
  v7_owner_techno: 'эоловый -> техногенный по метке автора',
  v7_agent_techno: 'эоловый -> техногенный, два слепых прочтения (от 5 га)',
  v7_agent_small: 'эоловый -> техногенный, два слепых прочтения (до 5 га)'
};

// Кадастровый статус в итоговом слое (поле cad_status, 133). Значения exceed / noallot ожидаются после перестройки.
var CAD_STATUS_RU = {
  'in': 'в отводе',
  cross: 'часть контура за полосой 10 м от отвода',
  unreg: 'отвода ближе 10 м нет',
  nocad: 'нет сведений ЕГРН',
  exceed: 'превышение отвода',
  noallot: 'объект без отвода'
};
var AGE_RU = {
  'new': 'оголён после 2000 г. (доля голого в 2000 г. менее 0,30)',
  mid: 'частично оголён в 2000 г. (0,30-0,70)',
  old: 'оголён уже в 2000 г. (0,70 и более)'
};

// Группы техногенных песков по отношению к земельным отводам (supplement/S11, docs/METHODS.md, раздел 9)
var CAD_CLASSES = [
  {key: 'anthroIn', fv: 'anthroIn', title: 'В отводах', fill: '2B8CBE', line: '1B5E87',
   note: 'внутри отводов под объекты, включая территорию населённых пунктов и полосы дорог и трубопроводов: ' +
         '1 101,8 км², 58,7 % класса'},
  {key: 'anthroExceed', fv: 'anthroExceed', title: 'Превышение отвода', fill: 'FF7F00', line: 'B35900',
   note: 'часть объекта дальше 10 м от его отвода: 243,0 км² у 11 481 объекта'},
  {key: 'anthroNoallot', fv: 'anthroNoallot', title: 'Объекты без отвода', fill: 'D7301F', line: '8E1B10',
   note: 'отвода ближе 10 м нет (или в участке меньше 10 % объекта): 18 575 объектов, 349,3 км²'}
];
// Коды полей кадастровых слоёв (133: GROUP_RU; kind_ru)
var GRP_RU = {
  ind: 'земли промышленности',
  vri: 'ВРИ под объекты в иных категориях',
  ezp: 'часть единого землепользования (категория и ВРИ у родительского участка)',
  np: 'земли населённых пунктов',
  terr: 'территория населённого пункта вне участков (улицы, дачи, аэродромы, вахтовые посёлки)',
  big: 'отвод крупнее 1000 га (территориальная аренда, не локальный объект)',
  unk: 'участок без категории и ВРИ',
  forest: 'лесной фонд без объектового ВРИ',
  agri: 'сельхозназначение без объектового ВРИ',
  misc: 'иной участок (запас, ООПТ, водный фонд)',
  none: 'участков ЕГРН нет'
};
var KIND_RU = {none: 'отвода ближе 10 м нет', touch: 'касается чужого отвода (в отводе меньше 10 % контура)'};

// Растры плотности: «суммарная площадь, га/км²», способ центроидов (docs/METHODS.md, раздел 10; шкалы: share для
// ячейки 10 км, шкала карты 2022 г. для мелких ячеек)
var DENSITY_SCALES = {
  share: {bounds: [0.1, 0.5, 1, 2.5, 5, 10],
          labels: ['до 0,1', '0,11-0,5', '0,51-1', '1,1-2,5', '2,6-5', '5,1-10', 'более 10'],
          colors: ['5f7fa6', '8fb2da', 'b8c7c6', 'e4e9bd', 'fcd99c', 'f6a677', 'e8664a']},
  y2022: {bounds: [0.1, 1, 5, 10, 25, 50, 100],
          labels: ['0,01-0,1', '0,11-1', '1,1-5', '5,1-10', '10,1-25', '25,1-50', '50,1-100', 'более 100'],
          colors: ['5f7fa6', '8fb2da', 'b8c7c6', 'e4e9bd', 'fcd99c', 'f6a677', 'e8664a', 'd7301f']}
};
// Плотность по центроидам контуров (га/км² ячейки): класс и ячейка. В режиме «авто» ячейка зависит от масштаба
// карты: обзор 10 км, средние масштабы 5 км, крупные 2 км. Шкалы: share для 10 км, y2022 для 5 и 2 км (145).
var DENSITY_CLASSES = [
  {key: 'aeolian', label: 'эоловые'},
  {key: 'shoal', label: 'отмели (все типы)'},
  {key: 'anthropogenic', label: 'техногенные'}
];
var DENSITY_CELLS = [
  {km: 10, scale: 'share', maxZoom: 6},
  {km: 5, scale: 'y2022', maxZoom: 8},
  {km: 2, scale: 'y2022', maxZoom: 99}
];

function densityAsset(cls, km) {
  return PROJECT + '/density_' + cls + '_' + km + 'km';
}

function densityCell() {
  var i;
  if (state.densityCell !== 'auto') {
    for (i = 0; i < DENSITY_CELLS.length; i++) {
      if (String(DENSITY_CELLS[i].km) === state.densityCell) return DENSITY_CELLS[i];
    }
  }
  for (i = 0; i < DENSITY_CELLS.length; i++) if (state.zoom <= DENSITY_CELLS[i].maxZoom) return DENSITY_CELLS[i];
  return DENSITY_CELLS[DENSITY_CELLS.length - 1];
}

function densityAllAssets() {
  var out = [];
  DENSITY_CLASSES.forEach(function(c) { DENSITY_CELLS.forEach(function(d) { out.push(densityAsset(c.key, d.km)); }); });
  return out;
}

// Синтезы Sentinel-2: каналы и пределы как в gee_scripts/21_production_classify.js
var S2_VIS = {
  fcc: {label: 'Ложные цвета (B8, B4, B3)', vis: {bands: ['B8', 'B4', 'B3'], min: 180, max: 4950}},
  nat: {label: 'Натуральные цвета (B4, B3, B2)', vis: {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000}},
  swir: {label: 'SWIR (B12, B11, B4)', vis: {bands: ['B12', 'B11', 'B4'], min: 0, max: 4000}}
};
// Сцены тайлов: параметры отбора и номера выбранных сцен по скриптам классификации тайлов (supplement/S07); при
// нескольких номерах классифицировалась мозаика сцен.
var SCENE_STATUS_RU = {
  script: 'сцены по копии скрипта тайла автора',
  cover: 'копии с выбором сцен нет; сцены подобраны по копии 21_43VEJ.js и покрытию контуров итогового слоя'
};

// Инфраструктура OSM (150: infra_lines, infra_areas): что рисуется, цвет, толщина, масштаб показа, включено ли
var INFRA = [
  {key: 'road_major', label: 'дороги основные', color: '3a3a3a', width: 2, zoom: 5, on: true},
  {key: 'road_minor', label: 'дороги прочие', color: '8a8a8a', width: 1, zoom: 9, on: true},
  {key: 'road_track', label: 'грунтовые дороги', color: 'a0785a', width: 1, zoom: 10, on: false},
  {key: 'winter', label: 'зимники', color: '5aa7d6', width: 1, zoom: 8, on: true},
  {key: 'rail', label: 'железные дороги', color: '111111', width: 2, zoom: 5, on: true},
  {key: 'rail_old', label: 'железные дороги заброшенные', color: 'b0b0b0', width: 1, zoom: 8, on: false},
  {key: 'pipeline', label: 'трубопроводы', color: 'd62728', width: 1, zoom: 7, on: true},
  {key: 'power', label: 'ЛЭП', color: '7b3294', width: 1, zoom: 8, on: false},
  {key: 'areas', label: 'промплощадки, резервуары, подстанции', color: 'ff7f00', width: 1, zoom: 9, on: true},
  {key: 'quarry', label: 'карьеры', color: '8c510a', width: 1, zoom: 9, on: true}
];
var INFRA_KIND_AREA_RU = {industrial: 'промышленная площадка', storage_tank: 'резервуар', construction: 'стройка',
                          brownfield: 'заброшенная площадка', works: 'завод', substation: 'подстанция',
                          gasometer: 'газгольдер', helipad: 'вертолётная площадка'};
var INFRA_RU = {};
INFRA.forEach(function(r) { INFRA_RU[r.key] = r.label; });

var HANSEN_MODES = {
  first: 'композит около 2000 г. (SWIR1, NIR, красный)',
  loss: 'потеря древесного покрова 2001-2019 гг.',
  tree: 'древесный покров в 2000 г., %'
};

// Сцены Sentinel-2 по тайлам (supplement/tables/S07_scenes.csv): v = статус
// (SCENE_STATUS_RU), u = номера USE_SCENES в копии скрипта, c = сцены тайла (при нескольких классифицировалась их
// мозаика).
var SCENES = [
  {t: '41VPK', v: 'script', u: '[3]', c: ['20230812T070629_20230812T070626_T41VPK']},
  {t: '41VPL', v: 'script', u: '[6]', c: ['20230916T070621_20230916T071047_T41VPL']},
  {t: '41WPQ', v: 'script', u: '[4]', c: ['20250713T072641_20250713T072826_T41WPQ']},
  {t: '41WPR', v: 'script', u: '[6, 3, 5]', c: ['20240807T072621_20240807T072616_T41WPR', '20250727T070751_20250727T070753_T41WPR', '20250726T073641_20250726T073635_T41WPR']},
  {t: '41WPT', v: 'script', u: '[10, 9]', c: ['20250809T071641_20250809T071636_T41WPT', '20250818T074631_20250818T074630_T41WPT']},
  {t: '41WPU', v: 'script', u: '[8]', c: ['20250818T074631_20250818T074630_T41WPU']},
  {t: '41WPV', v: 'script', u: '[10]', c: ['20250818T074631_20250818T074630_T41WPV']},
  {t: '41XPA', v: 'script', u: '[8]', c: ['20240811T075609_20240811T075612_T41XPA']},
  {t: '42VUQ', v: 'script', u: '[2]', c: ['20230812T070629_20230812T070626_T42VUQ']},
  {t: '42VUR', v: 'script', u: '[6]', c: ['20230916T070621_20230916T071047_T42VUR']},
  {t: '42VVP', v: 'script', u: '[5, 3]', c: ['20230906T070631_20230906T071053_T42VVP', '20230806T064629_20230806T064628_T42VVP']},
  {t: '42VVQ', v: 'script', u: '[11]', c: ['20230906T070631_20230906T071053_T42VVQ']},
  {t: '42VVR', v: 'script', u: '[1]', c: ['20220728T070629_20220728T070626_T42VVR']},
  {t: '42VWP', v: 'script', u: '[12]', c: ['20230806T064629_20230806T064628_T42VWP']},
  {t: '42VWQ', v: 'script', u: '[2]', c: ['20220801T064629_20220801T064629_T42VWQ']},
  {t: '42VWR', v: 'script', u: '[4]', c: ['20230908T065629_20230908T065624_T42VWR']},
  {t: '42VXP', v: 'script', u: '[9]', c: ['20230806T064629_20230806T064628_T42VXP']},
  {t: '42VXQ', v: 'script', u: '[1]', c: ['20220801T064629_20220801T064629_T42VXQ']},
  {t: '42VXR', v: 'script', u: '[1]', c: ['20230915T064629_20230915T064908_T42VXR']},
  {t: '42WVA', v: 'script', u: '[3]', c: ['20230803T072621_20230803T072620_T42WVA']},
  {t: '42WVB', v: 'script', u: '[3]', c: ['20230803T072621_20230803T072620_T42WVB']},
  {t: '42WVC', v: 'script', u: '[20]', c: ['20230806T073621_20230806T073618_T42WVC']},
  {t: '42WVD', v: 'script', u: '[9]', c: ['20250818T074631_20250818T074630_T42WVD']},
  {t: '42WVE', v: 'script', u: '[10]', c: ['20250805T073631_20250805T073632_T42WVE']},
  {t: '42WVS', v: 'script', u: '[2, 1]', c: ['20230715T065631_20230715T065625_T42WVS', '20220731T071619_20220731T071947_T42WVS']},
  {t: '42WVT', v: 'script', u: '[3]', c: ['20230805T071619_20230805T071622_T42WVT']},
  {t: '42WVU', v: 'script', u: '[3]', c: ['20220731T071619_20220731T071947_T42WVU']},
  {t: '42WVV', v: 'script', u: '[6]', c: ['20230812T070629_20230812T070626_T42WVV']},
  {t: '42WWA', v: 'script', u: '[4]', c: ['20230807T070631_20230807T070625_T42WWA']},
  {t: '42WWB', v: 'script', u: '[1]', c: ['20230805T071619_20230805T071622_T42WWB']},
  {t: '42WWC', v: 'script', u: '[4]', c: ['20230805T071619_20230805T071622_T42WWC']},
  {t: '42WWD', v: 'script', u: '[4]', c: ['20220719T072631_20220719T072627_T42WWD']},
  {t: '42WWE', v: 'script', u: '[10]', c: ['20230801T073619_20230801T073618_T42WWE']},
  {t: '42WWS', v: 'script', u: '[11, 7]', c: ['20250701T064651_20250701T065141_T42WWS', '20240707T070629_20240707T070655_T42WWS']},
  {t: '42WWT', v: 'script', u: '[7]', c: ['20230715T065631_20230715T065625_T42WWT']},
  {t: '42WWU', v: 'script', u: '[12]', c: ['20210708T070621_20210708T070624_T42WWU']},
  {t: '42WWV', v: 'script', u: '[4]', c: ['20240707T070629_20240707T070655_T42WWV']},
  {t: '42WXA', v: 'script', u: '[2]', c: ['20230802T070629_20230802T070625_T42WXA']},
  {t: '42WXB', v: 'script', u: '[4]', c: ['20230802T070629_20230802T070625_T42WXB']},
  {t: '42WXC', v: 'script', u: '[3]', c: ['20230802T070629_20230802T070625_T42WXC']},
  {t: '42WXD', v: 'script', u: '[4]', c: ['20230802T070629_20230802T070625_T42WXD']},
  {t: '42WXE', v: 'script', u: '[12]', c: ['20230805T071619_20230805T071622_T42WXE']},
  {t: '42WXS', v: 'script', u: '[4]', c: ['20230806T064629_20230806T064628_T42WXS']},
  {t: '42WXT', v: 'script', u: '[3]', c: ['20230806T064629_20230806T064628_T42WXT']},
  {t: '42WXU', v: 'script', u: '[9, 11]', c: ['20240707T070629_20240707T070655_T42WXU', '20230806T064629_20230806T064628_T42WXU']},
  {t: '42WXV', v: 'script', u: '[3]', c: ['20240707T070629_20240707T070655_T42WXV']},
  {t: '42XVF', v: 'script', u: '[9]', c: ['20230802T075611_20230802T075613_T42XVF']},
  {t: '42XWF', v: 'script', u: '[5]', c: ['20200724T072619_20200724T072617_T42XWF']},
  {t: '42XWG', v: 'script', u: '[9]', c: ['20230802T075611_20230802T075613_T42XWG']},
  {t: '42XXF', v: 'script', u: '[2]', c: ['20230806T073621_20230806T073618_T42XXF']},
  {t: '43VCJ', v: 'script', u: '[9]', c: ['20230806T064629_20230806T064628_T43VCJ']},
  {t: '43VCK', v: 'script', u: '[4]', c: ['20220801T064629_20220801T064629_T43VCK']},
  {t: '43VCL', v: 'script', u: '[2]', c: ['20230915T064629_20230915T064908_T43VCL']},
  {t: '43VDJ', v: 'script', u: '[5]', c: ['20230805T062631_20230805T062632_T43VDJ']},
  {t: '43VDK', v: 'script', u: '[3, 1]', c: ['20240706T064631_20240706T064917_T43VDK', '20230805T062631_20230805T062632_T43VDK']},
  {t: '43VDL', v: 'script', u: '[2]', c: ['20240708T063629_20240708T063627_T43VDL']},
  {t: '43VEJ', v: 'cover', u: '[1, 2] (по покрытию контуров; в копии 21_43VEJ.js первая сцена)', c: ['20240916T063619_20240916T063904_T43VEJ', '20240915T061631_20240915T061817_T43VEJ']},
  {t: '43VEK', v: 'script', u: '[1]', c: ['20230805T062631_20230805T062632_T43VEK']},
  {t: '43VEL', v: 'script', u: '[4]', c: ['20230912T063629_20230912T063924_T43VEL']},
  {t: '43VFJ', v: 'script', u: '[2, 1]', c: ['20240707T061631_20240707T062053_T43VFJ', '20230805T062631_20230805T062632_T43VFJ']},
  {t: '43VFK', v: 'script', u: '[5]', c: ['20230805T062631_20230805T062632_T43VFK']},
  {t: '43VFL', v: 'script', u: '[4]', c: ['20230914T062631_20230914T062631_T43VFL']},
  {t: '43WDM', v: 'script', u: '[2]', c: ['20230806T064629_20230806T064628_T43WDM']},
  {t: '43WDN', v: 'script', u: '[2]', c: ['20230806T064629_20230806T064628_T43WDN']},
  {t: '43WDP', v: 'script', u: '[2]', c: ['20230806T064629_20230806T064628_T43WDP']},
  {t: '43WDQ', v: 'script', u: '[5]', c: ['20230702T064631_20230702T064628_T43WDQ']},
  {t: '43WDR', v: 'script', u: '[10]', c: ['20230804T065631_20230804T065625_T43WDR']},
  {t: '43WDS', v: 'script', u: '[2]', c: ['20230802T070629_20230802T070625_T43WDS']},
  {t: '43WDT', v: 'script', u: '[4]', c: ['20230802T070629_20230802T070625_T43WDT']},
  {t: '43WDU', v: 'script', u: '[1]', c: ['20230802T070629_20230802T070625_T43WDU']},
  {t: '43WDV', v: 'script', u: '[12]', c: ['20230805T071619_20230805T071622_T43WDV']},
  {t: '43WEM', v: 'script', u: '[2]', c: ['20250730T062629_20250730T063043_T43WEM']},
  {t: '43WEN', v: 'script', u: '[6]', c: ['20240708T063629_20240708T063627_T43WEN']},
  {t: '43WEP', v: 'script', u: '[2]', c: ['20230803T063629_20230803T063628_T43WEP']},
  {t: '43WEQ', v: 'script', u: '[7]', c: ['20230806T064629_20230806T064628_T43WEQ']},
  {t: '43WER', v: 'script', u: '[6]', c: ['20240721T064629_20240721T064626_T43WER']},
  {t: '43WES', v: 'script', u: '[6]', c: ['20230801T064631_20230801T064629_T43WES']},
  {t: '43WET', v: 'script', u: '[2]', c: ['20230804T065631_20230804T065625_T43WET']},
  {t: '43WEU', v: 'script', u: '[2]', c: ['20240811T070621_20240811T070622_T43WEU']},
  {t: '43WEV', v: 'script', u: '[6, 5, 4]', c: ['20240801T070621_20240801T070623_T43WEV', '20240812T072619_20240812T072619_T43WEV', '20250815T064629_20250815T064625_T43WEV']},
  {t: '43WFM', v: 'script', u: '[1]', c: ['20250730T062629_20250730T063043_T43WFM']},
  {t: '43WFN', v: 'script', u: '[6, 5]', c: ['20240826T061631_20240826T061936_T43WFN', '20250730T062629_20250730T063043_T43WFN']},
  {t: '43WFP', v: 'script', u: '[7]', c: ['20230813T063629_20230813T063748_T43WFP']},
  {t: '43WFQ', v: 'script', u: '[10]', c: ['20240728T063629_20240728T063745_T43WFQ']},
  {t: '43WFR', v: 'script', u: '[2]', c: ['20230813T063629_20230813T063748_T43WFR']},
  {t: '43WFS', v: 'script', u: '[8]', c: ['20250901T063629_20250901T063819_T43WFS']},
  {t: '43WFT', v: 'script', u: '[1]', c: ['20230801T064631_20230801T064629_T43WFT']},
  {t: '43WFU', v: 'script', u: '[5]', c: ['20230801T064631_20230801T064629_T43WFU']},
  {t: '43WFV', v: 'script', u: '[6]', c: ['20250806T070641_20250806T070640_T43WFV']},
  {t: '43XDA', v: 'script', u: '[1]', c: ['20230806T073621_20230806T073618_T43XDA']},
  {t: '43XEA', v: 'script', u: '[18]', c: ['20230805T071619_20230805T071622_T43XEA']},
  {t: '43XFA', v: 'script', u: '[3]', c: ['20230807T070631_20230807T070625_T43XFA']},
  {t: '44VLP', v: 'script', u: '[6, 1]', c: ['20240707T061631_20240707T062053_T44VLP', '20230805T062631_20230805T062632_T44VLP']},
  {t: '44VLQ', v: 'script', u: '[3]', c: ['20240915T061631_20240915T061817_T44VLQ']},
  {t: '44VLR', v: 'script', u: '[2]', c: ['20240915T061631_20240915T061817_T44VLR']},
  {t: '44VMP', v: 'script', u: '[6, 2]', c: ['20230730T060641_20230730T060734_T44VMP', '20230804T060639_20230804T060635_T44VMP']},
  {t: '44VMQ', v: 'script', u: '[4]', c: ['20240915T061631_20240915T061817_T44VMQ']},
  {t: '44VMR', v: 'script', u: '[1]', c: ['20250801T061651_20250801T061752_T44VMR']},
  {t: '44VNP', v: 'script', u: '[6]', c: ['20250810T055639_20250810T055830_T44VNP']},
  {t: '44VNQ', v: 'script', u: '[1, 3]', c: ['20240915T061631_20240915T061817_T44VNQ', '20240914T055639_20240914T055727_T44VNQ']},
  {t: '44VNR', v: 'script', u: '[1, 6]', c: ['20240915T061631_20240915T061817_T44VNR', '20250904T055651_20250904T055821_T44VNR']},
  {t: '44VPP', v: 'script', u: '[4, 5]', c: ['20250828T060651_20250828T061007_T44VPP', '20250703T054701_20250703T054658_T44VPP']},
  {t: '44VPQ', v: 'script', u: '[2]', c: ['20250731T055639_20250731T055948_T44VPQ']},
  {t: '44VPR', v: 'script', u: '[2]', c: ['20240914T055639_20240914T055727_T44VPR']},
  {t: '44WMA', v: 'script', u: '[4]', c: ['20250804T062651_20250804T062647_T44WMA']},
  {t: '44WMB', v: 'script', u: '[3]', c: ['20250901T063629_20250901T063819_T44WMB']},
  {t: '44WMC', v: 'script', u: '[3]', c: ['20250901T063629_20250901T063819_T44WMC']},
  {t: '44WMD', v: 'script', u: '[1, 2]', c: ['20250806T070641_20250806T070640_T44WMD', '20250901T063629_20250901T063819_T44WMD']},
  {t: '44WME', v: 'script', u: '[2, 1]', c: ['20240812T063631_20240812T063753_T44WME', '20250806T070641_20250806T070640_T44WME']},
  {t: '44WMS', v: 'script', u: '[2, 1]', c: ['20240912T061001_20240912T061000_T44WMS', '20250730T062629_20250730T063043_T44WMS']},
  {t: '44WMT', v: 'script', u: '[3]', c: ['20250801T061651_20250801T061752_T44WMT']},
  {t: '44WMU', v: 'script', u: '[4]', c: ['20250730T062629_20250730T062627_T44WMU']},
  {t: '44WMV', v: 'script', u: '[1]', c: ['20240728T063629_20240728T063745_T44WMV']},
  {t: '44WNA', v: 'script', u: '[4]', c: ['20250809T062629_20250809T062629_T44WNA']},
  {t: '44WNB', v: 'script', u: '[2]', c: ['20250804T062651_20250804T062647_T44WNB']},
  {t: '44WNC', v: 'script', u: '[5]', c: ['20250804T062651_20250804T062647_T44WNC']},
  {t: '44WND', v: 'script', u: '[8, 7]', c: ['20240802T063631_20240802T063626_T44WND', '20240802T063631_20240802T063912_T44WND']},
  {t: '44WNE', v: 'script', u: '[2]', c: ['20250830T064751_20250830T064752_T44WNE']},
  {t: '44WNS', v: 'script', u: '[2]', c: ['20250801T061651_20250801T061752_T44WNS']},
  {t: '44WNT', v: 'script', u: '[4]', c: ['20240912T061001_20240912T061000_T44WNT']},
  {t: '44WNU', v: 'script', u: '[6, 3]', c: ['20240808T060639_20240808T060634_T44WNU', '20250730T062629_20250730T062627_T44WNU']},
  {t: '44WNV', v: 'script', u: '[4]', c: ['20250809T062629_20250809T062629_T44WNV']},
  {t: '44WPA', v: 'script', u: '[3]', c: ['20240722T061639_20240722T061655_T44WPA']},
  {t: '44WPB', v: 'script', u: '[2]', c: ['20250804T062651_20250804T062647_T44WPB']},
  {t: '44WPC', v: 'script', u: '[3]', c: ['20240811T061639_20240811T061634_T44WPC']},
  {t: '44WPS', v: 'script', u: '[1]', c: ['20230806T055641_20230806T055638_T44WPS']},
  {t: '45WVQ', v: 'script', u: '[1, 5]', c: ['20240720T062631_20240720T062950_T45WVQ', '20240721T055641_20240721T055635_T45WVQ']},
  {t: '45WVR', v: 'script', u: '[1]', c: ['20240722T061639_20240722T061655_T45WVR']}
];

// Статистика по районам, широтным поясам и итог для правого блока (km2; python/155_app_stats.py)
// STATS-BEGIN (python/155_app_stats.py --write-app; не править вручную)
var STATS = {"version":"genesis v7 (06.10.2026), cadastre v7b (03.11.2026); python/155_app_stats.py","total":{"aeolian":2729.67,"river_shoal":3053.66,"lake_shoal":136.6,"shoal":315.76,"anthropogenic":1876.25,"undefined":43.76,"n":575054.0,"age_new":1065.92,"age_mid":324.72,"age_old":485.6,"age_na":0.0,"cad_in":1096.92,"cad_exceed":243.03,"cad_noallot":349.31,"cad_noallot_n":18575.0,"sand_km2":8155.7},"districts":[{"name":"муниципальный округ Ямальский район","label":"Ямальский район","aeolian":1672.35,"river_shoal":996.82,"lake_shoal":77.79,"shoal":216.74,"anthropogenic":127.41,"undefined":17.37,"n":285264.0,"age_new":112.97,"age_mid":13.11,"age_old":1.33,"age_na":0.0,"cad_in":86.23,"cad_exceed":14.07,"cad_noallot":17.27,"cad_noallot_n":663.0,"area_km2":113185.37,"sand_km2":3108.49,"sand_share":2.75},{"name":"муниципальный округ Тазовский район","label":"Тазовский район","aeolian":354.4,"river_shoal":940.25,"lake_shoal":22.06,"shoal":44.72,"anthropogenic":114.08,"undefined":5.85,"n":102445.0,"age_new":101.57,"age_mid":7.89,"age_old":4.62,"age_na":0.0,"cad_in":98.22,"cad_exceed":3.72,"cad_noallot":4.79,"cad_noallot_n":240.0,"area_km2":132437.44,"sand_km2":1481.37,"sand_share":1.12},{"name":"муниципальный округ Пуровский район","label":"Пуровский район","aeolian":262.19,"river_shoal":249.02,"lake_shoal":5.92,"shoal":0.15,"anthropogenic":602.43,"undefined":2.94,"n":53732.0,"age_new":239.17,"age_mid":133.78,"age_old":229.48,"age_na":0.0,"cad_in":411.26,"cad_exceed":74.43,"cad_noallot":56.46,"cad_noallot_n":3880.0,"area_km2":109278.07,"sand_km2":1122.66,"sand_share":1.03},{"name":"муниципальный округ Надымский район","label":"Надымский район","aeolian":312.69,"river_shoal":335.51,"lake_shoal":6.54,"shoal":23.93,"anthropogenic":150.52,"undefined":4.28,"n":38179.0,"age_new":75.33,"age_mid":28.56,"age_old":46.63,"age_na":0.0,"cad_in":87.0,"cad_exceed":17.66,"cad_noallot":23.8,"cad_noallot_n":2069.0,"area_km2":98285.16,"sand_km2":833.48,"sand_share":0.85},{"name":"Сургутский район","label":"Сургутский район","aeolian":28.05,"river_shoal":38.75,"lake_shoal":9.23,"shoal":0.0,"anthropogenic":565.75,"undefined":5.13,"n":34195.0,"age_new":326.01,"age_mid":103.75,"age_old":135.98,"age_na":0.0,"cad_in":238.65,"cad_exceed":101.52,"cad_noallot":168.16,"cad_noallot_n":7757.0,"area_km2":66701.15,"sand_km2":646.91,"sand_share":0.97},{"name":"Восточный сектор (Таймыр)","label":"Восточный сектор (Таймыр)","aeolian":54.35,"river_shoal":248.17,"lake_shoal":7.84,"shoal":9.8,"anthropogenic":18.89,"undefined":3.5,"n":26428.0,"age_new":17.48,"age_mid":1.0,"age_old":0.4,"age_na":0.0,"cad_in":4.18,"cad_exceed":0.3,"cad_noallot":13.97,"cad_noallot_n":271.0,"area_km2":63471.34,"sand_km2":342.55,"sand_share":0.54},{"name":"Нижневартовский район","label":"Нижневартовский район","aeolian":14.13,"river_shoal":12.66,"lake_shoal":1.0,"shoal":0.0,"anthropogenic":154.47,"undefined":2.35,"n":11032.0,"age_new":64.33,"age_mid":31.61,"age_old":58.52,"age_na":0.0,"cad_in":78.42,"cad_exceed":20.47,"cad_noallot":33.35,"cad_noallot_n":1317.0,"area_km2":63748.92,"sand_km2":184.6,"sand_share":0.29},{"name":"муниципальный округ Приуральский район","label":"Приуральский район","aeolian":21.7,"river_shoal":86.19,"lake_shoal":1.79,"shoal":7.69,"anthropogenic":16.37,"undefined":1.0,"n":10281.0,"age_new":14.54,"age_mid":1.57,"age_old":0.26,"age_na":0.0,"cad_in":11.15,"cad_exceed":1.29,"cad_noallot":1.5,"cad_noallot_n":141.0,"area_km2":65205.96,"sand_km2":134.73,"sand_share":0.21},{"name":"Белоярский район","label":"Белоярский район","aeolian":1.96,"river_shoal":37.98,"lake_shoal":1.78,"shoal":0.0,"anthropogenic":36.46,"undefined":0.46,"n":3840.0,"age_new":27.68,"age_mid":2.45,"age_old":6.33,"age_na":0.0,"cad_in":18.4,"cad_exceed":3.91,"cad_noallot":12.28,"cad_noallot_n":1087.0,"area_km2":41715.68,"sand_km2":78.65,"sand_share":0.19},{"name":"Туруханский муниципальный округ","label":"Туруханский округ","aeolian":6.16,"river_shoal":31.48,"lake_shoal":2.3,"shoal":0.0,"anthropogenic":22.26,"undefined":0.1,"n":2632.0,"age_new":22.1,"age_mid":0.16,"age_old":0.0,"age_na":0.0,"cad_in":20.56,"cad_exceed":0.56,"cad_noallot":0.12,"cad_noallot_n":15.0,"area_km2":112946.59,"sand_km2":62.3,"sand_share":0.06},{"name":"Ханты-Мансийский район","label":"Ханты-Мансийский район","aeolian":0.4,"river_shoal":13.25,"lake_shoal":0.32,"shoal":0.0,"anthropogenic":40.34,"undefined":0.44,"n":2641.0,"age_new":40.15,"age_mid":0.07,"age_old":0.12,"age_na":0.0,"cad_in":27.38,"cad_exceed":2.82,"cad_noallot":9.32,"cad_noallot_n":519.0,"area_km2":21997.86,"sand_km2":54.74,"sand_share":0.25},{"name":"Октябрьский район","label":"Октябрьский район","aeolian":0.23,"river_shoal":31.3,"lake_shoal":0.0,"shoal":0.0,"anthropogenic":14.4,"undefined":0.14,"n":1802.0,"age_new":14.08,"age_mid":0.18,"age_old":0.15,"age_na":0.0,"cad_in":4.16,"cad_exceed":1.96,"cad_noallot":7.75,"cad_noallot_n":534.0,"area_km2":10211.42,"sand_km2":46.07,"sand_share":0.45},{"name":"муниципальный округ Красноселькупский район","label":"Красноселькупский район","aeolian":1.05,"river_shoal":16.64,"lake_shoal":0.01,"shoal":0.0,"anthropogenic":12.21,"undefined":0.17,"n":1929.0,"age_new":10.02,"age_mid":0.48,"age_old":1.71,"age_na":0.0,"cad_in":10.88,"cad_exceed":0.27,"cad_noallot":0.41,"cad_noallot_n":50.0,"area_km2":106491.88,"sand_km2":30.07,"sand_share":0.03},{"name":"вне районов","label":"вне районов","aeolian":0.01,"river_shoal":2.29,"lake_shoal":0.01,"shoal":12.72,"anthropogenic":0.0,"undefined":0.0,"n":70.0,"age_new":0.0,"age_mid":0.0,"age_old":0.0,"age_na":0.0,"cad_in":0.0,"cad_exceed":0.0,"cad_noallot":0.0,"cad_noallot_n":0.0,"area_km2":0.0,"sand_km2":15.03,"sand_share":0.0},{"name":"Берёзовский район","label":"Берёзовский район","aeolian":0.0,"river_shoal":11.89,"lake_shoal":0.01,"shoal":0.0,"anthropogenic":0.21,"undefined":0.02,"n":331.0,"age_new":0.12,"age_mid":0.03,"age_old":0.06,"age_na":0.0,"cad_in":0.16,"cad_exceed":0.04,"cad_noallot":0.0,"cad_noallot_n":2.0,"area_km2":7773.94,"sand_km2":12.13,"sand_share":0.16},{"name":"муниципальный округ Шурышкарский район","label":"Шурышкарский район","aeolian":0.01,"river_shoal":1.43,"lake_shoal":0.0,"shoal":0.0,"anthropogenic":0.15,"undefined":0.01,"n":213.0,"age_new":0.15,"age_mid":0.0,"age_old":0.0,"age_na":0.0,"cad_in":0.02,"cad_exceed":0.0,"cad_noallot":0.12,"cad_noallot_n":27.0,"area_km2":54108.16,"sand_km2":1.6,"sand_share":0.0},{"name":"Нефтеюганский район","label":"Нефтеюганский район","aeolian":0.0,"river_shoal":0.03,"lake_shoal":0.0,"shoal":0.0,"anthropogenic":0.29,"undefined":0.0,"n":40.0,"age_new":0.2,"age_mid":0.09,"age_old":0.01,"age_na":0.0,"cad_in":0.24,"cad_exceed":0.01,"cad_noallot":0.01,"cad_noallot_n":3.0,"area_km2":157.65,"sand_km2":0.32,"sand_share":0.21}],"lat":[{"band":61,"aeolian":12.14,"river_shoal":55.54,"lake_shoal":4.0,"shoal":0.0,"anthropogenic":344.22,"undefined":2.66},{"band":62,"aeolian":33.5,"river_shoal":30.2,"lake_shoal":6.4,"shoal":0.0,"anthropogenic":413.67,"undefined":5.39},{"band":63,"aeolian":89.79,"river_shoal":85.67,"lake_shoal":6.52,"shoal":0.0,"anthropogenic":250.81,"undefined":3.07},{"band":64,"aeolian":240.03,"river_shoal":72.21,"lake_shoal":3.09,"shoal":0.0,"anthropogenic":147.36,"undefined":1.41},{"band":65,"aeolian":79.94,"river_shoal":134.11,"lake_shoal":0.86,"shoal":0.0,"anthropogenic":123.7,"undefined":1.09},{"band":66,"aeolian":103.05,"river_shoal":255.79,"lake_shoal":3.8,"shoal":0.0,"anthropogenic":290.72,"undefined":2.02},{"band":67,"aeolian":259.87,"river_shoal":326.43,"lake_shoal":10.45,"shoal":13.8,"anthropogenic":119.18,"undefined":5.55},{"band":68,"aeolian":409.63,"river_shoal":514.28,"lake_shoal":15.74,"shoal":54.05,"anthropogenic":62.17,"undefined":5.04},{"band":69,"aeolian":430.03,"river_shoal":472.85,"lake_shoal":31.18,"shoal":26.51,"anthropogenic":16.35,"undefined":5.71},{"band":70,"aeolian":412.76,"river_shoal":487.78,"lake_shoal":40.24,"shoal":12.28,"anthropogenic":59.77,"undefined":7.08},{"band":71,"aeolian":387.74,"river_shoal":423.46,"lake_shoal":11.13,"shoal":61.2,"anthropogenic":46.58,"undefined":3.27},{"band":72,"aeolian":271.18,"river_shoal":195.33,"lake_shoal":3.19,"shoal":147.92,"anthropogenic":1.73,"undefined":1.48}]};
// STATS-END

// ============================================================================
// 3. ОФОРМЛЕНИЕ
// ============================================================================

// Минималистичное оформление: белая панель, один акцентный цвет, шрифт 14 px. Ширины подобраны так, чтобы
// горизонтальные панели не выходили за ширину панели (иначе Code Editor рисует полосу прокрутки под строкой).
var C = {bg: '#ffffff', card: '#ffffff', ink: '#202124', muted: '#5f6368', faint: '#9aa0a6', line: '#e8e6e1',
         accent: '#a8692a'};
var S = {
  panel: {width: '400px', padding: '20px 20px 24px 20px', backgroundColor: C.bg},
  title: {fontSize: '22px', fontWeight: 'bold', color: C.ink, margin: '0 0 6px 0', backgroundColor: C.bg,
          whiteSpace: 'normal'},
  lead: {fontSize: '14px', color: C.muted, margin: '0 0 12px 0', whiteSpace: 'normal', backgroundColor: C.bg},
  text: {fontSize: '14px', color: C.ink, margin: '0 0 6px 0', whiteSpace: 'normal', backgroundColor: C.bg},
  small: {fontSize: '12px', color: C.muted, margin: '2px 0 4px 0', whiteSpace: 'normal', backgroundColor: C.bg},
  group: {fontSize: '12px', fontWeight: 'bold', color: C.accent, margin: '22px 0 4px 0', backgroundColor: C.bg},
  sub: {fontSize: '14px', fontWeight: 'bold', color: C.ink, margin: '12px 0 2px 0', backgroundColor: C.bg},
  rule: {height: '1px', padding: '0', margin: '2px 0 4px 0', backgroundColor: C.line, stretch: 'horizontal'},
  row: {margin: '0', padding: '0', backgroundColor: C.bg},
  checkbox: {fontSize: '14px', color: C.ink, margin: '7px 0 0 0', backgroundColor: C.bg},
  slider: {width: '150px', margin: '0 0 0 6px', backgroundColor: C.bg},
  status: {fontSize: '12px', color: '#9b4d1f', margin: '0 0 4px 28px', whiteSpace: 'normal', backgroundColor: C.bg,
           shown: false},
  legend: {margin: '2px 0 6px 28px', padding: '0', backgroundColor: C.bg},
  legendText: {fontSize: '13px', color: C.ink, margin: '3px 0 0 0', backgroundColor: C.bg, whiteSpace: 'normal',
               width: '262px'},
  select: {stretch: 'horizontal', margin: '2px 0 4px 0'},
  button: {margin: '6px 0 2px 0'},
  link: {fontSize: '14px', color: C.accent, margin: '0 16px 4px 0', backgroundColor: C.bg},
  info: {position: 'bottom-left', width: '340px', maxHeight: '460px', padding: '10px 12px', backgroundColor: C.card,
         border: '1px solid ' + C.line, shown: false},
  infoTitle: {fontSize: '13px', fontWeight: 'bold', color: C.ink, margin: '8px 0 2px 0', backgroundColor: C.card},
  infoKey: {fontSize: '12px', color: C.muted, width: '104px', margin: '1px 6px 1px 0', whiteSpace: 'normal',
            backgroundColor: C.card},
  infoVal: {fontSize: '12px', color: C.ink, width: '180px', margin: '1px 0', whiteSpace: 'normal',
            backgroundColor: C.card}
};

// Светлая сдержанная подложка (стиль Google Maps)
var LIGHT_STYLE = [
  {elementType: 'geometry', stylers: [{color: '#f2f1ed'}]},
  {elementType: 'labels.icon', stylers: [{visibility: 'off'}]},
  {elementType: 'labels.text.fill', stylers: [{color: '#6b6f76'}]},
  {elementType: 'labels.text.stroke', stylers: [{color: '#f7f6f2'}]},
  {featureType: 'administrative', elementType: 'geometry.stroke', stylers: [{color: '#c9c6bd'}]},
  {featureType: 'poi', stylers: [{visibility: 'off'}]},
  {featureType: 'road', elementType: 'geometry', stylers: [{color: '#e3e0d8'}]},
  {featureType: 'road', elementType: 'labels', stylers: [{visibility: 'off'}]},
  {featureType: 'transit', stylers: [{visibility: 'off'}]},
  {featureType: 'water', elementType: 'geometry', stylers: [{color: '#cfdde6'}]},
  {featureType: 'water', elementType: 'labels.text.fill', stylers: [{color: '#7f95a3'}]}
];

// ============================================================================
// 4. ВСПОМОГАТЕЛЬНОЕ
// ============================================================================

function isSet(path) {
  return typeof path === 'string' && path.length > 0 && path.indexOf('<') < 0;
}

// Число по-русски: десятичная запятая, пробел между тысячами
function fmt(x, digits) {
  if (x === null || x === undefined || x === '' || isNaN(Number(x))) return '';
  var s = Number(x).toFixed(digits);
  var parts = s.split('.');
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  return parts.join(',');
}

// Склонение существительного после числа: plural(21, ['контур', 'контура', 'контуров']) -> 'контур'
function plural(n, forms) {
  var a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b === 1) return forms[0];
  if (b >= 2 && b <= 4) return forms[1];
  return forms[2];
}

function haText(ha) {
  if (ha === null || ha === undefined || ha === '') return '';
  var v = Number(ha);
  return v >= 100 ? fmt(v, 1) + ' га (' + fmt(v / 100, 2) + ' км²)' : fmt(v, 2) + ' га';
}

function sceneDate(id) {
  return id.substr(0, 4) + '-' + id.substr(4, 2) + '-' + id.substr(6, 2);
}

function codesList(sel) {
  var out = [];
  CLASSES.forEach(function(c) { if (sel[c.code]) out.push(c.code); });
  return out;
}

function ones(n) {
  var a = [];
  for (var i = 0; i < n; i++) a.push(1);
  return a;
}

function palette(key) {
  return CLASSES.map(function(c) { return c[key]; });
}

function emptyImage() {
  return ee.Image(0).selfMask();
}

// Заливка и контур полигонов таблицы
function paintPolys(fc, fill, line, fillOpacity, width) {
  var parts = [];
  if (fillOpacity > 0) {
    parts.push(ee.Image().byte().paint(fc, 1).selfMask().visualize({palette: [fill], opacity: fillOpacity}));
  }
  parts.push(ee.Image().byte().paint(fc, 1, width || 1).selfMask().visualize({palette: [line]}));
  return ee.ImageCollection(parts).mosaic();
}

// Классификация растра плотности по границам шкалы (145: значение ниже первой границы идёт в первый класс)
function densityImage(asset, scale) {
  var sc = DENSITY_SCALES[scale];
  var v = ee.Image(asset).select(0);
  var idx = ee.Image(0);
  sc.bounds.forEach(function(b) { idx = idx.add(v.gte(b)); });
  return idx.updateMask(v.gt(0)).visualize({min: 0, max: sc.colors.length - 1, palette: sc.colors});
}

function metersPerPixel(zoom, lat) {
  return 156543.03392 * Math.cos(lat * Math.PI / 180) / Math.pow(2, zoom);
}

// ============================================================================
// 5. СОСТОЯНИЕ И ПРОВЕРКА АССЕТОВ
// ============================================================================

var state = {
  zoom: 5,
  classes: {1: true, 2: true, 3: true, 4: true, 5: true, 6: true},
  outlines: true,
  densityClass: 'aeolian',
  densityCell: 'auto',
  hansen: 'first',
  s2tile: 'ALL',
  s2scene: null,
  s2combo: 'fcc',
  assets: {}            // путь -> 'ok' | 'missing' | 'pending'
};

var assetListeners = [];

function assetState(path) {
  if (!isSet(path)) return 'unset';
  return state.assets[path] || 'pending';
}

// Асинхронная проверка: ассет есть и доступен (для App ассеты нужно открыть на чтение, README). Ответ «нет» не
// запоминается навсегда: при следующем включении слоя ассет проверяется снова (временная ошибка доступа).
function checkAsset(path) {
  if (!isSet(path) || state.assets[path] === 'ok' || state.assets[path] === 'pending') return;
  state.assets[path] = 'pending';
  ee.data.getAsset(path, function(result, error) {
    state.assets[path] = (result && !error) ? 'ok' : 'missing';
    assetListeners.forEach(function(fn) { fn(path); });
  });
}

// ============================================================================
// 6. КАРТА
// ============================================================================

var map = ui.Map();
map.setOptions('Светлая', {'Светлая': LIGHT_STYLE}, ['Светлая', 'SATELLITE', 'HYBRID', 'TERRAIN']);
map.setControlVisibility({all: false, zoomControl: true, scaleControl: true, mapTypeControl: true,
                          fullscreenControl: true});
map.style().set('cursor', 'crosshair');
map.setCenter(75.5, 66.3, 5);

// ============================================================================
// 7. СЛОИ
// ============================================================================
// Слой: id, группа, заголовок, включён ли, прозрачность, нужные ассеты, make(zoom) -> ee.Image (визуализированный)
// или null (на этом масштабе не показывается, текст в why), key(zoom) -> ключ уровня (перерисовка при смене),
// legend() -> виджет, query(pt, buf) -> ee-объект для evaluate и render(result) -> строки карточки.

var LAYERS = [];
var BY_ID = {};

function addLayer(def) {
  def.on = !!def.on;
  def.opacity = def.opacity === undefined ? 0.85 : def.opacity;
  def.assets = def.assets || [];
  def.levelKey = null;
  LAYERS.push(def);
  BY_ID[def.id] = def;
  return def;
}


// Все сцены всех тайлов: обзорная мозаика
function allSceneIds() {
  var out = [];
  SCENES.forEach(function(r) { r.c.forEach(function(id) { if (out.indexOf(id) < 0) out.push(id); }); });
  return out;
}
var S2_COMPAT = ee.ImageCollection(CATALOG.s2).filter(ee.Filter.inList('system:index', allSceneIds()));

function s2Collection() {
  if (state.s2tile === 'ALL') return S2_COMPAT;
  if (state.s2scene === 'TILE') return ee.ImageCollection(CATALOG.s2).filter(ee.Filter.inList('system:index', sceneByTile(state.s2tile).c));
  return ee.ImageCollection(CATALOG.s2).filter(ee.Filter.eq('system:index', state.s2scene));
}

function sceneByTile(t) {
  for (var i = 0; i < SCENES.length; i++) if (SCENES[i].t === t) return SCENES[i];
  return null;
}

// --- 1. Исходные снимки ---
addLayer({
  id: 's2', group: 2, title: 'Сцены Sentinel-2', on: false, opacity: 1,
  make: function() {
    var vis = S2_VIS[state.s2combo].vis;
    return s2Collection().mosaic().visualize(vis);
  },
  key: function() { return [state.s2tile, state.s2scene, state.s2combo].join('|'); },
  // карточка описывает показанные сцены (мозаики или выбранную сцену тайла)
  query: function(pt) {
    return s2Collection().filterBounds(pt).aggregate_array('system:index');
  },
  render: function(ids) {
    if (!ids || !ids.length) return [['Сцена', 'вне показанных сцен']];
    return ids.map(function(id) {
      var rec = sceneByTile(id.slice(-5));
      var note = rec ? (rec.c.length > 1 ? 'одна из ' + rec.c.length + ' сцен мозаики тайла' : 'сцена тайла') : 'сцена';
      return ['Сцена ' + id.slice(-5), sceneDate(id) + ' (' + note + '); ' + id];
    });
  }
});

// --- 2. Первичная маска и вектор ---
addLayer({
  id: 'mask', group: 2, title: 'Маска песка, 10 м', on: false, opacity: 0.9,
  assets: [ASSETS.maskRaster],
  make: function(z) {
    if (z >= Z_MASK && assetState(ASSETS.maskRaster) === 'ok') {
      return ee.Image(ASSETS.maskRaster).select('sand_mask').selfMask().visualize({palette: ['FFD700']});
    }
    if (assetState(ASSETS.genesisRaster) === 'ok') {
      // мелкий масштаб: охват контуров по растру итогового слоя (пирамиды MODE не теряют мелкие контуры)
      return ee.Image(ASSETS.genesisRaster).select(0).gt(0).selfMask().visualize({palette: ['FFD700']});
    }
    return null;
  },
  why: 'видно с масштаба ' + Z_MASK + ' (на мелких масштабах нужен растр классов genesis_r50)',
  key: function(z) { return z >= Z_MASK ? 'hi' : 'lo'; },
  legend: function() {
    return legendRows([['FFD700', 'песок по классификации сцен; с масштаба ' + Z_MASK + ' растр 10 м, мельче охват ' +
                        'контуров']]);
  }
});

addLayer({
  id: 'contours', group: 2, title: 'Первичный вектор маски', on: false, opacity: 0.9,
  assets: [ASSETS.contours], fv: 'contours',
  make: function(z) {
    if (z < Z_VECTOR || FEATURE_VIEWS.contours) return null;
    return paintPolys(ee.FeatureCollection(ASSETS.contours), 'FFD700', '8a6d00', 0.35, 1);
  },
  why: 'видно с масштаба ' + Z_VECTOR,
  key: function(z) { return z >= Z_VECTOR ? 'hi' : 'lo'; },
  fvVis: function() {
    return {polygonFillColor: '#FFD700', polygonFillOpacity: 0.35, polygonStrokeColor: '#8a6d00',
            polygonStrokeWidth: 1};
  },
  legend: function() {
    return legendRows([['FFD700', 'контуры маски до атрибуции генезиса: 574 520, не меньше 900 м² (с масштаба ' +
                        Z_VECTOR + ')']]);
  },
  query: function(pt, buf) { return nearestDict(ASSETS.contours, pt, buf); },
  render: function(p) {
    if (!p) return [['Контур', 'нет в радиусе клика']];
    // в ассете 150 у первичного вектора только id; площадь контура показывает итоговый слой генезиса
    var rows = [['id', String(p.id)]];
    if (p.area_ha !== null && p.area_ha !== undefined && p.area_ha !== '') rows.push(['Площадь', haText(p.area_ha)]);
    return rows;
  }
});

// --- 3. Итоговые слои ---
addLayer({
  id: 'genesis', group: 1, title: 'Генезис песков', on: true, opacity: 0.85,
  assets: [ASSETS.genesis, ASSETS.genesisRaster], fv: 'genesis',
  make: function(z) {
    var codes = codesList(state.classes);
    if (!codes.length) return null;
    var parts = [];
    var fc = ee.FeatureCollection(ASSETS.genesis).filter(ee.Filter.inList('gcode', codes));
    if (assetState(ASSETS.genesisRaster) === 'ok') {
      var r = ee.Image(ASSETS.genesisRaster).select(0);
      r = r.updateMask(r.remap(codes, ones(codes.length), 0));
      parts.push(r.visualize({min: 1, max: 6, palette: palette('fill')}));
    } else if (z >= Z_FILL && assetState(ASSETS.genesis) === 'ok') {
      parts.push(ee.Image().byte().paint(fc, 'gcode').selfMask()
        .visualize({min: 1, max: 6, palette: palette('fill')}));
    }
    if (state.outlines && z >= Z_VECTOR && !FEATURE_VIEWS.genesis && assetState(ASSETS.genesis) === 'ok') {
      parts.push(ee.Image().byte().paint(fc, 'gcode', 1).selfMask()
        .visualize({min: 1, max: 6, palette: palette('line')}));
    }
    return parts.length ? ee.ImageCollection(parts).mosaic() : null;
  },
  why: 'без растра классов заливка видна с масштаба ' + Z_FILL,
  key: function(z) {
    return [z >= Z_VECTOR, z >= Z_FILL, codesList(state.classes).join(','), state.outlines,
            assetState(ASSETS.genesisRaster), assetState(ASSETS.genesis)].join('|');
  },
  fvVis: function() {
    var hidden = [];
    CLASSES.forEach(function(c) { if (!state.classes[c.code]) hidden.push(c.code); });
    var vis = {
      polygonFillColor: {property: 'genesis', categories: CLASSES.map(function(c) { return [c.key, '#' + c.fill]; }),
                         defaultValue: '#000000'},
      polygonStrokeColor: {property: 'genesis', categories: CLASSES.map(function(c) { return [c.key, '#' + c.line]; }),
                           defaultValue: '#000000'},
      polygonFillOpacity: 0.8, polygonStrokeWidth: 0.8
    };
    if (hidden.length) vis.rules = [{filter: ee.Filter.inList('gcode', hidden), isVisible: false}];
    return vis;
  },
  legend: function() { return genesisLegend(); },
  // запрос только по включённым в легенде классам
  query: function(pt, buf) {
    return nearestDict(ee.FeatureCollection(ASSETS.genesis).filter(ee.Filter.inList('gcode', codesList(state.classes))),
                       pt, buf);
  },
  render: function(p) { return genesisRows(p); }
});

addLayer({
  id: 'density', group: 1, title: 'Плотность песков, га/км²', on: false, opacity: 0.85,
  assets: densityAllAssets(),
  make: function() {
    var a = densityAsset(state.densityClass, densityCell().km);
    fillDensityLegend();   // подпись ячейки соответствует текущему масштабу
    if (assetState(a) !== 'ok') return null;
    return densityImage(a, densityCell().scale);
  },
  why: 'нет растра плотности для выбранного варианта',
  key: function() { var a = densityAsset(state.densityClass, densityCell().km); return a + '|' + assetState(a); },
  legend: function() { return densityLegend(); },
  query: function(pt) {
    return ee.Image(densityAsset(state.densityClass, densityCell().km)).select(0)
      .reduceRegion(ee.Reducer.first(), pt, 100).values().get(0);
  },
  render: function(v) {
    var lab = classDensityLabel() + ', ячейка ' + densityCell().km + ' км';
    return [['Плотность', (v === null || v === undefined || v === 0) ? 'песков в ячейке нет (' + lab + ')' :
             fmt(v, 2) + ' га/км² (' + lab + ')']];
  }
});

addLayer({
  id: 'allotments', group: 1, sub: 'cad', title: 'Отводы под объекты (обобщённо)', on: false, opacity: 0.8,
  assets: [ASSETS.allotments],
  make: function(z) {
    if (z < Z_ANTHRO || assetState(ASSETS.allotments) !== 'ok') return null;
    return paintPolys(ee.FeatureCollection(ASSETS.allotments), '9ECAE1', '2171B5', 0.35, 1);
  },
  why: 'видно с масштаба ' + Z_ANTHRO,
  key: function(z) { return (z >= Z_ANTHRO ? 'hi' : 'lo') + '|' + assetState(ASSETS.allotments); },
  legend: function() {
    return legendRows([['9ECAE1', 'участки ЕГРН под объекты (промышленные земли, ВРИ под объекты, части единых ' +
                        'землепользований, земли и территория населённых пунктов) ближе 60 м к техногенным пескам; ' +
                        'слиты в массивы, без атрибутов, граница упрощена на 10 м']]);
  },
  query: function(pt) { return nearestDict(ASSETS.allotments, pt, 0); },
  render: function(p) { return [['Отвод под объект', p ? 'есть (обобщённо, по сведениям ЕГРН)' : 'нет в точке']]; }
});

CAD_CLASSES.forEach(function(cc) {
  addLayer({
    id: cc.key, group: 1, sub: 'cad', title: cc.title, on: false, opacity: 0.85,
    assets: [ASSETS[cc.key]], fv: cc.fv,
    make: function(z) {
      if (z < Z_ANTHRO || FEATURE_VIEWS[cc.fv]) return null;
      return paintPolys(ee.FeatureCollection(ASSETS[cc.key]), cc.fill, cc.line, 0.6, 1);
    },
    why: 'видно с масштаба ' + Z_ANTHRO,
    key: function(z) { return z >= Z_ANTHRO ? 'hi' : 'lo'; },
    fvVis: function() {
      return {polygonFillColor: '#' + cc.fill, polygonFillOpacity: 0.6, polygonStrokeColor: '#' + cc.line,
              polygonStrokeWidth: 1};
    },
    legend: function() { return legendRows([[cc.fill, cc.note]]); },
    query: function(pt, buf) { return nearestDict(ASSETS[cc.key], pt, buf); },
    render: function(p) { return genericRows(p, cc.title); }
  });
});

// --- 4. Дополнительные слои ---
addLayer({
  id: 'aoi', group: 3, title: 'Граница района работ', on: true, opacity: 1,
  assets: [ASSETS.aoi],
  make: function() {
    if (assetState(ASSETS.aoi) !== 'ok') return null;
    var fc = ee.FeatureCollection(ASSETS.aoi);
    return ee.ImageCollection([
      ee.Image().byte().paint(fc, 1, 3).selfMask().visualize({palette: ['ffffff'], opacity: 0.8}),
      ee.Image().byte().paint(fc, 1, 1).selfMask().visualize({palette: ['3a3d42']})
    ]).mosaic();
  },
  key: function() { return assetState(ASSETS.aoi); },
  legend: function() { return legendRows([['3a3d42', 'район работ: 1 068 411 км²']]); }
});

addLayer({
  id: 'coverage', group: 3, title: 'Покрытие маски', on: false, opacity: 0.8,
  assets: [ASSETS.aoi, ASSETS.coverage],
  make: function() {
    if (assetState(ASSETS.aoi) !== 'ok' || assetState(ASSETS.coverage) !== 'ok') return null;
    var cov = ee.FeatureCollection(ASSETS.coverage);
    var out = ee.FeatureCollection([ee.Feature(ee.FeatureCollection(ASSETS.aoi).geometry()
      .difference(cov.geometry(), ee.ErrorMargin(100)))]);
    return ee.ImageCollection([
      ee.Image().byte().paint(out, 1).selfMask().visualize({palette: ['9e9e9e'], opacity: 0.45}),
      ee.Image().byte().paint(cov, 1, 1).selfMask().visualize({palette: ['6b6f76']})
    ]).mosaic();
  },
  key: function() { return assetState(ASSETS.aoi) + assetState(ASSETS.coverage); },
  legend: function() {
    return legendRows([['ffffff', 'покрытие маски: 906 325 км², 84,8 % района'],
                       ['9e9e9e', 'вне покрытия (при подборе эталонов оголённые пески не обнаружены)']]);
  }
});

addLayer({
  id: 'tiles', group: 3, title: 'Тайлы MGRS', on: false, opacity: 0.9,
  assets: [ASSETS.tiles],
  make: function(z) {
    if (z < Z_TILES || assetState(ASSETS.tiles) !== 'ok') return null;
    var fc = ee.FeatureCollection(ASSETS.tiles);
    var img = ee.Image().byte().paint(fc, 1, 1).selfMask().visualize({palette: ['6b6f76']});
    if (state.s2tile !== 'ALL') {
      img = ee.ImageCollection([img, ee.Image().byte().paint(fc.filter(ee.Filter.eq('tile', state.s2tile)), 1, 3)
        .selfMask().visualize({palette: [C.accent.substr(1)]})]).mosaic();
    }
    return img;
  },
  why: 'видно с масштаба ' + Z_TILES,
  key: function(z) { return (z >= Z_TILES) + '|' + state.s2tile + '|' + assetState(ASSETS.tiles); },
  query: function(pt) {
    return ee.FeatureCollection(ASSETS.tiles).filterBounds(pt).aggregate_array('tile');
  },
  render: function(t) { return [['Тайл MGRS', t && t.length ? t.join(', ') : 'вне тайлов маски']]; }
});

addLayer({
  id: 'infra', group: 3, title: 'Инфраструктура (OSM)', on: false, opacity: 0.9,
  assets: [ASSETS.infraLines, ASSETS.infraAreas],
  make: function(z) {
    var parts = [];
    if (assetState(ASSETS.infraAreas) === 'ok') {
      var areas = ee.FeatureCollection(ASSETS.infraAreas);
      INFRA.forEach(function(r) {
        if (!r.on || z < r.zoom || (r.key !== 'areas' && r.key !== 'quarry')) return;
        var fc = r.key === 'quarry' ? areas.filter(ee.Filter.eq('kind', 'quarry')) :
          areas.filter(ee.Filter.neq('kind', 'quarry'));
        parts.push(paintPolys(fc, r.color, r.color, 0.35, 1));
      });
    }
    if (assetState(ASSETS.infraLines) === 'ok') {
      var lines = ee.FeatureCollection(ASSETS.infraLines);
      INFRA.forEach(function(r) {
        if (!r.on || z < r.zoom || r.key === 'areas' || r.key === 'quarry') return;
        var fc = r.key === 'winter' ? lines.filter(ee.Filter.eq('winter', 1)) : lines.filter(ee.Filter.eq('kind', r.key));
        parts.push(ee.Image().byte().paint(fc, 1, r.width).selfMask().visualize({palette: [r.color]}));
      });
    }
    return parts.length ? ee.ImageCollection(parts).mosaic() : null;
  },
  why: 'включённые виды видны с более крупного масштаба',
  key: function(z) {
    return INFRA.map(function(r) { return r.on && z >= r.zoom ? 1 : 0; }).join('') + '|' +
      assetState(ASSETS.infraLines) + assetState(ASSETS.infraAreas);
  },
  legend: function() { return infraLegend(); },
  query: function(pt, buf) {
    return ee.Dictionary({line: nearestDict(ASSETS.infraLines, pt, buf), area: nearestDict(ASSETS.infraAreas, pt, 0)});
  },
  render: function(d) {
    var rows = [];
    if (d && d.line) rows.push(['Линия', (INFRA_RU[d.line.kind] || d.line.kind) + (d.line.winter ? ', зимник' : '')]);
    if (d && d.area) {
      rows.push(['Площадка', d.area.kind === 'quarry' ? 'карьер' : (INFRA_KIND_AREA_RU[d.area.kind] || d.area.kind)]);
    }
    if (!rows.length) rows.push(['Инфраструктура', 'нет объектов OSM в радиусе клика']);
    return rows;
  }
});

addLayer({
  id: 'oilfields', group: 3, title: 'Месторождения', on: false, opacity: 0.85,
  assets: [ASSETS.oilfields],
  make: function() {
    if (assetState(ASSETS.oilfields) !== 'ok') return null;
    return paintPolys(ee.FeatureCollection(ASSETS.oilfields), '7ee05a', '3f8f2a', 0.18, 1);
  },
  key: function() { return assetState(ASSETS.oilfields); },
  legend: function() { return legendRows([['7ee05a', 'контуры месторождений (oilfields/Efield_region.shp)']]); },
  query: function(pt) { return nearestDict(ASSETS.oilfields, pt, 0); },
  render: function(p) {
    if (!p) return [['Месторождение', 'нет']];
    return [['Месторождение', p.name_ru || p.name_en || ''], ['Тип', p.type || ''],
            ['Стадия', p.stage_ru || p.stage_en || '']];
  }
});

addLayer({
  id: 'dem', group: 3, title: 'Рельеф ArcticDEM', on: false, opacity: 0.75,
  make: function() {
    var dem = ee.Image(CATALOG.dem).select('elevation');
    var hs = ee.Terrain.hillshade(dem);
    var col = dem.visualize({min: 0, max: 200, palette: ['3a3a3a', '8c8c8c', 'f4f4f4']});
    return col.multiply(hs.divide(255).multiply(0.6).add(0.4)).uint8();
  },
  key: function() { return 'dem'; },
  legend: function() {
    return legendRows([['3a3a3a', '0 м'], ['f4f4f4', '200 м и выше (над эллипсоидом WGS84, ' +
                        'отмывка; шкала как на картах 145)']]);
  },
  query: function(pt) {
    return ee.Image(CATALOG.dem).select('elevation').reduceRegion(ee.Reducer.first(), pt, 2).get('elevation');
  },
  render: function(v) { return [['Высота ArcticDEM', v === null || v === undefined ? 'нет данных' : fmt(v, 1) + ' м']]; }
});

addLayer({
  id: 'gsw', group: 3, title: 'Повторяемость воды (JRC GSW)', on: false, opacity: 0.8,
  make: function() {
    return ee.Image(CATALOG.gsw).select('occurrence').selfMask()
      .visualize({min: 0, max: 100, palette: ['d4e7f7', '2b7bba', '08306b']});
  },
  key: function() { return 'gsw'; },
  legend: function() {
    return legendRows([['d4e7f7', 'вода редко (1984-2021)'], ['08306b', 'вода постоянно']]);
  },
  query: function(pt) {
    return ee.Image(CATALOG.gsw).select('occurrence').reduceRegion(ee.Reducer.first(), pt, 30).get('occurrence');
  },
  render: function(v) { return [['Повторяемость воды', v === null || v === undefined ? 'нет' : fmt(v, 0) + ' %']]; }
});

addLayer({
  id: 'hansen', group: 3, title: 'Лесной покров (Hansen GFC)', on: false, opacity: 0.85,
  make: function() {
    var h = ee.Image(CATALOG.hansen);
    if (state.hansen === 'first') {
      return h.visualize({bands: ['first_b50', 'first_b40', 'first_b30'], min: [5, 5, 3], max: [100, 90, 65]});
    }
    if (state.hansen === 'loss') {
      return h.select('lossyear').selfMask().visualize({min: 1, max: 19, palette: ['ffe08a', 'f08c3c', 'b2182b']});
    }
    return h.select('treecover2000').selfMask().visualize({min: 0, max: 100, palette: ['eef5e9', '2d6a2d']});
  },
  key: function() { return state.hansen; },
  legend: function() { return hansenLegend(); },
  query: function(pt) {
    return ee.Image(CATALOG.hansen).select(['treecover2000', 'lossyear'])
      .reduceRegion(ee.Reducer.first(), pt, 30);
  },
  render: function(d) {
    if (!d) return [];
    return [['Древесный покров 2000', d.treecover2000 === null ? 'нет' : fmt(d.treecover2000, 0) + ' %'],
            ['Потеря покрова', d.lossyear ? String(2000 + d.lossyear) + ' г.' : 'нет']];
  }
});

// Запрос по клику возможен, если нужные ассеты доступны (у генезиса нужна таблица, у плотности текущий растр)
function canQuery(L) {
  var need = L.id === 'genesis' ? [ASSETS.genesis] :
             L.id === 'density' ? [densityAsset(state.densityClass, densityCell().km)] : L.assets;
  return need.every(function(a) { return assetState(a) === 'ok'; });
}

// Ближайший к точке объект таблицы (путь ассета или ee.FeatureCollection) в радиусе buf (м); внутри полигона
// расстояние 0. Возвращает словарь или null.
function nearestDict(asset, pt, buf) {
  var fc = typeof asset === 'string' ? ee.FeatureCollection(asset) : asset;
  var hits = buf > 0 ? fc.filterBounds(pt.buffer(buf)) : fc.filterBounds(pt);
  var first = ee.Feature(hits.map(function(f) {
    return f.set('_dist', f.geometry().distance(pt, 1));
  }).sort('_dist').first());
  return ee.Algorithms.If(hits.size().gt(0), first.toDictionary(), null);
}

// ============================================================================
// 8. ЛЕГЕНДЫ И КАРТОЧКИ
// ============================================================================

function swatch(color, bg) {
  return ui.Label('', {backgroundColor: '#' + color, padding: '6px 9px', margin: '3px 8px 0 0',
                       border: '1px solid ' + (bg || '#8c8c8c')});
}

// nested: легенда внутри другой легенды (без второго отступа слева, иначе строка шире панели)
function legendRows(rows, nested) {
  var p = ui.Panel([], ui.Panel.Layout.flow('vertical'), nested ? S.row : S.legend);
  rows.forEach(function(r) {
    if (!r[0]) {
      // пояснение без образца цвета: отдельной строкой с ограниченной шириной, чтобы переносилось
      p.add(ui.Label(r[1], {fontSize: '12px', color: C.muted, margin: '4px 0 4px 0', whiteSpace: 'normal',
                            backgroundColor: C.bg, width: '300px'}));
      return;
    }
    p.add(ui.Panel([swatch(r[0]), ui.Label(r[1], S.legendText)], ui.Panel.Layout.flow('horizontal'), S.row));
  });
  return p;
}

function genesisLegend() {
  var p = ui.Panel([], ui.Panel.Layout.flow('vertical'), S.legend);
  CLASSES.forEach(function(c) {
    var cb = ui.Checkbox({label: '', value: state.classes[c.code], style: {margin: '2px 0 0 0',
                          backgroundColor: C.bg}, onChange: function(v) {
      state.classes[c.code] = v;
      refresh(BY_ID.genesis);
    }});
    p.add(ui.Panel([cb, swatch(c.fill, '#' + c.line), ui.Label(c.label + ', ' + c.km2 + ' км²',
                                                                 {fontSize: '13px', color: C.ink, margin: '3px 0 0 0',
                                                                  backgroundColor: C.bg, width: '220px'})],
                   ui.Panel.Layout.flow('horizontal'), S.row));
  });
  p.add(ui.Checkbox({label: 'границы контуров (с масштаба ' + Z_VECTOR + ')', value: state.outlines,
                     style: {fontSize: '12px', color: C.muted, margin: '4px 0 0 0', backgroundColor: C.bg},
                     onChange: function(v) { state.outlines = v; refresh(BY_ID.genesis); }}));
  p.add(ui.Label('575 054 контура, 8 155,7 км². На обзорных масштабах мелкие контуры показаны по растру 50 м.',
                 S.small));
  return p;
}

var densityLegendBox = ui.Panel([], ui.Panel.Layout.flow('vertical'), S.row);

function classDensityLabel() {
  var out = state.densityClass;
  DENSITY_CLASSES.forEach(function(c) { if (c.key === state.densityClass) out = c.label; });
  return out;
}

function fillDensityLegend() {
  var cell = densityCell();
  var sc = DENSITY_SCALES[cell.scale];
  var rows = sc.colors.map(function(col, i) { return [col, sc.labels[i]]; });
  rows.push([null, 'Ячейка ' + cell.km + ' км' + (state.densityCell === 'auto' ? ' (по масштабу карты)' : '') +
                   '. Площадь контуров с центроидом в ячейке на км² ячейки.']);
  densityLegendBox.widgets().reset([legendRows(rows, true)]);
}

function densityLegend() {
  var clsSel = ui.Select({
    items: DENSITY_CLASSES.map(function(c) { return {label: c.label, value: c.key}; }),
    value: state.densityClass, style: S.select,
    onChange: function(v) { state.densityClass = v; fillDensityLegend(); refresh(BY_ID.density); }
  });
  var cellSel = ui.Select({
    items: [{label: 'ячейка по масштабу: 10, 5, 2 км', value: 'auto'}].concat(
      DENSITY_CELLS.map(function(d) { return {label: 'ячейка ' + d.km + ' км', value: String(d.km)}; })),
    value: state.densityCell, style: S.select,
    onChange: function(v) { state.densityCell = v; fillDensityLegend(); refresh(BY_ID.density); }
  });
  fillDensityLegend();
  return ui.Panel([clsSel, cellSel, densityLegendBox], ui.Panel.Layout.flow('vertical'), S.legend);
}

function infraLegend() {
  var p = ui.Panel([], ui.Panel.Layout.flow('vertical'), S.legend);
  INFRA.forEach(function(r) {
    var cb = ui.Checkbox({label: '', value: r.on, style: {margin: '2px 0 0 0', backgroundColor: C.bg},
                          onChange: function(v) { r.on = v; refresh(BY_ID.infra); }});
    p.add(ui.Panel([cb, swatch(r.color), ui.Label(r.label + (r.zoom > 5 ? ' (с масштаба ' + r.zoom + ')' : ''),
                    {fontSize: '13px', color: C.ink, margin: '3px 0 0 0', backgroundColor: C.bg, width: '220px'})],
                   ui.Panel.Layout.flow('horizontal'), S.row));
  });
  p.add(ui.Label('Данные © участники OpenStreetMap, ODbL 1.0 (выгрузка 05.09.2026).', S.small));
  return p;
}

function hansenLegend() {
  var sel = ui.Select({
    items: Object.keys(HANSEN_MODES).map(function(k) { return {label: HANSEN_MODES[k], value: k}; }),
    value: state.hansen, style: S.select,
    onChange: function(v) { state.hansen = v; refresh(BY_ID.hansen); }
  });
  return ui.Panel([sel, ui.Label('Hansen et al. (2013), версия 1.7: по ней определён возраст поверхности ' +
                                 'техногенных песков.', S.small)],
                  ui.Panel.Layout.flow('vertical'), S.legend);
}

function classLabel(key) {
  var out = key;
  CLASSES.forEach(function(c) { if (c.key === key) out = c.label; });
  return out;
}

function genesisRows(p) {
  if (!p) return [['Контур', 'нет в радиусе клика']];
  var cls = null;
  CLASSES.forEach(function(c) { if (c.key === p.genesis) cls = c; });
  var rows = [];
  rows.push(['Класс генезиса', (cls ? cls.label : (MAIN_RU[p.gen_main] || p.genesis || '')) +
             (p.shoal_type ? ' (тип: ' + (SHOAL_RU[p.shoal_type] || p.shoal_type) +
              (p.shoal_src ? ', источник типа: ' + (SHOAL_SRC_RU[p.shoal_src] || p.shoal_src) : '') + ')' : '')]);
  rows.push(['Площадь', haText(p.area_ha)]);
  if (p.rule) {
    rows.push(['Правило', (RULE_RU[p.rule] || (p.rule.indexOf('step') === 0 ? 'класс дан шагом без кода правила' :
               p.rule)) + ' [' + p.rule + ']']);
  }
  if (p.rule_step) rows.push(['Шаг', STEP_RU[p.rule_step] || String(p.rule_step)]);
  if (p.step6_rule && p.step6_rule !== p.rule) {
    rows.push(['Происхождение класса', (RULE_RU[p.step6_rule] || p.step6_rule) + ' [' + p.step6_rule + ']']);
  } else if (!p.rule) {
    // step6_rule пуст: класс дан каскадом правил и позже не менялся (ассет 150 не содержит кода правила каскада)
    rows.push(['Происхождение класса', 'каскад правил (шаги 1-5)']);
  }
  if (p.note) rows.push(['Метка автора', p.note]);
  if (p.gen_v6 && p.gen_v6 !== p.genesis) rows.push(['Класс до исправлений v7', classLabel(p.gen_v6)]);
  if (p.genesis === 'anthropogenic' && !p.cad_status) {
    rows.push(['Кадастр', 'включите слои «Техногенные пески и кадастровые отводы ЕГРН»']);
  } else if (p.genesis === 'anthropogenic') {
    rows.push(['Кадастровый статус', CAD_STATUS_RU[p.cad_status] || p.cad_status]);
    if (p.cad_in_ha !== null && p.cad_in_ha !== undefined && p.cad_in_ha !== '') {
      rows.push(['В отводах / вне', haText(p.cad_in_ha) + ' / ' + haText(p.cad_out_ha)]);
    }
    if (Number(p.exc10_ha) > 0) rows.push(['За полосой 10 м', haText(p.exc10_ha)]);
    if (p.age2000) rows.push(['Возраст поверхности', AGE_RU[p.age2000] || p.age2000]);
  }
  rows.push(['id', String(p.id)]);
  return rows;
}

// Подписи известных полей кадастровых слоёв (133); прочие поля показываются как есть
var FIELD_RU = {
  area_ha: 'Площадь', in_ha: 'В отводе', ctr_ha: 'Площадь контура', in_pct: 'Доля в отводе, %',
  grp_ru: 'Группа участка', under_ru: 'Под объектом', grp: 'Группа участка', under: 'Под объектом',
  kind: 'Вид', kind_ru: 'Вид', age2000: 'Возраст поверхности', id: 'id контура'
};
var FIELD_SKIP = {_dist: 1, ge_mmu: 1, system_index: 1};
// Порядок строк карточки: известные поля первыми, прочие следом
var FIELD_ORDER = ['kind_ru', 'kind', 'grp_ru', 'grp', 'under_ru', 'under', 'area_ha', 'in_ha', 'ctr_ha', 'in_pct',
                   'age2000', 'id'];

function genericRows(p, title) {
  if (!p) return [[title, 'нет объекта в радиусе клика']];
  var rows = [];
  // коды не дублируют русские поля, если те есть в ассете
  var skip = {grp: !!p.grp_ru, under: !!p.under_ru, kind: !!p.kind_ru};
  var keys = FIELD_ORDER.filter(function(k) { return k in p; })
    .concat(Object.keys(p).filter(function(k) { return FIELD_ORDER.indexOf(k) < 0; }));
  keys.forEach(function(k) {
    if (FIELD_SKIP[k] || skip[k] || k.indexOf('system:') === 0) return;
    var v = p[k];
    if (v === null || v === undefined || v === '') return;
    if (k.slice(-3) === '_ha') v = haText(v);
    else if (k === 'age2000') v = AGE_RU[v] || v;
    else if (k === 'grp' || k === 'under') v = GRP_RU[v] || v;
    else if (k === 'kind') v = KIND_RU[v] || v;
    else if (k === 'id') v = String(v);
    else if (typeof v === 'number') v = fmt(v, v % 1 === 0 ? 0 : 2);
    rows.push([FIELD_RU[k] || k, String(v)]);
  });
  return rows;
}

// ============================================================================
// 9. ПОКАЗ СЛОЁВ
// ============================================================================

// Места слоёв на карте создаются сразу в нужном порядке (снизу вверх), поэтому порядок не зависит от порядка включения
var DRAW_ORDER = ['s2', 'dem', 'hansen', 'gsw', 'density', 'mask', 'genesis', 'contours', 'allotments', 'anthroIn',
                  'anthroExceed', 'anthroNoallot', 'oilfields', 'infra', 'coverage', 'tiles', 'aoi'];

DRAW_ORDER.forEach(function(id) {
  var L = BY_ID[id];
  L.mapLayer = ui.Map.Layer(emptyImage(), {}, L.title, false, L.opacity);
  map.layers().add(L.mapLayer);
  if (L.fv && isSet(FEATURE_VIEWS[L.fv])) {
    L.fvLayer = ui.Map.FeatureViewLayer(FEATURE_VIEWS[L.fv], L.fvVis(), L.title + ' (FeatureView)', false, L.opacity);
    map.layers().add(L.fvLayer);
  }
});

function setStatus(L, text) {
  if (!L.status) return;
  L.status.setValue(text || '');
  L.status.style().set('shown', !!text);
}

function refresh(L) {
  if (!L.mapLayer) return;
  if (!L.on) {
    L.mapLayer.setShown(false);
    if (L.fvLayer) L.fvLayer.setShown(false);
    setStatus(L, '');
    return;
  }
  var unset = L.assets.filter(function(a) { return !isSet(a); });
  var missing = L.assets.filter(function(a) { return assetState(a) === 'missing'; });
  var z = state.zoom;
  var key = L.key ? L.key(z) : 'one';
  if (L.fvLayer) {
    if (key !== L.levelKey) L.fvLayer.setVisParams(L.fvVis());
    L.fvLayer.setShown(z >= Z_VECTOR || L.sub === 'cad');
  }
  if (key !== L.levelKey || !L.mapLayer.getShown()) {
    var img = L.make(z);
    L.levelKey = key;
    if (img) {
      L.mapLayer.setEeObject(img);
      L.mapLayer.setShown(true);
    } else {
      L.mapLayer.setShown(false);
    }
    L.lastHasImage = !!img;
  }
  var msg = '';
  if (unset.length === L.assets.length && L.assets.length) msg = 'ассет не задан (раздел 1 скрипта)';
  else if (L.id === 'genesis' && missing.length === 1 && missing[0] === ASSETS.genesisRaster) {
    msg = 'нет растра классов (' + ASSETS.genesisRaster + '): заливка из таблицы с масштаба ' + Z_FILL;
  } else if (missing.length) msg = 'ассет не найден или закрыт: ' + missing.join(', ');
  else if (!L.lastHasImage && !L.fvLayer) msg = L.why || 'нет данных для показа';
  setStatus(L, msg);
}

function setOpacity(L, v) {
  L.opacity = v;
  if (L.mapLayer) L.mapLayer.setOpacity(v);
  if (L.fvLayer) L.fvLayer.setOpacity(v);
}

map.onChangeZoom(function(z) {
  state.zoom = Number(z);
  if (BY_ID.density.on && state.densityCell === 'auto') fillDensityLegend();
  LAYERS.forEach(function(L) { if (L.on) refresh(L); });
});

assetListeners.push(function(path) {
  LAYERS.forEach(function(L) {
    if (L.assets.indexOf(path) >= 0 || L.id === 'mask' || L.id === 'genesis') {
      L.levelKey = null;
      if (L.on) refresh(L);
    }
  });
});

// ============================================================================
// 10. ПАНЕЛЬ
// ============================================================================

function divider() {
  return ui.Label('', S.rule);
}

function layerRow(L) {
  var cb = ui.Checkbox({label: L.title, value: L.on, style: S.checkbox, onChange: function(v) {
    L.on = v;
    if (v) L.assets.forEach(checkAsset);
    L.legendPanel.style().set('shown', v);
    refresh(L);
  }});
  L.status = ui.Label('', S.status);
  var inner = [];
  if (L.legend) inner.push(L.legend());
  inner.push(ui.Panel([
    ui.Label('непрозрачность, %', {fontSize: '12px', color: C.muted, margin: '6px 0 0 0', backgroundColor: C.bg}),
    ui.Slider({min: 0, max: 100, step: 5, value: Math.round(L.opacity * 100), style: S.slider,
               onChange: function(v) { setOpacity(L, v / 100); }})
  ], ui.Panel.Layout.flow('horizontal'), {margin: '0 0 4px 28px', padding: '0', backgroundColor: C.bg}));
  L.legendPanel = ui.Panel(inner, ui.Panel.Layout.flow('vertical'), {shown: L.on, margin: '0', padding: '0',
                           backgroundColor: C.bg});
  return ui.Panel([cb, L.status, L.legendPanel], ui.Panel.Layout.flow('vertical'), S.row);
}

// --- Блок сцен Sentinel-2 ---
var s2StatusLabel = ui.Label('', S.small);
var s2SceneSelect = ui.Select({items: [], placeholder: 'сцена', style: S.select, onChange: function(v) {
  if (!v) return;
  state.s2scene = v;
  refresh(BY_ID.s2);
}});
s2SceneSelect.style().set('shown', false);

function s2TileItems() {
  var items = [{label: 'Все тайлы', value: 'ALL'}];
  SCENES.forEach(function(r) {
    items.push({label: r.t + '   ' + r.c.map(sceneDate).join(', '), value: r.t});
  });
  return items;
}

function onTile(t) {
  state.s2tile = t;
  if (t === 'ALL') {
    state.s2scene = null;
    s2SceneSelect.style().set('shown', false);
    var nMulti = SCENES.filter(function(r) { return r.c.length > 1; }).length;
    s2StatusLabel.setValue('Сцены, по которым классифицирован каждый тайл: восстановлены по копиям скрипта тайла ' +
      'автора (номера сцен из списка наименее облачных); у ' + nMulti + ' тайлов это мозаика двух-трёх сцен. ' +
      'Выберите тайл, чтобы посмотреть его сцены.');
  } else {
    var rec = sceneByTile(t);
    var items = [];
    if (rec.c.length > 1) items.push({label: 'мозаика сцен тайла (' + rec.c.length + ')', value: 'TILE'});
    rec.c.forEach(function(id) { items.push({label: 'сцена ' + sceneDate(id), value: id}); });
    state.s2scene = rec.c.length > 1 ? 'TILE' : rec.c[0];
    s2SceneSelect.items().reset(items);
    s2SceneSelect.setValue(state.s2scene, false);
    s2SceneSelect.style().set('shown', items.length > 1);
    s2StatusLabel.setValue('Тайл ' + t + ': ' + rec.c.map(sceneDate).join(', ') + '. ' + SCENE_STATUS_RU[rec.v] +
      (rec.u ? ' (USE_SCENES ' + rec.u + ')' : '') + '.');
    if (assetState(ASSETS.tiles) === 'ok') {
      map.centerObject(ee.FeatureCollection(ASSETS.tiles).filter(ee.Filter.eq('tile', t)), 8);
    } else {
      map.centerObject(ee.Image(CATALOG.s2 + '/' + rec.c[0]).geometry(), 8);
    }
  }
  refresh(BY_ID.s2);
  refresh(BY_ID.tiles);
}

function s2Block() {
  var tileSel = ui.Select({items: s2TileItems(), value: 'ALL', style: S.select, onChange: onTile});
  var comboSel = ui.Select({
    items: Object.keys(S2_VIS).map(function(k) { return {label: S2_VIS[k].label, value: k}; }),
    value: state.s2combo, style: S.select,
    onChange: function(v) { state.s2combo = v; refresh(BY_ID.s2); }
  });
  onTile('ALL');
  return ui.Panel([tileSel, s2SceneSelect, comboSel, s2StatusLabel], ui.Panel.Layout.flow('vertical'), S.legend);
}
BY_ID.s2.legend = s2Block;

// --- Скачивание контуров ---
// Ссылка строится на стороне Earth Engine (getDownloadURL) по видимой области карты. Геометрия ассетов упрощена на
// 10 м; точные слои: выкладка данных (LINKS.data). Проверка 19.11.2026: 20 766 контуров генезиса дают GeoJSON 18 МБ
// за 11 с. Shapefile Earth Engine в этот день не выгружал даже таблицу из одного объекта (ошибка 500 на стороне
// сервера, NoSuchFileException geotools), поэтому SHP в списке нет.
var DOWNLOAD_MAX = 50000;
var Z_DOWNLOAD = 8;    // мельче подсчёт всех контуров в видимой области идёт около 30 с, поэтому сразу подсказка
var DOWNLOAD_LAYERS = [
  {label: 'Генезис песков', asset: 'genesis', file: 'baresand_genesis_v7'},
  {label: 'Техногенные: в отводах', asset: 'anthroIn', file: 'baresand_anthro_in_v7b'},
  {label: 'Техногенные: превышение отвода', asset: 'anthroExceed', file: 'baresand_anthro_exceed_v7b'},
  {label: 'Техногенные: без отвода', asset: 'anthroNoallot', file: 'baresand_anthro_noallot_v7b'},
  {label: 'Отводы под объекты (обобщённо)', asset: 'allotments', file: 'baresand_allotments_generalized_v7b'}
];
var DOWNLOAD_FORMATS = ['GeoJSON', 'KML', 'CSV'];
var dl = {layer: 0, format: 'GeoJSON', seq: 0};
var dlResult = ui.Panel([], ui.Panel.Layout.flow('vertical'), S.row);

function dlMessage(text, url) {
  var w = url ? ui.Label({value: text, targetUrl: url, style: S.link}) : ui.Label(text, S.small);
  dlResult.widgets().reset([w]);
}

function makeDownload() {
  var seq = ++dl.seq;
  var def = DOWNLOAD_LAYERS[dl.layer];
  if (state.zoom < Z_DOWNLOAD) {
    dlMessage('Приблизьте карту (масштаб ' + Z_DOWNLOAD + ' и крупнее): скачиваются контуры видимой области.');
    return;
  }
  var b = map.getBounds();
  var fc = ee.FeatureCollection(ASSETS[def.asset]).filterBounds(ee.Geometry.Rectangle(b, null, false));
  dlMessage('Считаю контуры в видимой области...');
  fc.size().evaluate(function(n, err) {
    if (seq !== dl.seq) return;
    if (err) { dlMessage('Ошибка: ' + err); return; }
    if (!n) { dlMessage('В видимой области контуров нет.'); return; }
    if (n > DOWNLOAD_MAX) {
      dlMessage('В видимой области ' + fmt(n, 0) + ' ' + plural(n, ['контур', 'контура', 'контуров']) +
                ', предел ' + fmt(DOWNLOAD_MAX, 0) + ': приблизьте карту.');
      return;
    }
    var name = def.file + '_' + b.map(function(x) { return Math.round(x * 10) / 10; }).join('_');
    fc.getDownloadURL(dl.format, null, name, function(url, err2) {
      if (seq !== dl.seq) return;
      if (err2 || !url) { dlMessage('Ошибка: ' + (err2 || 'ссылка не получена')); return; }
      dlMessage('Скачать: ' + fmt(n, 0) + ' ' + plural(n, ['контур', 'контура', 'контуров']) + ', ' + dl.format, url);
    });
  });
}

function downloadBlock() {
  var layerSel = ui.Select({
    items: DOWNLOAD_LAYERS.map(function(d, i) { return {label: d.label, value: String(i)}; }),
    value: '0', style: S.select, onChange: function(v) { dl.layer = Number(v); dlResult.clear(); }
  });
  var fmtSel = ui.Select({items: DOWNLOAD_FORMATS, value: dl.format, style: S.select,
                          onChange: function(v) { dl.format = v; dlResult.clear(); }});
  var btn = ui.Button({label: 'Получить ссылку на видимую область', style: S.button, onClick: makeDownload});
  var w = [layerSel, fmtSel, btn, dlResult,
           ui.Label('Геометрия упрощена на 10 м, до ' + fmt(DOWNLOAD_MAX, 0) + ' контуров за раз.', S.small)];
  if (LINKS.data) w.push(ui.Label({value: 'Полные слои без упрощения', targetUrl: LINKS.data, style: S.link}));
  return ui.Panel(w, ui.Panel.Layout.flow('vertical'), S.row);
}

// --- Сборка панели ---
var panel = ui.Panel({style: S.panel});
panel.add(ui.Label('Оголённые пески севера Западной Сибири', S.title));
panel.add(ui.Label('Sentinel-2, июль-сентябрь 2020-2025 гг. · 575 054 контура · 8 155,7 км²', S.lead));
panel.add(ui.Label('Точность эоловых песков: F1 0,90 (пользователя 94,9 %, производителя 86,0 %). Техногенные ' +
  'пески выделены экспертно, без оценки точности.', S.small));
panel.add(ui.Label('Щёлкните по карте, чтобы увидеть атрибуты.', S.small));

var GROUPS = {1: 'РЕЗУЛЬТАТ', 2: 'СНИМКИ И МАСКА', 3: 'СПРАВОЧНЫЕ СЛОИ'};
[1, 2, 3].forEach(function(g) {
  panel.add(ui.Label(GROUPS[g], S.group));
  panel.add(divider());
  var cadHeader = false;
  LAYERS.forEach(function(L) {
    if (L.group !== g) return;
    // слой без единого заданного ассета (например, месторождения) в публичную панель не выводится
    if (L.assets.length && L.assets.every(function(a) { return !isSet(a); })) return;
    if (L.sub === 'cad' && !cadHeader) {
      cadHeader = true;
      panel.add(ui.Label('Техногенные пески и отводы ЕГРН', S.sub));
      panel.add(ui.Label('Пространственное сопоставление с участками ЕГРН (НСПД, 2026): показывает места для ' +
        'проверки, нарушений не устанавливает.', S.small));
    }
    panel.add(layerRow(L));
  });
});

panel.add(ui.Label('СКАЧАТЬ КОНТУРЫ', S.group));
panel.add(divider());
panel.add(downloadBlock());

panel.add(ui.Label('О ПРОЕКТЕ', S.group));
panel.add(divider());
var links = [];
if (LINKS.methods) links.push(ui.Label({value: 'Методика', targetUrl: LINKS.methods, style: S.link}));
if (LINKS.article) links.push(ui.Label({value: 'Статья', targetUrl: LINKS.article, style: S.link}));
if (LINKS.repo) links.push(ui.Label({value: 'Репозиторий', targetUrl: LINKS.repo, style: S.link}));
if (links.length) panel.add(ui.Panel(links, ui.Panel.Layout.flow('horizontal'), S.row));
panel.add(ui.Label('Источники: Copernicus Sentinel-2 (ESA), JRC Global Surface Water, ArcticDEM (PGC), Hansen GFC, ' +
  'ЕГРН (НСПД). Содержит данные © участники OpenStreetMap, ODbL 1.0. Генезис v7 (06.10.2026), кадастровые ' +
  'группы v7b (03.11.2026), приложение 19.11.2026.', S.small));

// ============================================================================
// 10а. ПРАВАЯ ПАНЕЛЬ: СТАТИСТИКА И ГРАФИКИ
// ============================================================================
// Итог, районы и широтные пояса берутся из STATS (155, площади по точным геометриям, район по центроиду контура);
// видимая область считается на лету по растрам плотности 2 км (сумма площадей контуров по центроидам).

var CAD_ROWS = [
  {key: 'cad_in', label: 'в отводах', color: '#2B8CBE'},
  {key: 'cad_exceed', label: 'превышение отвода', color: '#FF7F00'},
  {key: 'cad_noallot', label: 'без отвода', color: '#D7301F'}
];
var AGE_ROWS = [
  {key: 'age_new', label: 'оголены после 2000 г.', color: '#E66101'},
  {key: 'age_mid', label: 'частично в 2000 г.', color: '#FDB863'},
  {key: 'age_old', label: 'оголены уже в 2000 г.', color: '#5E3C99'}
];
var STAT_METRICS = [
  {key: 'aeolian', label: 'эоловые пески, км²', color: '#FF9F1A'},
  {key: 'shoals', label: 'отмели, км²', color: '#0078FF'},
  {key: 'anthropogenic', label: 'техногенные пески, км²', color: '#C800C8'},
  {key: 'cad_noallot', label: 'техногенные без отвода, км²', color: '#D7301F'},
  {key: 'cad_exceed', label: 'превышение отвода, км²', color: '#FF7F00'},
  {key: 'sand_share', label: 'доля песков в площади района, %', color: '#A8692A'}
];
var stats = {scope: 'all', metric: 'aeolian', seq: 0, pick: true};

function dVal(d, key) {
  if (key === 'shoals') return (d.river_shoal || 0) + (d.lake_shoal || 0) + (d.shoal || 0);
  return d[key] || 0;
}

function statDistricts() {
  return STATS ? STATS.districts.filter(function(d) { return d.name !== 'вне районов'; }) : [];
}

function districtByName(name) {
  var out = null;
  statDistricts().forEach(function(d) { if (d.name === name || d.label === name) out = d; });
  return out;
}

function chartStyle(h) {
  return {height: h + 'px', margin: '0', padding: '0', backgroundColor: C.bg, stretch: 'horizontal'};
}

function baseOpts(extra) {
  var o = {backgroundColor: 'transparent', fontName: 'Roboto, Arial', fontSize: 12, legend: {position: 'none'},
           chartArea: {left: 140, top: 6, right: 16, bottom: 22}, hAxis: {format: '0', textStyle: {fontSize: 11}},
           vAxis: {format: '0', textStyle: {fontSize: 11}}, tooltip: {textStyle: {fontSize: 12}}};
  Object.keys(extra || {}).forEach(function(k) { o[k] = extra[k]; });
  return o;
}

// Кольцевая диаграмма по классам: items = [{label, value, color}]
function donut(items, h) {
  var dt = {cols: [{label: 'Класс', type: 'string'}, {label: 'км²', type: 'number'}],
            rows: items.map(function(it) { return {c: [{v: it.label}, {v: Math.round(it.value * 10) / 10}]}; })};
  var ch = ui.Chart(dt, 'PieChart', baseOpts({
    pieHole: 0.55, pieSliceText: 'none', colors: items.map(function(it) { return it.color; }),
    legend: {position: 'none'}, chartArea: {left: 0, top: 6, width: '100%', height: '94%'}
  }));
  ch.style().set(chartStyle(h || 170));
  // своя легенда под кольцом: цвет, класс, площадь и доля (легенда Google Charts на узкой панели не помещается)
  var tot = items.reduce(function(a, it) { return a + it.value; }, 0);
  var rows = items.filter(function(it) { return it.value > 0; }).map(function(it) {
    return [it.color.replace('#', ''), it.label + ': ' + fmt(it.value, 1) + ' км² (' + fmt(tot ? 100 * it.value / tot : 0, 1) + ' %)'];
  });
  return ui.Panel([ch, legendRows(rows, true)], ui.Panel.Layout.flow('vertical'), S.row);
}

// Горизонтальные столбцы: items = [{label, value, color}]; onPick(label) по щелчку по столбцу
function bars(items, h, onPick, left) {
  var dt = {cols: [{label: '', type: 'string'}, {label: 'км²', type: 'number'}, {role: 'style', type: 'string'}],
            rows: items.map(function(it) {
              return {c: [{v: it.label}, {v: Math.round(it.value * 10) / 10}, {v: it.color}]};
            })};
  var ch = ui.Chart(dt, 'BarChart', baseOpts({bar: {groupWidth: '70%'},
                                              chartArea: {left: left || 140, top: 6, right: 16, bottom: 22}}));
  ch.style().set(chartStyle(h));
  if (onPick) ch.onClick(function(x) { if (x) onPick(x); });
  return ch;
}

function classItems(src) {
  return CLASSES.map(function(c) { return {label: c.label, value: src[c.key] || 0, color: '#' + c.fill}; });
}

function bigNumber(value, unit, note) {
  return ui.Panel([
    ui.Label(fmt(value, 1) + ' ' + unit, {fontSize: '26px', fontWeight: 'bold', color: C.ink, margin: '4px 0 0 0',
                                          backgroundColor: C.bg}),
    ui.Label(note, S.small)
  ], ui.Panel.Layout.flow('vertical'), S.row);
}

var summaryBox = ui.Panel([], ui.Panel.Layout.flow('vertical'), S.row);
var rankBox = ui.Panel([], ui.Panel.Layout.flow('vertical'), S.row);
var latBox = ui.Panel([], ui.Panel.Layout.flow('vertical'), S.row);
var districtLayer = ui.Map.Layer(emptyImage(), {}, 'Выбранный район', false, 1);

function showDistrictOnMap(name) {
  checkAsset(ASSETS.districts);
  var fc = ee.FeatureCollection(ASSETS.districts).filter(ee.Filter.eq('name', name));
  districtLayer.setEeObject(ee.ImageCollection([
    ee.Image().byte().paint(fc, 1, 5).selfMask().visualize({palette: ['ffffff'], opacity: 0.9}),
    ee.Image().byte().paint(fc, 1, 2).selfMask().visualize({palette: ['202124']})
  ]).mosaic());
  districtLayer.setShown(true);
  map.centerObject(fc, 7);
}

function fillSummary() {
  summaryBox.clear();
  if (!STATS) { summaryBox.add(ui.Label('Статистика не загружена (python/155).', S.small)); return; }
  if (stats.scope === 'view') { fillViewSummary(); return; }
  districtLayer.setShown(stats.scope !== 'all');
  var src = stats.scope === 'all' ? STATS.total : districtByName(stats.scope);
  if (!src) return;
  var note = stats.scope === 'all' ? fmt(src.n, 0) + ' контуров, район работ 1 068 411 км²' :
    fmt(src.n, 0) + ' контуров; ' + fmt(src.sand_share, 2) + ' % площади района (' + fmt(src.area_km2, 0) + ' км²)';
  summaryBox.add(bigNumber(src.sand_km2, 'км² песков', note));
  summaryBox.add(donut(classItems(src), 170));
  summaryBox.add(ui.Label('Техногенные пески и отводы ЕГРН, км²', S.sub));
  summaryBox.add(bars(CAD_ROWS.map(function(r) { return {label: r.label, value: src[r.key] || 0, color: r.color}; }),
                      110, null, 130));
  summaryBox.add(ui.Label('Возраст поверхности техногенных песков, км²', S.sub));
  summaryBox.add(bars(AGE_ROWS.map(function(r) { return {label: r.label, value: src[r.key] || 0, color: r.color}; }),
                      140, null, 170));
}

// Видимая область: суммы растров плотности 2 км (га/км² x 4 км² / 100 = км²) по трём классам
function fillViewSummary() {
  var seq = ++stats.seq;
  districtLayer.setShown(false);
  summaryBox.add(ui.Label('Считаю пески в видимой области...', S.small));
  var b = map.getBounds();
  var geom = ee.Geometry.Rectangle(b, null, false);
  var keys = ['aeolian', 'shoal', 'anthropogenic'];
  var img = ee.Image.cat(keys.map(function(k) { return ee.Image(densityAsset(k, 2)).select(0).rename(k); }))
    .unmask(0).multiply(0.04);
  img.reduceRegion({reducer: ee.Reducer.sum(), geometry: geom, crs: 'EPSG:3576', scale: 2000, maxPixels: 1e9})
    .evaluate(function(r, err) {
      if (seq !== stats.seq || stats.scope !== 'view') return;
      summaryBox.clear();
      if (err || !r) { summaryBox.add(ui.Label('Ошибка: ' + err, S.small)); return; }
      var items = [{label: 'эоловые', value: r.aeolian || 0, color: '#FF9F1A'},
                   {label: 'отмели', value: r.shoal || 0, color: '#0078FF'},
                   {label: 'техногенные', value: r.anthropogenic || 0, color: '#C800C8'}];
      var tot = items.reduce(function(a, it) { return a + it.value; }, 0);
      summaryBox.add(bigNumber(tot, 'км² песков', 'в видимой области; по центроидам контуров в ячейках 2 км, без ' +
                               'неопределённых; обновляется при сдвиге карты'));
      summaryBox.add(donut(items, 170));
    });
}

function fillRank() {
  rankBox.clear();
  if (!STATS) return;
  var m = null;
  STAT_METRICS.forEach(function(x) { if (x.key === stats.metric) m = x; });
  var ds = statDistricts().slice().sort(function(a, c) { return dVal(c, m.key) - dVal(a, m.key); })
    .filter(function(d) { return dVal(d, m.key) > 0; });
  rankBox.add(bars(ds.map(function(d) {
    return {label: d.label, value: dVal(d, m.key), color: d.name === stats.scope ? '#202124' : m.color};
  }), 24 * ds.length + 30, function(label) { setScope(districtByName(label) ? districtByName(label).name : 'all'); }, 170));
  rankBox.add(ui.Label('Щёлкните по столбцу, чтобы выбрать район.', S.small));
}

function fillLat() {
  latBox.clear();
  if (!STATS) return;
  var cols = [{label: 'Широта', type: 'string'}].concat(CLASSES.map(function(c) { return {label: c.label, type: 'number'}; }));
  var rows = STATS.lat.map(function(r) {
    return {c: [{v: r.band + '°'}].concat(CLASSES.map(function(c) { return {v: Math.round((r[c.key] || 0) * 10) / 10}; }))};
  });
  var ch = ui.Chart({cols: cols, rows: rows}, 'ColumnChart', baseOpts({
    isStacked: true, colors: CLASSES.map(function(c) { return '#' + c.fill; }), bar: {groupWidth: '80%'},
    legend: {position: 'bottom', textStyle: {fontSize: 11}, maxLines: 3},
    chartArea: {left: 46, top: 10, right: 8, bottom: 70}, vAxis: {title: 'км²', textStyle: {fontSize: 11}}
  }));
  ch.style().set(chartStyle(300));
  latBox.add(ch);
  latBox.add(ui.Label('Площадь песков по поясам 1° широты (по центроидам контуров).', S.small));
}

var scopeSelect = ui.Select({style: S.select, onChange: function(v) { setScope(v, true); }});

function scopeItems() {
  var items = [{label: 'Весь район работ', value: 'all'}, {label: 'Видимая область карты', value: 'view'}];
  statDistricts().forEach(function(d) { items.push({label: d.label, value: d.name}); });
  return items;
}

function setScope(v, fromSelect) {
  stats.scope = v;
  if (!fromSelect) scopeSelect.setValue(v, false);
  if (v !== 'all' && v !== 'view') showDistrictOnMap(v);
  fillSummary();
  fillRank();
}

var statsPanel = ui.Panel({style: {width: '380px', padding: '20px 18px 24px 18px', backgroundColor: C.bg}});
var statsShow = ui.Button({label: 'Статистика', style: {position: 'top-right', shown: false, margin: '8px'},
                           onClick: function() { statsPanel.style().set('shown', true); statsShow.style().set('shown', false); }});

function buildStatsPanel() {
  var head = ui.Panel([
    ui.Label('Статистика', {fontSize: '22px', fontWeight: 'bold', color: C.ink, margin: '0', backgroundColor: C.bg,
                            width: '250px'}),
    ui.Button({label: '×', style: {margin: '0', padding: '0'}, onClick: function() {
      statsPanel.style().set('shown', false); statsShow.style().set('shown', true);
    }})
  ], ui.Panel.Layout.flow('horizontal'), S.row);
  statsPanel.add(head);
  statsPanel.add(ui.Label('Территория', S.group));
  statsPanel.add(divider());
  scopeSelect.items().reset(scopeItems());
  scopeSelect.setValue('all', false);
  statsPanel.add(scopeSelect);
  statsPanel.add(ui.Checkbox({label: 'выбирать район щелчком по карте', value: stats.pick, style: S.checkbox,
                              onChange: function(v) { stats.pick = v; }}));
  statsPanel.add(summaryBox);
  statsPanel.add(ui.Label('РЕЙТИНГ РАЙОНОВ', S.group));
  statsPanel.add(divider());
  statsPanel.add(ui.Select({
    items: STAT_METRICS.map(function(m) { return {label: m.label, value: m.key}; }), value: stats.metric,
    style: S.select, onChange: function(v) { stats.metric = v; fillRank(); }
  }));
  statsPanel.add(rankBox);
  statsPanel.add(ui.Label('ШИРОТНЫЙ ПРОФИЛЬ', S.group));
  statsPanel.add(divider());
  statsPanel.add(latBox);
  statsPanel.add(ui.Label('Районы: границы OSM (admin_level 6), города присоединены к районам; восточный сектор без ' +
    'границ OSM. Площади по итоговым слоям (генезис v7, кадастр v7b), район контура по центроиду.', S.small));
  fillSummary();
  fillRank();
  fillLat();
}

// выбор района щелчком по карте и пересчёт видимой области при сдвиге
function pickDistrict(pt) {
  if (!stats.pick || !STATS) return;
  ee.FeatureCollection(ASSETS.districts).filterBounds(pt).aggregate_array('name').evaluate(function(names) {
    if (names && names.length && districtByName(names[0])) setScope(names[0]);
  });
}
map.onChangeBounds(ui.util.debounce(function() { if (stats.scope === 'view') fillSummary(); }, 800));

// --- Карточка атрибутов (на карте) ---
var infoBody = ui.Panel([], ui.Panel.Layout.flow('vertical'), {margin: '0', padding: '0', backgroundColor: C.card});
var infoPanel = ui.Panel([
  ui.Panel([
    ui.Label('Атрибуты в точке', {fontSize: '14px', fontWeight: 'bold', color: C.ink, margin: '4px 0 0 0',
                                  backgroundColor: C.card, width: '262px'}),
    ui.Button({label: '×', style: {margin: '0', padding: '0'}, onClick: function() {
      infoPanel.style().set('shown', false);
    }})
  ], ui.Panel.Layout.flow('horizontal'), {margin: '0', padding: '0', backgroundColor: C.card}),
  infoBody
], ui.Panel.Layout.flow('vertical'), S.info);
map.add(infoPanel);

var clickSeq = 0;

function infoSection(title, rows) {
  var w = [ui.Label(title, S.infoTitle)];
  rows.forEach(function(r) {
    w.push(ui.Panel([ui.Label(r[0], S.infoKey), ui.Label(r[1], S.infoVal)], ui.Panel.Layout.flow('horizontal'),
                    {margin: '0', padding: '0', backgroundColor: C.card}));
  });
  return ui.Panel(w, ui.Panel.Layout.flow('vertical'), {margin: '0', padding: '0', backgroundColor: C.card});
}

map.onClick(function(c) {
  var seq = ++clickSeq;
  var pt = ee.Geometry.Point([c.lon, c.lat]);
  pickDistrict(pt);
  var buf = Math.max(5, 3 * metersPerPixel(state.zoom, c.lat));
  infoBody.clear();
  infoBody.add(ui.Label(fmt(c.lat, 4) + '° с. ш., ' + fmt(c.lon, 4) + '° в. д.; радиус поиска ' + fmt(buf, 0) + ' м',
                        {fontSize: '12px', color: C.faint, margin: '2px 0', backgroundColor: C.card}));
  infoPanel.style().set('shown', true);
  var any = false;
  LAYERS.forEach(function(L) {
    if (!L.on || !L.query) return;
    if (!canQuery(L)) return;
    any = true;
    var slot = ui.Panel([ui.Label(L.title + ': загрузка...', {fontSize: '12px', color: C.faint,
                         backgroundColor: C.card})], ui.Panel.Layout.flow('vertical'),
                        {margin: '0', padding: '0', backgroundColor: C.card});
    infoBody.add(slot);
    L.query(pt, buf).evaluate(function(res, err) {
      if (seq !== clickSeq) return;
      var rows = err ? [['Ошибка', String(err)]] : L.render(res);
      slot.widgets().reset([infoSection(L.title, rows)]);
    });
  });
  if (!any) {
    infoBody.add(ui.Label('Включите слой с атрибутами (генезис, первичный вектор, кадастровые классы, плотность, ' +
                          'рельеф, вода, Hansen, сцены).', S.infoVal));
  }
});

// ============================================================================
// 11. ЗАПУСК
// ============================================================================

map.layers().add(districtLayer);
map.add(statsShow);
buildStatsPanel();
ui.root.clear();
ui.root.add(panel);
ui.root.add(map);
ui.root.add(statsPanel);
LAYERS.forEach(function(L) {
  if (L.on) {
    L.assets.forEach(checkAsset);
    refresh(L);
  }
});
