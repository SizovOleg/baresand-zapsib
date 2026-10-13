"""
151_territory.py - территория населённых пунктов, считаемая отводом в кадастровом сопоставлении (2026-10-13).

Решение автора 13.10.2026 (вариант А): класс техногенных песков v7 не меняется; в кадастровом сопоставлении (133) вся
территория населённых пунктов считается отводом, чтобы в слоях «превышение отвода» и «без отвода» не было городов,
посёлков, вахтовых посёлков, дач, аэродромов. Части территории (слой component):
- np: участки ЕГРН «земли населённых пунктов» (группа np в 133, слой parcels в exports/final/baresand_anthro_cadastre_v7.gpkg),
  замыкание CLOSE_M (улицы и проезды между участками);
- dacha_egrn: участки ЕГРН с садоводческим ВРИ (DACHA_RE) любой категории, замыкание CLOSE_M;
- residential, allotments: OSM landuse = residential / allotments (дачные массивы);
- aerodrome: OSM aeroway = aerodrome;
- camp: вахтовые посёлки «по снимку»: здания OSM (отрисованы по снимкам) без промышленных тегов (BLD_SKIP) около
  посёлков OSM (place village / hamlet / isolated_dwelling / town и названия с «вахт», «ВЖК»), где нет земель населённых
  пунктов ЕГРН; кластеры зданий с замыканием CAMP_CLOSE_M и не меньше CAMP_MIN_BLD зданий. Полигоны place OSM целиком не
  берутся: у посёлков при месторождениях они захватывают КС, базы и аэродромы (разбор 149, 12.10.2026).
Выход: exports/qc/territory/territory.gpkg (слои territory: объединение для 133 --territory; components: части с полем
component), report.md; с --review обзорные снимки review/ (части раскрашены) и index.html.
Запуск: PYTHONIOENCODING=utf-8 python -u python/151_territory.py [--review 40]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import html
import math
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
CAD = ROOT / 'exports' / 'final' / 'baresand_anthro_cadastre_v7.gpkg'
PRODUCT = ROOT / 'exports' / 'final' / 'baresand_genesis_v7.gpkg'
OSM_DIR = ROOT / 'exports' / 'osm'
PBF = [OSM_DIR / 'ural-fed-district-latest.osm.pbf', OSM_DIR / 'siberian-fed-district-latest.osm.pbf']
OSM_CACHE = OSM_DIR / 'osm_territory_AOI.gpkg'
INFRA = OSM_DIR / 'osm_infra_AOI.gpkg'
COVER = ROOT / 'exports' / 'final' / 'aoi' / 'mask_coverage_128tiles.shp'
OUT = ROOT / 'exports' / 'qc' / 'territory'
CRS = 'EPSG:3576'
BBOX = (62.0, 61.0, 90.1, 73.0)
CLOSE_M = 50.0
CAMP_CLOSE_M = 40.0
CAMP_MIN_BLD = 5
CAMP_RADIUS_M = 1500.0
CAMP_MAX_IND = 0.30
INDUSTRIAL_NAME_RE = r'УПСВ|ДНС|ЦПС|УКПГ|УППГ|КНС|(?<![а-яё])КС(?![а-яё])|площадка|промбаза|база'
DACHA_RE = r'садовод|огородн|дачн|садово-огород'
BLD_SKIP = {'industrial', 'storage_tank', 'hangar', 'roof', 'service', 'garages', 'garage', 'warehouse', 'tank',
            'silo', 'transformer_tower', 'shed', 'construction', 'ruins', 'container'}
CAMP_PLACES = ('village', 'hamlet', 'isolated_dwelling', 'town')
# промзоны городов (автор 13.10.2026: промзоны тоже исключаем): промышленные полигоны OSM (слой industrial 60-го скрипта)
# не дальше URBAN_BUF_M от земель населённых пунктов крупнее URBAN_MIN_KM2; резервуарные парки, карьеры и стройплощадки
# не берутся (бывают промысловыми). Разбор 152 (13.10.2026): крупнейшие «превышения» были промзонами на окраинах городов
URBAN_IND_KINDS = ('industrial', 'commercial', 'garages', 'railway', 'works', 'brownfield', 'depot')
URBAN_BUF_M, URBAN_MIN_KM2 = 1000.0, 1.0
COLORS = {'np': '#ff2a2a', 'dacha_egrn': '#ff7ad9', 'residential': '#ffd400', 'allotments': '#b06bff',
          'aerodrome': '#00d5ff', 'camp': '#ff8c1a', 'urban_industrial': '#ffffff'}


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def closed(geoms: gpd.GeoSeries, d: float) -> gpd.GeoSeries:
    """Замыкание: буфер наружу, объединение, буфер обратно; отдельные полигоны."""
    u = shapely.union_all(np.asarray(geoms.buffer(d, resolution=4).values))
    u = shapely.buffer(u, -d, quad_segs=4)
    return gpd.GeoSeries(shapely.get_parts(u), crs=CRS)


def osm_polys() -> gpd.GeoDataFrame:
    """OSM: жилая застройка, дачи, аэродромы, полигоны и точки населённых пунктов (кэш)."""
    if OSM_CACHE.exists():
        return gpd.read_file(OSM_CACHE, layer='osm')
    pyogrio.set_gdal_config_options({'OSM_MAX_TMPFILE_SIZE': '8000'})
    where = ("landuse IN ('residential', 'allotments') OR aeroway = 'aerodrome' OR "
             "place IN ('" + "', '".join(CAMP_PLACES + ('allotments',)) + "')")
    parts = []
    for pbf in PBF:
        d = pyogrio.read_dataframe(pbf, layer='multipolygons', bbox=BBOX, where=where,
                                   columns=['osm_id', 'osm_way_id', 'name', 'landuse', 'aeroway', 'place'])
        log(f'{pbf.name}: {len(d)} полигонов')
        parts.append(d)
    g = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs).to_crs(CRS)
    g['geometry'] = shapely.make_valid(g.geometry.values)
    g = g[g.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])]
    g['kind'] = np.select([g['aeroway'].eq('aerodrome'), g['landuse'].eq('allotments') | g['place'].eq('allotments'),
                           g['landuse'].eq('residential')], ['aerodrome', 'allotments', 'residential'], 'place')
    g = g.drop_duplicates(subset=['osm_id', 'osm_way_id', 'kind'])
    g.to_file(OSM_CACHE, layer='osm', driver='GPKG')
    return g


def camps(np_mask: gpd.GeoSeries, osm: gpd.GeoDataFrame, cover) -> gpd.GeoDataFrame:
    """Вахтовые и малые посёлки без земель НП: кластеры зданий OSM около посёлков."""
    pts = pyogrio.read_dataframe(INFRA, layer='places', columns=['place', 'name'])
    pts = pts[pts['place'].isin(CAMP_PLACES)]
    named = osm[osm['name'].fillna('').str.contains('вахт|ВЖК', case=False) | osm['kind'].eq('place')]
    seeds = pd.concat([pts[['name', 'geometry']], gpd.GeoDataFrame(named[['name']], geometry=named.geometry.representative_point(), crs=CRS)],
                      ignore_index=True)
    seeds = gpd.GeoDataFrame(seeds, geometry='geometry', crs=CRS)
    seeds = seeds[seeds.within(cover)]
    npu = np_mask.union_all()
    seeds = seeds[~seeds.geometry.buffer(300).intersects(npu)]
    log(f'посёлков-кандидатов без земель НП рядом: {len(seeds)}')
    b = pyogrio.read_dataframe(INFRA, layer='buildings', columns=['building'],
                               bbox=tuple(seeds.total_bounds + np.array([-CAMP_RADIUS_M, -CAMP_RADIUS_M, CAMP_RADIUS_M, CAMP_RADIUS_M])))
    b = b[~b['building'].isin(BLD_SKIP)]
    near = gpd.sjoin(b, gpd.GeoDataFrame(geometry=seeds.geometry.buffer(CAMP_RADIUS_M), crs=CRS), predicate='intersects', how='inner')
    b = b.loc[near.index.unique()]
    log(f'зданий около кандидатов (без промышленных тегов): {len(b)}')
    if not len(b):
        return gpd.GeoDataFrame(columns=['name', 'n_bld', 'geometry'], geometry='geometry', crs=CRS)
    cl = closed(b.geometry, CAMP_CLOSE_M)
    cl = gpd.GeoDataFrame(geometry=cl, crs=CRS)
    cnt = gpd.sjoin(gpd.GeoDataFrame(geometry=b.geometry.representative_point(), crs=CRS), cl, predicate='within').groupby('index_right').size()
    cl['n_bld'] = cnt.reindex(cl.index).fillna(0).astype(int)
    cl = cl[cl['n_bld'] >= CAMP_MIN_BLD]
    # разбор территории (13.10.2026): кластеры зданий захватывали производственные базы (ангары, склады с building=yes);
    # кластер, лежащий в промышленных полигонах OSM на CAMP_MAX_IND и больше, не считается посёлком
    ind = pyogrio.read_dataframe(INFRA, layer='industrial', columns=['kind'], bbox=tuple(cl.total_bounds))
    if len(ind):
        iu = shapely.union_all(np.asarray(ind.geometry.values))
        share = shapely.area(shapely.intersection(np.asarray(cl.geometry.values), iu)) / cl.geometry.area.to_numpy()
        log(f'кластеров зданий в промзонах OSM (>= {CAMP_MAX_IND:.0%}): {int((share >= CAMP_MAX_IND).sum())} из {len(cl)}')
        cl = cl[share < CAMP_MAX_IND]
    nm = gpd.sjoin_nearest(gpd.GeoDataFrame(geometry=cl.geometry.representative_point(), crs=CRS), seeds[['name', 'geometry']], how='left')
    cl['name'] = nm.groupby(level=0)['name'].first().reindex(cl.index)
    return cl.reset_index(drop=True)


def esri(ax, minx: float, miny: float, maxx: float, maxy: float, max_px: int = 1500) -> None:
    from PIL import Image
    from qc_thumb_xyz import R_MERC, TILE, fetch_tile, tile_xy
    z = next((z for z in range(17, 8, -1) if (maxx - minx) / (2 * R_MERC / TILE / 2 ** z) <= max_px), 9)
    tx0, ty0 = tile_xy(minx, maxy, z)
    tx1, ty1 = tile_xy(maxx, miny, z)
    X0, Y0, X1, Y1 = int(tx0), int(ty0), int(tx1), int(ty1)
    m = Image.new('RGB', ((X1 - X0 + 1) * TILE, (Y1 - Y0 + 1) * TILE))
    for X in range(X0, X1 + 1):
        for Y in range(Y0, Y1 + 1):
            m.paste(fetch_tile(z, X, Y), ((X - X0) * TILE, (Y - Y0) * TILE))
    img = m.crop((int((tx0 - X0) * TILE), int((ty0 - Y0) * TILE), int((tx1 - X0) * TILE), int((ty1 - Y0) * TILE)))
    ax.imshow(img, extent=(minx, maxx, miny, maxy), interpolation='lanczos')


def review(comp: gpd.GeoDataFrame, n: int) -> None:
    """Обзорные снимки: окна вокруг кластеров территории с наибольшей площадью техногена внутри."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    rd = OUT / 'review'
    rd.mkdir(parents=True, exist_ok=True)
    terr = gpd.GeoDataFrame(geometry=closed(comp.geometry, 300), crs=CRS)     # кластеры для окон
    tech = pyogrio.read_dataframe(PRODUCT, layer='genesis', columns=['genesis'], where="genesis = 'anthropogenic'")
    j = gpd.overlay(tech[['geometry']], comp[['geometry']].dissolve(), how='intersection')
    a = gpd.sjoin(gpd.GeoDataFrame(geometry=j.geometry.representative_point(), crs=CRS).assign(a=j.area.values), terr,
                  predicate='within').groupby('index_right')['a'].sum().sort_values(ascending=False)
    # обязательно показать все вахтовые посёлки и аэродромы, затем крупнейшие по техногену
    must = set(gpd.sjoin(terr, comp[comp['component'].isin(['camp', 'aerodrome'])], predicate='intersects').index)
    order = list(dict.fromkeys([i for i in a.index[:n]] + sorted(must)))
    items = []
    for k, i in enumerate(order, 1):
        g = terr.geometry.loc[i]
        minx, miny, maxx, maxy = g.bounds
        side = max(maxx - minx, maxy - miny, 3000) * 1.3
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        win = shapely.box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
        to = lambda s: gpd.GeoSeries(s, crs=CRS).to_crs(3857)
        w = to([win]).iloc[0]
        fig, ax = plt.subplots(figsize=(8, 8), dpi=140)
        esri(ax, *w.bounds)
        tw = tech[tech.intersects(win)]
        if len(tw):
            to(tw.geometry).boundary.plot(ax=ax, color='#3dff6e', lw=0.4)
        cw = comp[comp.intersects(win)]
        for c, col in COLORS.items():
            s = cw[cw['component'] == c]
            if len(s):
                to(s.geometry).boundary.plot(ax=ax, color=col, lw=1.1)
        ax.set_xlim(w.bounds[0], w.bounds[2])
        ax.set_ylim(w.bounds[1], w.bounds[3])
        ax.set_xticks([])
        ax.set_yticks([])
        names = cw['name'].dropna().astype(str)
        title = ', '.join(sorted(set(names))[:3]) or f'кластер {i}'
        ax.set_title(f'{title}: техноген внутри территории {a.get(i, 0) / 1e6:.2f} км²', fontsize=9)
        ax.legend(handles=[Patch(facecolor='none', edgecolor=c, label=l) for l, c in COLORS.items()] +
                  [Patch(facecolor='none', edgecolor='#3dff6e', label='техноген v7')], loc='lower right', fontsize=7)
        fn = f'{k:02d}.jpg'
        fig.savefig(rd / fn, bbox_inches='tight', pil_kwargs={'quality': 85})
        plt.close(fig)
        items.append((k, title, a.get(i, 0) / 1e6, sorted(cw['component'].unique()), fn))
    rows = ''.join(f'<h3>{k}. {html.escape(t)}</h3><p>техноген внутри территории {ar:.2f} км²; части: {", ".join(cs)}</p>'
                   f'<img src="{fn}" style="max-width:100%">' for k, t, ar, cs, fn in items)
    leg = '; '.join(f'<span style="color:{c}">■</span> {l}' for l, c in COLORS.items())
    (rd / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Территория населённых пунктов</title>'
                                   '<body style="font:15px system-ui;max-width:980px;margin:auto;padding:16px">'
                                   f'<h2>Территория населённых пунктов как отвод (151)</h2><p>{leg}; зелёный: техноген v7.</p>'
                                   + rows + '</body>', encoding='utf-8')
    log(f'-> {rd / "index.html"} ({len(items)} окон)')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--review', type=int, default=0)
    a = ap.parse_args()
    cpu_limit.apply_cores(12)
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    cover = gpd.read_file(COVER).to_crs(CRS).union_all()
    par = pyogrio.read_dataframe(CAD, layer='parcels', columns=['grp', 'vri', 'cad_num'])
    par['geometry'] = shapely.make_valid(par.geometry.values)
    npm = closed(par.loc[par['grp'].eq('np'), 'geometry'], CLOSE_M)
    dch = par[par['vri'].fillna('').str.contains(DACHA_RE, case=False, regex=True)]
    dcm = closed(dch.geometry, CLOSE_M)
    log(f'ЕГРН: np {len(npm)} полигонов {npm.area.sum() / 1e6:.1f} км²; садоводческие {len(dch)} участков -> {dcm.area.sum() / 1e6:.1f} км²')
    osm = osm_polys()
    camp = camps(npm, osm, cover)
    log(f'вахтовые и малые посёлки по зданиям: {len(camp)} кластеров, {camp.area.sum() / 1e6:.2f} км²')
    ind = pyogrio.read_dataframe(INFRA, layer='industrial', columns=['kind', 'name'])
    ind = ind[ind['kind'].isin(URBAN_IND_KINDS)]
    towns = npm[npm.area > URBAN_MIN_KM2 * 1e6]
    near = gpd.sjoin(ind, gpd.GeoDataFrame(geometry=towns.buffer(URBAN_BUF_M), crs=CRS), predicate='intersects')
    uind = ind.loc[near.index.unique()]
    log(f'промзоны городов (OSM industrial у {len(towns)} населённых пунктов): {len(uind)} полигонов, {uind.area.sum() / 1e6:.1f} км²')
    def part(name: str, geoms, names=None) -> gpd.GeoDataFrame:
        geoms = list(np.asarray(gpd.GeoSeries(geoms).values))
        nm = list(names) if names is not None else [None] * len(geoms)
        return gpd.GeoDataFrame({'component': [name] * len(geoms), 'name': nm}, geometry=geoms, crs=CRS)

    sel = {k: osm[osm['kind'].eq(k)] for k in ('residential', 'allotments', 'aerodrome')}
    # жилые полигоны OSM с названиями промысловых объектов (ошибочный тег, например «Площадка УПСВ») не берутся
    bad = sel['residential']['name'].fillna('').str.contains(INDUSTRIAL_NAME_RE, case=False, regex=True)
    log(f'жилых полигонов OSM с промысловыми названиями отброшено: {int(bad.sum())}')
    sel['residential'] = sel['residential'][~bad]
    comp = pd.concat([part('np', npm), part('dacha_egrn', dcm)]
                     + [part(k, d.geometry, d['name']) for k, d in sel.items()]
                     + [part('camp', camp.geometry, camp['name']), part('urban_industrial', uind.geometry, uind['name'])],
                     ignore_index=True)
    comp = comp[~comp.geometry.is_empty]
    comp = gpd.GeoDataFrame(comp, geometry='geometry', crs=CRS)
    terr = gpd.GeoDataFrame(geometry=shapely.get_parts(shapely.union_all(np.asarray(comp.geometry.values))), crs=CRS)
    out = OUT / 'territory.gpkg'
    if out.exists():
        out.unlink()
    pyogrio.write_dataframe(terr, out, layer='territory', driver='GPKG')
    pyogrio.write_dataframe(comp, out, layer='components', driver='GPKG')
    tab = comp.assign(km2=comp.area / 1e6).groupby('component').agg(n=('km2', 'size'), km2=('km2', 'sum'))
    tech = pyogrio.read_dataframe(PRODUCT, layer='genesis', columns=['genesis'], where="genesis = 'anthropogenic'")
    tin = gpd.overlay(tech[['geometry']], terr, how='intersection').area.sum() / 1e6
    L = ['# Территория населённых пунктов как отвод (151)', '',
         f'Объединение: {len(terr)} полигонов, {terr.area.sum() / 1e6:.1f} км²; техногенных песков v7 внутри: {tin:.1f} км².', '',
         '| Часть | полигонов | км² |', '|---|---|---|'] + [f'| {c} | {r.n} | {r.km2:.1f} |' for c, r in tab.iterrows()]
    L += ['', f'Вахтовые и малые посёлки (camp): {len(camp)} кластеров зданий OSM (не меньше {CAMP_MIN_BLD} зданий, замыкание {CAMP_CLOSE_M:g} м), '
          'около посёлков без земель населённых пунктов ЕГРН.', f'Время {(time.time() - t0) / 60:.1f} мин.']
    (OUT / 'report.md').write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))
    if a.review:
        review(comp, a.review)


if __name__ == '__main__':
    main()
