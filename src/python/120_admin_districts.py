"""
120_admin_districts.py - границы муниципальных районов (OSM, admin_level = 6) в пределах района работ (2026-09-27).

Нужны для таблицы распределения песков по районам во второй версии статьи (в статье 2022 г. таблица 1).
Источник: выгрузки Geofabrik exports/osm/{ural,siberian}-fed-district-latest.osm.pbf (слой multipolygons).
ВНИМАНИЕ: OGR_INTERLEAVED_READING не включать (при чтении одного слоя даёт 0 объектов).
Выход: exports/aux/admin6_aoi.gpkg (name, admin_level, geometry), только районы, пересекающие AOI.
Запуск: PYTHONIOENCODING=utf-8 python -u python/120_admin_districts.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
PBF = [ROOT / 'exports' / 'osm' / 'ural-fed-district-latest.osm.pbf', ROOT / 'exports' / 'osm' / 'siberian-fed-district-latest.osm.pbf']
AOI = ROOT / 'exports' / 'aoi_v2.geojson'
OUT = ROOT / 'exports' / 'aux' / 'admin6_aoi.gpkg'


def main() -> None:
    cpu_limit.apply()
    t0 = time.time()
    aoi = gpd.read_file(AOI).to_crs(4326)
    parts = []
    for p in PBF:
        g = pyogrio.read_dataframe(p, layer='multipolygons', columns=['name', 'admin_level', 'boundary'],
                                   where="boundary = 'administrative' AND admin_level IN ('4', '6')")
        print(f'{p.name}: {len(g)} границ уровней 4 и 6, {(time.time() - t0) / 60:.1f} мин', flush=True)
        parts.append(g)
    g = pd.concat(parts, ignore_index=True)
    g = gpd.GeoDataFrame(g, geometry='geometry', crs=4326)
    g = g[g.intersects(aoi.geometry.iloc[0])]
    g.to_file(OUT, layer='admin', driver='GPKG')
    print(g[['name', 'admin_level']].sort_values(['admin_level', 'name']).to_string())
    print(f'-> {OUT}: {len(g)} границ | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
