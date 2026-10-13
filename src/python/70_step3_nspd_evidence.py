"""
70_step3_nspd_evidence.py — улики шага 3 по данным ЕГРН (НСПД, выгрузка 69): участки, сооружения, ЗОУИТ.

Вход:  exports/nspd/nspd_36048.gpkg (земельные участки), nspd_36328.gpkg (сооружения ЕГРН), nspd_36302.gpkg (ЗОУИТ) — какие есть;
       exports/baresand_genesis_step2_v3_split.gpkg (остаток), exports/qc/step3/step3_evidence.csv (порядок контуров).
Классы объектов ЕГРН → «инфраструктурный след»:
  участки: категория «Земли промышленности, энергетики, транспорта…» ИЛИ ВРИ с ключевыми словами (недропользование, добыча, трубопровод,
           карьер, промышлен, производств, транспорт, энергет, склад, размещени, строительств, обустройств, скважин, площадк, дорог, аэро,
           коммунальн, связи) — И площадь < PARCEL_MAX_HA (крупные лицензионные/лесные аренды не считаем следом объекта);
  сооружения: все (площадки, дороги, трубопроводы, ЛЭП как объекты капстроительства);
  ЗОУИТ: охранные зоны трубопроводов, электросетевого хозяйства, инженерных коммуникаций, связи, транспорта
         (исключая геодезические пункты, водоохранные/ЗСО/прибрежные, ООПТ и т.п.).
  любой землеотвод (широкий след): участок < PARCEL_MAX_HA, кроме пастбищ/лесхоза/ООПТ/водного фонда без инфраструктурных слов в ВРИ
         (в тундре мелкие участки регистрируют только под объекты; «обособленные» части линейных отводов идут без категории и ВРИ).
Улики по контуру: nspd_parcel_ind_frac (доля площади в «промышленных» участках), d_parcel_ind_m, nspd_parcel_any_frac, d_parcel_any_m,
                  nspd_parcel_cov (доля контура, покрытая выгрузкой: 1 − потерянные ячейки nspd_36048_lost.gpkg), nspd_struct_frac, d_struct_m,
                  nspd_struct_cov, nspd_zouit_frac, d_zouit_m, parcel_category (категория участка под центроидом), parcel_vri (ВРИ), parcel_area_ha.
Выход: колонки добавляются в step3_evidence.csv.
Запуск: python -u python/70_step3_nspd_evidence.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.strtree import STRtree

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC3 = EXPORTS / 'qc' / 'step3'
SRC = EXPORTS / 'baresand_genesis_step2_v3_split.gpkg'
EVID = QC3 / 'step3_evidence.csv'
NSPD = EXPORTS / 'nspd'
EA_CRS = 'EPSG:3576'
DIST_CAP_M = 5000.0
PARCEL_MAX_HA = 500.0
IND_CATEGORY = 'промышленности'
VRI_WORDS = ('недропольз', 'добыч', 'трубопровод', 'карьер', 'промышлен', 'производств', 'транспорт', 'энергет', 'склад', 'размещени',
             'строительств', 'обустройств', 'скважин', 'площадк', 'дорог', 'аэро', 'коммунальн', 'связи', 'газ', 'нефт',
             'геологическ', 'месторожд', 'полезных ископаемых')   # лицензионные ВРИ — тоже «промышленные» (их страхует флаг nspd_lic_suspect в 62),
                                                                    # иначе «геологическое изучение» уходило в «любой землеотвод» без страховки (QC мелких: 5530, 278043)
ZOUIT_WORDS = ('трубопровод', 'газопровод', 'нефтепровод', 'электросет', 'электроэнерг', 'лэп', 'линии электропередач', 'инженерных коммуникаций',
               'связи', 'транспорта', 'автомобильн', 'железн', 'аэродром', 'тепловых сетей')
ZOUIT_EXCLUDE = ('геодезическ', 'водоохран', 'прибрежн', 'санитарн', 'особо охраня', 'культурн', 'стационарного пункта наблюдений')
# «любой землеотвод» (широкий след): участок < PARCEL_MAX_HA, кроме пастбищ/лесхоза/ООПТ/водного фонда без инфраструктурных слов в ВРИ —
# в тундре мелкие участки регистрируют только под объекты (в т.ч. «обособленные» части линейных отводов без категории и ВРИ)
EXCL_VRI_WORDS = ('традиционн', 'оленевод', 'сельскохозяйственное использование', 'сельскохозяйственного использования', 'сельскохозяйственного производства',
                  'эксплуатационные леса', 'заготовка древесины', 'лесного хозяйства', 'лесное хозяйство', 'лесохозяйств', 'защитные леса',
                  'резервные леса', 'городскими лесами', 'рыболовств', 'охотничь', 'особо охраня', 'рекреацион')   # словоформы: «для ведения лесного хозяйства» (QC: 6686)
EXCL_CATEGORIES = ('земли особо охраняемых', 'земли водного фонда')


def coverage(geoms, lost_path: Path) -> np.ndarray:
    """Доля площади контура вне потерянных ячеек выгрузки (1 — данные слоя есть по всему контуру)."""
    if not lost_path.exists():
        return np.ones(len(geoms), dtype='float32')
    lost = gpd.read_file(lost_path).to_crs(EA_CRS)
    log(f'  потерянных ячеек выгрузки ({lost_path.name}): {len(lost)}')
    return (1.0 - overlap(geoms, lost.geometry.values)).astype('float32')


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def nearest(tree: STRtree, geoms, cap: float = DIST_CAP_M) -> np.ndarray:
    d = np.full(len(geoms), cap, dtype='float32')
    if len(tree.geometries):
        idx, dist = tree.query_nearest(geoms, max_distance=cap, return_distance=True, all_matches=False)
        d[idx[0]] = dist
    return d


def overlap(geoms, foot) -> np.ndarray:
    frac = np.zeros(len(geoms), dtype='float32')
    if len(foot) == 0:
        return frac
    ci, fi = STRtree(foot).query(geoms, predicate='intersects')
    if len(ci):
        inter = shapely.area(shapely.intersection(geoms[ci], foot[fi]))
        frac[:] = np.minimum(np.bincount(ci, weights=inter, minlength=len(geoms)) / shapely.area(geoms), 1.0)
    return frac


def main() -> None:
    t0 = time.time()
    ev = pd.read_csv(EVID, low_memory=False)
    log('читаю остаток маски...')
    g = gpd.read_file(SRC, where="genesis = 'unassigned'", columns=['id']).to_crs(EA_CRS)
    g = g.set_index('id').loc[ev['id'].values]
    geoms = g.geometry.values
    cen = shapely.centroid(geoms)

    p_par = NSPD / 'nspd_36048.gpkg'
    if p_par.exists():
        log('участки ЕГРН...')
        par = gpd.read_file(p_par).to_crs(EA_CRS)
        par = par[par.geometry.notna()]
        bad = ~par.geometry.is_valid
        if bad.any():
            par.loc[bad, 'geometry'] = par.loc[bad, 'geometry'].make_valid()
        par = par[~par.geometry.is_empty]
        cat = par.get('land_record_category_type', pd.Series('', index=par.index)).fillna('').str.lower()
        vri = par.get('permitted_use_established_by_document', pd.Series('', index=par.index)).fillna('').str.lower()
        small = par['area_ha_geom'] < PARCEL_MAX_HA
        has_ind = vri.apply(lambda s: any(w in s for w in VRI_WORDS))
        ind = (cat.str.contains(IND_CATEGORY) | has_ind) & small
        excl = (vri.apply(lambda s: any(w in s for w in EXCL_VRI_WORDS)) | cat.apply(lambda s: any(s.startswith(w) for w in EXCL_CATEGORIES))) & ~has_ind
        anyp = small & ~excl
        log(f'  участков {len(par):,}, «промышленных» < {PARCEL_MAX_HA:.0f} га: {int(ind.sum()):,}, любых землеотводов < {PARCEL_MAX_HA:.0f} га '
            f'(без пастбищ/лесхоза/ООПТ): {int(anyp.sum()):,}')
        ev['nspd_parcel_ind_frac'] = overlap(geoms, par.loc[ind, 'geometry'].values)
        ev['d_parcel_ind_m'] = nearest(STRtree(par.loc[ind, 'geometry'].values), geoms)
        ev['nspd_parcel_any_frac'] = overlap(geoms, par.loc[anyp, 'geometry'].values)
        ev['d_parcel_any_m'] = nearest(STRtree(par.loc[anyp, 'geometry'].values), geoms)
        ev['nspd_parcel_cov'] = coverage(geoms, NSPD / 'nspd_36048_lost.gpkg')
        # атрибуты «главного» участка: землеотвод (< PARCEL_MAX_HA, не пастбище/лесхоз) с наибольшим перекрытием контура;
        # если таких нет — участок под центроидом (пастбище, лесной квартал…)
        ev['parcel_category'] = ''
        ev['parcel_vri'] = ''
        ev['parcel_area_ha'] = np.nan
        ev['parcel_kind'] = ''
        tree = STRtree(par.geometry.values)
        ci, pi = tree.query(cen, predicate='within')
        first = pd.DataFrame({'ci': ci, 'pi': pi}).drop_duplicates('ci')
        ev.loc[first['ci'].values, 'parcel_category'] = par['land_record_category_type'].fillna('').values[first['pi'].values]
        ev.loc[first['ci'].values, 'parcel_vri'] = par['permitted_use_established_by_document'].fillna('').values[first['pi'].values]
        ev.loc[first['ci'].values, 'parcel_area_ha'] = par['area_ha_geom'].values[first['pi'].values]
        ev.loc[first['ci'].values, 'parcel_kind'] = 'centroid'
        foot = par.loc[anyp]
        ci, fi = STRtree(foot.geometry.values).query(geoms, predicate='intersects')
        if len(ci):
            inter = shapely.area(shapely.intersection(geoms[ci], foot.geometry.values[fi]))
            best = pd.DataFrame({'ci': ci, 'fi': fi, 'a': inter}).sort_values('a', ascending=False).drop_duplicates('ci')
            best = best[best['a'] > 0]
            ev.loc[best['ci'].values, 'parcel_category'] = foot['land_record_category_type'].fillna('').values[best['fi'].values]
            ev.loc[best['ci'].values, 'parcel_vri'] = foot['permitted_use_established_by_document'].fillna('').values[best['fi'].values]
            ev.loc[best['ci'].values, 'parcel_area_ha'] = foot['area_ha_geom'].values[best['fi'].values]
            ev.loc[best['ci'].values, 'parcel_kind'] = np.where(ind.loc[anyp].values[best['fi'].values], 'industrial', 'allotment')
    p_str = NSPD / 'nspd_36328.gpkg'
    if p_str.exists():
        log('сооружения ЕГРН...')
        st = gpd.read_file(p_str).to_crs(EA_CRS)
        st = st[st.geometry.notna()]
        bad = ~st.geometry.is_valid
        if bad.any():
            st.loc[bad, 'geometry'] = st.loc[bad, 'geometry'].make_valid()
        st = st[~st.geometry.is_empty]
        ev['nspd_struct_frac'] = overlap(geoms, st.geometry.values)
        ev['d_struct_m'] = nearest(STRtree(st.geometry.values), geoms)
        ev['nspd_struct_cov'] = coverage(geoms, NSPD / 'nspd_36328_lost.gpkg')
        log(f'  сооружений {len(st):,}')
    p_z = NSPD / 'nspd_36302.gpkg'
    if p_z.exists():
        log('ЗОУИТ...')
        z = gpd.read_file(p_z).to_crs(EA_CRS)
        z = z[z.geometry.notna() & z.geometry.is_valid]
        tz = (z.get('type_zone', pd.Series('', index=z.index)).fillna('') + ' ' + z.get('name_by_doc', pd.Series('', index=z.index)).fillna('')).str.lower()
        keep = tz.apply(lambda s: any(w in s for w in ZOUIT_WORDS) and not any(w in s for w in ZOUIT_EXCLUDE))
        log(f'  ЗОУИТ {len(z):,}, инфраструктурных {int(keep.sum()):,}')
        ev['nspd_zouit_frac'] = overlap(geoms, z.loc[keep, 'geometry'].values)
        ev['d_zouit_m'] = nearest(STRtree(z.loc[keep, 'geometry'].values), geoms)
    ev.to_csv(EVID, index=False, encoding='utf-8')
    cols = [c for c in ('nspd_parcel_ind_frac', 'd_parcel_ind_m', 'nspd_parcel_any_frac', 'd_parcel_any_m', 'nspd_parcel_cov',
                        'nspd_struct_frac', 'd_struct_m', 'nspd_struct_cov', 'nspd_zouit_frac', 'd_zouit_m') if c in ev.columns]
    print(ev[cols].describe().round(2).to_string())
    log(f'сохранено {EVID.name} | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
