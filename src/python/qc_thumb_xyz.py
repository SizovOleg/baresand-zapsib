"""
BareSand — Рендер окон Esri World Imagery для визуальной QC (без GEE, без квот).

Для каждого id: тайлы Esri World Imagery (XYZ, EPSG:3857) сшиваются в окно вокруг контура,
поверх рисуются контуры: ЦЕЛЬ — красный; другие shoal — жёлтый; кандидаты — оранжевый;
граница AOI — голубой. Масштабная линейка 1 км, подпись id/координат.

Окно: bbox контура ×3, в пределах [MIN_KM, MAX_KM]; zoom подбирается под ~768 px.
Тайлы кэшируются в exports/qc/thumbs/_tiles/.

Запуск:
  python python/qc_thumb_xyz.py --ids 302011 176058
  python python/qc_thumb_xyz.py --ids 12345 --km 4
Печатает JSON: путь PNG, центр lat/lon, окно, zoom, улики из evidence_local.csv (если есть).
"""
import sys
import os
import io
import json
import math
import argparse
import time
from pathlib import Path

import requests
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import box
from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer

sys.stdout.reconfigure(encoding='utf-8')

QC = Path(r'D:\test\baresand_zapsib\exports\qc')
SHOAL = QC / 'qc_step1_shoal_review.gpkg'
CAND = QC / 'qc_step1_omission_candidates.gpkg'
AOI = QC.parent / 'aoi_v2.geojson'
EVID = QC / 'qc_step1_evidence_local.csv'
TILE_CACHE = QC / 'thumbs' / '_tiles'
URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
UA = {'User-Agent': 'BareSand-QC/1.0 (research)'}

MIN_KM, MAX_KM, TARGET_PX, TILE = 2.5, 15.0, 768, 256
ZMIN, ZMAX = 10, 17
R_MERC = 6378137.0 * math.pi
_c: dict = {}
_to_wgs = Transformer.from_crs(3857, 4326, always_xy=True)

# Универсальный оверлей (шаг 2 и далее): gpkg + поле класса + цвета по значениям.
# Задаётся из CLI (--overlay/--field/--sample); если не задан — поведение шага 1.
OVERLAY: dict = {'path': None, 'field': 'genesis', 'sample': None}
CLASS_COLORS = {
    'shoal': (255, 230, 0),          # жёлтый — морская отмель (шаг 1)
    'river_shoal': (0, 120, 255),    # синий
    'lake_shoal': (0, 220, 220),     # бирюзовый
    'anthropogenic': (200, 0, 200),  # пурпурный (шаг 3)
    'unassigned': (255, 159, 26),    # оранжевый
    'aeolian': (60, 200, 60),        # зелёный (шаг 4)
    'undefined': (150, 150, 150),    # серый (шаг 4)
}


def layers() -> dict:
    if not _c:
        ov_p = Path(OVERLAY['path']) if OVERLAY['path'] else QC / 'coastal_v2_overlay.gpkg'
        smp_p = Path(OVERLAY['sample']) if OVERLAY['sample'] else QC / 'visual_sample_geoms.gpkg'
        if OVERLAY['path']:
            # универсальный режим: один слой, классы по полю OVERLAY['field']
            ov = gpd.read_file(ov_p).to_crs(3857)
            _c['ov'] = ov
            sh = ov[ov[OVERLAY['field']] == 'shoal']
            cand = ov[ov[OVERLAY['field']] == 'unassigned']
        elif ov_p.exists():
            # v2: жёлтый = shoal v2, оранжевый = unassigned прибрежной зоны
            ov = gpd.read_file(ov_p).to_crs(3857)
            sh = ov[ov['genesis'] == 'shoal']
            cand = ov[ov['genesis'] != 'shoal']
        else:
            sh = gpd.read_file(SHOAL).to_crs(3857)
            cand = gpd.read_file(CAND).to_crs(3857)
        _c['sample'] = gpd.read_file(smp_p).to_crs(3857) if smp_p.exists() else None
        aoi = gpd.read_file(AOI).to_crs(3857)
        coast_p = QC / 'sea_coastline.gpkg'
        coast = gpd.read_file(coast_p).to_crs(3857) if coast_p.exists() else None
        _c.update(sh=sh, cand=cand, aoi_line=aoi.geometry.union_all().boundary,
                  coast=coast, ev=pd.read_csv(EVID) if EVID.exists() else None)
    return _c


def tile_xy(x_m: float, y_m: float, z: int) -> tuple[float, float]:
    """Web Mercator метры → дробные координаты тайла."""
    n = 2 ** z
    return (x_m + R_MERC) / (2 * R_MERC) * n, (R_MERC - y_m) / (2 * R_MERC) * n


def fetch_tile(z: int, x: int, y: int) -> Image.Image:
    p = TILE_CACHE / str(z) / str(x) / f'{y}.jpg'
    if p.exists():
        try:
            return Image.open(p).convert('RGB')
        except Exception:  # noqa: BLE001 — недописанный файл соседним воркером
            pass
    p.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        r = requests.get(URL.format(z=z, x=x, y=y), headers=UA, timeout=20)
        if r.status_code == 200:
            tmp = p.with_suffix(f'.{os.getpid()}.tmp')
            tmp.write_bytes(r.content)
            try:
                os.replace(tmp, p)      # атомарно — безопасно при параллельных воркерах
            except OSError:
                tmp.unlink(missing_ok=True)
            return Image.open(io.BytesIO(r.content)).convert('RGB')
        time.sleep(1.0)
    return Image.new('RGB', (TILE, TILE), (40, 40, 40))


def draw_geom(dr: ImageDraw.ImageDraw, g, color, width: int, to_px) -> None:
    if g.is_empty:
        return
    if g.geom_type == 'Polygon':
        for ring in [g.exterior] + list(g.interiors):
            pts = [to_px(x, y) for x, y in ring.coords]
            if len(pts) > 1:
                dr.line(pts, fill=color, width=width)
    elif g.geom_type == 'LineString':
        pts = [to_px(x, y) for x, y in g.coords]
        if len(pts) > 1:
            dr.line(pts, fill=color, width=width)
    elif hasattr(g, 'geoms'):
        for sub in g.geoms:
            draw_geom(dr, sub, color, width, to_px)


def render(cid: int, out_dir: Path, fixed_km) -> dict:
    L = layers()
    sh, cand = L['sh'], L['cand']
    src = 'sample'
    smp = L.get('sample')
    row = smp[smp['id'] == cid] if smp is not None else sh.iloc[0:0]
    if len(row) == 0:
        row = sh[sh['id'] == cid]
        src = 'shoal'
    if len(row) == 0:
        row = cand[cand['id'] == cid]
        src = 'cand'
    if len(row) == 0:
        return {'id': cid, 'error': 'id не найден'}
    geom = row.geometry.iloc[0]
    minx, miny, maxx, maxy = geom.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    lon, lat = _to_wgs.transform(cx, cy)
    # метры Web Mercator растянуты в 1/cos(lat) раз относительно истинных
    k = 1.0 / math.cos(math.radians(lat))
    if fixed_km:
        half = fixed_km * 500.0 * k
    else:
        span_true = max(maxx - minx, maxy - miny) / k * 3.0
        half = min(max(span_true, MIN_KM * 1000), MAX_KM * 1000) / 2.0 * k
    win = box(cx - half, cy - half, cx + half, cy + half)

    res_needed = (2 * half) / TARGET_PX
    z = int(max(ZMIN, min(ZMAX, round(math.log2(2 * R_MERC / TILE / res_needed)))))
    tx0, ty0 = tile_xy(cx - half, cy + half, z)
    tx1, ty1 = tile_xy(cx + half, cy - half, z)
    X0, Y0 = int(math.floor(tx0)), int(math.floor(ty0))
    X1, Y1 = int(math.floor(tx1)), int(math.floor(ty1))
    mosaic = Image.new('RGB', ((X1 - X0 + 1) * TILE, (Y1 - Y0 + 1) * TILE))
    for X in range(X0, X1 + 1):
        for Y in range(Y0, Y1 + 1):
            mosaic.paste(fetch_tile(z, X, Y), ((X - X0) * TILE, (Y - Y0) * TILE))
    px0, py0 = int((tx0 - X0) * TILE), int((ty0 - Y0) * TILE)
    px1, py1 = int((tx1 - X0) * TILE), int((ty1 - Y0) * TILE)
    img = mosaic.crop((px0, py0, px1, py1))
    W, H = img.size
    sx, sy = W / (2 * half), H / (2 * half)

    def to_px(x: float, y: float) -> tuple[float, float]:
        return ((x - (cx - half)) * sx, ((cy + half) - y) * sy)

    dr = ImageDraw.Draw(img)
    ab = L['aoi_line'].intersection(win)
    draw_geom(dr, ab, (0, 229, 255), 2, to_px)
    if L['coast'] is not None:
        for _, r in L['coast'][L['coast'].intersects(win)].iterrows():
            draw_geom(dr, r.geometry.intersection(win), (255, 0, 255), 2, to_px)
    if OVERLAY['path']:
        ov = L['ov']
        sub = ov[ov.intersects(win) & (ov['id'] != cid)]
        for _, r in sub.iterrows():
            col = CLASS_COLORS.get(str(r[OVERLAY['field']]), (200, 200, 200))
            draw_geom(dr, r.geometry.intersection(win), col, 2, to_px)
    else:
        for _, r in cand[cand.intersects(win) & (cand['id'] != cid)].iterrows():
            draw_geom(dr, r.geometry.intersection(win), (255, 159, 26), 2, to_px)
        for _, r in sh[sh.intersects(win) & (sh['id'] != cid)].iterrows():
            draw_geom(dr, r.geometry.intersection(win), (255, 230, 0), 2, to_px)
    draw_geom(dr, geom, (255, 0, 0), 3, to_px)

    # линейка: 1 км, а если не помещается в 60 % ширины (малые окна --km) — 500 или 200 м
    bar_m, bar_lbl = 1000.0, '1 km'
    for m, lbl in ((1000.0, '1 km'), (500.0, '500 m'), (200.0, '200 m')):
        bar_m, bar_lbl = m, lbl
        if m * k * sx <= 0.6 * W:
            break
    km_px = bar_m * k * sx
    dr.rectangle([10, H - 28, 10 + km_px, H - 20], fill=(255, 255, 255), outline=(0, 0, 0))
    f = ImageFont.load_default()
    dr.text((12, H - 46), bar_lbl, fill=(255, 255, 255), font=f)
    dr.text((10, 8), f'id {cid}  {lat:.4f}N {lon:.4f}E  win {2 * half / k / 1000:.1f} km  z{z}  Esri',
            fill=(255, 255, 255), font=f)

    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f'{cid}_esri.png'
    img.save(p)
    info = {'id': cid, 'source_layer': src, 'lat': round(lat, 4), 'lon': round(lon, 4),
            'window_km': round(2 * half / k / 1000, 1), 'zoom': z,
            'area_ha': round(float(row['area_ha'].iloc[0]), 2), 'png': str(p),
            'legend': 'red=target, yellow=other shoal, orange=candidates, cyan=AOI boundary, magenta=OSM sea coastline'}
    ev = L['ev']
    if ev is not None:
        e = ev[ev['id'] == cid]
        if len(e):
            skip = {'id', 'lat', 'lon', 'fid', 'geometry'}
            info['evidence'] = {c: (None if pd.isna(e[c].iloc[0]) else (float(e[c].iloc[0]) if np.issubdtype(e[c].dtype, np.number) else str(e[c].iloc[0])))
                                for c in e.columns if c not in skip}
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ids', type=int, nargs='+', required=True)
    ap.add_argument('--out', default=str(QC / 'thumbs'))
    ap.add_argument('--km', type=float, default=None)
    ap.add_argument('--overlay', default=None, help='gpkg с классами (шаг 2+): цвета по --field')
    ap.add_argument('--field', default='genesis')
    ap.add_argument('--sample', default=None, help='gpkg с геометриями проверяемых контуров (приоритетный поиск id)')
    ap.add_argument('--evidence', default=None, help='csv улик для подписи (по умолчанию шаг 1)')
    a = ap.parse_args()
    OVERLAY.update(path=a.overlay, field=a.field, sample=a.sample)
    if a.evidence:
        global EVID
        EVID = Path(a.evidence)
    out = []
    for cid in a.ids:
        try:
            out.append(render(cid, Path(a.out), a.km))
        except Exception as e:  # noqa: BLE001
            out.append({'id': cid, 'error': str(e)[:200]})
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
