"""
134_aeolian_techno_candidates.py - кандидаты «техноген, отнесённый к эоловым» и снимки для слепой разметки (2026-10-05).

Повод: владелец на Суторминском месторождении увидел явный техноген в классе эоловых. Причина: старые объекты 1980-х
(насыпи, карьеры) к 1985-2000 гг. уже голые, проверка новизны шага 3 их отсекает, шаг 4 относит к эоловым.
Кандидаты: эоловые контуры v6 не меньше MIN_HA, ближе 20 м к техногенному контуру или к построенной дороге OSM;
без уже размеченных владельцем (step6_rule = v4_expert, step4_rule = expert_override).
Снимок на контур: слева обзор (окно в 3 раза больше охвата контура, не меньше 1,5 км), справа крупный план; Esri World
Imagery, только красная граница цели (класс карты и другие контуры не показываются: разметка вслепую), масштаб, сенсор
и дата снимка (метаданные World Imagery).
Выход: exports/qc/aeolian_techno/img/<id>.png, batch.csv, chunks/chunk_<k>.txt (списки для читателей).
Запуск: PYTHONIOENCODING=utf-8 python -u python/134_aeolian_techno_candidates.py
"""
import math
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
SRC = ROOT / 'exports' / 'baresand_genesis_step6_v6.gpkg'
OUT = ROOT / 'exports' / 'qc' / 'aeolian_techno'
MIN_HA, NEAR_M, CHUNK = 5.0, 20.0, 30
META_URL = 'https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/identify'
SENSORS = {'WV01': 'WorldView-1', 'WV02': 'WorldView-2', 'WV03': 'WorldView-3', 'WV04': 'WorldView-4', 'GE01': 'GeoEye-1'}
BARS = [50, 100, 200, 250, 500, 1000, 2000, 5000]


def candidates() -> gpd.GeoDataFrame:
    cols = ['id', 'genesis', 'area_ha', 'd_road_built', 'step4_rule', 'step6_rule']
    v = pyogrio.read_dataframe(SRC, layer='genesis', columns=cols, where="genesis IN ('aeolian','anthropogenic')")
    ae = v[v['genesis'] == 'aeolian'].reset_index(drop=True)
    an = v[v['genesis'] == 'anthropogenic']
    tr = shapely.STRtree(np.asarray(an.geometry.values))
    adj = np.zeros(len(ae), bool)
    adj[np.unique(tr.query(np.asarray(ae.geometry.values), predicate='dwithin', distance=NEAR_M)[0])] = True
    ae['near_anthro'] = adj.astype(int)
    ae['near_road'] = ae['d_road_built'].fillna(1e9).le(NEAR_M).astype(int)
    owner = ae['step6_rule'].eq('v4_expert') | ae['step4_rule'].eq('expert_override')
    c = ae[(ae['area_ha'] >= MIN_HA) & ((ae['near_anthro'] == 1) | (ae['near_road'] == 1)) & ~owner].copy()
    ll = c.geometry.centroid.to_crs(4326)
    c['lat'], c['lon'] = ll.y.round(4), ll.x.round(4)
    return c.sort_values('area_ha', ascending=False).reset_index(drop=True)


def imagery_meta(lon: float, lat: float, z: int) -> str:
    import requests
    from qc_thumb_xyz import UA
    try:
        r = requests.get(META_URL, headers=UA, timeout=30, params={
            'geometry': f'{lon},{lat}', 'geometryType': 'esriGeometryPoint', 'sr': 4326, 'layers': f'all:{28 - z}',
            'tolerance': 0, 'mapExtent': f'{lon - 0.1},{lat - 0.1},{lon + 0.1},{lat + 0.1}',
            'imageDisplay': '1000,1000,96', 'returnGeometry': 'false', 'f': 'json'})
        a = r.json()['results'][0]['attributes']
        d = str(a['SRC_DATE'])
        return f'{SENSORS.get(a["SRC_DESC"], a["SRC_DESC"])}, {d[6:8]}.{d[4:6]}.{d[:4]}'
    except Exception:  # noqa: BLE001 - подпись без даты, причина в stderr
        traceback.print_exc()
        return 'дата снимка неизвестна'


def panel(ax, geom, lat: float, lon: float, side_m: float, min_px: int = 900) -> str:
    """Окно Esri вокруг геометрии (Web Mercator), красная граница, масштаб; возвращает сенсор и дату."""
    import matplotlib.patheffects as pe
    from PIL import Image
    from qc_thumb_xyz import R_MERC, TILE, fetch_tile, tile_xy
    k = 1.0 / math.cos(math.radians(lat))
    minx, miny, maxx, maxy = geom.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    half = side_m / 2 * k
    z = next((z for z in range(10, 18) if 2 * half / (2 * R_MERC / TILE / 2 ** z) >= min_px), 17)
    tx0, ty0 = tile_xy(cx - half, cy + half, z)
    tx1, ty1 = tile_xy(cx + half, cy - half, z)
    X0, Y0, X1, Y1 = int(tx0), int(ty0), int(tx1), int(ty1)
    m = Image.new('RGB', ((X1 - X0 + 1) * TILE, (Y1 - Y0 + 1) * TILE))
    for X in range(X0, X1 + 1):
        for Y in range(Y0, Y1 + 1):
            m.paste(fetch_tile(z, X, Y), ((X - X0) * TILE, (Y - Y0) * TILE))
    img = m.crop((int((tx0 - X0) * TILE), int((ty0 - Y0) * TILE), int((tx1 - X0) * TILE), int((ty1 - Y0) * TILE)))
    ax.imshow(img, extent=(cx - half, cx + half, cy - half, cy + half), interpolation='lanczos')
    for p in getattr(geom, 'geoms', [geom]):
        for ring in [p.exterior] + list(p.interiors):
            xs, ys = ring.xy
            ax.plot(xs, ys, color='#ff2a2a', lw=1.1, path_effects=[pe.withStroke(linewidth=2.2, foreground='black')])
    ax.set_xlim(cx - half, cx + half)
    ax.set_ylim(cy - half, cy + half)
    ax.set_xticks([])
    ax.set_yticks([])
    bar = max(b for b in BARS if b <= side_m * 0.3)
    x0, y0 = cx - half + 0.05 * 2 * half, cy - half + 0.05 * 2 * half
    halo = [pe.withStroke(linewidth=1.6, foreground='black')]
    ax.plot([x0, x0 + bar * k], [y0, y0], color='white', lw=2.2, path_effects=[pe.withStroke(linewidth=3.4, foreground='black')])
    ax.text(x0 + bar * k / 2, y0 + 0.02 * 2 * half, f'{bar // 1000} км' if bar >= 1000 else f'{bar} м', ha='center',
            va='bottom', color='white', fontsize=8, path_effects=halo)
    return imagery_meta(lon, lat, z)


def render(args: tuple) -> str:
    cid, wkb, lat, lon = args
    out = OUT / 'img' / f'{cid}.png'
    if out.exists():
        return str(out)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    try:
        g = shapely.from_wkb(wkb)
        g3857 = gpd.GeoSeries([g], crs=3576).to_crs(3857).iloc[0]
        k = 1.0 / math.cos(math.radians(lat))
        b = g3857.bounds
        span = max(b[2] - b[0], b[3] - b[1]) / k            # истинные метры
        fig, axes = plt.subplots(1, 2, figsize=(16, 8.3))
        m1 = panel(axes[0], g3857, lat, lon, max(span * 3, 1500))
        panel(axes[1], g3857, lat, lon, max(span * 1.25, 400))
        fig.suptitle(f'контур {cid}: {lat:.4f}° с. ш., {lon:.4f}° в. д.; снимок {m1}. Слева обзор, справа крупный план', fontsize=11)
        fig.tight_layout()
        fig.savefig(out, dpi=100)
        plt.close(fig)
        return str(out)
    except Exception:
        traceback.print_exc()
        return f'ОШИБКА {cid}'


def main() -> None:
    cpu_limit.apply()
    (OUT / 'img').mkdir(parents=True, exist_ok=True)
    (OUT / 'chunks').mkdir(exist_ok=True)
    c = candidates()
    print(f'кандидатов: {len(c)}, {c.area_ha.sum() / 100:.1f} км2; у техногенного {int(c.near_anthro.sum())}, у дороги {int(c.near_road.sum())}', flush=True)
    c.drop(columns=['geometry']).to_csv(OUT / 'batch.csv', index=False, encoding='utf-8')
    tasks = [(int(r.id), shapely.to_wkb(r.geometry), float(r.lat), float(r.lon)) for r in c.itertuples()]
    with ProcessPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(render, tasks, chunksize=2))
    bad = [r for r in res if r.startswith('ОШИБКА')]
    print(f'снимков: {len(res) - len(bad)}, ошибок: {len(bad)} {bad[:5]}', flush=True)
    # порядок для читателей перемешан с фиксированным зерном (не по площади), куски по CHUNK
    order = c['id'].sample(frac=1, random_state=20261005).tolist()
    for k in range(0, len(order), CHUNK):
        (OUT / 'chunks' / f'chunk_{k // CHUNK + 1}.txt').write_text('\n'.join(str(i) for i in order[k:k + CHUNK]), encoding='utf-8')
    print(f'кусков: {math.ceil(len(order) / CHUNK)} -> {OUT}', flush=True)


if __name__ == '__main__':
    main()
