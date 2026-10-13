"""
84_cascade_order_check.py — проверка инварианта DNA §6.5.6 (антропоген оценивается ПЕРВЫМ) на уже собранном продукте.

Зачем: в реализации каскад идёт берег → отмели → антропоген → эоловый, то есть A-правила применяются только к остатку после W.
Аудит фазы 3 указал: контуры, ушедшие в классы шагов 1–2 (морская, речная, озёрная отмель), никогда не проверяются
антропогенными правилами, а это 38.9 % площади маски. Скрипт измеряет, сколько там на самом деле техногена, — по двум
независимым уликам, которые для этих контуров ещё не считались:
  * кадастр ЕГРН: доля площади контура в «промышленном» участке (< 500 га; категория промышленности ∨ ВРИ про недра, трубы,
    карьеры, площадки — тот же фильтр, что в 70_step3_nspd_evidence.py);
  * OSM: доля площади в следе построенной инфраструктуры (промплощадки, здания + буферы дорог) из exports/osm/osm_infra_AOI.gpkg.
Выход: exports/qc/step4/cascade_order_check.csv (по классам: сколько контуров и км² имеют след ≥ порога) и
       exports/qc/step4/cascade_order_suspects.gpkg (контуры отмелей с сильным техногенным следом — кандидаты на пересмотр).
Запуск: python -u python/84_cascade_order_check.py [--frac 0.3]
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import argparse
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.strtree import STRtree

EXPORTS = Path(r'D:\test\baresand_zapsib')
EXPORTS = EXPORTS / 'exports'
QC4 = EXPORTS / 'qc' / 'step4'
PRODUCT = EXPORTS / 'baresand_genesis_step4_v2e.gpkg'
NSPD_PARCELS = EXPORTS / 'nspd' / 'nspd_36048.gpkg'
OSM = EXPORTS / 'osm' / 'osm_infra_AOI.gpkg'
EA_CRS = 'EPSG:3576'
PARCEL_MAX_HA = 500.0
IND_CATEGORY = 'промышленности'
VRI_WORDS = ('недропольз', 'добыч', 'трубопровод', 'карьер', 'промышлен', 'производств', 'транспорт', 'энергет', 'склад', 'размещени',
             'строительств', 'обустройств', 'скважин', 'площадк', 'дорог', 'аэро', 'коммунальн', 'связи', 'газ', 'нефт',
             'геологическ', 'месторожд', 'полезных ископаемых')
EXCL_VRI = ('традиционн', 'оленевод', 'сельскохозяйственное использование', 'эксплуатационные леса', 'заготовка древесины',
            'лесного хозяйства', 'лесохозяйств', 'городскими лесами', 'рыболовств', 'охотничь', 'особо охраня', 'рекреацион')
SHOAL_CLASSES = ('shoal', 'river_shoal', 'lake_shoal')
ROAD_BUF_M = 20.0


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def overlap_frac(geoms, foot) -> np.ndarray:
    frac = np.zeros(len(geoms), dtype='float32')
    if len(foot) == 0:
        return frac
    ci, fi = STRtree(foot).query(geoms, predicate='intersects')
    if len(ci):
        inter = shapely.area(shapely.intersection(geoms[ci], foot[fi]))
        frac[:] = np.minimum(np.bincount(ci, weights=inter, minlength=len(geoms)) / shapely.area(geoms), 1.0)
    return frac


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--frac', type=float, default=0.30, help='порог доли площади в техногенном следе')
    a = ap.parse_args()
    t0 = time.time()
    log('читаю продукт (классы шагов 1–2)...')
    g = gpd.read_file(PRODUCT, columns=['id', 'genesis', 'area_ha', 'area_km2'],
                      where="genesis IN ('shoal','river_shoal','lake_shoal')").to_crs(EA_CRS)
    log(f'  {len(g):,} контуров / {g.area_km2.sum():,.1f} км²')
    geoms = g.geometry.values

    log('кадастр ЕГРН: отбор «промышленных» участков...')
    par = gpd.read_file(NSPD_PARCELS).to_crs(EA_CRS)
    par = par[par.geometry.notna()]
    par['geometry'] = par.geometry.make_valid()
    par = par[~par.geometry.is_empty]
    cat = par.get('land_record_category_type', pd.Series('', index=par.index)).fillna('').str.lower()
    vri = par.get('permitted_use_established_by_document', pd.Series('', index=par.index)).fillna('').str.lower()
    has_ind = vri.apply(lambda s: any(w in s for w in VRI_WORDS))
    excl = vri.apply(lambda s: any(w in s for w in EXCL_VRI)) & ~has_ind
    ind = (cat.str.contains(IND_CATEGORY) | has_ind) & ~excl & (par['area_ha_geom'] < PARCEL_MAX_HA)
    log(f'  участков {len(par):,}, «промышленных» < {PARCEL_MAX_HA:.0f} га: {int(ind.sum()):,}')
    g['nspd_ind_frac'] = overlap_frac(geoms, par.loc[ind, 'geometry'].values)
    del par

    log('OSM: след построенной инфраструктуры...')
    foot = []
    for lay, buf in (('industrial', 0.0), ('buildings', 0.0), ('roads', ROAD_BUF_M), ('rail', ROAD_BUF_M), ('linear', ROAD_BUF_M)):
        try:
            o = gpd.read_file(OSM, layer=lay).to_crs(EA_CRS)
        except Exception as e:
            log(f'  слой {lay} пропущен: {type(e).__name__}')
            continue
        if lay == 'roads' and 'cls' in o.columns:
            o = o[o['cls'].isin(['major', 'minor', 'other'])]          # только построенные дороги (без зимников/троп)
        gm = o.geometry.values
        if buf:
            gm = shapely.buffer(gm, buf)
        foot.append(gm)
        log(f'  {lay}: {len(gm):,}')
    foot = np.concatenate(foot) if foot else np.array([], dtype=object)
    g['osm_frac'] = overlap_frac(geoms, foot)

    g['anthro_frac'] = np.maximum(g['nspd_ind_frac'], g['osm_frac'])
    rows = []
    for cls in SHOAL_CLASSES:
        s = g[g['genesis'] == cls]
        for name, m in (('кадастр ≥ порога', s['nspd_ind_frac'] >= a.frac), ('OSM ≥ порога', s['osm_frac'] >= a.frac),
                        ('любой след ≥ порога', s['anthro_frac'] >= a.frac)):
            rows.append({'класс': cls, 'улика': name, 'контуров': int(m.sum()), 'км2': round(s.loc[m, 'area_km2'].sum(), 2),
                         'доля_числа_%': round(100 * m.mean(), 2) if len(s) else 0,
                         'доля_площади_%': round(100 * s.loc[m, 'area_km2'].sum() / max(s['area_km2'].sum(), 1e-9), 2)})
    t = pd.DataFrame(rows)
    t.to_csv(QC4 / 'cascade_order_check.csv', index=False, encoding='utf-8')
    print(t.to_string(index=False))
    tot = g['anthro_frac'] >= a.frac
    print(f'\nИТОГО в классах шагов 1–2: {int(tot.sum()):,} контуров / {g.loc[tot, "area_km2"].sum():,.1f} км² '
          f'({100 * g.loc[tot, "area_km2"].sum() / g["area_km2"].sum():.1f} % их площади) имеют техногенный след ≥ {a.frac:.0%}')
    sus = g[tot].sort_values('area_km2', ascending=False)
    sus.to_file(QC4 / 'cascade_order_suspects.gpkg', driver='GPKG')
    log(f'подозрительные → cascade_order_suspects.gpkg ({len(sus):,}) | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
