"""
128_article_map.py - основная карта компактной статьи (2026-09-30; замечания Астры к рис. 2 черновика).

Четыре панели в EPSG:3576: а) район работ, фактическое покрытие маски, непокрытые полосы (просмотрены визуально, песков не
выявлено), опорные названия; б-г) площадь эоловых песков, отмелей и техногенных песков в ячейках 20 x 20 км, вычисленная
ПЕРЕСЕЧЕНИЕМ полигонов с сеткой (не по центроиду). Общая ступенчатая логарифмическая шкала 0,01-100 км2 на ячейку, один
последовательный синий ряд (навык dataviz, references/palette.md). Сетка координат, масштаб.
Выход: docs/article_v2/fig_map.tif (300 dpi, LZW) и fig_map.png (просмотр).
Запуск: PYTHONIOENCODING=utf-8 python -u python/128_article_map.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import time
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch
from pyproj import Transformer
from shapely.geometry import box

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
AOI = ROOT / 'exports' / 'aoi_v2.geojson'
COV = ROOT / 'exports' / 'aux' / 'coverage_tiles.gpkg'
OUT = ROOT / 'docs' / 'article_v2'
CELL = 20000.0
BOUNDS = [0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30, 100]
RAMP = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#2a78d6', '#1c5cab', '#184f95', '#0d366b']   # синий 100-700
INK, MUTED, GRID = '#222222', '#666666', '#bdbdbd'
PANELS = [('aeolian', 'б) эоловые пески'), ('alluvial_littoral', 'в) отмели'), ('anthropogenic', 'г) техногенные пески')]
PLACES = [('Салехард', 66.53, 66.61), ('Надым', 65.53, 72.52), ('Новый Уренгой', 66.08, 76.68), ('Ноябрьск', 63.20, 75.45),
          ('Тазовский', 67.47, 78.72), ('Сабетта', 71.27, 72.07), ('Сургут', 61.25, 73.40)]
REGIONS = [('п-ов Ямал', 70.2, 68.3), ('Гыданский п-ов', 70.3, 78.3), ('Обская губа', 68.3, 73.7)]


def fmt(v: float) -> str:
    """Число с десятичной запятой без лишних нулей."""
    s = f'{v:g}'
    return s.replace('.', ',')


def km2(v: float) -> str:
    return f'{v:,.0f}'.replace(',', ' ') + ' км²'


def cell_areas(g: gpd.GeoDataFrame) -> pd.DataFrame:
    """Площадь класса в ячейках сетки по пересечению полигонов с ячейками, км2."""
    b = g.geometry.bounds
    ix0, ix1 = np.floor(b['minx'] / CELL).astype(int), np.floor((b['maxx'] - 1e-6) / CELL).astype(int)
    iy0, iy1 = np.floor(b['miny'] / CELL).astype(int), np.floor((b['maxy'] - 1e-6) / CELL).astype(int)
    single = (ix0 == ix1) & (iy0 == iy1)
    area = g.geometry.area / 1e6
    parts = [pd.DataFrame({'ix': ix0[single], 'iy': iy0[single], 'cls': g.loc[single, 'genesis_main'], 'km2': area[single]})]
    rows = []
    for k in np.flatnonzero(~single.to_numpy()):
        geom, cls = g.geometry.iloc[k], g['genesis_main'].iloc[k]
        for ix in range(ix0.iloc[k], ix1.iloc[k] + 1):
            for iy in range(iy0.iloc[k], iy1.iloc[k] + 1):
                a = geom.intersection(box(ix * CELL, iy * CELL, (ix + 1) * CELL, (iy + 1) * CELL)).area / 1e6
                if a > 0:
                    rows.append((ix, iy, cls, a))
    parts.append(pd.DataFrame(rows, columns=['ix', 'iy', 'cls', 'km2']))
    print(f'контуров в одной ячейке {int(single.sum())}, на границах ячеек {int((~single).sum())}', flush=True)
    return pd.concat(parts, ignore_index=True).groupby(['cls', 'ix', 'iy'], as_index=False)['km2'].sum()


def _cross(a: np.ndarray, b: np.ndarray, level: float) -> float | None:
    """Значение b в точке, где a пересекает level (линейная интерполяция), или None."""
    s = np.sign(a - level)
    idx = np.flatnonzero(s[:-1] * s[1:] < 0)
    if not len(idx):
        return None
    i = idx[0]
    return float(b[i] + (b[i + 1] - b[i]) * (level - a[i]) / (a[i + 1] - a[i]))


def graticule(ax, extent, crs, labels: bool = True) -> None:
    """Сетка координат: параллели через 2° (подписи по левой рамке), меридианы через 4° (подписи по нижней рамке)."""
    tr = Transformer.from_crs(4326, crs, always_xy=True)
    x0, x1, y0, y1 = extent
    for lat in range(62, 74, 2):
        lons = np.linspace(50, 100, 800)
        x, y = tr.transform(lons, np.full_like(lons, lat))
        ax.plot(x, y, color=GRID, lw=0.35, zorder=1)
        yy = _cross(x, y, x0)
        if labels and yy is not None and y0 < yy < y1:
            ax.text(x0 - 0.01 * (x1 - x0), yy, f'{lat}°', fontsize=5.5, color=MUTED, ha='right', va='center', clip_on=False)
    for lon in range(64, 92, 4):
        lats = np.linspace(56, 78, 800)
        x, y = tr.transform(np.full_like(lats, lon), lats)
        ax.plot(x, y, color=GRID, lw=0.35, zorder=1)
        xx = _cross(y, x, y0)
        if labels and xx is not None and x0 < xx < x1:
            ax.text(xx, y0 - 0.01 * (y1 - y0), f'{lon}°', fontsize=5.5, color=MUTED, ha='center', va='top', clip_on=False)


def scalebar(ax, extent) -> None:
    """Масштаб 200 км в левом верхнем углу (за пределами района работ)."""
    x0, x1, y0, y1 = extent
    L = 200_000
    xs, ys = x0 + 0.04 * (x1 - x0), y1 - 0.07 * (y1 - y0)
    ax.plot([xs, xs + L], [ys, ys], color=INK, lw=1.6, solid_capstyle='butt', zorder=7)
    for xx in (xs, xs + L / 2, xs + L):
        ax.plot([xx, xx], [ys, ys + 0.008 * (y1 - y0)], color=INK, lw=0.8, zorder=7)
    ax.text(xs, ys + 0.012 * (y1 - y0), '0', fontsize=5.5, ha='center', color=INK, zorder=7)
    ax.text(xs + L, ys + 0.012 * (y1 - y0), '200 км', fontsize=5.5, ha='center', color=INK, zorder=7)


def main() -> None:
    cpu_limit.apply()
    t0 = time.time()
    g = gpd.read_file(PRODUCT, layer='genesis', columns=['genesis_main'])
    crs = g.crs
    aoi = gpd.read_file(AOI).to_crs(crs)
    cov = gpd.read_file(COV, layer='coverage').to_crs(crs)
    uncov = gpd.GeoSeries([aoi.geometry.iloc[0].difference(cov.geometry.iloc[0])], crs=crs)
    ca = cell_areas(g[g['genesis_main'].isin([p[0] for p in PANELS])])
    ca.to_csv(OUT / 'fig_map_cells.csv', index=False, encoding='utf-8')
    print(f'ячейки посчитаны за {(time.time() - t0) / 60:.1f} мин', flush=True)
    xmin, ymin, xmax, ymax = aoi.total_bounds
    pad = 20000
    extent = (xmin - pad, xmax + pad, ymin - pad, ymax + pad)
    cmap = ListedColormap(RAMP)
    cmap.set_under('#ffffff')
    norm = BoundaryNorm(BOUNDS, cmap.N)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 7, 'text.color': INK})
    fig, axes = plt.subplots(2, 2, figsize=(17 / 2.54, 17.5 / 2.54), constrained_layout=True)
    axes = axes.ravel()
    # а) район работ и покрытие
    ax = axes[0]
    aoi.plot(ax=ax, color='#f4f3ef', edgecolor=INK, lw=0.4, zorder=2)
    cov.plot(ax=ax, color='#dfe9f5', edgecolor='none', zorder=3)
    uncov.plot(ax=ax, facecolor='none', edgecolor='#8c8c8c', hatch='////', lw=0, zorder=4)
    aoi.boundary.plot(ax=ax, color=INK, lw=0.4, zorder=5)
    tr = Transformer.from_crs(4326, crs, always_xy=True)
    for name, lat, lon in PLACES:
        x, y = tr.transform(lon, lat)
        ax.plot(x, y, 'o', ms=2.2, color=INK, zorder=8)
        ax.text(x + 12000, y + 8000, name, fontsize=5.8, color=INK, zorder=8)
    for name, lat, lon in REGIONS:
        x, y = tr.transform(lon, lat)
        ax.text(x, y, name, fontsize=6, color=MUTED, style='italic', ha='center', zorder=8)
    ax.set_title('а) район работ и покрытие маски', fontsize=7.5, loc='left')
    ax.legend(handles=[Patch(facecolor='#dfe9f5', edgecolor='none', label='покрытие маски\n(128 тайлов Sentinel-2)'),
                       Patch(facecolor='none', edgecolor='#8c8c8c', hatch='////', label='не обработано; просмотрено\nвизуально, песков не выявлено')],
              loc='upper center', bbox_to_anchor=(0.5, -0.045), ncol=2, fontsize=5.5, frameon=False, handlelength=1.6)
    # б-г) классы
    for ax, (cls, title) in zip(axes[1:], PANELS):
        c = ca[ca['cls'] == cls]
        aoi.plot(ax=ax, color='#ffffff', edgecolor='none', zorder=1)
        cells = gpd.GeoDataFrame(c, geometry=[box(ix * CELL, iy * CELL, (ix + 1) * CELL, (iy + 1) * CELL) for ix, iy in zip(c['ix'], c['iy'])], crs=crs)
        cells = cells.clip(aoi)
        cells.plot(ax=ax, column='km2', cmap=cmap, norm=norm, edgecolor='none', zorder=2)
        uncov.plot(ax=ax, facecolor='none', edgecolor='#b0b0b0', hatch='////', lw=0, zorder=3)
        aoi.boundary.plot(ax=ax, color=INK, lw=0.4, zorder=5)
        ax.set_title(f'{title}: {km2(c["km2"].sum())}', fontsize=7.5, loc='left')
    for ax in axes:
        graticule(ax, extent, crs)
        scalebar(ax, extent)
        ax.set_xlim(extent[0], extent[1])
        ax.set_ylim(extent[2], extent[3])
        ax.set_aspect('equal')
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_linewidth(0.4)
            s.set_color(MUTED)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cb = fig.colorbar(sm, ax=axes[1:], orientation='horizontal', fraction=0.035, pad=0.02, aspect=40,
                      ticks=BOUNDS, spacing='uniform')
    cb.ax.set_xticklabels([fmt(v) for v in BOUNDS], fontsize=6)
    cb.set_label('площадь класса в ячейке 20 × 20 км, км² (белое: не выявлено)', fontsize=6.5)
    cb.outline.set_linewidth(0.4)
    fig.savefig(OUT / 'fig_map.tif', dpi=300, pil_kwargs={'compression': 'tiff_lzw'})
    fig.savefig(OUT / 'fig_map.png', dpi=150)
    tot = ca.groupby('cls')['km2'].sum()
    print('суммы по классам (пересечение с сеткой), км2:', tot.round(1).to_dict())
    print(f'-> {OUT / "fig_map.tif"} | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
