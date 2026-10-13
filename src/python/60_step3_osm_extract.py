"""
60_step3_osm_extract.py — извлечение инфраструктуры OSM для шага 3 (антропоген) из выгрузок Geofabrik.

Вход:  exports/osm/ural-fed-district-latest.osm.pbf, siberian-fed-district-latest.osm.pbf
       (ЯНАО и ХМАО — Уральский ФО; Красноярский край (Гыдан, Енисей) — Сибирский ФО). Скачать:
       curl -L -o exports/osm/<name>-latest.osm.pbf https://download.geofabrik.de/russia/<name>-latest.osm.pbf
Выход: exports/osm/osm_infra_AOI.gpkg (EPSG:3576), слои:
       roads      — highway=* (линии) с классом (major/minor/track/path/other)
       rail       — railway=* (линии)
       linear     — man_made=pipeline, power=line/minor_line, aeroway (линии)
       industrial — полигоны: landuse industrial/quarry/construction/landfill/military/depot/garages/railway,
                    man_made=*, aeroway=*, power=plant/substation, amenity=fuel/waste_*
       buildings  — building=* (полигоны)
       places     — place=* (точки) с населением, если есть
Читается драйвером GDAL OSM через pyogrio с bbox AOI; OSM_MAX_TMPFILE_SIZE поднят, чтобы индекс узлов жил в памяти
(каждый слой — отдельный проход по файлу, ~1–5 мин).
Запуск: python -u python/60_step3_osm_extract.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
OSM_DIR = EXPORTS / 'osm'
PBF = [OSM_DIR / 'ural-fed-district-latest.osm.pbf', OSM_DIR / 'siberian-fed-district-latest.osm.pbf']
OUT = OSM_DIR / 'osm_infra_AOI.gpkg'
EA_CRS = 'EPSG:3576'
BBOX = (62.0, 61.0, 90.1, 73.0)          # AOI (lon/lat) с запасом

MAJOR = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'motorway_link', 'trunk_link', 'primary_link',
         'secondary_link', 'tertiary_link'}
MINOR = {'unclassified', 'residential', 'service', 'living_street', 'road'}
TRACK = {'track', 'winter_road', 'ice_road'}
PATH = {'path', 'footway', 'cycleway', 'bridleway', 'steps', 'pedestrian'}
IND_LANDUSE = {'industrial', 'quarry', 'construction', 'landfill', 'military', 'depot', 'garages', 'railway',
               'brownfield', 'port', 'commercial', 'retail'}
IND_MAN_MADE_SKIP = {'pipeline', 'cutline', 'embankment', 'dyke'}     # линии — не полигоны площадок


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def tag(other_tags: pd.Series, key: str) -> pd.Series:
    """Значение ключа из строки other_tags вида "k"=>"v","k2"=>"v2"."""
    return other_tags.fillna('').str.extract(rf'"{key}"=>"([^"]*)"')[0]


def read(pbf: Path, layer: str, where: str | None = None) -> gpd.GeoDataFrame:
    t = time.time()
    df = pyogrio.read_dataframe(pbf, layer=layer, bbox=BBOX, where=where)
    log(f'  {pbf.name} / {layer}: {len(df):,} объектов за {(time.time() - t) / 60:.1f} мин')
    return df


def main() -> None:
    t0 = time.time()
    # OGR_INTERLEAVED_READING=YES НЕ ставить: при чтении одного слоя драйвер тогда возвращает 0 объектов
    pyogrio.set_gdal_config_options({'OSM_MAX_TMPFILE_SIZE': '8000'})
    for p in PBF:
        if not p.exists():
            sys.exit(f'нет файла {p}')
    out = {k: [] for k in ('roads', 'rail', 'linear', 'industrial', 'buildings', 'places')}
    for pbf in PBF:
        log(f'{pbf.name}: линии...')
        ln = read(pbf, 'lines')
        hw = ln[ln['highway'].notna()].copy()
        hw['cls'] = 'other'
        hw.loc[hw['highway'].isin(MAJOR), 'cls'] = 'major'
        hw.loc[hw['highway'].isin(MINOR), 'cls'] = 'minor'
        hw.loc[hw['highway'].isin(TRACK), 'cls'] = 'track'
        hw.loc[hw['highway'].isin(PATH), 'cls'] = 'path'
        hw['surface'] = tag(hw['other_tags'], 'surface')
        hw['winter'] = tag(hw['other_tags'], 'winter_road').notna() | tag(hw['other_tags'], 'ice_road').notna()
        out['roads'].append(hw[['osm_id', 'highway', 'cls', 'surface', 'winter', 'name', 'geometry']])
        rl = ln[ln['railway'].notna()]
        out['rail'].append(rl[['osm_id', 'railway', 'name', 'geometry']])
        power = tag(ln['other_tags'], 'power')
        aero = tag(ln['other_tags'], 'aeroway')
        lin = ln[(ln['man_made'] == 'pipeline') | power.isin(['line', 'minor_line', 'cable']) | aero.notna()].copy()
        lin['kind'] = 'pipeline'
        lin.loc[power.reindex(lin.index).isin(['line', 'minor_line', 'cable']), 'kind'] = 'power'
        lin.loc[aero.reindex(lin.index).notna(), 'kind'] = 'aeroway'
        out['linear'].append(lin[['osm_id', 'kind', 'name', 'geometry']])
        del ln

        log(f'{pbf.name}: полигоны...')
        pg = read(pbf, 'multipolygons')
        power_p = tag(pg['other_tags'], 'power')
        ind = pg[pg['landuse'].isin(IND_LANDUSE) | (pg['man_made'].notna() & ~pg['man_made'].isin(IND_MAN_MADE_SKIP))
                 | pg['aeroway'].notna() | power_p.isin(['plant', 'substation', 'generator'])
                 | pg['amenity'].isin(['fuel', 'waste_disposal', 'waste_transfer_station', 'recycling'])
                 | pg['military'].notna()].copy()
        ind['kind'] = ind['landuse'].fillna(ind['man_made']).fillna(ind['aeroway']).fillna(power_p.reindex(ind.index)).fillna(
            ind['amenity']).fillna(ind['military']).fillna('other')
        out['industrial'].append(ind[['osm_id', 'osm_way_id', 'kind', 'name', 'geometry']])
        bl = pg[pg['building'].notna()]
        out['buildings'].append(bl[['osm_id', 'osm_way_id', 'building', 'geometry']])
        del pg

        log(f'{pbf.name}: точки (place)...')
        pt = read(pbf, 'points', where="place IS NOT NULL")
        pt = pt.copy()
        pt['population'] = pd.to_numeric(tag(pt['other_tags'], 'population'), errors='coerce')
        out['places'].append(pt[['osm_id', 'place', 'name', 'population', 'geometry']])

    if OUT.exists():
        OUT.unlink()
    for layer, parts in out.items():
        gdf = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs='EPSG:4326').to_crs(EA_CRS)
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
        gdf.to_file(OUT, layer=layer, driver='GPKG')
        log(f'слой {layer}: {len(gdf):,} объектов')
        if layer == 'roads':
            print(gdf['cls'].value_counts().to_string())
        if layer == 'industrial':
            print(gdf['kind'].value_counts().head(15).to_string())
    log(f'сохранено {OUT} | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
