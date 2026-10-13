"""
130_article_district_table.py - таблица 4 компактной статьи: эоловые и техногенные пески по районам, карта 2022 г. и v4
(2026-09-30; параметры --product и --out добавлены 2026-10-06).

Район контура определяется по центроиду (границы OSM admin_level 6 из exports/aux/admin6_aoi.gpkg, города окружного
значения присоединены к районам, как в 121). Восточный сектор: центроид вне районов OSM и восточнее 79° в. д. (граница
Таймырского Долгано-Ненецкого района в выгрузке OSM отсутствует). Прочие: остальные районы. Вне районов: центроид вне
границ OSM западнее 79° в. д. (акватории, устья).
Доли считаются от суммы по районам без строки «вне районов», как в таблице 1 статьи 2022 г. (там сумма по районам
1 922,53 км² при общей площади 1 929,15 км²).
Метка версии в шапке таблицы берётся из имени файла продукта (baresand_genesis_step6_v4 -> v4, baresand_genesis_v7 -> v7).
Выход по умолчанию: docs/article_v2/table_districts.md (продукт v4); для другого продукта без --out:
docs/article_v2/table_districts_<метка>.md. Относительные пути в --product и --out считаются от корня проекта.
Запуск: PYTHONIOENCODING=utf-8 python -u python/130_article_district_table.py [--product PATH] [--out PATH]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import re
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
ADMIN = ROOT / 'exports' / 'aux' / 'admin6_aoi.gpkg'
OUT = ROOT / 'docs' / 'article_v2' / 'table_districts.md'
TABLE_DATE = '2026-09-30'  # дата таблицы по продукту по умолчанию (v4, статья); для другого продукта дата запуска
EAST_LON = 79.0
ROWS = ['Ямальский', 'Тазовский', 'Надымский', 'Пуровский', 'Приуральский', 'восточный сектор', 'прочие районы',
        'вне районов']
# таблица 1 статьи 2022 г., естественные эоловые формы, км²: восточный сектор = Усть-Енисейский + Долгано-Ненецкий,
# прочие = Красноселькупский + Туруханский + Шурышкарский + Белоярский, вне районов = 1929,15 - сумма по районам
A2022 = {'Ямальский': 1203.07, 'Тазовский': 223.83, 'Надымский': 255.24, 'Пуровский': 190.28, 'Приуральский': 19.50,
         'восточный сектор': 25.53 + 0.88, 'прочие районы': 0.81 + 3.34 + 0.05 + 0.00}
A2022['вне районов'] = 1929.15 - sum(A2022.values())


def product_label(product: Path) -> str:
    """Метка версии продукта для шапки: суффикс _vN в имени файла (baresand_genesis_step6_v4 -> v4), иначе имя файла."""
    m = re.search(r'_(v\d+[a-z]?)$', product.stem)
    return m.group(1) if m else product.stem


def project_path(p: Path) -> Path:
    """Относительный путь считается от корня проекта, абсолютный остаётся как есть."""
    return p if p.is_absolute() else ROOT / p


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Параметры запуска; без параметров: продукт v4 и docs/article_v2/table_districts.md, как до 2026-10-06."""
    ap = argparse.ArgumentParser(description='Таблица 4 статьи: эоловые и техногенные пески по районам.')
    ap.add_argument('--product', type=Path, default=PRODUCT,
                    help='GeoPackage продукта со слоем genesis (по умолчанию exports/baresand_genesis_step6_v4.gpkg)')
    ap.add_argument('--out', type=Path, default=None,
                    help='файл таблицы .md (по умолчанию docs/article_v2/table_districts.md для v4, '
                         'table_districts_<метка>.md для другого продукта)')
    a = ap.parse_args(argv)
    a.product = project_path(a.product)
    if not a.product.exists():
        ap.error(f'нет файла продукта: {a.product}')
    a.is_default = a.product.resolve() == PRODUCT.resolve()
    if a.out is None:
        a.out = OUT if a.is_default else OUT.with_name(f'{OUT.stem}_{product_label(a.product)}.md')
    else:
        a.out = project_path(a.out)
    return a


def row_of(name: str | float, lon: float) -> str:
    """Строка таблицы по имени района OSM (NaN: вне районов) и долготе центроида."""
    if not isinstance(name, str):
        return 'восточный сектор' if lon >= EAST_LON else 'вне районов'
    for key in ROWS[:5]:
        if key in name:
            return key
    return 'прочие районы'


def fmt(x: float, nd: int = 1) -> str:
    """Число по-русски: пробел в тысячах, десятичная запятая."""
    return f'{x:,.{nd}f}'.replace(',', ' ').replace('.', ',')


def main(argv: list[str] | None = None) -> None:
    a = parse_args(argv)
    cpu_limit.apply()
    g = gpd.read_file(a.product, layer='genesis', columns=['id', 'genesis_main', 'area_ha'])
    c = g.geometry.centroid
    lon = gpd.GeoSeries(c, crs=g.crs).to_crs(4326).x
    adm = gpd.read_file(ADMIN, layer='admin')
    d6 = adm[(adm['admin_level'].astype(str) == '6') & adm['name'].notna()].to_crs(3576).dissolve(by='name').reset_index()
    # город окружного значения присоединяется к району с самой длинной общей границей (как в 121)
    is_city = d6['name'].str.startswith('городской округ')
    host = {}
    for _, cty in d6[is_city].iterrows():
        best, blen = None, 0.0
        for _, dst in d6[~is_city].iterrows():
            ln = cty.geometry.boundary.intersection(dst.geometry.buffer(50)).length
            if ln > blen:
                best, blen = dst['name'], ln
        host[cty['name']] = best
    d6['district'] = [host.get(n, n) for n in d6['name']]
    pts = gpd.GeoDataFrame(g[['id', 'genesis_main', 'area_ha']], geometry=gpd.GeoSeries(c, crs=g.crs).to_crs(3576).values,
                           crs=3576)
    j = gpd.sjoin(pts, d6[['district', 'geometry']], how='left', predicate='within')
    j = j[~j.index.duplicated()]
    j['row'] = [row_of(n, x) for n, x in zip(j['district'], lon.loc[j.index])]
    t = j.pivot_table(index='row', columns='genesis_main', values='area_ha', aggfunc='sum').reindex(ROWS).fillna(0) / 100
    t['a2022'] = pd.Series(A2022)
    in_d = t.index != 'вне районов'
    for col in ('aeolian', 'a2022'):
        t[f'{col}_pct'] = 100 * t[col] / t.loc[in_d, col].sum()
    v = product_label(a.product)
    L = ['# Таблица 4 компактной статьи: эоловые и техногенные пески по районам '
         f'(python/130, {TABLE_DATE if a.is_default else date.today().isoformat()})', '']
    if not a.is_default:
        L += [f'Файл продукта: {a.product.name}.', '']
    L += [f'Восточный сектор: центроид вне районов OSM восточнее {EAST_LON:g}° в. д. Доли от суммы по районам без строки '
          '«вне районов» (как в таблице 1 статьи 2022 г.).', '',
          f'| Район | 2022 г., км² (доля, %) | {v} эоловые, км² (доля, %) | {v} техногенные, км² |', '|---|---|---|---|']
    for r in ROWS:
        pct22 = '' if r == 'вне районов' else f' ({fmt(t.at[r, "a2022_pct"], 2)})'
        pct = '' if r == 'вне районов' else f' ({fmt(t.at[r, "aeolian_pct"])})'
        L.append(f'| {r} | {fmt(t.at[r, "a2022"], 2)}{pct22} | {fmt(t.at[r, "aeolian"])}{pct} | '
                 f'{fmt(t.at[r, "anthropogenic"])} |')
    L.append(f'| всего | {fmt(t["a2022"].sum(), 2)} | {fmt(t["aeolian"].sum())} | {fmt(t["anthropogenic"].sum())} |')
    L += ['', f'Сумма по районам: 2022 г. {fmt(t.loc[in_d, "a2022"].sum(), 2)} км², {v} эоловые '
              f'{fmt(t.loc[in_d, "aeolian"].sum())} км².', '',
          'Контроль, все классы по строкам, км²:', '', t.drop(columns=['a2022', 'aeolian_pct', 'a2022_pct']).round(2).to_markdown()]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
