# Licenses for documentation and data / Лицензии документации и данных

**EN.** The code in this repository (`src/`, `gee_app/`) is released under the MIT License (`LICENSE`). Documentation
(`README.md`, `docs/`) and the BareSand data products (sand mask, primary vector, genesis layer in its public version,
density rasters, cadastre groups of anthropogenic sands, the generalized allotment mask, statistics) are released under
the Creative Commons Attribution 4.0 International License (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/).
Parts derived from OpenStreetMap (the infrastructure layer of the viewer and any version of the genesis layer that keeps
fields computed from OSM) are a derivative database of OpenStreetMap and are available under the Open Database License
1.0 (ODbL, https://opendatacommons.org/licenses/odbl/1-0/). Cadastre parcels with cadastral numbers are not published.

**RU.** Решение автора от 19.11.2026: лицензия открытая.

| Часть | Лицензия | Условия |
|---|---|---|
| код: `src/`, `gee_app/` | MIT (`LICENSE`) | сохранять уведомление об авторстве и текст лицензии |
| документация: `README.md`, `docs/` | CC BY 4.0 | ссылка на авторов и источник, указание изменений |
| данные: маска песка, первичный вектор, публичная версия слоя генезиса, растры плотности, кадастровые группы техногенных песков, обобщённая маска отводов, статистика | CC BY 4.0 | то же |
| части, производные от OpenStreetMap: слой инфраструктуры приложения, полная версия слоя генезиса с полями, рассчитанными по OSM | ODbL 1.0 | share-alike: производная база распространяется под ODbL с указанием способа получения |

Участки ЕГРН с кадастровыми номерами, категорией и ВРИ не публикуются (`docs/DATA.md`, раздел 5.1б); вместо них
публикуется обобщённая маска отводов без атрибутов. Условия использования сведений НСПД перед выкладкой данных стоит
сверить на nspd.gov.ru.

## Как ссылаться

Сизов О.С. и др. Оголённые пески севера Западной Сибири (BareSand): карта по снимкам Sentinel-2 и генезис песков. 2026.
Репозиторий: https://github.com/SizovOleg/baresand-zapsib; интерактивная карта:
https://nodal-thunder-481307-u1.projects.earthengine.app/view/baresand. Статья и DOI выкладки: `CITATION.cff`.

## Атрибуция исходных данных

- Copernicus Sentinel-2 (ESA), обработка в Google Earth Engine (`COPERNICUS/S2_SR_HARMONIZED`).
- JRC Global Surface Water (Pekel et al., 2016), MERIT Hydro (Yamazaki et al., 2019), ArcticDEM (Polar Geospatial
  Center), Hansen Global Forest Change (Hansen et al., 2013), Landsat (USGS).
- © участники OpenStreetMap, ODbL 1.0.
- Сведения ЕГРН (НСПД, Росреестр), в обобщённом виде.

Подробная атрибуция и условия каждого источника: `docs/DATA.md`, раздел 11.
