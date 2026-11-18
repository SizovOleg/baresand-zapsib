"""
154_allot_review.py - окна для проверки правила отводов под локальные объекты (2026-10-13, редакция v7b).

Автор 13.10.2026: «дороги и трубопроводы выпали повсеместно»; «правильно выделить все отводы, именно для локальных
объектов». 133 --ezp --local-max-ha 1000 считает отводами части единых землепользований (обособленные и условные участки
без категории и ВРИ) и не считает отводами контуры крупнее 1000 га. Проверка на снимке Esri World Imagery:
- ezp: случайные N_RAND и N_TOP с наибольшим техногеном внутри части ЕЗП: лежит ли участок под локальным объектом
  (дорога, трубопровод, ЛЭП, куст, площадка, карьер) или это территория без объекта;
- noallot: случайные N_RAND и N_TOP крупнейших объектов без отвода v7b: нет ли рядом участка, который по снимку и
  атрибутам является отводом этого объекта, но правило его не засчитало.
Выход: <qc>/review_allot/{ezp,noallot}_NNN.jpg, items.csv (атрибуты участков ближе 60 м к объекту), index.html.
Запуск: PYTHONIOENCODING=utf-8 python -u python/154_allot_review.py [--qc exports/qc/cadastre_v7b]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import html
import importlib.util
import math
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import pyogrio
import shapely

matplotlib.use('Agg')
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT = Path(r'D:\test\baresand_zapsib')
N_TOP, N_RAND, SEED = 10, 30, 20261013
NEAR_M = 60.0
COLORS = {'ind': '#ffe600', 'vri': '#ffe600', 'np': '#ffe600', 'terr': '#ff3df5', 'ezp': '#7cff4f', 'big': '#00e5ff',
          'unk': '#00e5ff', 'forest': '#bbbbbb', 'agri': '#bbbbbb', 'misc': '#bbbbbb'}
STATUS = {'in': '#b07020', 'cross': '#ff00ff', 'unreg': '#ff2a2a'}

spec = importlib.util.spec_from_file_location('r152', ROOT / 'python' / '152_outside_review.py')
r152 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r152)


def window(g: shapely.Geometry) -> shapely.Geometry:
    minx, miny, maxx, maxy = g.bounds
    side = min(max(maxx - minx, maxy - miny, 600) * 1.6, 6000)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    return shapely.box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)


def render(path: Path, win: shapely.Geometry, par: gpd.GeoDataFrame, tech: gpd.GeoDataFrame, focus: shapely.Geometry,
           focus_color: str, title: str) -> None:
    to = lambda d: d.to_crs(3857)
    w = gpd.GeoSeries([win], crs=3576).to_crs(3857).iloc[0]
    fig, ax = plt.subplots(figsize=(8, 8), dpi=120)
    r152.esri(ax, *w.bounds, max_px=1500)
    pw = par[par.intersects(win)]
    for g, c in COLORS.items():
        s = pw[pw['grp'] == g]
        if len(s):
            to(s).boundary.plot(ax=ax, color=c, lw=0.7)
    tw = tech[tech.intersects(win)]
    for st, c in STATUS.items():
        s = tw[tw['cad_status'] == st]
        if len(s):
            to(s).plot(ax=ax, color=c, alpha=0.55, lw=0)
    to(gpd.GeoDataFrame(geometry=[focus], crs=3576)).boundary.plot(ax=ax, color=focus_color, lw=2.2)
    ax.set_xlim(w.bounds[0], w.bounds[2])
    ax.set_ylim(w.bounds[1], w.bounds[3])
    ax.set_xticks([])
    ax.set_yticks([])
    side = win.bounds[2] - win.bounds[0]
    k = 1 / math.cos(math.radians(gpd.GeoSeries([win.centroid], crs=3576).to_crs(4326).iloc[0].y))
    bar = 100 if side < 1500 else (500 if side < 4000 else 1000)
    x0, y0 = w.bounds[0] + 0.05 * (w.bounds[2] - w.bounds[0]), w.bounds[1] + 0.04 * (w.bounds[3] - w.bounds[1])
    ax.plot([x0, x0 + bar * k], [y0, y0], color='white', lw=2.5, path_effects=[pe.withStroke(linewidth=4, foreground='black')])
    ax.text(x0, y0 + 0.015 * (w.bounds[3] - w.bounds[1]), f'{bar} м', color='white', fontsize=9,
            path_effects=[pe.withStroke(linewidth=2, foreground='black')])
    ax.set_title(title, fontsize=9)
    ax.legend(handles=[Patch(fc='none', ec=focus_color, lw=2, label='проверяемый объект'),
                       Patch(fc=STATUS['in'], alpha=0.55, label='техноген в отводе'),
                       Patch(fc=STATUS['cross'], alpha=0.55, label='техноген с превышением'),
                       Patch(fc=STATUS['unreg'], alpha=0.55, label='техноген без отвода'),
                       Patch(fc='none', ec='#ffe600', label='отводы: промземли, объектовый ВРИ, НП'),
                       Patch(fc='none', ec='#7cff4f', label='отводы: части ЕЗП (новое правило)'),
                       Patch(fc='none', ec='#00e5ff', label='не отвод: крупнее 1000 га, без категории'),
                       Patch(fc='none', ec='#bbbbbb', label='не отвод: лесной фонд, сельхоз, иное'),
                       Patch(fc='none', ec='#ff3df5', label='территория НП')], loc='lower right', fontsize=6.5)
    fig.savefig(path, bbox_inches='tight', pil_kwargs={'quality': 85})
    plt.close(fig)


def describe(p: gpd.GeoDataFrame) -> str:
    """Атрибуты участков (ближе NEAR_M к объекту) одной строкой для агента."""
    out = []
    for r in p.itertuples():
        out.append(f'{r.cad_num or "территория НП"} [{r.grp}] {(r.cat or "")[:40]}; ВРИ: {(r.vri or "")[:120]}; '
                   f'{r.geometry.area / 1e4:.1f} га')
    return ' | '.join(out[:12]) + (f' | ... ещё {len(out) - 12}' if len(out) > 12 else '')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--qc', type=Path, default=ROOT / 'exports' / 'qc' / 'cadastre_v7b')
    a = ap.parse_args()
    layers = next(a.qc.glob('baresand_anthro_cadastre_*.gpkg'))
    product = next(a.qc.glob('baresand_genesis_*.gpkg'))
    out = a.qc / 'review_allot'
    out.mkdir(parents=True, exist_ok=True)
    par = pyogrio.read_dataframe(layers, layer='parcels')
    tech = pyogrio.read_dataframe(product, layer='genesis', where="genesis = 'anthropogenic'", columns=['id', 'cad_status', 'area_ha'])
    na = pyogrio.read_dataframe(layers, layer='anthro_noallot', columns=['id', 'area_ha', 'kind'])
    rng = np.random.default_rng(SEED)
    # ezp: части ЕЗП, пересекающие техноген; площадь техногена внутри части
    ezp = par[par['grp'] == 'ezp'].reset_index(drop=True)
    T = np.asarray(tech.geometry.values)
    ei, tj = shapely.STRtree(T).query(np.asarray(ezp.geometry.values), predicate='intersects')
    ia = shapely.area(shapely.intersection(np.asarray(ezp.geometry.values)[ei], T[tj])) / 1e4
    ezp['t_ha'] = pd.Series(ia).groupby(ei).sum().reindex(range(len(ezp)), fill_value=0).to_numpy()
    ezp = ezp[ezp['t_ha'] > 0]
    top = ezp.nlargest(N_TOP, 't_ha')
    rnd = ezp.drop(index=top.index).iloc[rng.choice(len(ezp) - len(top), N_RAND, replace=False)]
    s_ezp = pd.concat([top.assign(pick='наибольший техноген'), rnd.assign(pick='случайный')])
    top_n = na.nlargest(N_TOP, 'area_ha')
    rest = na.drop(index=top_n.index)
    rnd_n = rest.iloc[rng.choice(len(rest), N_RAND, replace=False)]
    s_na = pd.concat([top_n.assign(pick='крупнейший'), rnd_n.assign(pick='случайный')])
    ptree = shapely.STRtree(np.asarray(par.geometry.values))
    rows = []
    for n, r in enumerate(s_ezp.itertuples(), 1):
        g = r.geometry
        tt = tech[tech.intersects(g)]
        focus_area = shapely.union_all(np.asarray(tt.geometry.values)) if len(tt) else g
        win = window(shapely.intersection(g, focus_area.buffer(200)) if len(tt) else g)
        fn = f'ezp_{n:03d}.jpg'
        render(out / fn, win, par, tech, g, '#7cff4f', f'часть ЕЗП {r.cad_num}, {g.area / 1e4:.1f} га, техногена внутри '
               f'{r.t_ha:.1f} га ({r.pick})')
        rows.append({'file': fn, 'kind': 'ezp', 'pick': r.pick, 'key': r.cad_num, 'area_ha': round(g.area / 1e4, 2),
                     't_ha': round(r.t_ha, 2), 'parcels': describe(par.iloc[ptree.query(g, predicate='dwithin', distance=NEAR_M)].head(13))})
    for n, r in enumerate(s_na.itertuples(), 1):
        g = r.geometry
        win = window(g)
        fn = f'noallot_{n:03d}.jpg'
        render(out / fn, win, par, tech, g, '#ffffff', f'без отвода, контур {int(r.id)}, {r.area_ha:.1f} га, {r.kind} ({r.pick})')
        rows.append({'file': fn, 'kind': 'noallot', 'pick': r.pick, 'key': int(r.id), 'area_ha': round(r.area_ha, 2), 't_ha': None,
                     'parcels': describe(par.iloc[ptree.query(g, predicate='dwithin', distance=NEAR_M)].head(13)) or 'участков ближе 60 м нет'})
    d = pd.DataFrame(rows)
    d.to_csv(out / 'items.csv', index=False, encoding='utf-8')
    body = ''.join(f'<h3>{html.escape(r.file)}</h3><p>{html.escape(str(r.parcels))}</p><img src="{r.file}" style="max-width:100%">'
                   for r in d.itertuples())
    (out / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Проверка отводов</title><body style="font:15px '
                                    'system-ui;max-width:900px;margin:auto;padding:16px"><h2>Части ЕЗП и объекты без отвода '
                                    '(154)</h2>' + body + '</body>', encoding='utf-8')
    print(f'-> {out / "index.html"} ({len(d)} окон)')


if __name__ == '__main__':
    main()
