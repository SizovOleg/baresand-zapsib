# Лицензия: варианты для выбора автором

**Status (EN): no license has been chosen yet.** Until the author selects one, no permission to reuse, modify or
redistribute the code, documentation or data is granted (all rights reserved by default). The options below are drafts
for the author's decision, not a license.

Состояние на 13.10.2026: лицензия не выбрана. Пока автор не выбрал её, по умолчанию все права сохраняются за автором:
другие могут смотреть файлы, но не получают права использовать, менять и распространять код и данные. Ниже варианты
по частям репозитория; после выбора этот файл заменяется текстом выбранной лицензии (или двумя файлами: `LICENSE` для
кода и `LICENSE-DATA.md` для данных), а в `CITATION.cff` добавляется поле `license`.

## 1. Код (`src/`, `gee_app/`)

| Вариант | Что разрешает | Условия | Когда подходит |
|---|---|---|---|
| **MIT** | использовать, менять, распространять, в том числе в закрытых и коммерческих проектах | сохранять уведомление об авторстве и текст лицензии | самый короткий и распространённый вариант для научного кода |
| Apache 2.0 | то же | то же плюс пометка изменённых файлов; явная лицензия на патенты | если важна защита от патентных претензий |
| GPL 3.0 | то же | производные программы распространяются только под GPL с исходным кодом | если нужно, чтобы доработки оставались открытыми |
| BSD 3-Clause | как MIT | плюс запрет использовать имя автора для продвижения | близкая к MIT альтернатива |

Шаблон текста MIT (заполнить год и владельца прав, например автора или организацию):

```
MIT License

Copyright (c) [ГОД] [ВЛАДЕЛЕЦ ПРАВ]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 2. Данные (выкладка на облаке, не в git)

Состав выкладки и ограничения: `docs/DATA.md` (разделы 10 и 11) и `docs/release_files.csv`.

| Вариант | Для чего | Условия |
|---|---|---|
| **CC BY 4.0** | публичный итоговый слой без полей, прямо производных от OSM и ЕГРН (11 основных полей, `docs/DATA.md`, раздел 9); маска, первичный вектор, растры плотности, граница, выборки и метки автора | ссылка на авторов и источник, указание изменений |
| **ODbL 1.0** | полная версия итогового слоя (133 поля): поля, прямо производные от OSM (расстояния до дорог OSM, совпадение с объектами OSM и др.), делают таблицу производной базой данных OpenStreetMap | share-alike: производная база распространяется под ODbL с указанием способа получения |
| CC0 1.0 | если автор хочет отказаться от прав на собственные данные | не годится для частей, производных от OSM |

Вывод из `docs/DATA.md`, раздел 11 (не решение): публичный слой можно выложить под CC BY 4.0 с атрибуцией ниже; полную
версию, если она будет выложена, только под ODbL 1.0.

## 3. Документация (`README.md`, `docs/`)

Варианты: CC BY 4.0 (как данные) или та же лицензия, что у кода. Статья и дополнительные материалы к ней в репозиторий
не входят: до публикации права у журнала «Геодезия и картография».

## 4. Обязательная атрибуция источников (при любом выборе)

- OpenStreetMap (ODbL 1.0), на картах и в описании выкладки:

  > Содержит данные © участники OpenStreetMap, доступные по лицензии Open Database License (ODbL) 1.0,
  > https://www.openstreetmap.org/copyright

- Copernicus Sentinel-2: «Contains modified Copernicus Sentinel data 2017-2025».
- ЕГРН (НСПД): выгрузки реестра (слой parcels, кадастровые номера, ВРИ) не распространяются; производные классы
  техногенных песков сопровождаются оговоркой из `docs/DATA.md`, раздел 11: сопоставление пространственное и не
  устанавливает нарушений.
- JRC Global Surface Water, MERIT Hydro, Hansen Global Forest Change v1.7, Landsat 5 (USGS), ArcticDEM (PGC), AlphaEarth
  Satellite Embedding, MODIS MCD64A1, ALOS AW3D30: ссылки и условия по таблице `docs/DATA.md`, раздел 11; условия,
  помеченные там «сверить», автор проверяет на сайтах источников до выкладки (у MERIT Hydro двойная лицензия
  CC BY-NC 4.0 или ODbL 1.0).
- Esri World Imagery: снимки использовались только для визуальной проверки и не распространяются.
- Слой месторождений (`oilfields/Efield_region.shp`, показывается в мини-приложении): источник и условия в проекте не
  указаны; до публикации App выяснить (`gee_app/README.md`, раздел 9).

## 5. Что решить автору

1. Лицензия кода: MIT, Apache 2.0, GPL 3.0 или иная; владелец прав (автор или организация).
2. Лицензия данных: CC BY 4.0 для публичного слоя; выкладывать ли полную версию под ODbL 1.0.
3. Лицензия документации.
4. Можно ли распространять слой месторождений; условия источников, помеченные «сверить».
