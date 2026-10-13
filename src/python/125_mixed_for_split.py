"""
125_mixed_for_split.py - шейп смешанных по генезису контуров для ручного разреза владельцем (2026-09-30).

Просьба владельца: «класс смешанные контуры - может их отдельно пройти и разрезать? можешь шейп сделать?».
DNA, инвариант 3: один контур, один генезис; смешанные делятся на части.
Слой 1 mixed_known: контуры, отмеченные как смешанные или спорные: последняя метка владельца «смешанный / спорный /
  не понять» (owner_gold), класс disputed в продукте, итог агентов «смешанный / спор трёх» (multireader), если владелец
  после этого не поставил уверенный класс.
Слой 2 xl_candidates: остальные контуры >= 100 га, которые владелец ещё не размечал (по выборке V1-V1c смешанных среди
  крупнейших около 8 %), по убыванию площади; для просмотра и разреза при необходимости.
Геометрия: make_valid (растровые контуры самокасаются; без этого разрез в QGIS даёт Ring Self-intersection).
Поля для владельца: part_cls (класс части или целого: эоловый / речная / озёрная / морская / техноген / не песок /
  смешанный), note_own (заметка). Перенос разрезов в продукт - отдельным скриптом после возврата шейпа.
Выход: exports/qc/mixed_split/mixed_known.shp, xl_candidates.shp (+ .gpkg с обоими слоями), README.md.
Запуск: PYTHONIOENCODING=utf-8 python -u python/125_mixed_for_split.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
QC = ROOT / 'exports' / 'qc'
OUT = QC / 'mixed_split'
AMBIG = {'mixed', 'disputed', 'unresolved', 'disputed3'}
RU = {'aeolian': 'эоловый', 'river_shoal': 'речная', 'lake_shoal': 'озёрная', 'shoal': 'морская', 'anthropogenic': 'техноген',
      'undefined': 'неопределённый', 'disputed': 'спорный', 'alluvial_littoral': 'отмель'}


def polygonal(geom):
    """make_valid и только полигональная часть."""
    g = make_valid(geom)
    if isinstance(g, (Polygon, MultiPolygon)):
        return g
    parts = [p for p in getattr(g, 'geoms', []) if isinstance(p, (Polygon, MultiPolygon))]
    polys = []
    for p in parts:
        polys.extend(p.geoms if isinstance(p, MultiPolygon) else [p])
    return MultiPolygon(polys) if len(polys) > 1 else (polys[0] if polys else None)


def main() -> None:
    # 2026-10-04: mixed_known.shp размечен владельцем вручную (копия mixed_known_owner_2026-10-04.*); перезапуск
    # молча затёр бы разметку, поэтому без явного --force скрипт не пишет поверх существующих слоёв
    done = [n for n in ('mixed_known', 'xl_candidates') if (OUT / f'{n}.shp').exists()]
    if done and '--force' not in sys.argv:
        raise SystemExit(f'слои {done} уже есть в {OUT} и могут содержать разметку владельца; перезапись только с --force')
    cpu_limit.apply()
    OUT.mkdir(parents=True, exist_ok=True)
    gold = pd.read_csv(QC / 'owner_click' / 'owner_gold.csv')
    order = {b: k for k, b in enumerate(['O1', 'O2', 'O3', 'O4', 'O5', 'O6', 'O7', 'O8', 'V1', 'V1b', 'V1c'])}
    gold['ord'] = gold['batch'].map(order).fillna(-1)
    last = gold.sort_values('ord').groupby('id').last()
    src: dict[int, list[str]] = {}
    for i, r in last[last['label'].isin(AMBIG)].iterrows():
        src.setdefault(int(i), []).append(f'владелец:{r["label"]}:{r["batch"]}')
    sure_owner = set(last.index[~last['label'].isin(AMBIG)])
    # уверенные решения владельца из пакетов пилота (expert_big) и owner30 тоже снимают отметку агентов
    eb = pd.read_csv(QC / 'lake' / 'big' / 'expert_big.csv')
    sure_owner |= set(eb.loc[~eb['verdict'].isin(['pending']), 'id'])
    o30 = pd.read_csv(QC / 'lake' / 'owner30' / 'owner30_compare.csv')
    sure_owner |= set(o30.loc[~o30['owner'].isin(['смешанный', 'неразрешимо']), 'id'])
    mr = pd.read_csv(QC / 'disputed' / 'multireader.csv')
    for r in mr[mr['final'].isin(AMBIG) & mr['source'].isin(['fit', 'audit', 'big'])].itertuples():
        if int(r.id) not in sure_owner:
            src.setdefault(int(r.id), []).append(f'агенты:{r.final}:{r.source}')
    g = gpd.read_file(PRODUCT, layer='genesis', columns=['id', 'genesis', 'genesis_main', 'area_ha', 'expert_note', 'dispute_reason'])
    for i in g.loc[g['genesis'] == 'disputed', 'id']:
        src.setdefault(int(i), []).append('класс спорный')
    # для слоя крупнейших исключаются все контуры, уже просмотренные на любом шаге (эталоны шагов 1-4, отложенная выборка,
    # целевая выборка шага 5, озёрный проход, пилот, ручные решения владельца)
    labelled = set(gold['id']) | set(eb['id']) | set(o30['id']) | set(mr['id'])
    for p in (QC / 'regression_step1.csv', QC / 'step2' / 'regression_step2.csv', QC / 'step3' / 'regression_step3.csv',
              QC / 'step4' / 'regression_step4.csv', QC / 'expert_overrides.csv', QC / 'final' / 'validation_sample.csv',
              QC / 'target' / 'target_sample.csv', QC / 'lake' / 'lake_fit.csv', QC / 'lake' / 'lake_audit.csv',
              QC / 'lake' / 'big' / 'big_sample.csv'):
        if p.exists():
            labelled |= set(pd.to_numeric(pd.read_csv(p, usecols=['id'])['id'], errors='coerce').dropna().astype(int))
        else:
            print(f'нет файла просмотренных: {p}', flush=True)
    # слои с вердиктами владельца прошлых шагов (разрезы оставляют исходный id у остатка контура)
    for p in ('Beach.shp', 'final/FinFin.shp', 'lake/big/owner_notsand/owner_notsand.shp', 'lake/owner30/owner30.shp',
              'step2/Rivers.shp', 'step3/Antropogen.shp', 'step3/Mixed.shp', 'step3/NSPD.shp', 'step3/NSPD_fin.shp',
              'step4/Final.shp', 'target/Check14.shp', 'undef_review/aeolian18/dem.shp', 'undef_review/river18/river18.shp'):
        f = QC / p
        if f.exists():
            ids = pd.to_numeric(gpd.read_file(f, ignore_geometry=True)['id'], errors='coerce').dropna().astype(int)
            labelled |= set(ids) | {i // 10 for i in ids if i >= 1_000_000}   # части разрезов: id*10+k
        else:
            print(f'нет слоя владельца: {f}', flush=True)
    k = g[g['id'].isin(src)].copy()
    k['src'] = k['id'].map(lambda i: '; '.join(sorted(set(src[int(i)]))))
    x = g[(g['area_ha'] >= 100) & ~g['id'].isin(labelled) & ~g['id'].isin(src)].copy()
    x['src'] = 'крупнейший >= 100 га, не размечен'
    for d, name in ((k, 'mixed_known'), (x, 'xl_candidates')):
        d['geometry'] = d.geometry.apply(polygonal)
        d = d[d.geometry.notna() & ~d.geometry.is_empty].copy()
        c = gpd.GeoSeries(d.geometry.centroid, crs=d.crs).to_crs(4326)
        d['lat'], d['lon'] = c.y.round(4), c.x.round(4)
        d['genesis'] = d['genesis'].map(lambda s: RU.get(s, s))
        d['gen_main'] = d['genesis_main'].map(lambda s: RU.get(s, s))
        d['note'] = d['expert_note'].fillna('')
        d['part_cls'] = ''
        d['note_own'] = ''
        d = d.sort_values('area_ha', ascending=False)
        cols = ['id', 'area_ha', 'genesis', 'gen_main', 'src', 'note', 'lat', 'lon', 'part_cls', 'note_own', 'geometry']
        d = d[cols]
        d.to_file(OUT / f'{name}.shp', encoding='utf-8')
        d.to_file(OUT / 'mixed_split.gpkg', layer=name, driver='GPKG')
        print(f'{name}: {len(d)} контуров, {d["area_ha"].sum() / 100:.1f} км2; по классу: '
              + ', '.join(f'{a} {b}' for a, b in d['genesis'].value_counts().items()))
        if name == 'mixed_known':
            print(d[['id', 'area_ha', 'genesis', 'src']].to_string(index=False))
    print(f'-> {OUT}')


if __name__ == '__main__':
    main()
