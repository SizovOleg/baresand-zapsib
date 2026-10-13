"""
129_article_examples.py - рис. 2 компактной статьи: примеры контуров проверочной выборки на снимках Esri World Imagery
(2026-09-30; переделан: собственный рендер без служебных линий берега и границы района).

Тайлы Esri World Imagery (XYZ) берутся через кэш qc_thumb_xyz (exports/qc/thumbs/_tiles); поверх рисуется только
контур (красный с тёмной обводкой) и масштабная линейка. Сенсор и дата снимка в точке центроида берутся из слоя
метаданных World Imagery (identify, слой по фактическому уровню тайлов).
а) эоловый раздув; б) техногенная поверхность; в) эоловый покров, отнесённый картой к отмели (главная путаница);
г) смешанный контур (пляж и насыпь порта). Класс карты в подписи относится к версии, зафиксированной до выборки V1.
Выход: docs/article_v2/fig_examples.tif (300 dpi, LZW) и fig_examples.png.
Запуск: PYTHONIOENCODING=utf-8 python -u python/129_article_examples.py
"""
import math
import sys
import traceback

sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use('Agg')
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import requests
from PIL import Image

from qc_thumb_xyz import R_MERC, TILE, UA, fetch_tile, tile_xy

ROOT = Path(r'D:\test\baresand_zapsib')
PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
OUT = ROOT / 'docs' / 'article_v2'
META_URL = 'https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/identify'
# id, заголовок, класс карты (версия до V1) и метка эксперта, окно в долях охвата контура
PANELS = [
    (235294, 'а) эоловый раздув в северной тайге', 'карта: эоловый', 1.8),
    (132039, 'б) техногенная отсыпка и карьер, п-ов Ямал', 'карта: техногенный', 1.8),
    (369952, 'в) эоловый покров на приморской равнине', 'карта: отмель, эксперт: эоловый', 1.8),
    (370534, 'г) смешанный контур у пос. Сабетта: пляж и насыпь порта', 'карта: отмель, эксперт: смешанный', 1.25),
]
WIN_MIN_M, MIN_PX, ZMAX = 1200.0, 1600, 17
BARS = [100, 200, 250, 500, 1000, 2000, 5000]
SENSORS = {'WV01': 'WorldView-1', 'WV02': 'WorldView-2', 'WV03': 'WorldView-3', 'WV04': 'WorldView-4', 'GE01': 'GeoEye-1'}


def ru(x: float, nd: int) -> str:
    """Число с десятичной запятой."""
    return f'{x:.{nd}f}'.replace('.', ',')


def imagery_meta(lon: float, lat: float, z: int) -> str:
    """Сенсор и дата снимка Esri World Imagery в точке на уровне тайлов z (слой метаданных 28 - z: zoom 16 = слой 12,
    2.4m Resolution Metadata); при сбое пишет traceback в stderr и возвращает '?'."""
    try:
        r = requests.get(META_URL, headers=UA, timeout=30, params={
            'geometry': f'{lon},{lat}', 'geometryType': 'esriGeometryPoint', 'sr': 4326, 'layers': f'all:{28 - z}',
            'tolerance': 0, 'mapExtent': f'{lon - 0.1},{lat - 0.1},{lon + 0.1},{lat + 0.1}',
            'imageDisplay': '1000,1000,96', 'returnGeometry': 'false', 'f': 'json'})
        a = r.json()['results'][0]['attributes']
        d = str(a['SRC_DATE'])
        return f'{SENSORS.get(a["SRC_DESC"], a["SRC_DESC"])}, {d[6:8]}.{d[4:6]}.{d[:4]}'
    except Exception:  # noqa: BLE001 - подпись без даты, причина видна в stderr
        traceback.print_exc()
        return '?'


def mosaic(cx: float, cy: float, half: float, z: int) -> Image.Image:
    """Окно Web Mercator [cx +- half, cy +- half] из тайлов Esri уровня z."""
    tx0, ty0 = tile_xy(cx - half, cy + half, z)
    tx1, ty1 = tile_xy(cx + half, cy - half, z)
    X0, Y0, X1, Y1 = int(tx0), int(ty0), int(tx1), int(ty1)
    m = Image.new('RGB', ((X1 - X0 + 1) * TILE, (Y1 - Y0 + 1) * TILE))
    for X in range(X0, X1 + 1):
        for Y in range(Y0, Y1 + 1):
            m.paste(fetch_tile(z, X, Y), ((X - X0) * TILE, (Y - Y0) * TILE))
    return m.crop((int((tx0 - X0) * TILE), int((ty0 - Y0) * TILE), int((tx1 - X0) * TILE), int((ty1 - Y0) * TILE)))


def rings(geom):
    """Все кольца (внешние и внутренние) полигона или мультиполигона."""
    for p in getattr(geom, 'geoms', [geom]):
        yield p.exterior
        yield from p.interiors


def main() -> None:
    ids = ', '.join(str(p[0]) for p in PANELS)
    g = gpd.read_file(PRODUCT, layer='genesis', columns=['id', 'area_ha'], where=f'id IN ({ids})').set_index('id')
    ll = g.geometry.centroid.to_crs(4326)
    gm = g.to_crs(3857)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 7})
    fig, axes = plt.subplots(2, 2, figsize=(17 / 2.54, 18.8 / 2.54), constrained_layout=True)
    halo = [pe.withStroke(linewidth=1.6, foreground='black')]
    for ax, (cid, title, cls, factor) in zip(axes.ravel(), PANELS):
        geom = gm.geometry.loc[cid]
        lon, lat = ll.loc[cid].x, ll.loc[cid].y
        k = 1.0 / math.cos(math.radians(lat))  # растяжение Web Mercator на широте контура
        minx, miny, maxx, maxy = geom.bounds
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        side = max(max(maxx - minx, maxy - miny) / k * factor, WIN_MIN_M)  # истинные метры
        half = side / 2 * k
        z = next((z for z in range(12, ZMAX + 1) if 2 * half / (2 * R_MERC / TILE / 2 ** z) >= MIN_PX), ZMAX)
        img = mosaic(cx, cy, half, z)
        ax.imshow(img, extent=(cx - half, cx + half, cy - half, cy + half), interpolation='lanczos')
        for ring in rings(geom):
            xs, ys = ring.xy
            ax.plot(xs, ys, color='#ff2a2a', lw=0.9, path_effects=[pe.withStroke(linewidth=1.8, foreground='black')])
        ax.set_xlim(cx - half, cx + half)
        ax.set_ylim(cy - half, cy + half)
        # масштабная линейка: около четверти окна, внизу слева
        bar = max(b for b in BARS if b <= side * 0.3)
        x0, y0 = cx - half + 0.06 * 2 * half, cy - half + 0.06 * 2 * half
        ax.plot([x0, x0 + bar * k], [y0, y0], color='white', lw=2.2, solid_capstyle='butt',
                path_effects=[pe.withStroke(linewidth=3.4, foreground='black')])
        lab = f'{bar // 1000} км' if bar >= 1000 else f'{bar} м'
        ax.text(x0 + bar * k / 2, y0 + 0.025 * 2 * half, lab, ha='center', va='bottom', color='white', fontsize=6.5,
                path_effects=halo)
        meta = imagery_meta(lon, lat, z)
        ax.text(cx + half - 0.03 * 2 * half, cy - half + 0.04 * 2 * half, meta, ha='right', va='bottom', color='white',
                fontsize=6, path_effects=halo)
        area = g.at[cid, 'area_ha']
        ax.set_title(f'{title}\n{ru(lat, 2)}° с. ш., {ru(lon, 2)}° в. д.; {area:.0f} га\n{cls}', fontsize=6.8, loc='left')
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_linewidth(0.4)
        print(f'{cid}: z={z}, окно {side / 1000:.2f} км, линейка {lab}, {meta}, {img.size[0]} px')
    fig.savefig(OUT / 'fig_examples.tif', dpi=300, pil_kwargs={'compression': 'tiff_lzw'})
    fig.savefig(OUT / 'fig_examples.png', dpi=150)
    print(f'-> {OUT / "fig_examples.tif"}')


if __name__ == '__main__':
    main()
