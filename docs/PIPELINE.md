# Конвейер BareSand: от сцен Sentinel-2 до итоговых слоёв

Инвентаризация на 13.10.2026. Источники: docstring всех `python/*.py`, заголовки `gee_scripts/*.js`, `DNA.md`, `RNA.md`,
`ROADMAP.md`, `exports/final/README.md`, отчёты `docs/genesis_*.md`, `docs/article_v2/supplement_v2_final.md` (разделы S1-S12),
журналы `exports/qc/**/run*.log`. Построчная таблица всех скриптов: `scripts_manifest.csv` рядом с этим файлом (поля
script, stage, role, inputs, outputs, include_in_repo; с 13.10.2026 также level: уровень воспроизведения A, B, C по
разделу 4, «-» вне маршрута; repo_copy: yes копия в `src/` совпадает с рабочим файлом, outdated рабочий файл изменён
после копирования, no копии нет). Пути даны от корня проекта `D:\test\baresand_zapsib\`; в манифесте
имя файла без папки лежит в той же папке, что предыдущий путь списка. Роли: «ядро конвейера» (пишет слой или таблицу,
которая входит в итоговые слои), «проверка и QC» (выборки, страницы проверки, сводки вердиктов, оценки точности, сверки),
«исследование и отвергнутое» (пилоты, сравнения методов, не принятые варианты), «вспомогательный» (утилиты, рисунки,
статистика статьи, стили, серверы). include_in_repo = no: мёртвые поколения, заменённые варианты, неиспользованные в статье
эксперименты, служебные инструменты среды и оформление статьи.

Связанные документы: [METHODS.md](METHODS.md) (алгоритмы, правила и пороги стадий), [DATA.md](DATA.md) (слои, поля,
лицензии; состав выкладки в [release_files.csv](release_files.csv)), [../gee_app/README.md](../gee_app/README.md)
(мини-приложение, группы слоёв раздела 7), [../src/README.md](../src/README.md) (копии скриптов в репозитории, пути,
краткий порядок запуска). В репозитории скрипты лежат в `src/python/` и `src/gee_scripts/`: путь `python/...` этого
файла соответствует `src/python/...`; пути `gee_app/...` даны от корня репозитория.

## 1. Коротко

- Итоговый слой: `exports/final/baresand_genesis_v7.gpkg`, слой `genesis`, 575 054 контура, 8 155,7 км². Основные классы
  (`genesis_main`): aeolian 2 728,5 км², alluvial_littoral 3 506,0 км², anthropogenic 1 876,2 км², undefined 43,8 км²
  (`exports/final/README.md`). Покрытие маски: 128 тайлов MGRS, 906 325 км² из 1 068 411 км² района работ.
- Техноген и кадастр: в `exports/final/baresand_anthro_cadastre_v7.gpkg` пока слои сборки 06.10.2026 (anthro_in,
  anthro_out, anthro_excess, anthro_unreg, parcels, shift_windows; шейпы в `exports/final/anthro_shp/`). Решение автора
  13.10.2026 (вариант А): класс v7 не меняется, территория населённых пунктов считается отводом, техноген делится на три
  группы. `python/151_territory.py` -> `exports/qc/territory/territory.gpkg` (земли населённых пунктов и садоводческие
  участки ЕГРН, жилая застройка, дачи и аэродромы OSM, вахтовые посёлки, промзоны городов; 998,0 км²) ->
  `133 --territory` -> `exports/qc/cadastre_v7a/` (отчёт `cadastre_anthro.md`): **anthro_in** (в отводах) 995,4 км²,
  **anthro_exceed** (превышение отвода) 262,9 км² у 11 057 контуров, **anthro_noallot** (без отвода, площадь объекта
  целиком) 455,0 км² у 26 731 контуров; сумма 1 713,3 из 1 876,2 км² (полосы допуска и куски меньше 900 м² в группы не
  входят). Проверки: 152 (просмотр внешних слоёв агентами), 153 (согласованность полей и слоёв). `exports/final` ещё не
  обновлён.
- Точность в статье приводится только для эоловых песков: точность пользователя 94,9 %, производителя 86,0 %, F1 0,90,
  площадь по эталону 3 024 км² (`exports/qc/owner_click/V1/accuracy_V1+V1b+V1c_split100_U.md`, скрипт 119; выборка 276
  контуров V1 + V1b + V1c; объект оценки: версия карты на момент отбора V1, до исправлений v5-v7, домен U). Общая
  точность 91,6 % по трём классам уходит в приложение. Техногенный класс экспертный (OSM, ЕГРН, история поверхности,
  метки автора), показатели точности для него не приводятся; контрольные выборки T1, T2 (136) и T3 (141-143) проверяли
  только переводы v7 (около 1 % площади класса) и остаточный техноген у инфраструктуры, а не весь класс.
- Скриптов: 117 в `python/` (вместе с 150-153, появившимися 13.10.2026), 20 в `gee_scripts/` (с `utils/accuracy.js`),
  5 вне этих папок (раздел 8). По ролям: ядро конвейера 50, проверка и QC 37, исследование и отвергнутое 29,
  вспомогательные 26; в репозиторий предлагается 119 из 142, скопировано 115, из них 4 устарели после правок
  13.10.2026 (133, 140, 150, 151; поле repo_copy манифеста).
- Минимальный набор для пересборки итоговых слоёв из опубликованного первичного вектора и замороженных решений
  (раздел 4): 29 скриптов сборки v7 и 2 скрипта варианта А (151 и проверка 153), 2 скрипта сбора данных и 2 модуля;
  векторизация 30 остаётся отдельной проверкой и в точную пересборку не входит.

## 2. Схема стадий

```
ИСХОДНЫЕ СЦЕНЫ (GEE, аккаунт автора)
  20_tile_inventory.js -> 21_production_classify.js x 128 тайлов (одна сцена S2 L2A на тайл,
  июль-сентябрь 2020-2025, облачность сцены < 15 %, разметка sand / lichen точками)
  -> ассеты baresand_mask_<TILE> -> 22_check_mosaic_assets.py -> 22_run_mosaic.py (или 22_mosaic_export.js)
  -> baresand_mask_AOI_v2 -> 6 GeoTIFF в exports/baresand_mask/ (скачиваются с Google Drive вручную)
  сцены тайлов восстановлены: 126 -> exports/aux/tile_scenes.csv, проверка 127; покрытие 123
        |
ВСПОМОГАТЕЛЬНЫЕ РАСТРЫ: 31 -> GSW occurrence и seasonality, MERIT HND и UPA, Landsat-1985 (exports/*.vrt)
        |
ВЕКТОРИЗАЦИЯ, MMU 900 м²: 30 -> exports/baresand_contours_v2.gpkg (574 520 контуров)
        |
КАСКАД ГЕНЕЗИСА (каждый шаг работает с остатком genesis = unassigned)
  шаг 1 морские отмели   32a, 32b, 44b -> 45                          -> baresand_genesis_step1_v3.gpkg
  шаг 2 речные, озёрные   50, 50b, [50c, 54] -> 51 -> 55               -> baresand_genesis_step2_v3_split.gpkg
  шаг 3 техноген          60, 61, 61b, 66, 67, 69, 70, [65] -> 62 -> 68 -> baresand_genesis_step3_v4e.gpkg
  шаг 4 эоловые           80 -> 81 -> [82] -> 83                       -> baresand_genesis_step4_v2e.gpkg
  шаг 5 рельеф            90 -> [91, 92] -> 93 -> 94 -> 95             -> baresand_genesis_step5_v3e.gpkg
  шаг 6 остаток           [101-103, 105/107, 108, 109-110, 111-114] -> 104 -> baresand_genesis_step6_v4.gpkg
        |
ОЦЕНКА ТОЧНОСТИ (карта на момент отбора V1, до исправлений): 118 -> 105 (партии V1, V1b, V1c) -> 107 -> 119
        |
РАЗРЕЗ СМЕШАННЫХ    125 -> разрез автором в ArcGIS -> 132 -> step6_v5
КАДАСТР             133 -> step6_v6 (+ слои техногена v6)
ИТОГ v7             134, 137 -> два слепых чтения -> 135 -> 136 (T1, T2) -> 138 -> 133 --kras
                    -> exports/final/*.gpkg -> 139 (сверка) -> 140 (шейпы, граница, README)
КОНТРОЛЬ v7         141 -> 143 -> 142 (партия T3; в слой по плану не вносится)
ВАРИАНТ А 13.10    151 -> 133 --territory -> exports/qc/cadastre_v7a/ -> 152 (просмотр внешних слоёв), 153 (проверка);
                    в exports/final не перенесено (139 ждёт старые слои, 140 переводится на новые)
СТАТЬЯ              120 -> 121, 130 (таблицы); 128, 129, 145 (+ 146) (карты и рисунки)
МИНИ-ПРИЛОЖЕНИЕ     150 (выгрузка слоёв в ассеты GEE ZapSib_baresands/app; prepare_assets.py: альтернативный путь)
ЧЕРНОВИК v8         147 -> 149 -> 148 (не принят решением 13.10.2026)

[ ] - скрипты, которые готовят таблицы решений из меток эксперта, автора и агентов (уровень B раздела 4)
```

Порядок каскада в реализации: берег -> отмели -> техноген -> эоловый. DNA 6.5.6 требует техноген первым; проверку
порядка делает 84 (`exports/qc/step4/cascade_order_check.csv`). По приложению S3 техногенный след не менее 30 % площади
имеют 1 771 контур отмелей, 65,2 км² (0,8 % маски).

## 3. Стадии подробно

### 3.0 Выбор метода (GEE, фаза 1)

`00_config.js` (параметры), `01_explore_scenes.js` (сцены), модули `02_cloud_mask.js` (SCL 5 не маскируется, DNA 3.1) и
`03_spectral_indices.js` (индексы, GLCM по B11, стеки A/B/C), методы 10-16 на сцене T42WXT 11.07.2024 (пороги,
K-средних, RF, двухэтапный, AlphaEarth, сравнение; приложение S2), проверка двухэтапного метода на шести сценах
`17_validation.js` (среднее F1 0,93; приложение S1, `ROADMAP.md` 1C), `utils/accuracy.js`. Принят двухэтапный метод
(13): предфильтр, бинарный RF, MMU. Роль: исследование; в массовой обработке параметры встроены в 21.

### 3.1 Классификация сцен и маска (GEE, фаза 2)

`21_production_classify.js` (параметры из кода): `COPERNICUS/S2_SR_HARMONIZED`, интервал 2020-06-01..2025-10-01, месяцы
7-9, `CLOUDY_PIXEL_PERCENTAGE` < 15, сцена с минимальной облачностью; предфильтр MNDWI <= 0 и NDVI <= 0,40; RF 200 деревьев,
minLeaf 5, bagFraction 0,5, seed 42; связность `connectedPixelCount(16, true) >= 9` пикселей, `focal_mode` радиус 1;
экспорт ассета `baresand_mask_<TILE>`. Обучающие точки (Geometry Imports) хранятся только в копиях `21_<тайл>` в аккаунте
GEE автора. Сшивка: `22_run_mosaic.py` (Python-вариант `22_mosaic_export.js`): selfMask и mosaic в EPSG:3576, песок там,
где он есть хотя бы в одном тайле; перед запуском сверка ассетов `22_check_mosaic_assets.py`. Сцены тайлов в ассетах не
записаны, их восстанавливают 126 (`exports/aux/tile_scenes.csv`, приложение S7) и 127 (по следу ассета). Повторная
сверка охвата сцены реестра с охватом ассета (`gee_app/_test/scene_registry_check.py`): совпадение у 26 из 126
проверяемых тайлов, проверка 127 ответа о реестре не даёт ([../gee_app/README.md](../gee_app/README.md), раздел 7).

### 3.2 Вспомогательные растры

`31_download_aux_data.py`: GSW occurrence и seasonality (JRC/GSW1_4), HND и UPA (MERIT/Hydro/v1_0_1), яркость Landsat 5
1984-1995 (LANDSAT/LT05/C02/T1_L2), задачи GEE -> Google Drive -> ручное скачивание в `exports/` (+ `.vrt`). Растр
`aoi_boundary.tif` дефектный (`paint(aoi_fc, 0, 1)`, все нули); его читал только отвергнутый 32.

### 3.3 Векторизация и MMU 900 м²

`30_vectorize_local.py`: VRT из 6 тайлов маски v2, окна 50 км с перекрытием 2 км, объединение, EPSG:3576, фильтр
площади `MMU_M2 = 900` (DNA 4.2), поля area_ha, perimeter_m, compactness -> `exports/baresand_contours_v2.gpkg`, слой
`contours`, 574 520 контуров. MMU применён дважды: 9 связных пикселей в GEE (21) и 900 м² после векторизации.

### 3.4 Каскад генезиса, шаги 1-5

Общая схема каждого шага: правило -> стратифицированная выборка -> два агента (дешифровщик и скептик) -> свод вердиктов и
регрессионный эталон -> финальная проверка экспертом в шейпе -> перенос правок эксперта в продукт. Доли верных на эталонах
шагов оптимистичны: эталоны отобраны из результатов правил и использовались для подбора порогов (приложение S3).

| Шаг | Ядро | Проверка | Продукт | Итог (источник) |
|---|---|---|---|---|
| 1 морские отмели | 32a (только зональные атрибуты GSW, HND, UPA), 32b (v1), 44b (берег OSM), 45 (v3: до моря <= 400 м и HND <= 8 м, гиганты режутся буфером берега) | 41, 43, 46, 47 | `baresand_genesis_step1_v3.gpkg` | 3 638 контуров, 211,4 км² (`docs/genesis_step1_iteration1_report.md`); на эталоне 84 % (S3) |
| 2 речные и озёрные отмели | 50, 50b, 50c, 54, 51 `--tag v3 --anthro-prefilter`, 55 `--tag v3 --grow` | 52, 53, 56 | `baresand_genesis_step2_v3_split.gpkg` | речные 73 169 / 2 754,7 км², озёрные 8 085 / 102,1 км² (`docs/genesis_step2_iteration2_report.md`); 88 % (S3) |
| 3 техноген | 60, 61, 61b, 66 (Hansen 2000), 67 (S2 2017-2019), 69 (НСПД), 70, 65, 62 `--tag v4`, 68 `--tag v4` | 63, 64, 71 | `baresand_genesis_step3_v4e.gpkg` | техноген 77 327 / 1 828,3 км² (`exports/qc/step3/run68_v4.log`); правило 82 %, с правками 94 % (S3) |
| 4 эоловые и неопределённые | 80, 81 `--tag v2` (параметры DEFAULTS совпадают с `run81_v2.log`), 83 `--tag v2 --layer Final.shp` | 82, 84, 87 | `baresand_genesis_step4_v2e.gpkg` | 575 028 контуров, 8 155,7 км² (`docs/genesis_step4_iteration1_report.md`); 86 %, с правками 90 % (S3) |
| 5 рельеф | 90 (+ `--merge`), 93 `--tag v3` (A1 2,0 м; A2 0,5; A3 0,5 м; B1 1,0 м; B2 0,3 м), 94 `--tag v3 --layer Check14.shp`, 95 `--tag v3e` | 91, 92 (подбор порогов); 88, 89 (пилот) | `baresand_genesis_step5_v3e.gpkg` | 56 951 контур, 405,3 км² сменили класс; неопределённые 382,8 -> 116,9 км² (S4, `exports/qc/target/apply_v3.md`) |

Отвергнуто: первое поколение 32, 33 и попиксельный генезис в GEE (`30_genesis_attribution.js`, `30a`, `30b`,
`30b_v2`); 44 (расстояние до моря по GSW: локальный GSW обрезан по AOI, заменён 44b); 42 (улики в GEE, заменён 43 при
исчерпанной квоте). Промежуточная независимая проверка шагов 1-5: 85, 86 (отложенная выборка 322 контура: 87,4 % по
площади после шага 4, 91,0 % после шага 5; выборка использована, повторно как контроль не применяется; S3).

### 3.5 Шаг 6: уточнение остатка и перенос меток (v4)

Сборщик `104_apply_big_pilot.py` (docstring описывает только пилот, код делает весь шаг 6): из `step5_v3e` пишет
`baresand_genesis_step6_v4.gpkg` с полями `step6_rule`, `genesis_main`, `shoal_type`, `shoal_type_src`. Источники решений:

| step6_rule | Откуда | Скрипты | Контуров / км² в v4 (S5.3) |
|---|---|---|---|
| v4_expert | метки автора в окне проверки (`owner_gold.csv`: O1-O8, V1-V1c) и вердикты по морским барам (`expert_big.csv`) | 105, 107, owner_click_server | 842 / 178,72 |
| v4_transfer | модель переноса E2, E3, E4 (`transfer_accepted.json`, `tail_pred_E*.csv`) | 111, 112, 113, 114, 115 | 10 378 / 44,91 |
| v4_big_nb | описание крупнейших неопределённых языковой моделью и наивный Байес | 101, 102, 103 | 95 / 8,07 |
| v4_clear_anthro | рубки по Hansen без пожара по MODIS | 108 | 1 375 / 6,15 |
| v4_disputed | спорные (DNA 6.5.5а) | 109, 110 | 5 / 0,31 |

Отвергнуто: озёрный проход 96-100 (правило L1g не допущено аудитом: чистота по площади 0,632,
`exports/qc/lake/lake_audit_report.md`; 100 не применялся), признаки снимков DINOv2 116-117 (отрицательный результат,
`docs/genesis_tail_transfer_report.md`), идея Jev (`exports/qc/jev/`). Итог шага 6: неопределённые 44,5 км² (S5).

Шаг 6 собирался итеративно: 108, 111, 113, 114 читают промежуточную v4, а 104 перезапускался по мере появления решений.
Для воспроизведения 104 запускается один раз на замороженных таблицах (раздел 4).

### 3.6 Оценка точности

`118_validation_v4_pop.py` (страты: основной класс x размер) -> `105_owner_click_batch.py --pop-csv ... --arms ...` (партии
V1, V1b, V1c; план до разметки `exports/qc/owner_click/V1/prereg.md`) -> `107_owner_click_ingest.py` -> `119_validation_v4.py
--batches V1,V1b,V1c --split-ha 100` (домен U по умолчанию) -> `accuracy_V1+V1b+V1c_split100_U.md`. Объект оценки:
версия карты на момент отбора V1 (до исправлений v5-v7), домен U. Анализ чувствительности: `--product
exports/final/baresand_genesis_v7.gpkg --cf-map exports/qc/aeolian_techno_cf/cf_map.csv` ->
`..._baresand_genesis_v7_cf.md`: подстановка правила v7 для одной единицы (395404), остальные 275 единиц сохраняют
класс на момент отбора (эоловые: точность пользователя 0,951, производителя 0,860, F1 0,903, площадь по эталону та же
3 024,0 км²). Это не оценка точности итогового слоя v7. Все 276 единиц выборки несут метки автора и в продукте
круговые (v4_expert), их класс берётся на момент отбора. Кроме партий выборки 119 читает совокупность
`exports/qc/owner_click/validation_v4_pop.csv` и пять таблиц домена E (`exports/qc/final/validation_sample.csv`,
`target/target_sample.csv`, `lake/lake_fit.csv`, `lake/lake_audit.csv`, `lake/big/big_sample.csv`); в план выкладки они
добавлены 13.10.2026 (`release_files.csv`), но пакет не собран.

### 3.7 Разрез смешанных контуров (v5)

125 -> `exports/qc/mixed_split/mixed_known.shp` -> разрез и классы автора (поля part_cls, note_own) -> `132 --layers
mixed_known` -> `baresand_genesis_step6_v5.gpkg`: 31 контур с классом автора, из них 11 разрезаны; всего 55 частей
(24 новых id 900000-900023), 575 030 -> 575 054 контура (`exports/qc/mixed_split/apply_v5.md`). Слой xl_candidates автор решил не размечать (04.10.2026).

### 3.8 Кадастр ЕГРН (v6, v7, вариант А 13.10.2026)

`133_cadastre_anthro.py`: участки ЕГРН (снимок 08.09.2026) из `E:/cadastre-local/data/layers/parcels_89.gpkg`,
`parcels_86.gpkg`, с `--kras` также `parcels_24.gpkg` (Красноярский край, загружен 06.10.2026). Группы отводов под объекты:
ind, np, vri; прочие unk, forest, agri, misc. Оценка сдвига кадастра (окна 4 x 4 км, FFT). Поля cad_status (in, cross,
unreg, nocad), cad_in_ha, cad_out_ha, cad_exc10_ha, cad_exc20_ha, cad_exc10u_ha, age2000 (пороги 0,30 и 0,70 из DEFAULTS
62). Запуски: по умолчанию v5 -> `step6_v6.gpkg` + `exports/baresand_anthro_cadastre.gpkg`; итоговый
`--src exports/qc/final_build/v7_classes.gpkg --out-product exports/final/baresand_genesis_v7.gpkg --out-layers
exports/final/baresand_anthro_cadastre_v7.gpkg --qc exports/qc/cadastre_v7 --label "133, v7" --cores 12 --kras`
(отчёт `exports/qc/cadastre_v7/cadastre_anthro.md`). 92 % площади класса выделено каскадом с участием ЕГРН, поэтому
сопоставление не является независимой проверкой класса (`exports/final/README.md`). Вариант А 13.10.2026: 151 ->
`exports/qc/territory/territory.gpkg` (7 частей, объединение 998,0 км²; `report.md`) -> 133 с ключом `--territory` ->
`exports/qc/cadastre_v7a/` (`baresand_genesis_v7a.gpkg`, `baresand_anthro_cadastre_v7a.gpkg` со слоями anthro_in,
anthro_exceed, anthro_noallot, parcels, shift_windows; anthro_out больше не пишется; `cadastre_anthro.md`,
`run133.log`, участки Красноярского края подключены; полная командная строка в журнале не записана) -> 152 (снимки
внешних слоёв и метки агентов `review_outside/labels_agents.csv`; выборка снята до добавления промзон городов в 151)
-> 153 (`check_cadastre_a.md`: id и классы как в v7, статусы, согласованность слоёв и полей; 11 из 11 проверок
пройдены). В `exports/final` вариант А
не перенесён: 139 читает anthro_out и сверяет неизменность cad_* (к варианту А не подходит), рабочая 140 переводится на
новые имена слоёв, копии 139 и 140 в репозитории старые. Определения групп: [METHODS.md](METHODS.md), раздел 8.4; поля:
[DATA.md](DATA.md), раздел 5.

### 3.9 Итоговая версия v7 и контроль

134 (эоловые v6 ближе 20 м к техногенному контуру или построенной дороге OSM) и 137 (то же, меньше 5 га) -> два слепых
читателя-агента (readerA, readerB; для мелких сценарий `readers_workflow_2026-10-06.js`) -> 135 (`merged.csv` по
правилу prereg) -> 136 (партии автора T1, T2) -> `138 --owner-batches T1,T2 --small`: 1 854 контура, 22,86 км² из эоловых в
техногенные (v7_owner_techno 44 / 2,95; v7_agent_techno 74 / 8,91; v7_agent_small 1 736 / 11,00;
`exports/qc/final_build/build_v7.md`) -> 133 (выше) -> 139 (`check_v7.md`) -> 140 (шейпы для ArcMap 10.8, граница, README).
Контроль T3 (141 -> 143 -> 142, 150 контуров): переводы агентов верны на 89,6 % площади (95 % ДИ бутстрэп 83,2-94,7),
остаточный техноген в эоловых вблизи инфраструктуры 2,36 км² (95 % ДИ с поправкой 1,62-7,65)
(`exports/qc/control_v7/report.md`); метки T3 в слой не вносятся.

### 3.10 Статистика, карты, утилиты

- Статистика статьи: 120 (районы OSM) -> `121 --product exports/final/baresand_genesis_v7.gpkg` (`stats_v7.md`),
  `130 --product ...` (`table_districts_v7.md`).
- Карты и рисунки: 128 (основная карта; продукт v4 жёстко в коде), 129 (примеры на снимках Esri), 145 (карты
  распространения в стиле 2022 г., v7) с реками 146; 122 и 124 черновые, заменены.
- Окно проверки: 105 (страница и снимки; модуль для 136 и 141), `owner_click_server.py` (127.0.0.1, POST /api/save/<партия>),
  107 (приём меток в `owner_click/owner_gold.csv`), 143 (просмотр меток на промахи).
- Утилиты: `qc_thumb_xyz.py` (снимки Esri XYZ, кэш `exports/qc/thumbs/_tiles`), `qc_render_parallel.py`, `qc_thumb.py`
  (вариант через GEE), `cpu_limit.py` (пониженный приоритет, лимит потоков), `job_monitor_server.py` (служебная панель),
  131 (стили ArcGIS Pro), 144 (статья в Word).
- Мини-приложение: `150_gee_upload.py` (13.10.2026) выгружает слои частями `<слой>_pNNN` в
  `projects/nodal-thunder-481307-u1/assets/ZapSib_baresands/app` (геометрия упрощена на 10 м) и склеивает крупные:
  genesis (поля id, genesis, area_ha, step6_rule, gcode), genesis_r50 (`--class-raster`, растр классов 50 м, строится),
  contours (первичный вектор, грузится), anthro_in, anthro_exceed, anthro_noallot (из `cadastre_v7a`), density_aeolian_r,
  density_anthropogenic_r (`--raster`: ячейки 10 км, растр 1 км в EPSG:3576), coverage_p000, tiles_p000, roads_p000,
  rivers_p000; маска baresand_mask_AOI_v2 лежала в проекте раньше. Месторождения из публичного приложения убраны до
  выяснения лицензии. Приложение `gee_app/baresand_app.js` переведено на эти пути. `gee_app/prepare_assets.py`
  (файлы для ручной загрузки, расширенный набор полей генезиса `rule`, `rule_step`, `gen_main` и др.) остаётся
  альтернативным путём и для текущих ассетов не использовался ([../gee_app/README.md](../gee_app/README.md), разделы 3-5).
- Черновик v8 (147 маска населённых пунктов, 149 снимки, 148 сборка; `docs/settlements_v8_2026-10-12.md`) решением
  13.10.2026 не принят: класс v7 не меняется, территория населённых пунктов учитывается как отвод (151).

## 4. Минимальный набор для воспроизведения

### Уровень A: пересборка итоговых слоёв из первичного вектора, внешних данных и замороженных решений

Уровень A начинается с опубликованного первичного вектора `exports/baresand_contours_v2.gpkg`, а не с повторной
векторизации: id назначаются по порядку компонент после `unary_union` (30) и по порядку частей разрезов (55, 68, 83,
94, 132), повторная векторизация тех же id не гарантирует, а замороженные решения привязаны к id. Сверки id, parent_id
и геометрии частей перед применением решений в коде нет. Векторизация 30 из маски остаётся отдельной проверкой
(площадь и число контуров), не частью точной пересборки. Ограничения уровня A на 13.10.2026: пакета замороженных
входов с хешами нет, файла окружения с версиями библиотек нет, участки ЕГРН не публикуются (шаги 20, 22 и 25 вне
машины автора не повторить, шаги 0б и 9 дадут выгрузку НСПД на другую дату), выгрузки OSM (`*-latest.osm.pbf`, скачаны 05.09.2026) и ЕГРН (08.09.2026,
06.10.2026) привязаны к датам ([../README.md](../README.md), раздел «Статус и ограничения воспроизводимости»).

Порядок запуска (из корня проекта, `PYTHONIOENCODING=utf-8 python -u python/...`):

| N | Скрипт и аргументы | Результат |
|---|---|---|
| 0а | `31_download_aux_data.py` (GEE -> Drive -> `exports/`) | растры GSW, HND, UPA, Landsat-1985 |
| 0б | `69_step3_nspd_download.py --layer 36048 ...` и `--layer 36328` (сеть, НСПД) или готовые `exports/nspd/*.gpkg` | участки и сооружения ЕГРН |
| 1 | вход: опубликованный `baresand_contours_v2.gpkg`; отдельная проверка: `30_vectorize_local.py` (те же id не гарантированы) | `baresand_contours_v2.gpkg` |
| 2 | `32a_step1_littoral.py` | `baresand_littoral_v2.gpkg` |
| 3 | `32b_step1_shoal.py` | `baresand_genesis_step1.gpkg` |
| 4 | `44b_sea_distance_osm.py` | `qc/coastal_zone_evidence.*`, `sea_shore_buffer.gpkg` |
| 5 | `45_step1_shoal_v2.py` (по умолчанию 400 8) | `baresand_genesis_step1_v3.gpkg` |
| 6 | `50_step2_water_evidence.py`, `50b_step2_channel_evidence.py` | улики шага 2 |
| 7 | `51_step2_rule.py --tag v3 --anthro-prefilter --flood-touch 0.1` (ключи по отчётам итераций 1-2; точная командная строка прогона v3 не записана, [METHODS.md](METHODS.md), раздел 4.2) | `baresand_genesis_step2_v3.gpkg` |
| 8 | `55_step2_split_mixed.py --tag v3 --grow` | `baresand_genesis_step2_v3_split.gpkg` |
| 9 | `60_step3_osm_extract.py`, `61_step3_infra_evidence.py`, `61b_step3_osm_built.py`, `66_step3_temporal_evidence.py`, `67_step3_s2_evidence.py`, `70_step3_nspd_evidence.py` | `qc/step3/step3_evidence.csv` |
| 10 | `62_step3_rule.py --tag v4` | `baresand_genesis_step3_v4.gpkg` |
| 11 | `68_step3_apply_expert.py --tag v4` | `baresand_genesis_step3_v4e.gpkg` |
| 12 | `80_step4_evidence.py`, `81_step4_rule.py --tag v2` | `baresand_genesis_step4_v2.gpkg` |
| 13 | `83_step4_apply_expert.py --tag v2 --layer Final.shp` | `baresand_genesis_step4_v2e.gpkg` |
| 14 | `90_dem_evidence_mass.py --workers 4 --chunk 400`, затем `--merge` (GEE) | `qc/dem/dem_evidence_mass.csv` |
| 15 | `93_apply_dem_rules.py --tag v3` | `baresand_genesis_step5_v3.gpkg` |
| 16 | `94_step5_apply_expert.py --tag v3 --layer Check14.shp` | `baresand_genesis_step5_v3e.gpkg` |
| 17 | `95_flag_not_sand.py --tag v3e` | поле `not_sand_suspect` |
| 18 | `104_apply_big_pilot.py` | `baresand_genesis_step6_v4.gpkg` |
| 19 | `132_apply_mixed_split.py --layers mixed_known` | `baresand_genesis_step6_v5.gpkg` |
| 20 | `133_cadastre_anthro.py` (по умолчанию) | `baresand_genesis_step6_v6.gpkg` |
| 21 | `138_build_final.py --owner-batches T1,T2 --small` | `qc/final_build/v7_classes.gpkg` |
| 22 | `133_cadastre_anthro.py --src exports/qc/final_build/v7_classes.gpkg --out-product exports/final/baresand_genesis_v7.gpkg --out-layers exports/final/baresand_anthro_cadastre_v7.gpkg --qc exports/qc/cadastre_v7 --kras` | итоговые gpkg |
| 23 | `139_check_final.py` | `qc/final_build/check_v7.md` |
| 24 | `140_assemble_final.py` | `exports/final/anthro_shp/`, `aoi/`, `README.md` |
| 25 | вариант А: `151_territory.py`, затем `133_cadastre_anthro.py --src ... --territory exports/qc/territory/territory.gpkg --kras` (прогон 13.10.2026 писал в `exports/qc/cadastre_v7a/`; полная командная строка не записана) | слои anthro_in, anthro_exceed, anthro_noallot, поля cad_* варианта А |
| 26 | `153_check_cadastre_a.py [--qc exports/qc/cadastre_v7a]` | `check_cadastre_a.md` (11 проверок; код возврата 1 при ошибке) |

Шаги 23-24 относятся к сборке 06.10.2026: 139 читает слой anthro_out и сверяет неизменность полей cad_*, поэтому для
варианта А не подходит; рабочая 140 переводится на имена anthro_in, anthro_exceed, anthro_noallot (копия в
репозитории ещё на старых именах). Перенос варианта А в `exports/final` не выполнен.

132 и 133 не перезаписывают существующие выходы без `--force`. `104_apply_big_pilot.py` при отсутствии части таблиц
решений пропускает соответствующие правила и завершается без ошибки, давая правдоподобный, но другой результат: перед
запуском нужно проверить наличие всех замороженных входов (такой проверки в коде нет). Промежуточные v5, v6 и
`v7_classes.gpkg` сейчас лежат на `E:\baresand_zapsib_archive` (`docs/moved_to_E_B.md`); v4 и шаги 1-5 остаются в
`exports/` до принятия статьи.

Модули: `cpu_limit.py` (импортируют 132, 133, 138, 151 и ещё 19 скриптов), `qc_thumb_xyz.py` (рендер окон в 133).

Замороженные входы уровня A (без них пересборка невозможна или даст другой результат):

| Группа | Файлы |
|---|---|
| первичный вектор | `exports/baresand_contours_v2.gpkg` (вход уровня A, носитель исходных id) |
| маска | `exports/baresand_mask/baresand_mask_AOI_v2-*.tif` (6 файлов; для проверочной векторизации 30) |
| граница и покрытие | `exports/aoi_v2.geojson`, `vector/baresand_aoi_v2.*`, `vector/mask_coverage_128tiles.*` |
| шаг 2 | `exports/qc/step2/giants_nearwater.csv` (50c по предыдущему прогону 51), `exports/qc/expert_overrides.csv` (54) |
| шаг 3 | `exports/qc/step3/expert_verdicts_step3*.gpkg` (65 из Antropogen.shp, Mixed.shp, NSPD.shp, NSPD_fin.shp) |
| шаг 4 | `exports/qc/step4/Final.shp`, `visual_sample_geoms_step4.gpkg` (82) |
| шаг 5 | `exports/qc/target/Check14.shp` |
| шаг 6 | `exports/qc/lake/big/big_labels.csv`, `expert_big.csv`; `exports/qc/owner_click/owner_gold.csv`, `burn_pop.csv`; `exports/qc/alphaearth/transfer_accepted.json`, `tail_pred_E2.csv`, `tail_pred_E3.csv`, `tail_pred_E4.csv`; `exports/qc/disputed/disputed_current.csv` |
| v5 | `exports/qc/mixed_split/mixed_known.shp` (разрез автора) |
| v7 | `exports/qc/owner_click/T1/labels.json`, `T2/labels.json`; `exports/qc/aeolian_techno/merged.csv`, `exports/qc/aeolian_techno_small/merged.csv` |
| вариант А | участки ЕГРН (`E:/cadastre-local`, не публикуются); `exports/osm/*.osm.pbf` и кэш `exports/osm/osm_territory_AOI.gpkg` (151) |
| оценка точности (119) | `exports/qc/owner_click/V1/batch.csv`, `V1b/batch.csv`, `V1c/batch.csv`, `owner_gold.csv`, `validation_v4_pop.csv`; домен E: `exports/qc/final/validation_sample.csv`, `target/target_sample.csv`, `lake/lake_fit.csv`, `lake/lake_audit.csv`, `lake/big/big_sample.csv`; для анализа чувствительности `exports/qc/aeolian_techno_cf/cf_map.csv` |

Пакет этих файлов (frozen_inputs) не собран, контрольных сумм SHA-256 нет; в `release_files.csv` они перечислены
группами как план выкладки (13.10.2026).

### Уровень B: пересчёт таблиц решений из меток

50c (после предварительного прогона 51 без `giants_nearwater.csv`), 54, 65, 82 (геометрии выборки), 101, 102, 103,
105, 107, 108, 109, 110, 111, 112, 113 (модуль), 114, 125, 134, 135, 136, 137. Исходные метки: шейпы эксперта,
`labels.json` окна проверки, JSON вердиктов агентов (результаты рабочих процессов, повторный запуск агентов даст другие
тексты). Без скрипта созданы: `transfer_accepted.json` (запись решений о переносе), `expert_big.csv`,
`exports/qc/lake/owner30/owner30_compare.csv`.

### Уровень C: от исходных сцен

`20_tile_inventory.js`, `21_production_classify.js` (128 копий с точками в аккаунте GEE автора), `22_check_mosaic_assets.py`,
`22_run_mosaic.py` (или `22_mosaic_export.js`). Без точек автора маску повторить нельзя; повторяемый вход проекта:
ассеты тайлов и GeoTIFF маски v2.

## 5. Зависимости

Импорт кода между скриптами:

| Модуль | Кто импортирует |
|---|---|
| `cpu_limit.py` | 23 скрипта: 105, 113, 116, 120-122, 125, 127, 128, 130, 132-134, 136-138, 141, 145, 147-149, 151, 152 |
| `qc_thumb_xyz.py` | 46, 56, 129, 133, 134, 149, 151, 152, qc_render_parallel |
| `105_owner_click_batch.py` | 136, 141 (страница и снимки S2) |
| `113_tail_transfer_eval.py` | 114, 115, 117 |
| `134_aeolian_techno_candidates.py` | 137 |
| `62_step3_rule.py` | 71 |
| `97_lake_sample.py`, `98_lake_verdicts.py` | 99; 100 (98) |

Циклы по данным: 50c читает выход 51 и пишет его вход; 69 выбирал ячейки по `step3_v3e` (предыдущая итерация шага 3,
перенесена на `E:\baresand_zapsib_archive`); 108, 111, 113, 114 читают промежуточную v4, которую пишет 104; 134, 137, 138,
139 читают `step6_v6`; 151 читает слой parcels кадастра сборки 06.10.2026 (`exports/final`), а 133 с `--territory`
пишет новый parcels (цикл по данным: после переноса варианта А в `exports/final` слой parcels будет содержать и 1 120
полигонов территории с grp = terr).

Пакеты Python (по импортам): pandas, geopandas, numpy, shapely, pyogrio, rasterio, pyproj, scipy, scikit-learn,
threadpoolctl, matplotlib, Pillow, earthengine-api, requests, urllib3, tqdm, rasterstats, psutil (панель), python-docx и
pypandoc (144), torch, transformers и opencv (116), arcpy (131). Файла requirements.txt или другого файла окружения с
закреплёнными версиями (Python, библиотеки, GEOS, GDAL) в проекте нет; от версии GEOS зависит порядок id при
векторизации (раздел 4).

Пути заданы в коде абсолютно: `D:\test\baresand_zapsib`, `E:\cadastre-local`, `E:\DEM\AW3D30`, `I:\Hansen`; проект GEE
автора `nodal-thunder-481307-u1` прописан в 00_config.js, 10, 20, 21, 22_mosaic_export.js, 22_check_mosaic_assets.py,
22_run_mosaic.py, 31, 126, 127, 150, проект `ee-author-project` в `ee.Initialize` скриптов 88, 89, 90, 96, 105, 108, 111, 123,
126, 127 (полный перечень по константам: [../src/README.md](../src/README.md), раздел 2). Файла `python/config.py` нет,
скрипты его не импортируют (вопреки CLAUDE.md и RNA 2): параметры в константах и DEFAULTS скриптов.

## 6. Внешние данные

| Данные | Источник | Где лежит / как получается | Скрипты |
|---|---|---|---|
| Sentinel-2 L2A | `COPERNICUS/S2_SR_HARMONIZED` (GEE) | GEE | 20, 21, 105, 123, 126, 127, qc_thumb |
| маска тайлов и мозаика | ассеты GEE автора `ZapSib_baresands/baresand_mask_<TILE>`, `baresand_mask_AOI_v2` | GEE, Drive -> `exports/baresand_mask/` | 22, 30 |
| JRC GSW 1.4 (occurrence, seasonality, YearlyHistory) | GEE | `exports/gsw_*_AOI*.tif` (31) и GEE | 31, 32a, 44b, 50, 55, 90, 96 |
| MERIT Hydro (HND, UPA, русла) | `MERIT/Hydro/v1_0_1` | `exports/hnd_AOI*.tif`, `upa_AOI*.tif` и GEE | 31, 32a, 45, 50, 50b, 51, 55, 90 |
| Landsat 5 1984-1995 | `LANDSAT/LT05/C02/T1_L2` | `exports/landsat_1985_brightness*.tif` | 31, 61 |
| ArcticDEM V4 2 м | `UMN/PGC/ArcticDEM/V4/2m_mosaic` | GEE | 88, 89, 90, 96 |
| Hansen GFC 2019 v1.7 | First2000, Lossyear, Treecover2000 | `I:/Hansen/` | 66 |
| подложка S2 2017-2019 | 48 тайлов 10 м | `I:/Hansen/S2/Middle`, `S2/North` | 67 |
| OSM | Geofabrik ural-fed-district-latest и siberian-fed-district-latest (скачаны 05.09.2026, хешей нет) | `exports/osm/*.osm.pbf` -> `osm_infra_AOI.gpkg` (60), `osm_rivers_AOI.gpkg` (146), `osm_territory_AOI.gpkg` (151) | 60, 120, 146, 147, 151 |
| береговая линия OSM | land polygons, osmdata.openstreetmap.de | `exports/aux/osm_land/` | 44b |
| ЕГРН (НСПД) | WMS nspd.gov.ru | `exports/nspd/nspd_36048.gpkg`, `nspd_36328.gpkg` | 69, 70, 84 |
| ЕГРН (участки, локальная копия автора) | `E:/cadastre-local/data/layers/parcels_89, 86, 24.gpkg` (сведения на 08.09.2026, Красноярский край загружен 06.10.2026; не публикуются) | только чтение | 133; 151 через слой parcels |
| AlphaEarth | `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL` 2024 | GEE -> `exports/qc/alphaearth/ae_2024.csv` | 111 |
| MODIS MCD64A1 | `MODIS/061/MCD64A1` | GEE | 108 |
| Copernicus GLO-30 | `COPERNICUS/DEM/GLO30_2024_1` (как в коде 42) | GEE | 42 |
| Esri World Imagery | XYZ | кэш `exports/qc/thumbs/_tiles` | qc_thumb_xyz, 105, 129, 134, 137, 149 |
| ALOS AW3D30 v4.1 | подложка карт | `E:/DEM/AW3D30` | 145 |
| границы месторождений | `oilfields/Efield_region` (источник и лицензия не установлены; из публичного приложения убраны) | в проекте | 145, 150 |
| DINOv2 small | `facebook/dinov2-small` | Hugging Face | 116 |

## 7. Слои для просмотра (исходные снимки, первичный вектор, итоговые, дополнительные)

| Группа | Слой | Откуда |
|---|---|---|
| исходные снимки | сцены S2 тайлов (идентификатор и дата) | `exports/aux/tile_scenes.csv` (126, реестр восстановлен; охват ассета подтверждает его у 26 из 126 тайлов), сверка `gee_app/_test/scene_registry_check.csv`; вывод 127 ошибочен; снимки в GEE |
| растровая маска | `baresand_mask_AOI_v2` (10 м, 0/1) | ассет GEE; `exports/baresand_mask/*.tif` + `.vrt` |
| первичный вектор | `exports/baresand_contours_v2.gpkg`, слой contours | 30 |
| этапы каскада | `exports/baresand_genesis_step1_v3`, `step2_v3_split`, `step3_v4e`, `step4_v2e`, `step5_v3e`, `step6_v4.gpkg`; v5 и v6 на `E:\baresand_zapsib_archive` | 45, 55, 68, 83, 94/95, 104, 132, 133 |
| итоговые | `exports/final/baresand_genesis_v7.gpkg`; `baresand_anthro_cadastre_v7.gpkg` (сборка 06.10.2026); `anthro_shp/`; `aoi/baresand_aoi_v2.shp`, `aoi/mask_coverage_128tiles.shp`; вариант А: `exports/qc/cadastre_v7a/baresand_anthro_cadastre_v7a.gpkg` (anthro_in, anthro_exceed, anthro_noallot) | 133, 140 |
| дополнительные | GSW occurrence и seasonality, HND, UPA, Landsat-1985 (`exports/*.vrt`); `exports/osm/osm_infra_AOI.gpkg`, `osm_rivers_AOI.gpkg`; `exports/aux/admin6_aoi.gpkg`, `coverage_tiles.gpkg`; `exports/nspd/*.gpkg`; `exports/qc/territory/territory.gpkg`; плотность `exports/figures/density_*.tif`; `exports/qc/sea_coastline.gpkg` | 31, 60, 146, 120, 123, 69, 151, 145, 44b |
| ассеты мини-приложения | `projects/nodal-thunder-481307-u1/assets/ZapSib_baresands/app/<слой>` (150; на них переведён `gee_app/baresand_app.js`); альтернативный путь `gee_app/prepare_assets.py` (файлы для ручной загрузки) для текущих ассетов не использовался | 150 |

Какие из этих слоёв показывает мини-приложение, с какими полями и масштабами: [../gee_app/README.md](../gee_app/README.md),
раздел 1 (группы «исходные снимки», «первичный вектор», «итоговые», «дополнительные»).

## 8. Скрипты вне python/ и gee_scripts/

| Файл | Что | В репозиторий |
|---|---|---|
| `exports/qc/jev/jev_baseline.py` | разбор перед идеей Jev; обоснование конфигурации модели 102 | предложено да, но не скопировано (repo_copy = no) |
| `exports/qc/jev/baseline_verify.py` | проверка рецензента к jev_baseline (исправлены группы) | предложено да, но не скопировано (repo_copy = no) |
| `exports/qc/lake/mass/96_lake_evidence_v1_backup.py`, `98_lake_verdicts_v1_backup.py` | копии редакции 1 | нет |
| `exports/qc/aeolian_techno_small/readers_workflow_2026-10-06.js` | сценарий запуска двух слепых читателей-агентов | нет |

## 9. Расхождения документации и кода

- `ROADMAP.md` обновлён 11.04.2026 (фаза 2 помечена текущей); `RNA.md` раздел 1 перечисляет несуществующие файлы
  (`config.py`, `20_production_pipeline.py`, `31_genesis_attribution.py`, `tests/`, `training_data/`).
- `python/config.py` отсутствует; `gee_scripts/00_config.js` не исполняется: `yamalGeom` используется (строка 89), но не
  определён.
- Устаревшие docstring: 30 (маска v1, 15 тайлов; в коде v2, 6 тайлов), 45 (пишет step1_v3, а не step1_v2), 104 (описан
  только пилот), 93 (нет правила B2, в коде `--t-b2` 0,3), 133 (заголовок docstring описывает слои anthro_in,
  anthro_out сборки 06.10.2026; вариант А описан в комментариях к константам и коду).
- `127_tile_scene_footprint_check.py` даёт ошибочный вывод «0 из 128» (сравнивает несопоставимые охваты); замена:
  `gee_app/_test/scene_registry_check.py`. В манифесте 127 оставлен как историческая проверка.
- 139 и копия 140 в репозитории ждут слои сборки 06.10.2026 (anthro_out, anthro_excess, anthro_unreg); для варианта А
  написан 153, рабочая 140 переводится на новые имена.
- `31_download_aux_data.py`: `paint(aoi_fc, 0, 1)` даёт нулевой `aoi_boundary.tif`.
- 128 берёт продукт v4 из константы (параметра `--product` нет); 121 и 130 по умолчанию тоже v4.
- Без скрипта созданы `vector/mask_coverage_128tiles.*` (есть `exports/aux/coverage_tiles.gpkg` от 123), граница AOI
  (`exports/aoi_v2.geojson`, `vector/baresand_aoi_v2.*`, правка вручную), `transfer_accepted.json`, `expert_big.csv`,
  `owner30_compare.csv`.
