"""
132_apply_mixed_split.py - перенос ручного разреза смешанных контуров владельцем в продукт (2026-10-04).

Вход: продукт exports/baresand_genesis_step6_v4.gpkg и слои владельца exports/qc/mixed_split/<слой>.shp (собраны 125,
размечены в ArcGIS). Класс части: поле part_cls, если пусто, то note_own (владелец пишет класс туда); пустой класс у
всех частей контура: контур не трогается; пустой класс у части разрезанного контура: часть получает исходный класс.
Разрез по схеме шага 2 (55): самая крупная часть сохраняет id (геометрия уменьшена, split_n = число новых частей),
новые части получают id = PART_ID_BASE + n, parent_id = исходный id, part_kind = owner_split; split_from = исходный
класс у всех частей разреза. Улики (числовые поля) считались по целому контуру, поэтому у всех частей разреза,
включая основную с исходным id, они обнуляются (NaN; в 55 основная часть их сохраняла, здесь класс части часто другой);
поля истории классов (genesis_step2 ... genesis_v3e, *_rule) копируются от исходного контура. Новое поле genesis_v4:
класс до этого переноса у всех строк продукта. Неразрезанный контур сохраняет геометрию и улики, меняется только класс.
not_sand_suspect по соглашению шага 6 (104): «не песок» владельца 1, песчаный класс владельца 0. Щепки меньше MMU (900 м2) приливаются к соседней части того же контура с самой
длинной общей границей. Геометрия частей: make_valid, только полигоны, MultiPolygon.
Классы владельца: эоловый, отмель речная, отмель озёрная, морская отмель, техноген, не песок (undefined +
not_sand_suspect = 1, как метки v4_expert), смешанный / спорный (disputed, dispute_reason = owner). Отмели:
shoal_type_src = owner. Всем изменённым строкам step6_rule = v5_mixed_owner, expert_note = класс владельца.
Выход: exports/baresand_genesis_step6_v5.gpkg (+ стили .qml копией из v4) и отчёт exports/qc/mixed_split/apply_v5.md.
v4 не перезаписывается; существующий v5 перезаписывается только с --force. Слой xl_candidates владелец решил не
размечать (2026-10-04). Запуск: PYTHONIOENCODING=utf-8 python -u python/132_apply_mixed_split.py [--layers mixed_known] [--force]
"""
import argparse
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
SRC = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
OUT = ROOT / 'exports' / 'baresand_genesis_step6_v5.gpkg'
MS = ROOT / 'exports' / 'qc' / 'mixed_split'
PART_ID_BASE = 900000          # 700000+ и 800000+ заняты разрезами шагов 2-3
MMU_M2 = 900.0
RULE = 'v5_mixed_owner'
MAIN = {'shoal': 'alluvial_littoral', 'river_shoal': 'alluvial_littoral', 'lake_shoal': 'alluvial_littoral'}
SHOAL_TYPE = {'shoal': 'sea', 'river_shoal': 'river', 'lake_shoal': 'lake'}
NOTE = {'aeolian': 'эоловый', 'river_shoal': 'речная отмель', 'lake_shoal': 'озёрная отмель', 'shoal': 'морская отмель',
        'anthropogenic': 'техноген', 'not_sand': 'не песок', 'disputed': 'смешанный'}
# поля истории и правил, которые части наследуют от исходного контура (остальные числовые улики у новых частей NaN)
KEEP_NUMERIC = {'id', 'parent_id', 'area_ha', 'area_km2', 'split_n', 'not_sand_suspect'}


def owner_class(text: str | None) -> str | None:
    """Класс владельца по свободной записи; None, если пусто; ошибка, если не распознан."""
    t = (text or '').strip().lower().replace('ё', 'е')
    if not t:
        return None
    if 'не песок' in t:
        return 'not_sand'
    for key, cls in (('смеш', 'disputed'), ('спор', 'disputed'), ('эол', 'aeolian'), ('реч', 'river_shoal'),
                     ('озер', 'lake_shoal'), ('мор', 'shoal'), ('техн', 'anthropogenic'), ('антроп', 'anthropogenic')):
        if key in t:
            return cls
    raise ValueError(f'класс владельца не распознан: «{text}»')


def polygonal(g) -> MultiPolygon:
    """make_valid и только полигональная часть как MultiPolygon."""
    g = make_valid(g)
    polys = [p for p in getattr(g, 'geoms', [g]) if isinstance(p, (Polygon, MultiPolygon))]
    flat = [q for p in polys for q in getattr(p, 'geoms', [p])]
    return MultiPolygon([q for q in flat if q.area > 0])


def absorb_slivers(parts: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Приливает части меньше MMU к соседней части того же контура с самой длинной общей границей."""
    parts = parts.copy()
    while len(parts) > 1:
        small = parts[parts.geometry.area < MMU_M2]
        if small.empty:
            break
        i = small.geometry.area.idxmin()
        g = parts.at[i, 'geometry']
        others = parts.drop(index=i)
        shared = others.geometry.apply(lambda o: g.boundary.intersection(o.buffer(0.01)).length)
        j = shared.idxmax() if shared.max() > 0 else others.geometry.distance(g).idxmin()
        print(f'   щепка {g.area:.1f} м2 ({parts.at[i, "cls"]}) прилита к части {parts.at[j, "cls"]}')
        parts.at[j, 'geometry'] = polygonal(unary_union([parts.at[j, 'geometry'], g]))
        parts = parts.drop(index=i)
    return parts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--layers', default='mixed_known', help='слои владельца через запятую (mixed_known, xl_candidates)')
    ap.add_argument('--force', action='store_true', help='перезаписать существующий v5')
    a = ap.parse_args()
    if OUT.exists() and not a.force:
        raise SystemExit(f'{OUT} уже есть; перезапись только с --force')
    cpu_limit.apply()
    shp = pd.concat([gpd.read_file(MS / f'{n}.shp').assign(layer=n) for n in a.layers.split(',')], ignore_index=True)
    shp['cls'] = [owner_class(p) if owner_class(p) else owner_class(n) for p, n in zip(shp['part_cls'], shp['note_own'])]
    todo = shp.groupby('id').filter(lambda x: x['cls'].notna().any())
    print(f'слои {a.layers}: объектов {len(shp)}, контуров {shp["id"].nunique()}, с классом владельца {todo["id"].nunique()}')

    g = pyogrio.read_dataframe(SRC, layer='genesis')
    g.insert(list(g.columns).index('genesis_v3e') + 1, 'genesis_v4', g['genesis'])   # класс до переноса, у всех строк
    crs, cols = g.crs, list(g.columns)
    if g['id'].duplicated().any():
        raise ValueError('в продукте повторяются id')
    if shp.crs != crs:
        raise ValueError(f'CRS слоя {shp.crs} не совпадает с продуктом {crs}')
    if g['id'].max() >= PART_ID_BASE:
        raise ValueError(f'диапазон новых id {PART_ID_BASE}+ уже занят')
    num_cols = [c for c in cols if c != 'geometry' and pd.api.types.is_numeric_dtype(g[c]) and c not in KEEP_NUMERIC]
    idx = g.set_index('id').index
    missing = sorted(set(todo['id']) - set(idx))
    if missing:
        raise ValueError(f'контуров нет в продукте: {missing}')

    next_id = PART_ID_BASE
    new_rows, log = [], []
    pos = pd.Series(np.arange(len(g)), index=g['id'])
    for cid, x in todo.groupby('id', sort=False):
        k = pos[cid]
        orig = g.iloc[k]
        x = x.copy()
        x['cls'] = x['cls'].fillna(orig['genesis'])    # пустой класс части: исходный класс
        x['geometry'] = x.geometry.apply(polygonal)
        x = absorb_slivers(gpd.GeoDataFrame(x, geometry='geometry', crs=crs)) if len(x) > 1 else x
        x = x.assign(a=x.geometry.area).sort_values('a', ascending=False)
        n_new = len(x) - 1
        a_orig = orig.geometry.area
        a_parts = unary_union(list(x.geometry)).area
        for j, (_, p) in enumerate(x.iterrows()):
            row = orig.copy()
            cls = p['cls']
            gen = 'undefined' if cls == 'not_sand' else cls
            row['genesis'] = gen
            row['genesis_main'] = MAIN.get(gen, gen)
            row['shoal_type'] = SHOAL_TYPE.get(gen)
            row['shoal_type_src'] = 'owner' if gen in SHOAL_TYPE else None
            row['step6_rule'] = RULE
            row['expert_note'] = NOTE[cls] if cls in NOTE else orig['expert_note']
            row['dispute_reason'] = 'owner' if gen == 'disputed' else None
            row['not_sand_suspect'] = 1 if cls == 'not_sand' else 0
            if n_new:
                row['geometry'] = p.geometry
                row['area_ha'] = round(p.geometry.area / 1e4, 3)
                row['area_km2'] = round(p.geometry.area / 1e6, 6)
                row['split_from'] = orig['genesis']
                for c in num_cols:          # улики целого контура к части не относятся
                    row[c] = np.nan
            if j == 0:
                row['split_n'] = (orig['split_n'] if pd.notna(orig['split_n']) else 0) + n_new
                g.iloc[k] = row
            else:
                row['id'] = next_id
                row['parent_id'] = int(cid)
                row['split_n'] = 0
                row['part_kind'] = 'owner_split'
                new_rows.append(row)
                next_id += 1
            log.append(dict(id=int(cid), part=j, new_id=int(row['id']), было=orig['genesis'], стало=gen, класс_владельца=NOTE.get(cls, cls),
                            га=round(p.geometry.area / 1e4 if n_new else a_orig / 1e4, 2)))
        if n_new and abs(a_parts - a_orig) / a_orig > 0.01:
            print(f'   внимание: {cid}: площадь частей {a_parts / 1e4:.2f} га против {a_orig / 1e4:.2f} га в продукте')

    before = pyogrio.read_dataframe(SRC, layer='genesis', columns=['genesis_main', 'area_ha'], read_geometry=False)
    if new_rows:
        g = pd.concat([g, gpd.GeoDataFrame(new_rows, crs=crs)], ignore_index=True)
    g = gpd.GeoDataFrame(g[cols], geometry='geometry', crs=crs)
    if g['id'].duplicated().any():
        raise ValueError('после переноса повторяются id')
    lg = pd.DataFrame(log)
    tb = before.groupby('genesis_main')['area_ha'].sum() / 100
    ta = g.groupby('genesis_main')['area_ha'].sum() / 100
    tab = pd.DataFrame({'v4, км2': tb, 'v5, км2': ta}).fillna(0).round(2)
    tab['изменение, км2'] = (tab['v5, км2'] - tab['v4, км2']).round(2)
    nb = before['genesis_main'].value_counts()
    na = g['genesis_main'].value_counts()
    tab['контуров v4'] = nb
    tab['контуров v5'] = na
    tab = tab.fillna(0)
    L = ['# Перенос ручного разреза смешанных контуров в продукт (132, v5)', '',
         f'Слои владельца: {a.layers}. Контуров с классом владельца: {lg["id"].nunique()}; разрезано: '
         f'{int((lg.groupby("id").size() > 1).sum())}; частей после прилива щепок: {len(lg)}; новых id: {len(new_rows)} '
         f'({PART_ID_BASE}-{next_id - 1 if new_rows else "-"}). Продукт: {len(before)} -> {len(g)} контуров.', '',
         '## Площади по основным классам', '', tab.to_markdown(), '',
         '## Контуры и части', '', lg.to_markdown(index=False)]
    if OUT.exists():
        OUT.unlink()
    pyogrio.write_dataframe(g, OUT, layer='genesis', driver='GPKG')
    for suf in ('.qml', '_main.qml'):
        shutil.copy(SRC.with_name(SRC.stem + suf), OUT.with_name(OUT.stem + suf))
    (MS / 'apply_v5.md').write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L[:8]))
    print(f'-> {OUT}')


if __name__ == '__main__':
    main()
