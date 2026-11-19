"""
156_allotment_mask.py - обобщённая маска отводов под объекты для публикации (2026-11-19, решение автора: «обобщённая
маска отводов под объекты, без атрибутики, со слиянием контуров; риск минимальный»).

Источник: слой parcels итогового кадастрового файла exports/final/baresand_anthro_cadastre_v7b.gpkg (участки ЕГРН по
сведениям НСПД ближе 60 м к техногенным пескам, 133 --territory --ezp --local-max-ha 1000). В маску идут группы,
которые редакция v7b считает отводом под объект (GROUPS_IN 133): ind (промышленные земли), vri (ВРИ под объекты в иных
категориях), ezp (части единых землепользований), np (земли населённых пунктов), terr (территория населённых пунктов
вне участков). Не идут: big (отводы крупнее 1000 га), unk, forest, agri, misc.
Обезличивание: участки сливаются (union) в сплошные массивы, атрибутов нет (ни кадастровых номеров, ни категории, ни
ВРИ, ни группы), граница упрощается на SIMPLIFY_M, куски меньше MIN_M2 удаляются.
Выход: exports/final/allotments_generalized_v7b.gpkg, слой allotments (EPSG:3576, одно поле src) и отчёт
exports/qc/app_stats/allotments_report.md. Загрузка в GEE: 150 --layer allotments.
Запуск: PYTHONIOENCODING=utf-8 python -u python/156_allotment_mask.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyogrio
import shapely

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
SRC = ROOT / 'exports' / 'final' / 'baresand_anthro_cadastre_v7b.gpkg'
OUT = ROOT / 'exports' / 'final' / 'allotments_generalized_v7b.gpkg'
REPORT = ROOT / 'exports' / 'qc' / 'app_stats' / 'allotments_report.md'
GROUPS_IN = ('ind', 'vri', 'ezp', 'np', 'terr')
SIMPLIFY_M = 10.0
MIN_M2 = 900.0


def main() -> None:
    cpu_limit.apply()
    t0 = time.time()
    p = pyogrio.read_dataframe(SRC, layer='parcels', columns=['grp'])
    p = p[p['grp'].isin(GROUPS_IN)]
    n_in = len(p)
    area_in = float(p.geometry.area.sum()) / 1e6
    geom = shapely.make_valid(p.geometry.values)
    # слияние по связным группам касающихся участков: много мелких объединений вместо одного огромного (быстро)
    tree = shapely.STRtree(geom)
    a, b = tree.query(geom, predicate='intersects')
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    n = len(geom)
    _, lab = connected_components(coo_matrix((np.ones(len(a), dtype=np.int8), (a, b)), shape=(n, n)), directed=False)
    pieces = []
    order = np.argsort(lab, kind='stable')
    bounds = np.flatnonzero(np.diff(lab[order])) + 1
    for grp in np.split(order, bounds):
        pieces.append(geom[grp[0]] if len(grp) == 1 else shapely.union_all(geom[grp]))
    parts = gpd.GeoSeries(pieces, crs=p.crs).explode(index_parts=False).reset_index(drop=True)
    parts = parts[parts.geom_type.isin(['Polygon', 'MultiPolygon'])]
    parts = parts.simplify(SIMPLIFY_M, preserve_topology=True)
    parts = parts[~parts.is_empty & (parts.area >= MIN_M2)]
    g = gpd.GeoDataFrame({'src': ['ЕГРН (НСПД), обобщено'] * len(parts)}, geometry=parts.values, crs=p.crs)
    OUT.unlink(missing_ok=True)
    g.to_file(OUT, layer='allotments', driver='GPKG')
    area_out = float(g.geometry.area.sum()) / 1e6
    L = ['# Обобщённая маска отводов под объекты (python/156_allotment_mask.py)', '',
         f'Источник: {SRC.name}, слой parcels (участки ЕГРН ближе 60 м к техногенным пескам), группы {", ".join(GROUPS_IN)}.',
         '', f'- участков в маске: {n_in}, их суммарная площадь {area_in:,.1f} км² (с наложениями)'.replace(',', ' '),
         f'- после слияния и упрощения на {SIMPLIFY_M:g} м: {len(g)} массивов, {area_out:,.1f} км²'.replace(',', ' '),
         f'- куски меньше {MIN_M2:g} м² удалены; атрибутов нет (поле src с указанием источника)',
         f'- время {time.time() - t0:.0f} с']
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
