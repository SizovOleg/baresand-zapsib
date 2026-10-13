"""
BareSand — Локальные улики для QC класса «прибрежные» (без GEE).

Замена GEE-варианту (42_*) при исчерпанной квоте. Признаки:
  hnd_min       — высота над ближайшим водотоком (MERIT, 90 м). У побережья ближайшая
                  «дренажная» поверхность — море → прокси высоты над уровнем моря.
                  Морская отмель ≈ 0–2 м; терраса — выше. (у 75% контуров это 1 пиксель —
                  грубо, но для скрининга годится)
  upa_max       — водосбор ближайшего водотока (км²) — речная позиция.
  gsw_occ_*     — история воды 1984–2021 (уже посчитано).
  dist_perm_m   — расстояние от контура до ближайшей постоянной воды (GSW occ ≥ 80), м,
                  из локального растра (EDT в окне вокруг контура, анизотропия по широте учтена).

Вход:  exports/qc/qc_step1_shoal_review.gpkg, qc_step1_omission_candidates.gpkg,
       exports/baresand_littoral_v2.gpkg (hnd/upa/gsw по id), exports/gsw_occurrence_AOI.vrt
Выход: exports/qc/qc_step1_evidence_local.gpkg / .csv
Запуск: python -u python/43_qc_step1_evidence_local.py
"""
import sys, math, time
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.windows import from_bounds
from rasterio.features import rasterize
from scipy import ndimage

sys.stdout.reconfigure(encoding='utf-8')

QC = Path(r'D:\test\baresand_zapsib\exports\qc')
EXPORTS = QC.parent
SHOAL, CAND = QC / 'qc_step1_shoal_review.gpkg', QC / 'qc_step1_omission_candidates.gpkg'
ATTRS = EXPORTS / 'baresand_littoral_v2.gpkg'
GSW = EXPORTS / 'gsw_occurrence_AOI.vrt'
OUT_GPKG, OUT_CSV = QC / 'qc_step1_evidence_local.gpkg', QC / 'qc_step1_evidence_local.csv'

CAND_MIN_AREA_HA = 2.0
PERM_OCC = 80
WIN_DEG_LAT, WIN_DEG_LON = 0.05, 0.15     # ~5.5 км по широте, ~5 км по долготе на 70°N
DIST_CAP_M = 6000.0


def dist_to_perm(geom_wgs, src) -> float:
    """Мин. расстояние (м) от пикселей контура до ближайшей постоянной воды в окне."""
    minx, miny, maxx, maxy = geom_wgs.bounds
    b = (minx - WIN_DEG_LON, miny - WIN_DEG_LAT, maxx + WIN_DEG_LON, maxy + WIN_DEG_LAT)
    win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
    occ = src.read(1, window=win, boundless=True, fill_value=0)
    if occ.size == 0:
        return np.nan
    perm = occ >= PERM_OCC
    if not perm.any():
        return DIST_CAP_M
    tr = src.window_transform(win)
    lat_c = (miny + maxy) / 2
    dy = abs(tr.e) * 111_320.0
    dx = abs(tr.a) * 111_320.0 * math.cos(math.radians(lat_c))
    edt = ndimage.distance_transform_edt(~perm, sampling=(dy, dx))
    cmask = rasterize([(geom_wgs, 1)], out_shape=occ.shape, transform=tr, fill=0, all_touched=True).astype(bool)
    if not cmask.any():
        return np.nan
    return float(min(edt[cmask].min(), DIST_CAP_M))


def main() -> None:
    t0 = time.time()
    sh = gpd.read_file(SHOAL); sh['layer'] = 'shoal'
    cand = gpd.read_file(CAND)
    cand = cand[(cand['likely_shoal'] == 1) | (cand['area_ha'] >= CAND_MIN_AREA_HA)].copy(); cand['layer'] = 'cand'
    keep = ['id', 'layer', 'area_ha', 'dist_m', 'gsw_occ_mean', 'gsw_occ_max', 'lat', 'lon', 'geometry']
    g = gpd.GeoDataFrame(pd.concat([sh[keep + ['suspect']], cand[keep + ['likely_shoal']]], ignore_index=True),
                         geometry='geometry', crs=sh.crs)
    print(f'shoal {len(sh):,} | cand {len(cand):,} | всего {len(g):,}')

    attrs = gpd.read_file(ATTRS, ignore_geometry=True)[['id', 'hnd_min', 'upa_max', 'gsw_seas_max']]
    g = g.merge(attrs, on='id', how='left', validate='1:1')

    gw = g.to_crs('EPSG:4326')
    d = np.full(len(g), np.nan)
    with rasterio.open(GSW) as src:
        for i, geom in enumerate(gw.geometry):
            d[i] = dist_to_perm(geom, src)
            if (i + 1) % 500 == 0:
                print(f'  dist_perm: {i+1:,}/{len(g):,}', flush=True)
    g['dist_perm_m'] = np.round(d, 0)

    g.to_file(OUT_GPKG, layer='evidence', driver='GPKG')
    g.drop(columns='geometry').to_csv(OUT_CSV, index=False, encoding='utf-8')

    def q(s): return s.quantile([.1, .25, .5, .75, .9]).round(1).tolist()
    print('\n── hnd_min (м), p10/25/50/75/90 ──')
    print('  shoal suspect=0 :', q(g[(g.layer=='shoal')&(g.suspect==0)].hnd_min.dropna()))
    print('  shoal suspect=1 :', q(g[(g.layer=='shoal')&(g.suspect==1)].hnd_min.dropna()))
    print('  cand likely=1   :', q(g[(g.layer=='cand')&(g.likely_shoal==1)].hnd_min.dropna()))
    print('  cand likely=0   :', q(g[(g.layer=='cand')&(g.likely_shoal==0)].hnd_min.dropna()))
    print('── dist_perm_m, p10/25/50/75/90 ──')
    print('  shoal suspect=0 :', q(g[(g.layer=='shoal')&(g.suspect==0)].dist_perm_m.dropna()))
    print('  shoal suspect=1 :', q(g[(g.layer=='shoal')&(g.suspect==1)].dist_perm_m.dropna()))
    print('  cand likely=1   :', q(g[(g.layer=='cand')&(g.likely_shoal==1)].dist_perm_m.dropna()))
    print(f'\nСохранено: {OUT_GPKG}\n           {OUT_CSV}\nВремя: {(time.time()-t0)/60:.1f} мин')


if __name__ == '__main__':
    main()
