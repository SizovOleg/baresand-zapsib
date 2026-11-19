# BareSand: bare sands of the north of Western Siberia

**English summary.** BareSand is a map of bare (unvegetated) sands in the north of Western Siberia derived from
Sentinel-2 L2A imagery, with every sand contour attributed to a genesis class: aeolian sands, shoals (river, lake and
sea), anthropogenic sands, and undefined. The mask was produced scene by scene (one Sentinel-2 scene per MGRS tile,
July-September 2020-2025, 128 tiles covering 906,325 km² of a 1,068,411 km² study area) with a two-stage classifier
(spectral prefilter and binary random forest trained on the author's points), vectorized with a 900 m² minimum mapping
unit, and attributed by a rule cascade (GSW, MERIT Hydro, ArcticDEM, OpenStreetMap, Russian cadastre, surface history)
followed by expert review and model-based label transfer. Final layer v7 (06.10.2026): 575,054 contours, 8,155.7 km².

- **Status:** draft for discussion (13.10.2026; cadastre edition v7b and viewer updated 18.11.2026), not a release.
  Exact reproduction is not yet possible for an outside user: no frozen-input package with checksums, no environment
  file, cadastre parcels are not published. See "Статус и ограничения воспроизводимости" below.
- **Article:** Sizov O. S., [co-authors]. Updated map of bare sands in the north of Western Siberia and its accuracy
  assessment. *Geodezia i Kartografia*, 2026 (in Russian). DOI: `TODO`.
- **Accuracy** (reported for aeolian sands only): user's accuracy 94.9 %, producer's accuracy 86.0 %, F1 0.90,
  reference-based area 3,024 km² (stratified sample of 276 contours). The estimate refers to the map version at sampling
  time (before corrections v5-v7), not to the final layer v7. Anthropogenic sands are an expert class based on indirect
  evidence, with no accuracy estimate; control samples covered only the v7 reclassifications (about 1 % of the class
  area) and residual anthropogenic sand near infrastructure, not the class as a whole.
- **Cadastre comparison** (final edition v7b, accepted by the author on 03.11.2026): settlement territory and parts
  of unified land holdings count as allotments, parcels larger than 1,000 ha do not. Anthropogenic sands within
  allotments 1,101.8 km² (58.7 % of the class), beyond the allotment 243.0 km² (11,481 objects), no allotment
  349.3 km² (18,575 objects). Files: `exports/final/*_v7b.gpkg`. This is a spatial comparison, not a finding of
  violations.
- **Data:** hosted outside git, `TODO: data release URL / DOI`. Contents and fields: [docs/DATA.md](docs/DATA.md),
  file list: [docs/release_files.csv](docs/release_files.csv).
- **Interactive map:** Earth Engine App, `TODO: app URL` (assets uploaded 13.10.2026, cadastre layers v7b
  03.11.2026; script checked against the assets 18.11.2026; app not yet published, assets not yet shared); source and
  setup in [gee_app/](gee_app/README.md).
- **Reproduce:** see [docs/PIPELINE.md](docs/PIPELINE.md) (three reproduction levels) and [src/README.md](src/README.md)
  (paths). Scripts use absolute Windows paths and the author's Earth Engine project; they must be edited before
  running elsewhere. Training points of the 128 tiles exist only in the author's Earth Engine account.
- **License:** not chosen yet, `TODO`; options in [LICENSE.md](LICENSE.md). Until a license is added, all rights are
  reserved.
- **Cite:** [CITATION.cff](CITATION.cff) (article and dataset DOI placeholders).

Documentation is in Russian.

---

## Подробно (на русском)

### Что это

Репозиторий проекта BareSand: маска оголённых песков севера Западной Сибири по снимкам Sentinel-2 и атрибуция генезиса
песков. Здесь код (копии скриптов проекта), подробная документация и мини-приложение Google Earth Engine. Данные (маска,
векторные слои) в git не входят и выкладываются отдельно.

Состояние на 18.11.2026: черновик для показа и обсуждения, не выпуск. Итоговая версия карты v7 (сборка 06.10.2026,
`exports/final/baresand_genesis_v7.gpkg`): 575 054 контура, 8 155,7 км².

| Класс | Контуров | км² |
|---|---|---|
| эоловые пески | 347 885 | 2 729,7 |
| отмели (речные 3 053,7, морские 315,8, озёрные 136,6 км²) | 132 994 | 3 506,0 |
| техногенные пески | 82 729 | 1 876,2 |
| неопределённые | 11 446 | 43,8 |

Источник: `exports/final/README.md`, приложение к статье S8; подробно в [docs/DATA.md](docs/DATA.md), раздел 3.

Кратко о методе (для читателя: [docs/INTERPRETATION.md](docs/INTERPRETATION.md), методика дешифрирования; все
алгоритмы и пороги: [docs/METHODS.md](docs/METHODS.md)):
1. Классификация отдельных сцен Sentinel-2 L2A (`COPERNICUS/S2_SR_HARMONIZED`): одна сцена на тайл MGRS, июль-сентябрь
   2020-2025, облачность сцены меньше 15 %; предфильтр по MNDWI и NDVI и бинарный случайный лес по обучающим точкам
   автора; 128 тайлов, 906 325 км² из 1 068 411 км² района работ.
2. Сшивка тайлов и векторизация, минимальный контур 900 м²: первичный вектор 574 520 контуров.
3. Каскад атрибуции генезиса: морские отмели, речные и озёрные отмели, техногенные пески, эоловые и неопределённые,
   уточнение по рельефу (ArcticDEM); затем уточнение остатка автором и перенос его меток моделями на сходные контуры.
4. Исправления после оценки точности (v5-v7) и сопоставление техногенных песков с кадастровыми отводами ЕГРН.

### Статья

Сизов О.С., [соавторы: уточнить]. Оголённые пески севера Западной Сибири: уточнение карты и оценка точности //
Геодезия и картография. 2026. DOI: `TODO` (присваивается редакцией). Статья и дополнительные материалы в репозиторий
не входят (права журнала до публикации).

### Точность

По решению автора от 13.10.2026 точность приводится только для эоловых песков: точность пользователя 94,9 %,
производителя 86,0 %, F1 0,90, площадь по эталону 3 024 км². Источник:
`exports/qc/owner_click/V1/accuracy_V1+V1b+V1c_split100_U.md` (стратифицированная выборка 276 контуров, эталон: метка
автора в слепом окне проверки, скрипт `src/python/119_validation_v4.py`; определения показателей и доверительные
интервалы в [docs/METHODS.md](docs/METHODS.md), раздел 7). Объект оценки: версия карты на момент отбора выборки (до
исправлений v5-v7), часть маски, не размеченная ранее (домен U, 8 061,0 км²). Для итогового слоя v7 точность не
пересчитывалась. Общая точность по трём классам приводится в приложении к статье.

Техногенные пески описаны как экспертный класс по косвенным признакам (OSM, ЕГРН, история поверхности, метки автора),
показатели точности для них не приводятся. Весь техногенный класс контрольной выборкой не проверялся: партии T1, T2 и
T3 проверяли только переводы эоловых контуров в техногенные в версии v7 (около 1 % площади класса) и остаточный
техноген среди эоловых контуров вблизи инфраструктуры ([docs/METHODS.md](docs/METHODS.md), разделы 5.7 и 7.6).

### Техногенные пески и кадастровые отводы

Итоговая редакция v7b (принята автором 03.11.2026). Класс техногенных песков v7 не меняется (82 729 контуров,
1 876,2 км²). Отводом считаются отводы под локальные объекты, вся территория населённых пунктов и части единых
землепользований; контуры участков крупнее 1000 га (территориальные аренды) не считаются. Территорию населённых пунктов
собирает `src/python/151_territory.py`: земли населённых пунктов ЕГРН с замыканием 50 м, садоводческие участки ЕГРН,
жилая застройка, дачные массивы и аэродромы OSM, вахтовые посёлки (кластеры не менее 5 зданий OSM с замыканием 40 м) и
промзоны городов (промышленные полигоны OSM не далее 1 км от земель населённых пунктов крупнее 1 км²); объединение
998,0 км² (`exports/qc/territory/report.md`). Скрипт `src/python/133_cadastre_anthro.py --territory --ezp
--local-max-ha 1000` делит техногенные пески на три группы (`exports/qc/cadastre_v7b/cadastre_anthro.md`, итоговые
файлы `exports/final/*_v7b.gpkg`):

| Группа | Слой | Объектов | км² |
|---|---|---|---|
| в отводах (части контуров «в отводе» и «превышение» внутри отводов, без двойного счёта) | `anthro_in` | 90 887 частей | 1 096,9 |
| превышение отвода (отвод ближе 10 м, в отводе не меньше 10 % контура, часть дальше 10 м, куски не меньше 900 м²) | `anthro_exceed` | 11 481 | 243,0 |
| без отвода (отвода ближе 10 м нет или контур лишь касается чужого участка; площадь объекта целиком) | `anthro_noallot` | 18 575, из них касающихся 5 444 (154,6 км²) | 349,3 |

Полосы допуска 10 м и куски меньше 900 м² в группы не входят. По статистике контуров внутри отводов 1 101,8 км² (58,7 %
класса), из них части единых землепользований 109,0 км²; в участках крупнее 1000 га 15,4 км²; вне любых участков
492,9 км² (26,3 %). Проверка согласованности слоёв (`python/153_check_cadastre_a.py`) пройдена: 11 из 11. Выборочный
просмотр на снимках (`python/154_allot_review.py`, разметка агентами ИИ, не автором;
`exports/qc/cadastre_v7b/review_allot/summary.md`): 40 из 40 частей единых землепользований лежат под объектами; среди
30 случайных объектов без отвода у 20 объект есть, а отвода в выгрузке нет, у 2 отвод пропущен по геометрии (кусок за
границей участка дальше допуска), 3 оказались природным песком или гарью, 5 неясны. Среди крупнейших объектов без
отвода встречаются естественные пески и гари (ошибки шага 3 каскада), их класс по решению автора не исправлялся.

Предыдущие редакции (сборка 06.10.2026 и вариант А от 13.10.2026) оставлены в `exports/final` с суффиксами `_v7` и
`_v7a`. Сопоставление пространственное: слои указывают места для адресной проверки и не устанавливают нарушений.
Подробно: [docs/METHODS.md](docs/METHODS.md), раздел 8; поля: [docs/DATA.md](docs/DATA.md), раздел 5.

### Статус и ограничения воспроизводимости

Репозиторий пока черновик для обсуждения. Что известно на 13.10.2026 (в том числе по внешнему ревью Astra):

- **Нет пакета замороженных входов.** Таблицы решений шагов 2-6, v5, v7 и входы оценки точности перечислены в
  [docs/PIPELINE.md](docs/PIPELINE.md) (раздел 4) и [docs/release_files.csv](docs/release_files.csv), но не собраны в
  один пакет и не снабжены контрольными суммами SHA-256. `104_apply_big_pilot.py` при отсутствии части таблиц
  молча пропускает правила, поэтому наличие входов нужно проверять до запуска (проверки в коде нет).
- **Нет файла окружения.** Версии Python-библиотек, GEOS и GDAL не закреплены (`requirements.txt` нет); проект
  выполнялся на Python 3.12.
- **Уровень A начинается с опубликованного первичного вектора** `baresand_contours_v2.gpkg`, а не с повторной
  векторизации маски: id назначаются по порядку компонент и частей разрезов, повторная векторизация тех же id не
  гарантирует, а замороженные решения привязаны к id. Векторизация `30_vectorize_local.py` остаётся отдельной проверкой.
- **ЕГРН не публикуется.** Участки ЕГРН (выгрузки НСПД, кадастровые номера, ВРИ) в выкладку не входят, публикуются только
  производные классы (`anthro_in`, `anthro_exceed`, `anthro_noallot` без кадастровых номеров). Повторить кадастровое
  сопоставление (133, 151) внешний читатель не сможет без собственной выгрузки ЕГРН на те же даты.
- **Даты внешних выгрузок.** OSM: файлы Geofabrik `ural-fed-district-latest.osm.pbf` и
  `siberian-fed-district-latest.osm.pbf` скачаны 05.09.2026 (хешей нет, повторная загрузка `latest` даст другую
  версию). ЕГРН: сведения ЯНАО и ХМАО на 08.09.2026, Красноярский край загружен 06.10.2026; для каскада выгрузка WMS НСПД
  06-07.09.2026. Снимки Esri World Imagery со временем меняются.
- **Поля centroid_lon, centroid_lat** первичного вектора содержат координаты EPSG:3576 в метрах, а не градусы; при
  упаковке их нужно пересчитать или переименовать.
- **139 и 140 на старых именах слоёв.** `139_check_final.py` и копия `140_assemble_final.py` в `src/` ждут слои сборки
  06.10.2026 (`anthro_out`, `anthro_excess`, `anthro_unreg`); рабочая 140 переводится на новые имена, для варианта А
  написана проверка 153. Копии 133, 140, 150, 151 в `src/python/` устарели, 152 и 153 ещё не скопированы (поле
  `repo_copy` в [docs/scripts_manifest.csv](docs/scripts_manifest.csv)).
- **Реестр сцен Sentinel-2** восстановлен повторением правила выбора; по охвату ассета маски он подтверждается у 26 из
  126 проверяемых тайлов ([gee_app/README.md](gee_app/README.md), раздел 7). Распределение сцен по годам и месяцам
  относится к реестру, а не к фактически обработанным сценам.
- **Обучающие точки** 128 тайлов есть только в аккаунте Earth Engine автора: маску по сценам (уровень C) повторить
  нельзя.
- **Ссылки** на статью, облачную выкладку, DOI и App пока заглушки (`TODO`).
- В снимке репозитория остались служебные файлы (`excalidraw.log`, результаты проб в `gee_app/_test/out/`); перед
  выпуском их нужно убрать.

### Состав репозитория

```
README.md            этот файл
LICENSE.md           варианты лицензий (не выбраны)
CITATION.cff         цитирование (заглушки DOI)
.gitignore           данные, ключи, журналы, временные файлы не коммитятся
docs/
  PIPELINE.md        стадии конвейера, уровни воспроизведения, зависимости, внешние данные, слои для просмотра
  METHODS.md         алгоритмы: данные, классификация, каскад, шаг 6, исправления, точность, кадастр, карты, ограничения
  DATA.md            словарь данных: слои, поля, коды, точность, состав выкладки, лицензии и атрибуция
  scripts_manifest.csv   все 142 скрипта проекта: стадия, роль, входы, выходы, include_in_repo, level, repo_copy
  release_files.csv  файлы выкладки на облако: формат, размер, включать или нет (в том числе план замороженных входов)
src/
  README.md          пути, окружение, проверка на секреты; порядок запуска кратко (полный в docs/PIPELINE.md)
  python/            99 скриптов Python (копии; 4 устарели, см. repo_copy)
  gee_scripts/       16 скриптов Earth Engine (Code Editor), в том числе utils/accuracy.js
gee_app/
  baresand_app.js    мини-приложение Earth Engine (переведено на ассеты 150)
  prepare_assets.py  альтернативная подготовка файлов для ручной загрузки в ассеты
  README.md          что показывает приложение, ассеты, публикация
  _test/             проверки приложения и реестра сцен
```

### Документы и как они связаны

| Вопрос | Где |
|---|---|
| какие скрипты в каком порядке запускать | [docs/PIPELINE.md](docs/PIPELINE.md) (раздел 4), кратко [src/README.md](src/README.md) |
| что делает каждый скрипт | docstring скрипта, [docs/scripts_manifest.csv](docs/scripts_manifest.csv) |
| методика дешифрирования для читателя карты | [docs/INTERPRETATION.md](docs/INTERPRETATION.md) |
| правила каскада, пороги, формулы | [docs/METHODS.md](docs/METHODS.md) |
| поля и коды итоговых слоёв, лицензии | [docs/DATA.md](docs/DATA.md) |
| что выкладывается на облако | [docs/release_files.csv](docs/release_files.csv), [docs/DATA.md](docs/DATA.md) (раздел 10) |
| мини-приложение: группы слоёв, ассеты, публикация | [gee_app/README.md](gee_app/README.md), [docs/PIPELINE.md](docs/PIPELINE.md) (раздел 7) |

Пути вида `python/...`, `gee_scripts/...`, `exports/...` в документах даны от корня проекта автора
(`D:\test\baresand_zapsib`); в репозитории скрипты лежат в `src/python/` и `src/gee_scripts/`, а `exports/` относится к
выкладке данных.

### Данные

Выкладка на облаке: `TODO: ссылка`, DOI `TODO`. Рекомендуемый состав (около 460 МБ в zip, [docs/DATA.md](docs/DATA.md),
раздел 10): публичный итоговый слой с 11 основными полями, слои техногенных песков и отводов варианта А, граница района
и покрытие маски, растры плотности, маска 0/1 и первичный вектор, метки автора и выборки оценки точности; в план
добавлены входы оценки точности и замороженные входы уровня A (не собраны). Не выкладываются: выгрузки ЕГРН (участки,
кадастровые номера), снимки Esri, черновик v8, статья до публикации.

### Воспроизведение

Три уровня ([docs/PIPELINE.md](docs/PIPELINE.md), раздел 4):
- **A.** Итоговые слои из опубликованного первичного вектора, внешних данных и замороженных таблиц решений: 29 скриптов
  сборки v7 и 2 скрипта варианта А (151 и проверка 153), 2 скрипта сбора данных и 2 модуля. Ограничения перечислены
  выше (нет пакета входов и хешей, нет файла окружения, ЕГРН не публикуется).
- **B.** Пересчёт таблиц решений из меток эксперта, автора и ответов агентов (ответы моделей при повторе другие).
- **C.** От исходных сцен: нужны 128 копий скрипта классификации с обучающими точками, которые есть только в аккаунте
  Earth Engine автора.

Перед запуском на другой машине нужно заменить абсолютные пути и проект Earth Engine: общего файла параметров нет
(`config.py` не существует), пути заданы константами в каждом скрипте ([src/README.md](src/README.md), раздел 2).

### Мини-приложение

Интерактивная карта Earth Engine (`TODO: адрес App`): итоговые слои (генезис v7, плотность с ячейкой 10, 5 или 2 км
по масштабу, группы техногенных песков по отводам), снимки Sentinel-2 по тайлам, маска и первичный вектор,
справочные слои (граница района, покрытие, тайлы, инфраструктура OSM, рельеф, вода, Hansen), скачивание контуров
видимой области и правая панель статистики с графиками по районам, видимой области и широтным поясам (155).
Ассеты загружены 13.10.2026 скриптом `150_gee_upload.py` в
`projects/nodal-thunder-481307-u1/assets/ZapSib_baresands/app`, кадастровые слои v7b 03.11.2026; месторождения из
публичного приложения убраны до выяснения лицензии. Скрипт проверен на настоящих ассетах 18.11.2026 (выражения слоёв и
поиск по щелчку через Python API). App не опубликован, ассеты закрыты: публикует автор в Code Editor, перед этим ассеты
нужно открыть на чтение. Настройка, состав ассетов и порядок публикации: [gee_app/README.md](gee_app/README.md).

### Известные ограничения

- Сцены Sentinel-2 тайлов восстановлены по копиям скрипта тайлов в репозитории GEE автора (152 сцены, у 22 тайлов
  мозаика); распределение сцен в приложении S7 статьи нужно заменить ([gee_app/README.md](gee_app/README.md), раздел 7).
- Поле `not_sand_suspect` в итоговом слое имеет два смысла ([docs/DATA.md](docs/DATA.md), раздел 4.2).
- Расхождения реализации с инвариантами проекта (порядок каскада, сшивка перекрытий, состав обучающих точек, общий
  config): [docs/METHODS.md](docs/METHODS.md), раздел 10.3; [docs/PIPELINE.md](docs/PIPELINE.md), раздел 9.

### Лицензия

Не выбрана: `TODO`. Варианты (код MIT или иная, данные CC BY 4.0, части, производные от OSM, ODbL 1.0) и обязательная
атрибуция источников: [LICENSE.md](LICENSE.md). Пока лицензия не добавлена, все права сохраняются за автором.

### Цитирование

[CITATION.cff](CITATION.cff). До выхода статьи и выкладки данных DOI в нём заглушки.
