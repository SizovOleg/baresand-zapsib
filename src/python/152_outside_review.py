"""
152_outside_review.py - проверка внешних слоёв техногена (вариант А) на снимках (2026-10-13).

Слои 133 с территорией населённых пунктов как отводом: anthro_exceed (превышение отвода, части за допуском 10 м) и
anthro_noallot (объекты без отвода целиком). Выборка на класс: N_TOP крупнейших объектов и N_RAND случайных (зерно SEED);
для превышения объект = контур (сумма частей по id). Окно Esri World Imagery по контуру с запасом: контур техногена
(зелёный), превышение (красная заливка), отводы под объекты (жёлтый), территория населённых пунктов (пурпурный).
Цель: найти остатки населённых пунктов, дач, аэродромов, природные пески и смешанные контуры во внешних слоях.
Выход: <qc>/review_outside/<класс>_<n>.jpg, sample.csv, index.html.
Запуск: PYTHONIOENCODING=utf-8 python -u python/152_outside_review.py [--qc exports/qc/cadastre_v7a]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import html
import math
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
import shapely
from matplotlib.patches import Patch

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
TERR = ROOT / 'exports' / 'qc' / 'territory' / 'territory.gpkg'
N_TOP, N_RAND, SEED = 20, 30, 20261013


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def esri(ax, minx: float, miny: float, maxx: float, maxy: float, max_px: int = 1300) -> str:
    from PIL import Image
    from qc_thumb_xyz import R_MERC, TILE, fetch_tile, tile_xy
    z = next((z for z in range(17, 8, -1) if (maxx - minx) / (2 * R_MERC / TILE / 2 ** z) <= max_px), 9)
    tx0, ty0 = tile_xy(minx, maxy, z)
    tx1, ty1 = tile_xy(maxx, miny, z)
    X0, Y0, X1, Y1 = int(tx0), int(ty0), int(tx1), int(ty1)
    m = Image.new('RGB', ((X1 - X0 + 1) * TILE, (Y1 - Y0 + 1) * TILE))
    for X in range(X0, X1 + 1):
        for Y in range(Y0, Y1 + 1):
            m.paste(fetch_tile(z, X, Y), ((X - X0) * TILE, (Y - Y0) * TILE))
    img = m.crop((int((tx0 - X0) * TILE), int((ty0 - Y0) * TILE), int((tx1 - X0) * TILE), int((ty1 - Y0) * TILE)))
    ax.imshow(img, extent=(minx, maxx, miny, maxy), interpolation='lanczos')
    return f'z{z}'


def sample(d: pd.DataFrame, key: str) -> pd.DataFrame:
    top = d.nlargest(N_TOP, key)
    rest = d.drop(index=top.index)
    rnd = rest.sample(min(N_RAND, len(rest)), random_state=SEED)
    return pd.concat([top.assign(pick='крупнейший'), rnd.assign(pick='случайный')])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--qc', type=Path, default=ROOT / 'exports' / 'qc' / 'cadastre_v7a')
    a = ap.parse_args()
    cpu_limit.apply_cores(12)
    layers = next(a.qc.glob('baresand_anthro_cadastre_*.gpkg'))
    product = next(a.qc.glob('baresand_genesis_*.gpkg'))
    out = a.qc / 'review_outside'
    out.mkdir(parents=True, exist_ok=True)
    ex = pyogrio.read_dataframe(layers, layer='anthro_exceed')
    na = pyogrio.read_dataframe(layers, layer='anthro_noallot')
    allot = pyogrio.read_dataframe(layers, layer='parcels', where="grp IN ('ind', 'vri', 'np')", columns=['grp'])
    terr = pyogrio.read_dataframe(TERR, layer='territory')
    exa = ex.groupby('id').agg(area_ha=('area_ha', 'sum'), in_pct=('in_pct', 'first'), age2000=('age2000', 'first')).reset_index()
    s_ex = sample(exa, 'area_ha').assign(cls='exceed')
    s_na = sample(na.drop(columns='geometry'), 'area_ha').assign(cls='noallot')
    s = pd.concat([s_ex, s_na], ignore_index=True)
    ids = s['id'].astype(int).tolist()
    ctr = pyogrio.read_dataframe(product, layer='genesis', columns=['id', 'area_ha'], where=f"id IN ({','.join(map(str, ids))})")
    ctr = ctr.set_index('id')
    rows = []
    for n, r in enumerate(s.itertuples(), 1):
        g = ctr.geometry.loc[int(r.id)]
        minx, miny, maxx, maxy = g.bounds
        side = max(maxx - minx, maxy - miny, 600) * 1.6
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        win = shapely.box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
        to = lambda x: gpd.GeoSeries(x, crs=ctr.crs).to_crs(3857)
        w = to([win]).iloc[0]
        fig, ax = plt.subplots(figsize=(7, 7), dpi=130)
        esri(ax, *w.bounds)
        al = allot[allot.intersects(win)]
        if len(al):
            to(al.geometry).boundary.plot(ax=ax, color='#ffe600', lw=0.8)
        tw = terr[terr.intersects(win)]
        if len(tw):
            to(tw.geometry).boundary.plot(ax=ax, color='#ff3df5', lw=1.0, linestyle='--')
        if r.cls == 'exceed':
            e = ex[ex['id'] == r.id]
            to(e.geometry).plot(ax=ax, color='#ff2a2a', alpha=0.55, lw=0)
        to([g]).boundary.plot(ax=ax, color='#3dff6e', lw=1.1)
        ax.set_xlim(w.bounds[0], w.bounds[2])
        ax.set_ylim(w.bounds[1], w.bounds[3])
        ax.set_xticks([])
        ax.set_yticks([])
        k = 1 / math.cos(math.radians(gpd.GeoSeries([win.centroid], crs=ctr.crs).to_crs(4326).iloc[0].y))
        bar = 100 if side < 1500 else (500 if side < 6000 else 2000)
        x0, y0 = w.bounds[0] + 0.05 * (w.bounds[2] - w.bounds[0]), w.bounds[1] + 0.04 * (w.bounds[3] - w.bounds[1])
        ax.plot([x0, x0 + bar * k], [y0, y0], color='white', lw=2.5, path_effects=[pe.withStroke(linewidth=4, foreground='black')])
        ax.text(x0, y0 + 0.015 * (w.bounds[3] - w.bounds[1]), f'{bar} м', color='white', fontsize=9,
                path_effects=[pe.withStroke(linewidth=2, foreground='black')])
        name = 'превышение отвода' if r.cls == 'exceed' else 'без отвода'
        ax.set_title(f'{name}, {r.pick}: контур {int(r.id)}, {r.area_ha:.1f} га', fontsize=9)
        ax.legend(handles=[Patch(facecolor='none', edgecolor='#3dff6e', label='контур техногена'),
                           Patch(facecolor='#ff2a2a', alpha=0.55, label='превышение'),
                           Patch(facecolor='none', edgecolor='#ffe600', label='отводы ЕГРН'),
                           Patch(facecolor='none', edgecolor='#ff3df5', linestyle='--', label='территория НП')],
                  loc='lower right', fontsize=7)
        fn = f'{r.cls}_{n:03d}.jpg'
        fig.savefig(out / fn, bbox_inches='tight', pil_kwargs={'quality': 85})
        plt.close(fig)
        rows.append({'file': fn, 'cls': r.cls, 'pick': r.pick, 'id': int(r.id), 'area_ha': round(float(r.area_ha), 2),
                     'age2000': getattr(r, 'age2000', None)})
        if n % 20 == 0:
            log(f'{n} из {len(s)}')
    d = pd.DataFrame(rows)
    d.to_csv(out / 'sample.csv', index=False, encoding='utf-8')
    body = ''.join(f'<h3>{html.escape(r.file)}</h3><img src="{r.file}" style="max-width:100%">' for r in d.itertuples())
    (out / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Внешние слои техногена</title><body style="'
                                    'font:15px system-ui;max-width:900px;margin:auto;padding:16px"><h2>Превышение отвода и объекты '
                                    'без отвода: выборка для проверки (152)</h2>' + body + '</body>', encoding='utf-8')
    log(f'-> {out / "index.html"} ({len(d)} окон)')


if __name__ == '__main__':
    main()
