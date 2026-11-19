"""
155_app_stats.py - статистика для правого блока мини-приложения (2026-11-19, по просьбе автора: «справа динамичный
блок со статистикой и графиками по районам, по месторождениям»).

Район контура определяется по центроиду, как в 130 (границы OSM admin_level 6 из exports/aux/admin6_aoi.gpkg, города
окружного значения присоединены к району с самой длинной общей границей). Восточный сектор: часть района работ вне
районов OSM восточнее 79° в. д. (границы Таймырского Долгано-Ненецкого района в выгрузке OSM нет). Центроиды вне
районов западнее 79° в. д. (акватории) идут в строку «вне районов» и в итог, но не в рейтинг.
Источники: итоговый слой exports/final/baresand_genesis_v7b.gpkg (классы v7 и возраст поверхности age2000) и
кадастровые группы v7b exports/final/baresand_anthro_cadastre_v7b.gpkg (anthro_in, anthro_exceed, anthro_noallot;
площади частей и объектов, как в легенде приложения).
Выход (exports/qc/app_stats/):
  districts.gpkg  - границы районов для приложения (упрощение 500 м, EPSG:4326) с площадями, загружается 150
                    (--layer districts);
  stats.json      - сводка по районам, широтным поясам 1° и итог; вписывается в repo/gee_app/baresand_app.js между
                    метками STATS-BEGIN и STATS-END (--write-app);
  fields_stats.csv - пески по месторождениям (oilfields/Efield_region.shp, по центроиду); только локально: источник и
                    лицензия слоя месторождений не выяснены, в публичное приложение не идёт до решения автора;
  report.md       - таблицы для проверки.
Запуск: PYTHONIOENCODING=utf-8 python -u python/155_app_stats.py [--write-app]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
GEN = ROOT / 'exports' / 'final' / 'baresand_genesis_v7b.gpkg'
CAD = ROOT / 'exports' / 'final' / 'baresand_anthro_cadastre_v7b.gpkg'
ADMIN = ROOT / 'exports' / 'aux' / 'admin6_aoi.gpkg'
AOI = ROOT / 'exports' / 'final' / 'aoi' / 'baresand_aoi_v2.shp'
FIELDS = ROOT / 'oilfields' / 'Efield_region.shp'
OUT = ROOT / 'exports' / 'qc' / 'app_stats'
APP = ROOT / 'repo' / 'gee_app' / 'baresand_app.js'
EAST_LON = 79.0
EAST_NAME = 'Восточный сектор (Таймыр)'
OUTSIDE = 'вне районов'
CLASSES = ['aeolian', 'river_shoal', 'lake_shoal', 'shoal', 'anthropogenic', 'undefined']
SIMPLIFY_M = 500.0


def districts() -> gpd.GeoDataFrame:
    """Районы OSM в EPSG:3576 с присоединёнными городами и восточный сектор (часть района работ вне районов)."""
    adm = gpd.read_file(ADMIN, layer='admin')
    d6 = adm[(adm['admin_level'].astype(str) == '6') & adm['name'].notna()].to_crs(3576).dissolve(by='name').reset_index()
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
    d = d6.dissolve(by='district').reset_index()[['district', 'geometry']]
    aoi = gpd.read_file(AOI).to_crs(3576).union_all()
    rest = aoi.difference(d.union_all())
    east_box = gpd.GeoSeries([shapely.box(EAST_LON, 40, 120, 85)], crs=4326).to_crs(3576).iloc[0]
    east = rest.intersection(east_box)
    d = pd.concat([d, gpd.GeoDataFrame({'district': [EAST_NAME]}, geometry=[east], crs=3576)], ignore_index=True)
    d['geometry'] = d.geometry.intersection(aoi)
    return d[~d.geometry.is_empty].reset_index(drop=True)


def assign(pts: gpd.GeoDataFrame, d: gpd.GeoDataFrame) -> pd.Series:
    """Район каждой точки (центроида); вне районов: OUTSIDE."""
    j = gpd.sjoin(pts[['geometry']], d[['district', 'geometry']], how='left', predicate='within')
    j = j[~j.index.duplicated()]
    return j['district'].reindex(pts.index).fillna(OUTSIDE)


def centroids(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(g.drop(columns='geometry'), geometry=g.geometry.centroid, crs=g.crs).to_crs(3576)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--write-app', action='store_true', help='вписать stats.json в baresand_app.js (STATS-BEGIN/END)')
    a = ap.parse_args()
    cpu_limit.apply()
    OUT.mkdir(parents=True, exist_ok=True)
    d = districts()
    print('районов:', len(d))

    g = pyogrio.read_dataframe(GEN, layer='genesis', columns=['id', 'genesis', 'area_ha', 'age2000'])
    gc = centroids(g)
    gc['district'] = assign(gc, d)
    gc['lat'] = gc.geometry.to_crs(4326).y
    gc['km2'] = gc['area_ha'] / 100

    cls = gc.pivot_table(index='district', columns='genesis', values='km2', aggfunc='sum').reindex(columns=CLASSES).fillna(0)
    cnt = gc.groupby('district').size().rename('n')
    an = gc[gc['genesis'] == 'anthropogenic']
    age = an.pivot_table(index='district', columns='age2000', values='km2', aggfunc='sum').fillna(0)
    age = age.reindex(columns=['new', 'mid', 'old', 'na']).fillna(0).add_prefix('age_')

    cad = {}
    for lyr, key in (('anthro_in', 'cad_in'), ('anthro_exceed', 'cad_exceed'), ('anthro_noallot', 'cad_noallot')):
        c = pyogrio.read_dataframe(CAD, layer=lyr, columns=['id'])
        c['km2'] = c.geometry.area / 1e6
        cc = centroids(c)
        cc['district'] = assign(cc, d)
        cad[key] = cc.groupby('district')['km2'].sum()
        if key == 'cad_noallot':
            cad['cad_noallot_n'] = cc.groupby('district').size()
    cad = pd.DataFrame(cad).fillna(0)

    t = cls.join(cnt).join(age).join(cad).fillna(0)
    d['area_km2'] = d.geometry.area / 1e6
    t = t.join(d.set_index('district')['area_km2']).fillna({'area_km2': 0})
    t['sand_km2'] = t[CLASSES].sum(axis=1)
    t['sand_share'] = np.where(t['area_km2'] > 0, 100 * t['sand_km2'] / t['area_km2'].replace(0, np.nan), 0)
    t = t.sort_values('sand_km2', ascending=False)

    lat = gc.assign(band=np.floor(gc['lat']).astype(int)).pivot_table(index='band', columns='genesis', values='km2',
                                                                       aggfunc='sum').reindex(columns=CLASSES).fillna(0)

    def rec(row: pd.Series) -> dict:
        return {k: (round(float(v), 2) if isinstance(v, (float, np.floating)) else int(v)) for k, v in row.items()}

    def label(n: str) -> str:
        # короткая подпись: без «муниципальный округ»
        n = re.sub(r'^муниципальный округ ', '', n)
        return re.sub(r' муниципальный округ$', ' округ', n)

    stats = {
        'version': 'genesis v7 (06.10.2026), cadastre v7b (03.11.2026); python/155_app_stats.py',
        'total': rec(t.drop(columns=['area_km2', 'sand_share']).sum()),
        'districts': [{'name': n, 'label': label(n), **rec(r)} for n, r in t.iterrows()],
        'lat': [{'band': int(b), **rec(r)} for b, r in lat.iterrows()],
    }
    (OUT / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding='utf-8')

    dd = d.merge(t[['sand_km2', 'aeolian', 'anthropogenic', 'n']].reset_index(), on='district', how='left').fillna(0)
    dd['geometry'] = dd.geometry.simplify(SIMPLIFY_M)
    dd = dd.rename(columns={'district': 'name'}).to_crs(4326)
    dd['label'] = [label(n) for n in dd['name']]
    dd['geometry'] = shapely.make_valid(dd.geometry.values)
    dd.to_file(OUT / 'districts.gpkg', layer='districts', driver='GPKG')

    # месторождения: только локально (лицензия слоя не выяснена)
    if FIELDS.exists():
        f = gpd.read_file(FIELDS, encoding='cp1251').set_crs(4326, allow_override=True).to_crs(3576)
        f['geometry'] = shapely.make_valid(f.geometry.values)
        f = f[f.intersects(gpd.read_file(AOI).to_crs(3576).union_all())]
        j = gpd.sjoin(gc[['genesis', 'km2', 'geometry']], f[['NUMBER_1', 'TYPE_1', 'STAGES_1', 'geometry']],
                      how='inner', predicate='within')
        fs = j.pivot_table(index=['NUMBER_1', 'TYPE_1', 'STAGES_1'], columns='genesis', values='km2', aggfunc='sum')
        fs = fs.reindex(columns=CLASSES).fillna(0).round(3)
        fs['sand_km2'] = fs.sum(axis=1)
        fs.sort_values('anthropogenic', ascending=False).to_csv(OUT / 'fields_stats.csv', encoding='utf-8')
        print('месторождений с песками:', len(fs))

    L = ['# Статистика для мини-приложения (python/155_app_stats.py)', '', stats['version'], '',
         t.round(2).to_markdown(), '', '## Широтные пояса, км²', '', lat.round(2).to_markdown()]
    (OUT / 'report.md').write_text('\n'.join(L), encoding='utf-8')
    tot = stats['total']
    print('итог, км²:', {k: tot[k] for k in CLASSES + ['sand_km2', 'cad_in', 'cad_exceed', 'cad_noallot']})

    if a.write_app:
        src = APP.read_text(encoding='utf-8')
        block = ('// STATS-BEGIN (python/155_app_stats.py --write-app; не править вручную)\nvar STATS = ' +
                 json.dumps(stats, ensure_ascii=False, separators=(',', ':')) + ';\n// STATS-END')
        new, n = re.subn(r'// STATS-BEGIN.*?// STATS-END', lambda m: block, src, count=1, flags=re.S)
        if n != 1:
            raise SystemExit('метки STATS-BEGIN/STATS-END в приложении не найдены')
        APP.write_text(new, encoding='utf-8')
        print('STATS вписан в', APP)


if __name__ == '__main__':
    main()
