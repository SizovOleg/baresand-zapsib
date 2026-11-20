# Лицензии документации и данных

| Часть | Лицензия | Условия |
|---|---|---|
| код: `src/`, `gee_app/` | MIT ([LICENSE](LICENSE)) | сохранять уведомление об авторстве и текст лицензии |
| документация: `README.md`, `SUMMARY_EN.md`, `supplement/`, `docs/` | CC BY 4.0 | ссылка на автора и источник, указание внесённых изменений |
| данные: итоговый слой генезиса, маска песка, растры плотности, группы техногенных песков по отношению к земельным отводам, обобщённая маска отводов, таблицы | CC BY 4.0 | то же |
| части, производные от OpenStreetMap: слой инфраструктуры интерактивной карты, поля итогового слоя, рассчитанные по объектам OpenStreetMap | ODbL 1.0 | производная база данных распространяется на тех же условиях с указанием источника |

CC BY 4.0: https://creativecommons.org/licenses/by/4.0/; ODbL 1.0: https://opendatacommons.org/licenses/odbl/1-0/.

Сведения Единого государственного реестра недвижимости использованы в обобщённом виде: публикуются группы техногенных
песков и маска земельных отводов без атрибутов участков.

## Как ссылаться

Сизов О.С. BareSand: оголённые пески севера Западной Сибири. Дополнительные материалы к статье «Оголённые пески севера
Западной Сибири: уточнение карты и оценка точности». 2026. URL: https://github.com/SizovOleg/baresand-zapsib.

## Исходные данные

- Copernicus Sentinel-2 (ESA), коллекция `COPERNICUS/S2_SR_HARMONIZED` в Google Earth Engine.
- JRC Global Surface Water (Pekel et al., 2016); MERIT Hydro (Yamazaki et al., 2019).
- ArcticDEM, версия 4.1 (Polar Geospatial Center; Porter et al., 2023); ALOS AW3D30, версия 4.1 (JAXA).
- Global Forest Change (Hansen et al., 2013); MODIS MCD64A1 (Giglio et al., 2018); Landsat 5 (USGS).
- AlphaEarth Foundations (Brown et al., 2025); Esri World Imagery.
- © участники OpenStreetMap, ODbL 1.0.
- Сведения ЕГРН (Национальная система пространственных данных, Росреестр).

Условия каждого источника: [docs/DATA.md](docs/DATA.md), раздел «Исходные данные и атрибуция».
