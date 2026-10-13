"""
121_article_stats.py - сводные цифры продукта для второй версии статьи (2026-09-27; параметры --product и --out
добавлены 2026-10-06).

Таблицы: основные и детальные классы (число, площадь, доли, средний и медианный размер, крупнейший контур, объекты > 1 км2),
структура по размеру, широтные пояса, вклад шага 6, контуры, признанные владельцем «не песком», районы (если есть
exports/aux/admin6_aoi.gpkg от 120). Площадь района работ по exports/aoi_v2.geojson.
Для продуктов v5 и новее (есть поле genesis_v4 или genesis_v6) добавляется таблица переходов классов для поправок после
оценки точности (step6_rule v5_* и v7_*): класс до -> класс после, число контуров и км2.
Метка версии в заголовке берётся из имени файла продукта (baresand_genesis_step6_v4 -> v4, baresand_genesis_v7 -> v7).
Выход по умолчанию: docs/article_v2/stats_v4.md (продукт v4); для другого продукта без --out:
docs/article_v2/stats_<метка>.md. Относительные пути в --product и --out считаются от корня проекта.
Запуск: PYTHONIOENCODING=utf-8 python -u python/121_article_stats.py [--product PATH] [--out PATH]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import re
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
AOI = ROOT / 'exports' / 'aoi_v2.geojson'
ADMIN = ROOT / 'exports' / 'aux' / 'admin6_aoi.gpkg'
OUT = ROOT / 'docs' / 'article_v2' / 'stats_v4.md'
STATS_DATE = '2026-09-27'  # дата сводки по продукту по умолчанию (v4, цифры статьи); для другого продукта дата запуска
RU = {'alluvial_littoral': 'отмели (все)', 'aeolian': 'эоловый', 'anthropogenic': 'техногенный', 'undefined': 'неопределённый',
      'disputed': 'спорный', 'river_shoal': 'речная отмель', 'lake_shoal': 'озёрная отмель', 'shoal': 'морская отмель'}
# правила шага 6, в которых владелец ставил метку «не песок» (undefined + not_sand_suspect); правила v7_* (v7_owner_techno,
# v7_agent_techno, v7_agent_small) только переводят эоловый в техногенный и «не песка» не дают, поэтому сюда не входят
NOT_SAND_RULES = ['v4_expert', 'v5_mixed_owner']
# поле с классом до поправки для каждого префикса правила шага 6 (поправки после оценки точности)
PREV_FIELD = {'v5_': 'genesis_v4', 'v7_': 'genesis_v6'}


def product_label(product: Path) -> str:
    """Метка версии продукта для заголовков: суффикс _vN в имени файла (baresand_genesis_step6_v4 -> v4), иначе имя файла."""
    m = re.search(r'_(v\d+[a-z]?)$', product.stem)
    return m.group(1) if m else product.stem


def project_path(p: Path) -> Path:
    """Относительный путь считается от корня проекта, абсолютный остаётся как есть."""
    return p if p.is_absolute() else ROOT / p


def shown_path(p: Path) -> str:
    """Путь для отчёта: относительно корня проекта, если файл внутри него, иначе полный."""
    try:
        return p.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(p)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Параметры запуска; без параметров: продукт v4 и docs/article_v2/stats_v4.md, как до 2026-10-06."""
    ap = argparse.ArgumentParser(description='Сводные цифры продукта для статьи (слой genesis).')
    ap.add_argument('--product', type=Path, default=PRODUCT,
                    help='GeoPackage продукта со слоем genesis (по умолчанию exports/baresand_genesis_step6_v4.gpkg)')
    ap.add_argument('--out', type=Path, default=None,
                    help='файл отчёта .md (по умолчанию docs/article_v2/stats_v4.md для v4, stats_<метка>.md для '
                         'другого продукта)')
    a = ap.parse_args(argv)
    a.product = project_path(a.product)
    if not a.product.exists():
        ap.error(f'нет файла продукта: {a.product}')
    a.is_default = a.product.resolve() == PRODUCT.resolve()
    if a.out is None:
        a.out = OUT if a.is_default else OUT.with_name(f'stats_{product_label(a.product)}.md')
        if not a.is_default and a.out.resolve() == OUT.resolve():
            ap.error(f'метка продукта совпадает с v4, отчёт статьи {OUT.name} не перезаписываю: укажите --out явно')
    else:
        a.out = project_path(a.out)
    return a


def class_table(g: pd.DataFrame, col: str) -> pd.DataFrame:
    t = g.groupby(col).agg(N=('id', 'size'), km2=('area_ha', lambda s: s.sum() / 100), mean_ha=('area_ha', 'mean'),
                           median_ha=('area_ha', 'median'), max_km2=('area_ha', lambda s: s.max() / 100),
                           n_gt1km2=('area_ha', lambda s: int((s > 100).sum())),
                           share_n_lt1ha=('area_ha', lambda s: (s < 1).mean()),
                           share_a_lt1ha=('area_ha', lambda s: s[s < 1].sum() / s.sum()),
                           share_a_ge100ha=('area_ha', lambda s: s[s >= 100].sum() / s.sum()))
    t['share_area'] = t['km2'] / t['km2'].sum()
    t.index = [RU.get(i, i) for i in t.index]
    return t.round({'km2': 1, 'mean_ha': 2, 'median_ha': 2, 'max_km2': 2, 'share_n_lt1ha': 3, 'share_a_lt1ha': 3,
                    'share_a_ge100ha': 3, 'share_area': 4})


def transition_section(g: pd.DataFrame) -> list[str]:
    """Раздел отчёта: переходы классов (класс до -> класс после) для поправок после оценки точности, то есть для
    контуров с step6_rule v5_* (класс до: genesis_v4) и v7_* (класс до: genesis_v6). Классы детальные (поле genesis)."""
    rule = g['step6_rule'].fillna('')
    parts = []
    for prefix, field in PREV_FIELD.items():
        sel = g[rule.str.startswith(prefix)]
        if sel.empty:
            continue
        prev = sel[field].fillna('н/д') if field in sel.columns else pd.Series(f'н/д (нет поля {field})', index=sel.index)
        parts.append(pd.DataFrame({'step6_rule': sel['step6_rule'], 'класс до': prev.map(lambda x: RU.get(x, x)),
                                   'класс после': sel['genesis'].map(lambda x: RU.get(x, x)), 'area_ha': sel['area_ha']}))
    L = ['## Поправки после оценки точности (step6_rule v5_* и v7_*): класс до -> класс после', '',
         'Класс до: genesis_v4 для v5_* (разрез смешанных контуров владельцем; считаются части разреза), genesis_v6 для '
         'v7_* (техногенные среди эоловых). Классы детальные (поле genesis).', '']
    if not parts:
        return L + ['Контуров с правилами v5_* и v7_* в продукте нет.', '']
    d = pd.concat(parts)
    # класс до неизвестен (нет поля или пустое значение): такие контуры не считаются сменившими класс
    d['known'] = ~d['класс до'].str.startswith('н/д')
    d['changed'] = d['known'] & (d['класс до'] != d['класс после'])
    d['area_changed_ha'] = d['area_ha'].where(d['changed'], 0.0)
    t = d.groupby(['step6_rule', 'класс до', 'класс после']).agg(
        N=('area_ha', 'size'), km2=('area_ha', lambda x: round(x.sum() / 100, 2))).reset_index()
    s = d.groupby('step6_rule').agg(N=('area_ha', 'size'), km2=('area_ha', lambda x: round(x.sum() / 100, 2)),
                                    N_changed=('changed', 'sum'),
                                    km2_changed=('area_changed_ha', lambda x: round(x.sum() / 100, 2)))
    s.loc['всего'] = [len(d), round(d['area_ha'].sum() / 100, 2), int(d['changed'].sum()),
                      round(d['area_changed_ha'].sum() / 100, 2)]
    s[['N', 'N_changed']] = s[['N', 'N_changed']].astype(int)
    unknown = list(d.loc[~d['known'], 'step6_rule'].unique())
    if unknown:
        # смена класса для этих правил не определена: н/д вместо нуля, итог тоже неполный
        s = s.astype(object)
        s.loc[unknown + ['всего'], ['N_changed', 'km2_changed']] = 'н/д'
    return L + [t.to_markdown(index=False), '', 'Итог по правилам (changed: класс после отличается от класса до):', '',
                s.to_markdown(), '']


def main(argv: list[str] | None = None) -> None:
    a = parse_args(argv)
    cpu_limit.apply()
    fields = set(pyogrio.read_info(str(a.product), layer='genesis')['fields'])
    prev_fields = [f for f in ('genesis_v4', 'genesis_v6') if f in fields]
    g = gpd.read_file(a.product, layer='genesis', columns=['id', 'genesis', 'genesis_main', 'area_ha', 'step6_rule',
                                                            'not_sand_suspect', 'expert_note', 'shoal_type_src']
                      + prev_fields)
    c = g.geometry.centroid
    ll = gpd.GeoSeries(c, crs=g.crs).to_crs(4326)
    g['lat'], g['lon'] = ll.y, ll.x
    aoi_km2 = gpd.read_file(AOI).to_crs(3576).area.sum() / 1e6
    tot = g['area_ha'].sum() / 100
    label = product_label(a.product)
    L = [f'# Цифры продукта {label} для статьи ({STATS_DATE if a.is_default else date.today().isoformat()})', '']
    if not a.is_default:
        L += [f'Файл продукта: {shown_path(a.product)}.', '']
    L += [f'Район работ (exports/aoi_v2.geojson): {aoi_km2:,.0f} км2. Продукт: {len(g):,} контуров, {tot:,.1f} км2 '
          f'({tot / aoi_km2:.2%} площади района).', '',
          '## Основные классы', '', class_table(g, 'genesis_main').to_markdown(), '',
          '## Детальные классы (с типом отмели)', '', class_table(g, 'genesis').to_markdown(), '']
    bins = [0, 0.1, 1, 20, 100, np.inf]
    lab = ['< 0.1 га', '0.1-1 га', '1-20 га', '20-100 га', '>= 100 га']
    g['size'] = pd.cut(g['area_ha'], bins, right=False, labels=lab)
    s = g.pivot_table(index='size', columns='genesis_main', values='area_ha', aggfunc='sum', observed=False).fillna(0) / 100
    n = g.pivot_table(index='size', columns='genesis_main', values='id', aggfunc='size', observed=False).fillna(0).astype(int)
    L += ['## Структура по размеру: площадь, км2', '', s.round(1).rename(columns=RU).to_markdown(), '',
          '## Структура по размеру: число контуров', '', n.rename(columns=RU).to_markdown(), '']
    g['lat_band'] = pd.cut(g['lat'], [60, 64, 66, 68, 70, 74], right=False,
                           labels=['< 64', '64-66', '66-68', '68-70', '>= 70'])
    b = g.pivot_table(index='lat_band', columns='genesis_main', values='area_ha', aggfunc='sum', observed=False).fillna(0) / 100
    L += ['## Широтные пояса (центроид контура, с. ш.), км2', '', b.round(1).rename(columns=RU).to_markdown(), '']
    # все значения step6_rule, включая v5_* и v7_*, попадают в таблицу автоматически (группировка по полю)
    r = g.groupby(g['step6_rule'].fillna('каскад, шаги 1-5')).agg(N=('id', 'size'), km2=('area_ha', lambda x: round(x.sum() / 100, 2)))
    L += ['## Источник класса (шаг 6)', '', r.to_markdown(), '']
    ns = g[g['genesis'].eq('undefined') & g['step6_rule'].isin(NOT_SAND_RULES) & g['not_sand_suspect'].eq(1)]
    L += [f'Контуры, признанные владельцем «не песком» при просмотре (undefined + метка владельца): {len(ns)}, '
          f'{ns["area_ha"].sum() / 100:.2f} км2.', '']
    if prev_fields:
        L += transition_section(g)
    COV = ROOT / 'exports' / 'aux' / 'coverage_tiles.gpkg'
    if COV.exists():
        cov_km2 = gpd.read_file(COV, layer='coverage').to_crs(3576).area.iloc[0] / 1e6
        L += [f'Фактическое покрытие маски (128 тайлов MGRS внутри района работ, python/123_coverage.py): {cov_km2:,.0f} км2 '
              f'({cov_km2 / aoi_km2:.1%} района); песок {tot / cov_km2:.2%} покрытой площади.', '']
    if ADMIN.exists():
        adm = gpd.read_file(ADMIN, layer='admin')
        d6 = adm[(adm['admin_level'].astype(str) == '6') & adm['name'].notna()].to_crs(3576).dissolve(by='name').reset_index()
        # город окружного значения присоединяется к району с самой длинной общей границей (для сравнения с таблицей 2022 г.)
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
        cov_geom = gpd.read_file(COV, layer='coverage').to_crs(3576).geometry.iloc[0] if COV.exists() else \
            gpd.read_file(AOI).to_crs(3576).geometry.iloc[0]
        d6['a_cov'] = d6.intersection(cov_geom).area / 1e6
        pts = gpd.GeoDataFrame(g[['id', 'genesis_main', 'area_ha']], geometry=gpd.GeoSeries(c, crs=g.crs).to_crs(3576).values, crs=3576)
        j = gpd.sjoin(pts, d6[['name', 'district', 'geometry']], how='left', predicate='within')
        j = j[~j.index.duplicated()]
        t = j.pivot_table(index='district', columns='genesis_main', values='area_ha', aggfunc='sum').fillna(0) / 100
        t['всего'] = t.sum(axis=1)
        t['площадь района в покрытии, км2'] = d6.groupby('district')['a_cov'].sum()
        tot_cls = g.groupby('genesis_main')['area_ha'].sum() / 100
        for col in ('aeolian', 'anthropogenic', 'alluvial_littoral'):
            if col in t:
                t[f'{RU[col]}, % от класса'] = 100 * t[col] / tot_cls[col]
                t[f'{RU[col]}, % площади района'] = 100 * t[col] / t['площадь района в покрытии, км2']
        t = t.sort_values('всего', ascending=False)
        L += ['## Муниципальные районы (OSM admin_level 6; города присоединены к районам по общей границе; контур относится к '
              'району по центроиду), км2', '',
              'Города -> районы: ' + '; '.join(f'{k.replace("городской округ ", "")} -> {v}' for k, v in host.items()), '',
              t.rename(columns=RU).round(3).to_markdown(), '',
              f'Вне районов (центроид вне границ OSM, например, на акватории или в устье): {int(j["name"].isna().sum())} контуров, '
              f'{j.loc[j["name"].isna(), "area_ha"].sum() / 100:.1f} км2.', '']
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
