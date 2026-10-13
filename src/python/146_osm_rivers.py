"""
146_osm_rivers.py - реки OSM (waterway=river) для карт статьи (2026-10-12).

Читает линии waterway=river из выгрузок Geofabrik тем же способом, что 60_step3_osm_extract.py (драйвер GDAL OSM через
pyogrio, bbox района работ с запасом). Крупные реки отбираются на карте (145) по суммарной длине под одним названием.
Вход: exports/osm/ural-fed-district-latest.osm.pbf, siberian-fed-district-latest.osm.pbf.
Выход: exports/osm/osm_rivers_AOI.gpkg, слой rivers (EPSG:3576): osm_id, name, length_km.
Запуск: PYTHONIOENCODING=utf-8 python -u python/146_osm_rivers.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

OSM_DIR = Path(r'D:\test\baresand_zapsib\exports\osm')
PBF = [OSM_DIR / 'ural-fed-district-latest.osm.pbf', OSM_DIR / 'siberian-fed-district-latest.osm.pbf']
OUT = OSM_DIR / 'osm_rivers_AOI.gpkg'
EA_CRS = 'EPSG:3576'
BBOX = (56.0, 59.5, 96.0, 74.5)          # район работ (lon/lat) с запасом под рамку карты


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def main() -> None:
    t0 = time.time()
    # OGR_INTERLEAVED_READING=YES НЕ ставить (см. 60): при чтении одного слоя драйвер тогда возвращает 0 объектов
    pyogrio.set_gdal_config_options({'OSM_MAX_TMPFILE_SIZE': '8000'})
    parts = []
    for pbf in PBF:
        t = time.time()
        df = pyogrio.read_dataframe(pbf, layer='lines', bbox=BBOX, where="waterway = 'river'", columns=['osm_id', 'name'])
        log(f'{pbf.name}: {len(df):,} линий за {(time.time() - t) / 60:.1f} мин')
        parts.append(df)
    g = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs)
    g = g.drop_duplicates('osm_id').to_crs(EA_CRS)
    g['length_km'] = g.geometry.length / 1000
    g.to_file(OUT, layer='rivers', driver='GPKG')
    top = g.groupby('name')['length_km'].sum().sort_values(ascending=False)
    log(f'-> {OUT}: {len(g):,} линий, {g["length_km"].sum():,.0f} км; крупнейшие по длине: '
        + ', '.join(f'{n} {v:.0f}' for n, v in top.head(25).items()) + f' | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
