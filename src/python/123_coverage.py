"""
123_coverage.py - фактическое покрытие маски: объединение 128 обработанных тайлов MGRS внутри района работ (2026-09-27).

Список тайлов: PROCESSED_TILES в python/22_run_mosaic.py. След тайла: объединение следов сцен Sentinel-2 L2A этого тайла
за июль-август 2024 г. (до 40 сцен; разные орбиты дополняют друг друга до полного квадрата тайла).
Выход: exports/aux/coverage_tiles.gpkg (след по тайлам и объединение внутри AOI) и площадь, км2.
Запуск: PYTHONIOENCODING=utf-8 python -u python/123_coverage.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import re
from pathlib import Path

import geopandas as gpd
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(r'D:\test\baresand_zapsib')
AOI = ROOT / 'exports' / 'aoi_v2.geojson'
OUT = ROOT / 'exports' / 'aux' / 'coverage_tiles.gpkg'


def tiles() -> list[str]:
    s = (ROOT / 'python' / '22_run_mosaic.py').read_text(encoding='utf-8')
    m = re.search(r"PROCESSED_TILES = \[(.*?)\]", s, re.S)
    return re.findall(r"'(\d{2}[A-Z]{3})_+'", m.group(1))


def main() -> None:
    import ee
    try:
        ee.Initialize()
    except Exception:
        ee.Initialize(project='ee-ntcomz18')
    ts = tiles()
    col = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterDate('2024-07-01', '2024-09-01')
           .filter(ee.Filter.inList('MGRS_TILE', ts)))
    rows = []
    for k in range(0, len(ts), 16):
        part = ts[k:k + 16]
        fc = ee.FeatureCollection([ee.Feature(col.filter(ee.Filter.eq('MGRS_TILE', t)).limit(40).geometry().dissolve(100), {'tile': t})
                                   for t in part])
        info = fc.getInfo()
        for f in info['features']:
            rows.append({'tile': f['properties']['tile'], 'geometry': shape(f['geometry'])})
        print(f'  {min(k + 16, len(ts))}/{len(ts)}', flush=True)
    g = gpd.GeoDataFrame(rows, geometry='geometry', crs=4326)
    aoi = gpd.read_file(AOI).to_crs(4326)
    cov = unary_union(g.geometry.buffer(0)).intersection(aoi.geometry.iloc[0])
    cg = gpd.GeoDataFrame({'what': ['coverage_in_aoi']}, geometry=[cov], crs=4326)
    g.to_file(OUT, layer='tiles', driver='GPKG')
    cg.to_file(OUT, layer='coverage', driver='GPKG')
    a_cov = cg.to_crs(3576).area.iloc[0] / 1e6
    a_aoi = aoi.to_crs(3576).area.iloc[0] / 1e6
    print(f'тайлов {len(g)}; покрытие внутри AOI {a_cov:,.0f} км2 из {a_aoi:,.0f} ({a_cov / a_aoi:.1%}); -> {OUT}')


if __name__ == '__main__':
    main()
