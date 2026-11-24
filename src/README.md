# Код обработки

Скрипты, которыми построены маска оголённых песков, атрибуция генезиса, оценка точности, сопоставление с земельными
отводами, итоговые слои и интерактивная карта. Алгоритмы, правила и пороги описаны в
[../docs/METHODS.md](../docs/METHODS.md); там же (раздел 1) приведена схема обработки по этапам.

## Состав

- `gee_scripts/`: скрипты Google Earth Engine (JavaScript, Code Editor): выбор метода на калибровочных сценах,
  классификация тайлов, сшивка маски.
- `python/`: скрипты Python: векторизация, вспомогательные растры, каскад атрибуции генезиса, экспертная разметка и
  перенос меток, оценка точности, точечные правки, сопоставление с земельными отводами, статистика, карты, загрузка
  слоёв интерактивной карты.
- `requirements.txt`: пакеты Python с версиями, на которых проверены скрипты (Python 3.12).

## Запуск

Скрипты Python запускаются из корня проекта, в котором лежат папки `python/` (содержимое `src/python/`),
`gee_scripts/` и `exports/` (данные): `python -u python/<скрипт>.py [ключи]`. Пути к данным и проект Google Earth
Engine заданы константами в начале скриптов (`ROOT`, `EXPORTS`, `ee.Initialize(project=...)`) и значениями по умолчанию
ключей командной строки; для запуска в другом окружении их нужно заменить. Входы, выходы и ключи каждого скрипта описаны
в его docstring. Скрипты с длительными расчётами ограничивают число потоков через `cpu_limit.py`.

Скрипты Google Earth Engine выполняются в Code Editor. `21_production_classify.js` является шаблоном классификации
тайла: для каждого тайла создавалась копия с обучающими точками в Geometry Imports и параметрами отбора сцен
([../supplement/S07_scenes.md](../supplement/S07_scenes.md)).

## Указатель скриптов

| Этап | Скрипты | Назначение |
|---|---|---|
| выбор метода | gee_scripts/00_config.js, 01_explore_scenes.js, 02_cloud_mask.js, 03_spectral_indices.js | параметры, обзор сцен, облачная маска, спектральные индексы |
| | gee_scripts/10_method_threshold.js - 16_diff_rf_vs_combined.js | сравнение методов на эталонной сцене ([S2](../supplement/S02_method_comparison.md)) |
| | gee_scripts/17_validation.js, utils/accuracy.js | проверка классификатора на калибровочных сценах ([S1](../supplement/S01_classifier_check.md)) |
| маска песка | gee_scripts/20_tile_inventory.js, 21_production_classify.js | инвентаризация тайлов, классификация тайла |
| | gee_scripts/22_mosaic_export.js; python/22_check_mosaic_assets.py, 22_run_mosaic.py | сшивка масок тайлов |
| | python/123_coverage.py | покрытие маски |
| векторизация и вспомогательные данные | python/30_vectorize_local.py | контуры маски, минимальная единица 900 м² |
| | python/31_download_aux_data.py | растры GSW, MERIT Hydro, Landsat 1984-1995 гг. |
| шаг 1: морские отмели | python/32a_step1_littoral.py, 44b_sea_distance_osm.py | высота над водотоком, расстояние до моря |
| | python/32b_step1_shoal.py, 45_step1_shoal_v2.py | правило шага 1 |
| | python/41_qc_step1_package.py, 43_qc_step1_evidence_local.py, 46_qc_step1_sample.py, 47_qc_step1_synthesize.py | эталон и проверка шага 1 |
| шаг 2: речные и озёрные отмели | python/50_step2_water_evidence.py, 50b_step2_channel_evidence.py, 50c_step2_giant_nearwater.py | признаки воды, русел и затопляемости |
| | python/51_step2_rule.py, 55_step2_split_mixed.py | правило шага 2, разрез смешанных контуров |
| | python/52_step2_sample.py, 53_step2_synthesize.py, 54_step2_expert_verdicts.py, 56_step2_split_qc_sample.py | эталон и проверка шага 2 |
| шаг 3: техногенные пески | python/60_step3_osm_extract.py, 61_step3_infra_evidence.py, 61b_step3_osm_built.py | признаки инфраструктуры OSM и формы |
| | python/66_step3_temporal_evidence.py, 67_step3_s2_evidence.py | история поверхности (GFC 2000 г., Sentinel-2 2017-2019 гг.) |
| | python/69_step3_nspd_download.py, 70_step3_nspd_evidence.py | признаки участков и сооружений ЕГРН |
| | python/62_step3_rule.py, 68_step3_apply_expert.py | правило шага 3, экспертные правки |
| | python/63_step3_sample.py, 64_step3_synthesize.py, 65_step3_expert_verdicts.py, 71_step3_nspd_small_qc.py | эталон и проверка шага 3 |
| шаг 4: эоловые и неопределённые | python/80_step4_evidence.py, 81_step4_rule.py, 83_step4_apply_expert.py | признаки, правило шага 4, экспертные правки |
| | python/82_step4_qc.py, 84_cascade_order_check.py, 87_undef_review_package.py | проверка шага 4, техногенный след у отмелей, просмотр неопределённых |
| шаг 5: рельеф | python/88_dem_pilot.py, 89_dem_baselevel_compare.py, 90_dem_evidence_mass.py | превышения над локальным базисом по ArcticDEM |
| | python/91_target_sample.py, 92_target_verdicts.py, 93_apply_dem_rules.py, 94_step5_apply_expert.py | целевая выборка, пороги, правила шага 5 |
| | python/95_flag_not_sand.py | флаг not_sand_suspect |
| отложенная выборка каскада | python/85_final_validation_sample.py, 86_final_accuracy.py | проверка шагов 1-5 |
| шаг 6: неопределённый остаток | python/96_lake_evidence.py - 99_lake_audit_sample.py | признаки и выборки для озёрных отмелей |
| | python/101_big_undefined_sample.py - 104_apply_big_pilot.py | крупнейшие неопределённые контуры: описание снимков и классификатор |
| | python/108_burn_signature_modis.py, 109_disputed_analysis.py, 110_disputed_class.py | вырубки без пожара, контуры без надёжного решения |
| | python/111_alphaearth_features.py - 115_small_eval.py | эмбеддинги AlphaEarth, перенос меток и его проверка |
| окно проверки и утилиты | python/105_owner_click_batch.py, 107_owner_click_ingest.py, owner_click_server.py | окно экспертной разметки, приём меток |
| | python/qc_thumb_xyz.py, qc_render_parallel.py, cpu_limit.py | снимки Esri World Imagery для разметки, ограничение нагрузки |
| оценка точности | python/118_validation_v4_pop.py, 119_validation_v4.py | совокупность, оценки по площади ([S6](../supplement/S06_accuracy.md)) |
| точечные правки и итоговый слой | python/125_mixed_for_split.py, 132_apply_mixed_split.py | пересмотр смешанных контуров (v5) |
| | python/134_aeolian_techno_candidates.py, 135_merge_readers.py, 136_owner_techno_batch.py, 137_small_techno_candidates.py, 138_build_final.py | эоловые контуры вблизи инфраструктуры (v7) |
| | python/141_control_batch.py, 142_control_estimates.py, 143_control_review.py | контрольная выборка T3 ([S10](../supplement/S10_point_corrections.md)) |
| | python/139_check_final.py, 140_assemble_final.py | проверка и сборка итоговых слоёв |
| земельные отводы | python/151_territory.py, 133_cadastre_anthro.py, 153_check_cadastre_a.py, 154_allot_review.py | территория населённых пунктов, группы техногенных песков, проверки ([S11](../supplement/S11_cadastre.md)) |
| | python/157_allot_by_district.py, 159_age_north70.py, 160_age_into_layer.py | отводы по районам (табл. S11.7); возраст поверхности контуров вне использованных листов Global Forest Change (Earth Engine) и его запись в итоговые слои и ассеты карты |
| статистика, карты и рисунки | python/120_admin_districts.py, 121_article_stats.py, 130_article_district_table.py | районы, сводные показатели, таблица по районам |
| | python/article_facts.py, 158_buffer_background.py | показатели по ареалам, районам и месторождениям; доля суши и эоловых песков по расстоянию до воды и русел ([S13](../supplement/S13_hydro_proximity.md)) |
| | python/128_article_map.py, 129_article_examples.py, 145_distribution_map.py, 146_osm_rivers.py | карты и рисунки статьи |
| интерактивная карта | python/150_gee_upload.py, 155_app_stats.py, 156_allotment_mask.py | загрузка слоёв в Earth Engine, статистика панели, обобщённая маска отводов ([../gee_app/](../gee_app/README.md)) |
