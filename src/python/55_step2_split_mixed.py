"""
55_step2_split_mixed.py — разрез смешанных контуров речного/озёрного класса (шаг 2, итерация 2).

Проблема (финальная проверка эксперта, Rivers.shp): контур маски объединяет отмель у воды с раздувом на склоне/террасе
или с насыпью дороги — 349171 (раздув 59 га в цепочке побочней 999 га), 463492 (дороги 170 га), 313156/373168/542670
(«раздув с отмелью, разрезать»). Правило шага 2 (51) присваивает класс контуру целиком → раздув уходит в отмели.

Метод (попиксельно, PX_M = 10 м — родное разрешение маски, EPSG:3576, окно контура + PAD_M). Сухое ядро двух типов:
  (i)  далёкое: пиксели, которые никогда не заливались (GSW occurrence == 0) и дальше FAR_DIST_M (реки, 500 м) /
       FAR_DIST_LAKE_M (озёра, 300 м) от постоянной воды (GSW occ ≥ WATER_OCC) и от русловой сети MERIT — насыпи дорог,
       площадки; на реках порог больше: внутренние части широких побочней лежат в 300–500 м от меженного русла;
  (ii) широкие тела: морфологическое открытие контура радиусами R_OPEN_M (50 и 75 м) убирает полосы уже 2·R (бары узких
       рек — полосы, раздувы/карьеры — блобы); тело сухое, если доля пикселей occ > 0 в нём < BLOB_WET_MAX и медиана
       расстояния до воды/русла > BLOB_DMIN_MIN_M (осерёдки больших рек залиты на 100 %; широкие бары узких рек — occ>0
       у 16–29 % и медиана 30 м от русла; раздувы 349171/313156/542670 и карьер 441428 — occ>0 ≤ 10 %, 80–480 м).
  --grow: ядро дорастает по никогда не заливавшимся пикселям контура дальше GROW_MIN_DIST_M от воды (без роста —
       консервативно: у раздува остаётся прибрежная кайма).
  Сухие части < MIN_PART_HA или «утопленные» в отмель (общая граница > SHARED_MAX периметра — сухая макушка бара, не лопасть)
  остаются в отмели; сухая часть ≥ WHOLE_DRY_FRAC → весь контур в unassigned.
Почему не «дальше 150 м от воды» (вариант итерации 2a): осерёдок Енисея 574271 (379 га, эксперт: чистый бар) режется на 36 %,
цепочки баров узких рек (179787, 138791) — на 30 %: GSW видит воду лишь у 40–46 % пикселей их баров.

Вход:  exports/baresand_genesis_step2_<tag>.gpkg — river_shoal / lake_shoal с area_ha ≥ MIN_SPLIT_HA
Выход: exports/baresand_genesis_step2_<tag>_split.gpkg — отмель сохраняет id (геометрия уменьшена, split_n > 0),
       сухие части: id = PART_ID_BASE + n, parent_id = исходный id, genesis = unassigned, step2_rule = <tag>_split_dry,
       split_from = исходный класс, part_kind = far / blob / mixed; улики частей не пересчитываются (NaN, кроме ero50).
       exports/qc/step2/split_report_<tag>.csv — по каждому разрезанному контуру: dry_frac, n_parts, площади.
Запуск: python -u python/55_step2_split_mixed.py --tag v2 [--grow] [--ids 349171 463492 --out test.gpkg --no-regression]
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import argparse
import time
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize, shapes
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from scipy import ndimage as ndi
from shapely.geometry import shape
from shapely.ops import unary_union

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC2 = EXPORTS / 'qc' / 'step2'
GSW_OCC = EXPORTS / 'gsw_occurrence_AOI.vrt'
CHANNEL_DIST = QC2 / 'channel90_dist.tif'
REGRESSION = QC2 / 'regression_step2.csv'
SAMPLE_GEOMS = QC2 / 'visual_sample_geoms_step2.gpkg'
EA_CRS = 'EPSG:3576'

PX_M = 10.0                 # рабочее разрешение (родное для маски)
PAD_M = 600.0               # запас окна вокруг контура — чтобы вода снаружи попала в EDT
WATER_OCC = 50              # постоянная вода GSW (как в 50_step2_water_evidence)
MIN_SPLIT_HA = 5.0          # контуры меньше не режем
FAR_DIST_M = 500.0          # далёкое ядро (речной класс): никогда не заливалось ∧ дальше этого от воды/русла;
                            # 300 м режет внутренние части широких побочней (5 из 7 в QC), дороги 463492 лежат ≥ 518 м
FAR_DIST_LAKE_M = 300.0     # далёкое ядро (озёрный класс): пляжи узкие, дороги/площадки у озёр в 300–500 м — техноген
R_OPEN_M = (50.0, 75.0)     # радиусы открытия (многомасштабно): полосы уже 2·R (бары узких рек) не считаются телами
BLOB_WET_MAX = 0.12         # тело сухое, если доля occ > 0 меньше (ложные тела-бары 0.16–0.29, раздувы/карьер ≤ 0.10)
BLOB_DMIN_MIN_M = 50.0      # ... и медианное расстояние тела до воды/русла больше (бары прижаты к руслу: медиана ≈ 30 м)
GROW_MIN_DIST_M = 90.0      # --grow: дорастать только по пикселям дальше этого от воды
MIN_PART_HA = 2.0           # сухая часть меньше — остаётся в отмели
SHARED_MAX = 0.5            # часть, у которой > этой доли периметра — общая граница с отмелью, «утоплена» в бар → остаётся
                            # (ложные части на 349171: 0.51–0.54; лопасти раздувов 349171/313156/542670: 0.22–0.30)
WHOLE_DRY_FRAC = 0.9        # сухая часть ≥ доли → весь контур unassigned
PART_ID_BASE = 700_000      # id сухих частей (id маски ≤ 574 544; синтетические id эксперта ≥ 9e8)
CLASSES = ('river_shoal', 'lake_shoal')
LOG_EVERY = 500


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


class Evidence:
    """Открытые растры + чтение окна контура в равновеликой сетке PX_M."""

    def __init__(self) -> None:
        self.occ = rasterio.open(GSW_OCC)
        self.chd = rasterio.open(CHANNEL_DIST)

    def close(self) -> None:
        for s in (self.occ, self.chd):
            s.close()

    @staticmethod
    def grid(geom):
        x0, y0, x1, y1 = geom.bounds
        x0, y0, x1, y1 = x0 - PAD_M, y0 - PAD_M, x1 + PAD_M, y1 + PAD_M
        w, h = int(np.ceil((x1 - x0) / PX_M)), int(np.ceil((y1 - y0) / PX_M))
        return from_origin(x0, y1, PX_M, PX_M), w, h

    @staticmethod
    def _read(src, tr, w, h):
        with WarpedVRT(src, crs=EA_CRS, transform=tr, width=w, height=h, resampling=Resampling.nearest) as v:
            return v.read(1)

    def window(self, geom):
        tr, w, h = self.grid(geom)
        occ = self._read(self.occ, tr, w, h)
        chd = self._read(self.chd, tr, w, h)
        water = occ >= WATER_OCC
        dist_w = ndi.distance_transform_edt(~water) * PX_M if water.any() else np.full(occ.shape, 1e6, dtype='float32')
        dmin = np.minimum(dist_w, chd)
        inside = rasterize([(geom, 1)], out_shape=(h, w), transform=tr, fill=0, all_touched=False).astype(bool)
        return dict(occ=occ, dmin=dmin, inside=inside, tr=tr)


def dry_mask(e: dict, grow: bool, blob_wet: float = BLOB_WET_MAX, min_part: float = MIN_PART_HA, grow_dist: float = GROW_MIN_DIST_M,
             far_dist: float = FAR_DIST_M):
    """Маска сухих пикселей контура и тип ядра ('far' / 'blob') по пикселям."""
    inside, occ, dmin = e['inside'], e['occ'], e['dmin']
    occ0 = occ == 0
    far = inside & occ0 & (dmin > far_dist)
    blob = np.zeros_like(inside)
    edt_in = ndi.distance_transform_edt(inside)
    for r_m in R_OPEN_M:
        r_px = r_m / PX_M
        eroded = edt_in > r_px
        if not eroded.any():
            continue
        opened = inside & (ndi.distance_transform_edt(~eroded) <= r_px)
        lab, n = ndi.label(opened)
        if not n:
            continue
        idx = np.arange(1, n + 1)
        wet = ndi.mean((occ > 0).astype('float32'), lab, index=idx)
        dmed = ndi.median(dmin, lab, index=idx)
        area_ha = ndi.sum(opened, lab, index=idx) * PX_M ** 2 / 1e4
        blob |= np.isin(lab, idx[(wet < blob_wet) & (dmed > BLOB_DMIN_MIN_M) & (area_ha >= min_part)])
    core = far | blob
    if not core.any():
        return None, None
    if grow:
        lab2, _ = ndi.label(core | (inside & occ0 & (dmin > grow_dist)))
        touch = np.unique(lab2[core])
        dry = np.isin(lab2, touch[touch > 0]) & inside
    else:
        dry = core
    kind = np.where(blob, 2, np.where(far, 1, 0)).astype('uint8')   # 1 far, 2 blob, 0 — дорост
    return dry, kind


def split_contour(geom, ev: Evidence, grow: bool, blob_wet: float = BLOB_WET_MAX, min_part: float = MIN_PART_HA, grow_dist: float = GROW_MIN_DIST_M,
                  far_dist: float = FAR_DIST_M, shared_max: float = SHARED_MAX):
    """→ (геометрия отмели | None, [(геометрия сухой части, вид)], dry_frac). None = весь контур сухой."""
    e = ev.window(geom)
    n_in = int(e['inside'].sum())
    if n_in == 0:
        return geom, [], 0.0
    dry, kind = dry_mask(e, grow, blob_wet, min_part, grow_dist, far_dist)
    if dry is None:
        return geom, [], 0.0
    dry_frac = float(dry.sum()) / n_in
    if dry_frac >= WHOLE_DRY_FRAC:
        return None, [], 1.0
    polys = [shape(s) for s, v in shapes(dry.astype('uint8'), mask=dry, transform=e['tr'], connectivity=4) if v == 1]
    if not polys:
        return geom, [], 0.0
    dry_geom = unary_union(polys).intersection(geom)
    parts = [p for p in getattr(dry_geom, 'geoms', [dry_geom]) if p.area / 1e4 >= min_part]
    if not parts:
        return geom, [], 0.0
    shoal = geom.difference(unary_union(parts))
    if shoal.is_empty or shoal.area / 1e4 < min_part:
        return None, [], 1.0
    halo = shoal.buffer(1.0)
    parts = [p for p in parts if p.boundary.intersection(halo).length / p.length <= shared_max]
    if not parts:
        return geom, [], 0.0
    shoal = geom.difference(unary_union(parts))
    out = []
    for p in parts:
        m = rasterize([(p, 1)], out_shape=dry.shape, transform=e['tr'], fill=0, all_touched=False).astype(bool)
        k = kind[m & dry]
        n_far, n_blob = int((k == 1).sum()), int((k == 2).sum())
        out.append((p, 'blob' if n_blob >= n_far and n_blob else ('far' if n_far else 'mixed')))
    return shoal, out, sum(p.area for p, _ in out) / geom.area


def regression(g: gpd.GeoDataFrame, tag: str) -> None:
    """Как в 51: по id; для id, которых нет в результате (части разрезов), — по геометрии из visual_sample_geoms_step2.gpkg."""
    if not REGRESSION.exists():
        print('  регрессионного набора нет')
        return
    reg = pd.read_csv(REGRESSION)
    m = reg.merge(g[['id', 'genesis']], on='id', how='left')
    m['by_geom'] = False
    # разрезанные контуры и контуры со снятым классом оцениваем по исходной геометрии, а не по остатку с тем же id
    touched = set(g.loc[(g.get('split_n', 0) > 0) | g['step2_rule'].fillna('').str.endswith('_whole_dry'), 'id'])
    m.loc[m['id'].isin(touched), 'genesis'] = np.nan
    missing = m['genesis'].isna()
    if missing.any() and SAMPLE_GEOMS.exists():
        sg = gpd.read_file(SAMPLE_GEOMS, layer='sample').to_crs(EA_CRS).set_index('id')
        sidx = g.sindex
        for i in m.index[missing]:
            cid = int(m.at[i, 'id'])
            if cid not in sg.index:
                continue
            geom = sg.at[cid, 'geometry']
            hits = g.iloc[sidx.query(geom, predicate='intersects')]
            best, bf = 'unassigned', 0.0
            for c in CLASSES:
                u = hits.loc[hits['genesis'] == c, 'geometry']
                f = geom.intersection(u.union_all()).area / geom.area if len(u) and geom.area > 0 else 0.0
                if f > bf:
                    best, bf = c, f
            m.at[i, 'genesis'] = best if bf >= 0.5 else 'unassigned'
            m.at[i, 'by_geom'] = True
    exp, got = m['expected_genesis'], m['genesis'].fillna('unassigned')
    got_n = got.replace({'shoal': 'unassigned'})
    ok = (exp == got_n) | ((exp == 'any_shoal') & got.isin(CLASSES))
    print(f'\n  РЕГРЕССИЯ [{tag}]: {int(ok.sum())}/{len(m)} ({100 * ok.mean():.0f}%)')
    for _, r in m[~ok].iterrows():
        print(f'    {int(r.id)} → {r.expected_genesis} / {r.genesis} [{r.get("stratum", "")}]')
    print(f'    (по геометрии: {int(m.by_geom.sum())} строк)')
    m.to_csv(QC2 / f'regression_report_step2_{tag}.csv', index=False, encoding='utf-8')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='v2', help='тег входного результата 51')
    ap.add_argument('--out', default=None, help='выходной gpkg (по умолчанию <вход>_split.gpkg)')
    ap.add_argument('--ids', type=int, nargs='*', default=None, help='тест: только эти id')
    ap.add_argument('--grow', action='store_true', help='дорастать ядро по никогда не заливавшимся пикселям')
    ap.add_argument('--min-ha', type=float, default=MIN_SPLIT_HA)
    ap.add_argument('--no-regression', action='store_true')
    ap.add_argument('--blob-wet', type=float, default=BLOB_WET_MAX, help='порог доли occ>0 для сухого тела')
    ap.add_argument('--min-part', type=float, default=MIN_PART_HA, help='мин. площадь сухой части, га')
    ap.add_argument('--grow-dist', type=float, default=GROW_MIN_DIST_M, help='--grow: дорастать дальше этого от воды, м')
    ap.add_argument('--far-dist', type=float, default=FAR_DIST_M, help='далёкое ядро (речной класс): дальше этого от воды/русла, м')
    ap.add_argument('--far-dist-lake', type=float, default=FAR_DIST_LAKE_M, help='далёкое ядро (озёрный класс), м')
    ap.add_argument('--shared-max', type=float, default=SHARED_MAX, help='макс. доля периметра части, общая с отмелью')
    a = ap.parse_args()
    t0 = time.time()
    src = EXPORTS / f'baresand_genesis_step2_{a.tag}.gpkg'
    out = Path(a.out) if a.out else EXPORTS / f'baresand_genesis_step2_{a.tag}_split.gpkg'
    otag = f'{a.tag}s{"G" if a.grow else "C"}'

    log(f'читаю {src.name}...')
    g = gpd.read_file(src).to_crs(EA_CRS)
    g['parent_id'] = pd.to_numeric(g['parent_id'], errors='coerce').fillna(g['id']).astype('int64')
    if a.ids:
        g = g[g['id'].isin(a.ids)].copy()
    g = g.reset_index(drop=True)
    cand = g['genesis'].isin(CLASSES) & (g['area_ha'] >= a.min_ha)
    n_cand = int(cand.sum())
    log(f'контуров {len(g):,}; кандидатов на разрез (≥ {a.min_ha} га, {"/".join(CLASSES)}): {n_cand:,}')

    ev = Evidence()
    new_geoms, whole_dry, part_rows, report = {}, [], [], []
    next_id = PART_ID_BASE
    for k, (i, r) in enumerate(g[cand].iterrows(), start=1):
        shoal, parts, dry_frac = split_contour(r.geometry, ev, a.grow, a.blob_wet, a.min_part, a.grow_dist,
                                               a.far_dist_lake if r['genesis'] == 'lake_shoal' else a.far_dist, a.shared_max)
        if shoal is None:
            whole_dry.append(i)
            report.append(dict(id=int(r['id']), genesis=r['genesis'], area_ha=r['area_ha'], dry_frac=1.0, n_parts=0,
                               dry_ha=r['area_ha'], whole_dry=True))
        elif parts:
            new_geoms[i] = shoal
            for p, kind in parts:
                part_rows.append(dict(id=next_id, parent_id=int(r['id']), genesis='unassigned', step2_rule=f'{otag}_split_dry',
                                      split_from=r['genesis'], part_kind=kind, area_ha=round(p.area / 1e4, 3),
                                      area_km2=p.area / 1e6, ero50=round(p.buffer(-50).area / p.area, 3), geometry=p))
                next_id += 1
            report.append(dict(id=int(r['id']), genesis=r['genesis'], area_ha=r['area_ha'], dry_frac=round(dry_frac, 3),
                               n_parts=len(parts), dry_ha=round(sum(p.area for p, _ in parts) / 1e4, 2), whole_dry=False))
        if k % LOG_EVERY == 0:
            log(f'  {k:,} / {n_cand:,} обработано, разрезано {len(report):,}, сухих частей {len(part_rows):,}')
    ev.close()

    # ── сборка ──
    geoms = g.geometry.values.copy()
    for i, s in new_geoms.items():
        geoms[i] = s
    g = g.set_geometry(gpd.GeoSeries(geoms, index=g.index, crs=EA_CRS))
    counts = Counter(pr['parent_id'] for pr in part_rows)
    g['split_n'] = g['id'].map(counts).fillna(0).astype('int16')
    g['split_from'] = ''
    g['part_kind'] = ''
    if whole_dry:
        g.loc[whole_dry, 'split_from'] = g.loc[whole_dry, 'genesis']
        g.loc[whole_dry, 'genesis'] = 'unassigned'
        g.loc[whole_dry, 'step2_rule'] = f'{otag}_whole_dry'
    kept = list(new_geoms)
    g.loc[kept, 'area_ha'] = (g.loc[kept, 'geometry'].area / 1e4).round(3)
    g.loc[kept, 'area_km2'] = g.loc[kept, 'geometry'].area / 1e6
    res = g
    if part_rows:
        parts_gdf = gpd.GeoDataFrame(part_rows, geometry='geometry', crs=EA_CRS)
        res = gpd.GeoDataFrame(pd.concat([g, parts_gdf], ignore_index=True), geometry='geometry', crs=EA_CRS)

    rep = pd.DataFrame(report)
    rep.to_csv(QC2 / f'split_report_{otag}.csv', index=False, encoding='utf-8')
    L = [f'разрезано контуров: {len(rep):,} из {n_cand:,} кандидатов; целиком сухих (класс снят): {len(whole_dry):,}']
    if part_rows:
        kinds = Counter(pr['part_kind'] for pr in part_rows)
        L.append(f'сухих частей: {len(part_rows):,} | {sum(pr["area_km2"] for pr in part_rows):.1f} км² '
                 f'(медиана {np.median([pr["area_ha"] for pr in part_rows]):.1f} га); виды: {dict(kinds)}; '
                 f'медиана dry_frac {rep.dry_frac.median():.2f}, ≥ 0.5 у {(rep.dry_frac >= 0.5).sum():,}')
    for cls in CLASSES:
        s = res[res['genesis'] == cls]
        L.append(f'  {cls:12s}: {len(s):7,} конт | {s.area_km2.sum():7.1f} км²')
    print('\n' + '\n'.join(L))
    if a.ids and len(rep):
        print(rep.to_string())
    if not a.no_regression:
        regression(res, otag)

    keep = [c for c in ['id', 'parent_id', 'area_ha', 'area_km2', 'genesis', 'genesis_v1', 'shoal_rule', 'step2_rule', 'needs_split',
                        'split_n', 'split_from', 'part_kind', 'anthro_suspect', 'khasyrei_suspect', 'ero50', 'dist_sea_m',
                        'dist_water_m', 'dist_channel_m', 'nearest_type', 'comp_area_km2', 'comp_upa_km2', 'comp_elong',
                        'comp_seas_max', 'flood_frac0', 'flood_frac10', 'hnd_min', 'upa_max', 'gsw_seas_max', 'geometry']
            if c in res.columns]
    res[keep].to_file(out, layer='genesis', driver='GPKG')
    (QC2 / f'split_summary_{otag}.txt').write_text('\n'.join(L), encoding='utf-8')
    log(f'сохранено {out} | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
