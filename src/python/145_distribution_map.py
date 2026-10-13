"""
145_distribution_map.py - карта распространения песков в стиле рис. 1 статьи 2022 г. (2026-10-12).

Образец: О.С. Сизов, «Геодезия и картография», 2022, № 8, рис. 1 «Распространение оголённых эоловых песков на севере
Западной Сибири (суммарная площадь)». По просьбе автора: отдельные карты по классам итогового слоя v7 (эоловые, затем
техногенные), только суммарная площадь.
Показатель «суммарная площадь, га/км²», два способа (--method):
- centroid (по умолчанию, способ 2022 г. по описанию автора): площадь каждого контура целиком относится к ячейке растра
  (по умолчанию 250 м), в которой лежит его центроид; сумма га в ячейке делится на площадь ячейки. Значения больше 100
  возможны (крупный контур в одной ячейке). Шкала 2022 г. При ячейке 250 м минимальный контур (900 м²) даёт 1,44 га/км²,
  поэтому первые два класса шкалы пусты. Для рисунка ячейки мельче пикселя печати (около 1,3 км при 300 dpi) сводятся
  по максимуму; полный растр сохраняется в exports/figures/density_*.tif для ArcMap;
- intersect: площадь класса в ячейке (10 км) по ПЕРЕСЕЧЕНИЮ контуров с ячейками, отнесённая к площади ячейки (доля).
Ячейки с плотностью ниже нижней границы шкалы входят в первый класс («до 0,1»).
Подложка: ALOS AW3D30 v4.1 (E:/DEM/AW3D30, обзорный уровень около 1 км), серая шкала 0 -> > 200 м; граница района работ;
полосы вне покрытия маски (при подборе эталонов песков не обнаружено); границы месторождений (oilfields/Efield_region, только на карте техногенных песков);
крупные реки OSM (waterway=river из 146, список RIVERS_MAJOR) и автодороги OSM (highway trunk/primary), города.
Шкала intersect: ступени 2022 г. к доле площади ячейки не подходят (максимум около 24 га/км² при ячейке 10 км), поэтому
ступени подобраны под распределение ячеек. Цвета в обоих способах взяты с рис. 1 2022 г.
Выход: docs/article_v2/fig_distr_<класс>_<способ>_<ячейка>m.tif (300 dpi, LZW) и .png (просмотр, тот же dpi);
exports/figures/distr_*_cells.csv (ячейки) и density_*.tif (растр плотности в проекции карты).
Запуск: PYTHONIOENCODING=utf-8 python -u python/145_distribution_map.py --cls aeolian [--method centroid --cell 250]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import time
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use('Agg')
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyogrio
import rasterio
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon as MplPolygon, Rectangle
from pyproj import CRS, Transformer
from rasterio.warp import Resampling, reproject
from shapely.geometry import Point, box

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
PRODUCT = ROOT / 'exports' / 'final' / 'baresand_genesis_v7.gpkg'
AOI = ROOT / 'exports' / 'final' / 'aoi' / 'baresand_aoi_v2.shp'
COVER = ROOT / 'exports' / 'final' / 'aoi' / 'mask_coverage_128tiles.shp'
FIELDS = ROOT / 'oilfields' / 'Efield_region.shp'
OSM = ROOT / 'exports' / 'osm' / 'osm_infra_AOI.gpkg'
RIVERS = ROOT / 'exports' / 'osm' / 'osm_rivers_AOI.gpkg'      # 146: OSM waterway=river
DEM = Path(r'E:\DEM\AW3D30\AW3D30_v41.tif')
OUT = ROOT / 'docs' / 'article_v2'

# равновеликая коническая проекция, осевой меридиан 75° в. д. (как на карте 2022 г.)
PROJ = '+proj=aea +lat_0=66 +lon_0=75 +lat_1=63 +lat_2=70 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs'
CELL_DEFAULT = {'intersect': 10_000.0, 'centroid': 10_000.0}    # м (250 м и 1 км для печати мелко, автор 2026-10-12)
NOSAND_LABEL = {'aeolian': 'Эоловых песков\nне выявлено'}   # подпись полос вне покрытия маски (автор 13.10.2026)
FIELDS_FOR = {'anthropogenic'}   # границы месторождений только на карте техногенных песков (автор)
DEM_RES = 1000.0
DEM_OVR = 4                      # обзорный уровень AW3D30: 2^(4+1) = 32 пикселя по 1" (около 1 км)
DEM_MAX = 200.0
PAD = 30_000.0
PAD_RIGHT = 110_000.0          # справа шире: внутри рамки внизу справа стоит шкала высот (автор)
RIVERS_MAJOR = ['Обь', 'Малая Обь', 'Енисей', 'Таз', 'Пур', 'Пякупур', 'Айваседапур', 'Надым', 'Полуй', 'Казым',
                'Мессояха', 'Юрибей', 'Щучья', 'Танама', 'Турухан', 'Вах', 'Аган', 'Тромъёган']
RIVER_BIG = {'Обь', 'Малая Обь', 'Енисей'}
# шкалы: '2022' (ступени рис. 1 2022 г.) и 'share' (ступени под ячейки 5-10 км, где плотность не выше ~25-30 га/км²)
SCALES = {
    'share': ([0, 0.1, 0.5, 1, 2.5, 5, 10, 100],
                  ['до 0,1', '0,11-0,5', '0,51-1', '1,1-2,5', '2,6-5', '5,1-10', 'более 10'],
                  ['#5f7fa6', '#8fb2da', '#b8c7c6', '#e4e9bd', '#fcd99c', '#f6a677', '#e8664a']),
    '2022': ([0.01, 0.1, 1, 5, 10, 25, 50, 100, np.inf],
                 ['0,01-0,1', '0,11-1', '1,1-5', '5,1-10', '10,1-25', '25,1-50', '50,1-100', '>100'],
                 ['#5f7fa6', '#8fb2da', '#b8c7c6', '#e4e9bd', '#fcd99c', '#f6a677', '#e8664a', '#d7301f']),
}   # цвета рис. 1 2022 г.
DISPLAY_DPI = 300
FIGS = ROOT / 'exports' / 'figures'
INK, GREY = '#1e1e1e', '#555555'
AOI_C, FIELD_C, RIVER_C, ROAD_C = '#e8e8e8', '#7ee05a', '#a9d4f0', '#2b2b2b'
TITLES = {'aeolian': 'эоловые пески', 'anthropogenic': 'техногенные пески'}
CITIES = [('Салехард', 66.53, 66.61), ('Надым', 65.53, 72.52), ('Новый Уренгой', 66.08, 76.68), ('Ноябрьск', 63.20, 75.45),
          ('Тазовский', 67.47, 78.72), ('Сабетта', 71.27, 72.07), ('Сургут', 61.25, 73.40)]
# подписи рек: название, точка (широта, долгота), по которой берётся направление линии
RIVER_NAMES = {'Обь': (64.6, 65.4), 'Надым': (64.75, 71.7), 'Пур': (66.75, 77.95), 'Таз': (66.9, 81.5), 'Енисей': (64.8, 87.4)}


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def centroid_density(g: gpd.GeoDataFrame, cell: float) -> pd.DataFrame:
    """Способ 2022 г.: площадь каждого контура целиком в ячейку его центроида; га/км² = сумма га / площадь ячейки км²."""
    c = g.geometry.centroid
    d = pd.DataFrame({'ix': np.floor(c.x / cell).astype(int), 'iy': np.floor(c.y / cell).astype(int),
                      'km2': (g.geometry.area / 1e6).to_numpy()})
    d = d.groupby(['ix', 'iy'], as_index=False)['km2'].sum()
    d['ha_per_km2'] = d['km2'] * 100 / (cell * cell / 1e6)
    return d


def display_grid(c: pd.DataFrame, cell: float, disp: float) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Сетка для рисунка: ячейки мельче пикселя печати (disp) сводятся по максимуму, иначе рисуются как есть."""
    if cell >= disp:
        jx, jy, size, v = c['ix'].to_numpy(), c['iy'].to_numpy(), cell, c['ha_per_km2']
    else:
        jx = np.floor((c['ix'].to_numpy() + 0.5) * cell / disp).astype(int)
        jy = np.floor((c['iy'].to_numpy() + 0.5) * cell / disp).astype(int)
        m = pd.DataFrame({'jx': jx, 'jy': jy, 'v': c['ha_per_km2'].to_numpy()}).groupby(['jx', 'jy'], as_index=False)['v'].max()
        jx, jy, size, v = m['jx'].to_numpy(), m['jy'].to_numpy(), disp, m['v']
    x0, y0 = jx.min(), jy.min()
    grid = np.full((jy.max() - y0 + 1, jx.max() - x0 + 1), np.nan)
    grid[jy - y0, jx - x0] = v
    return grid, (x0 * size, (jx.max() + 1) * size, y0 * size, (jy.max() + 1) * size)


def save_raster(c: pd.DataFrame, cell: float, crs: CRS, path: Path) -> None:
    """Растр плотности (га/км², 0 = нет песков) в проекции карты, для ArcMap."""
    x0, y0 = c['ix'].min(), c['iy'].min()
    nx, ny = c['ix'].max() - x0 + 1, c['iy'].max() - y0 + 1
    arr = np.zeros((ny, nx), dtype='float32')
    arr[ny - 1 - (c['iy'] - y0), c['ix'] - x0] = c['ha_per_km2']
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, 'w', driver='GTiff', width=nx, height=ny, count=1, dtype='float32', crs=crs.to_wkt(),
                       transform=rasterio.transform.from_origin(x0 * cell, (y0 + ny) * cell, cell, cell), nodata=0,
                       compress='lzw', tiled=True) as dst:
        dst.write(arr, 1)


def cell_density(g: gpd.GeoDataFrame, CELL: float) -> pd.DataFrame:
    """Площадь контуров в ячейках CELL x CELL по пересечению, км²; плотность га/км² = км² * 100 / площадь ячейки."""
    b = g.geometry.bounds
    ix0, ix1 = np.floor(b['minx'] / CELL).astype(int), np.floor((b['maxx'] - 1e-6) / CELL).astype(int)
    iy0, iy1 = np.floor(b['miny'] / CELL).astype(int), np.floor((b['maxy'] - 1e-6) / CELL).astype(int)
    single = ((ix0 == ix1) & (iy0 == iy1)).to_numpy()
    area = (g.geometry.area / 1e6).to_numpy()
    parts = [pd.DataFrame({'ix': ix0[single], 'iy': iy0[single], 'km2': area[single]})]
    rows = []
    for k in np.flatnonzero(~single):
        geom = g.geometry.iloc[k]
        for ix in range(ix0.iloc[k], ix1.iloc[k] + 1):
            for iy in range(iy0.iloc[k], iy1.iloc[k] + 1):
                a = geom.intersection(box(ix * CELL, iy * CELL, (ix + 1) * CELL, (iy + 1) * CELL)).area / 1e6
                if a > 0:
                    rows.append((ix, iy, a))
    parts.append(pd.DataFrame(rows, columns=['ix', 'iy', 'km2']))
    log(f'контуров в одной ячейке {int(single.sum())}, на границах ячеек {int((~single).sum())}')
    c = pd.concat(parts, ignore_index=True).groupby(['ix', 'iy'], as_index=False)['km2'].sum()
    c['ha_per_km2'] = c['km2'] * 100 / (CELL * CELL / 1e6)
    return c


def dem_grid(extent: tuple[float, float, float, float], crs: CRS) -> np.ndarray:
    """AW3D30 на сетке карты (DEM_RES), NaN вне данных."""
    x0, x1, y0, y1 = extent
    w, h = int(np.ceil((x1 - x0) / DEM_RES)), int(np.ceil((y1 - y0) / DEM_RES))
    dst = np.full((h, w), np.nan, dtype='float32')
    transform = rasterio.transform.from_origin(x0, y1, DEM_RES, DEM_RES)
    with rasterio.open(DEM, overview_level=DEM_OVR) as src:
        arr = src.read(1)
        reproject(arr, dst, src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata, dst_transform=transform,
                  dst_crs=crs.to_wkt(), dst_nodata=np.nan, resampling=Resampling.bilinear)
    return dst


def graticule(ax, extent, tr: Transformer) -> None:
    """Сетка 6° по долготе и 3° по широте; подписи сверху и слева, засечки по всем сторонам (как в 2022 г.)."""
    x0, x1, y0, y1 = extent
    kw = dict(fontsize=8, style='italic', color=INK, clip_on=False)
    for lon in range(54, 100, 6):
        lats = np.linspace(55, 78, 600)
        x, y = tr.transform(np.full_like(lats, lon), lats)
        ax.plot(x, y, color='#9a9a9a', lw=0.3, zorder=1.5)
        for yy, va, dy in ((y1, 'bottom', 0.012), (y0, 'top', -0.012)):
            s = np.sign(y - yy)
            i = np.flatnonzero(s[:-1] * s[1:] < 0)
            if len(i):
                xx = float(np.interp(yy, [y[i[0]], y[i[0] + 1]], [x[i[0]], x[i[0] + 1]]))
                if x0 < xx < x1:
                    ax.plot([xx, xx], [yy, yy + np.sign(dy) * 0.008 * (y1 - y0)], color=INK, lw=0.8, clip_on=False)
                    if va == 'bottom':
                        ax.text(xx, yy + dy * (y1 - y0), f'{lon}°E', ha='center', va=va, **kw)
    for lat in range(60, 76, 3):
        lons = np.linspace(40, 110, 900)
        x, y = tr.transform(lons, np.full_like(lons, lat))
        ax.plot(x, y, color='#9a9a9a', lw=0.3, zorder=1.5)
        for xx, ha, dx in ((x0, 'right', -0.012), (x1, 'left', 0.012)):
            s = np.sign(x - xx)
            i = np.flatnonzero(s[:-1] * s[1:] < 0)
            if len(i):
                yy = float(np.interp(xx, [x[i[0]], x[i[0] + 1]], [y[i[0]], y[i[0] + 1]]))
                if y0 < yy < y1:
                    ax.plot([xx, xx + np.sign(dx) * 0.008 * (x1 - x0)], [yy, yy], color=INK, lw=0.8, clip_on=False)
                    if ha == 'right':
                        ax.text(xx + dx * (x1 - x0), yy, f'{lat}°N', ha=ha, va='center', **kw)


def north_arrow(ax, x: float, y: float, r: float) -> None:
    """Четырёхлучевая роза с буквой N (как в 2022 г.)."""
    w = r * 0.18
    for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        tip = (x + dx * r, y + dy * r)
        left = (x - dy * w, y + dx * w)
        right = (x + dy * w, y - dx * w)
        # белая окантовка: роза стоит на тёмном море
        ax.add_patch(MplPolygon([(x, y), tip, left], closed=True, facecolor=INK, edgecolor='white', lw=0.8, zorder=9))
        ax.add_patch(MplPolygon([(x, y), tip, right], closed=True, facecolor='white', edgecolor='white', lw=0.8, zorder=9))
    ax.text(x, y + r * 1.12, 'N', ha='center', va='bottom', fontsize=9, color=INK, zorder=9,
            path_effects=[pe.withStroke(linewidth=2.5, foreground='white')])


def scalebar(ax, x: float, y: float) -> None:
    L = 200_000
    ax.plot([x, x + L], [y, y], color=INK, lw=1.2, solid_capstyle='butt', zorder=9)
    for k in (0, 0.5, 1):
        ax.plot([x + k * L, x + k * L], [y, y + 12_000], color=INK, lw=1.0, zorder=9)
    halo = [pe.withStroke(linewidth=2.5, foreground='white')]
    ax.text(x, y + 18_000, '0', ha='center', va='bottom', fontsize=9, color=INK, zorder=9, path_effects=halo)
    ax.text(x + L, y + 18_000, '200 км', ha='center', va='bottom', fontsize=9, color=INK, zorder=9, path_effects=halo)


def river_label(ax, lines: gpd.GeoSeries, name: str, lat: float, lon: float, tr: Transformer) -> None:
    """Подпись реки вдоль линии у заданной точки."""
    px, py = tr.transform(lon, lat)
    p = Point(px, py)
    d = lines.distance(p)
    geom = lines.iloc[int(np.argmin(d.to_numpy()))]
    s = geom.project(p)
    a, b = geom.interpolate(max(s - 15_000, 0)), geom.interpolate(min(s + 15_000, geom.length))
    ang = np.degrees(np.arctan2(b.y - a.y, b.x - a.x))
    if ang > 90:
        ang -= 180
    elif ang < -90:
        ang += 180
    q = geom.interpolate(s)
    ax.text(q.x, q.y, name, rotation=ang, rotation_mode='anchor', ha='center', va='bottom', fontsize=8, style='italic',
            color='#5aa7d6', zorder=8, path_effects=[pe.withStroke(linewidth=2, foreground='white')])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--cls', default='aeolian', choices=list(TITLES))
    ap.add_argument('--method', default='centroid', choices=['centroid', 'intersect'])
    ap.add_argument('--product', type=Path, default=PRODUCT, help='слой классов (layer genesis)')
    ap.add_argument('--suffix', default='', help='добавка к имени выходных файлов (например _v8)')
    ap.add_argument('--cell', type=float, default=None, help='размер ячейки, м (по умолчанию CELL_DEFAULT)')
    ap.add_argument('--scale', default=None, choices=list(SCALES),
                    help='шкала; по умолчанию 2022 для ячеек мельче 5 км, иначе share')
    a = ap.parse_args()
    cell = a.cell or CELL_DEFAULT[a.method]
    scale = a.scale or ('2022' if cell < 5000 else 'share')
    BOUNDS, LABELS, COLORS = SCALES[scale]
    BOUNDS = list(BOUNDS)
    tag = f'{a.cls}_{a.method}_{int(cell)}m{a.suffix}'
    cpu_limit.apply_cores(12)
    t0 = time.time()
    crs = CRS.from_proj4(PROJ)
    tr = Transformer.from_crs(4326, crs, always_xy=True)
    aoi = gpd.read_file(AOI).to_crs(crs)
    cover = gpd.read_file(COVER).to_crs(crs)
    uncov = gpd.GeoSeries([aoi.union_all().difference(cover.union_all())], crs=crs)
    xmin, ymin, xmax, ymax = aoi.total_bounds
    extent = (xmin - PAD, xmax + PAD_RIGHT, ymin - PAD, ymax + PAD)

    g = pyogrio.read_dataframe(a.product, layer='genesis', columns=['genesis'], where=f"genesis = '{a.cls}'")
    log(f'{a.cls}: {len(g)} контуров, {g.geometry.area.sum() / 1e6:.1f} км²')
    g = g.to_crs(crs)
    c = centroid_density(g, cell) if a.method == 'centroid' else cell_density(g, cell)
    if c['ha_per_km2'].min() < BOUNDS[0]:
        BOUNDS[0] = 0.0
        LABELS = ['до 0,1'] + LABELS[1:]
    FIGS.mkdir(parents=True, exist_ok=True)
    c.to_csv(FIGS / f'distr_{tag}_cells.csv', index=False, encoding='utf-8')
    save_raster(c, cell, crs, FIGS / f'density_{tag}.tif')
    log(f'{a.method}, ячейка {cell:g} м: ячеек {len(c)}, сумма {c["km2"].sum():.1f} км², '
        f'плотность {c["ha_per_km2"].min():.3g}-{c["ha_per_km2"].max():.4g} га/км²; '
        + ', '.join(f'{lb}: {n}' for lb, n in zip(LABELS, np.histogram(c['ha_per_km2'], bins=[min(b, 1e9) for b in BOUNDS])[0])))

    dem = dem_grid(extent, crs)
    dem[dem < -500] = np.nan                 # нет данных, не помеченное в обзорном уровне
    dem = np.nan_to_num(dem, nan=0.0)         # пропуски ALOS (море, крупные водоёмы) как нулевая отметка
    log(f'рельеф: {dem.shape}, доля без данных {np.isnan(dem).mean():.3f}, отметки {np.nanmin(dem):.0f}-{np.nanmax(dem):.0f} м')
    clip = gpd.GeoDataFrame(geometry=[box(extent[0], extent[2], extent[1], extent[3])], crs=crs)
    bbox4326 = tuple(clip.to_crs(4326).total_bounds)
    fields = gpd.read_file(FIELDS, encoding='cp1251', bbox=bbox4326).set_crs(4326, allow_override=True).to_crs(crs)
    fields = fields[fields.intersects(clip.geometry.iloc[0])]
    roads = pyogrio.read_dataframe(OSM, layer='roads', columns=['highway'],
                                   where="highway IN ('trunk', 'primary', 'trunk_link', 'primary_link')").to_crs(crs)
    rivers = gpd.read_file(RIVERS, layer='rivers').to_crs(crs).clip(clip)
    rivers = rivers[rivers['name'].notna()]
    rivers = rivers[rivers['name'].isin(RIVERS_MAJOR)]
    log('реки: ' + ', '.join(f'{n} {v:.0f} км' for n, v in (rivers.geometry.length.groupby(rivers['name']).sum() / 1000).items()))
    log(f'месторождений {len(fields)}, дорог {len(roads)}, участков рек {len(rivers)}')

    plt.rcParams.update({'font.family': 'Arial', 'font.size': 8, 'text.color': INK})
    W = 17 / 2.54
    x0, x1, y0, y1 = extent
    AXW = 0.905
    H = W * AXW * (y1 - y0) / (x1 - x0) / 0.93
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([0.075, 0.02, AXW, 0.93])
    gray = LinearSegmentedColormap.from_list('dem', ['#3a3a3a', '#8c8c8c', '#f4f4f4'])
    gray.set_bad('white')
    ax.imshow(np.clip(dem, 0, DEM_MAX), cmap=gray, vmin=0, vmax=DEM_MAX, extent=extent, origin='upper', zorder=0,
              interpolation='bilinear')
    uncov.plot(ax=ax, facecolor='none', edgecolor='#d0d0d0', hatch='////', lw=0, zorder=1)
    # ячейки: мельче пикселя печати сводятся по максимуму (иначе при уменьшении мелкие ячейки пропадают)
    disp = (x1 - x0) / (AXW * W * DISPLAY_DPI)
    grid, gext = display_grid(c, cell, disp)
    log(f'пиксель печати {disp:.0f} м; сетка рисунка {grid.shape}')
    cmap = ListedColormap(COLORS)
    cmap.set_bad(alpha=0)
    norm = BoundaryNorm([b if np.isfinite(b) else 1e9 for b in BOUNDS], cmap.N)
    ax.imshow(np.ma.masked_invalid(grid), cmap=cmap, norm=norm, origin='lower', interpolation='nearest', zorder=2,
              extent=gext)
    if a.cls in FIELDS_FOR:
        fields.boundary.plot(ax=ax, color=FIELD_C, lw=0.35, zorder=3)
    big = rivers['name'].isin(RIVER_BIG)
    rivers[~big].plot(ax=ax, color=RIVER_C, lw=0.7, zorder=4)
    rivers[big].plot(ax=ax, color=RIVER_C, lw=1.2, zorder=4)
    aoi.boundary.plot(ax=ax, color=AOI_C, lw=1.6, zorder=5)
    roads.plot(ax=ax, color='white', lw=1.6, zorder=6)
    roads.plot(ax=ax, color=ROAD_C, lw=0.8, zorder=6.1)
    halo = [pe.withStroke(linewidth=2.2, foreground='white')]
    for name, lat, lon in CITIES:
        x, y = tr.transform(lon, lat)
        if extent[0] < x < extent[1] and extent[2] < y < extent[3]:
            ax.plot(x, y, 'o', ms=5, mfc='#8a8a8a', mec=INK, mew=0.6, zorder=7)
            ax.text(x + 14_000, y + 6_000, name, fontsize=8, fontweight='bold', style='italic', color='#4a4a4a', zorder=7,
                    path_effects=halo)
    for name, (lat, lon) in RIVER_NAMES.items():
        sub = rivers[rivers['name'] == name]
        if len(sub):
            river_label(ax, sub.geometry.reset_index(drop=True), name, lat, lon, tr)
    graticule(ax, extent, tr)
    x0, x1, y0, y1 = extent
    north_arrow(ax, x0 + 0.06 * (x1 - x0), y1 - 0.09 * (y1 - y0), 0.04 * (y1 - y0))
    scalebar(ax, x0 + 0.012 * (x1 - x0), y0 + 0.018 * (y1 - y0))
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect('equal')
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_linewidth(1.2)
        s.set_color(INK)
    handles = [Patch(facecolor=col, edgecolor='#7a7a7a', lw=0.6, label=lb) for col, lb in zip(COLORS, LABELS)]
    handles += [Line2D([], [], color=AOI_C, lw=3, label='Граница\nрайона работ'),
                Patch(facecolor='white', edgecolor='#bdbdbd', hatch='////', lw=0.6,
                      label=NOSAND_LABEL.get(a.cls, 'Песков\nне выявлено'))]
    if a.cls in FIELDS_FOR:
        handles.append(Line2D([], [], color=FIELD_C, lw=1.2, label='Границы\nместорождений'))
    handles += [Line2D([], [], marker='o', ls='none', ms=6, mfc='#8a8a8a', mec=INK, mew=0.6, label='Города'),
                Line2D([], [], color=ROAD_C, lw=1.6, label='Автодороги'),
                Line2D([], [], color=RIVER_C, lw=1.6, label='Реки')]
    leg = ax.legend(handles=handles, loc='upper right', fontsize=7.5, frameon=True, fancybox=False, edgecolor=INK,
                    framealpha=1, borderpad=0.5, handlelength=2.2, handleheight=1.1, labelspacing=0.35,
                    title='Суммарная\nплощадь, га/км²', title_fontproperties={'weight': 'bold', 'style': 'italic', 'size': 9})
    leg._legend_box.align = 'left'
    leg.get_frame().set_linewidth(0.8)
    leg.set_zorder(10)
    # шкала высот внутри рамки, в правом нижнем углу (автор)
    bx, by, bw, bh = 0.885, 0.012, 0.105, 0.215
    ax.add_patch(Rectangle((bx, by), bw, bh, transform=ax.transAxes, facecolor='white', edgecolor=INK, lw=0.8, zorder=10))
    ax.text(bx + bw / 2, by + bh - 0.008, 'Абс.\nвысота, м', transform=ax.transAxes, ha='center', va='top', fontsize=8,
            fontweight='bold', zorder=11)
    cax = ax.inset_axes([bx + 0.02, by + 0.015, 0.02, bh - 0.085])
    cax.set_zorder(11)
    cb = fig.colorbar(plt.cm.ScalarMappable(cmap=gray, norm=plt.Normalize(0, DEM_MAX)), cax=cax, ticks=[0, DEM_MAX])
    cb.ax.set_yticklabels(['0', '>200'], fontsize=8)
    cb.outline.set_linewidth(0.5)
    base = OUT / f'fig_distr_{tag}'
    fig.savefig(f'{base}.tif', dpi=300, pil_kwargs={'compression': 'tiff_lzw'})
    fig.savefig(f'{base}.png', dpi=DISPLAY_DPI)
    log(f'-> {base}.tif | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
