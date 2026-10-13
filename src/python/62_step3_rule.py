"""
62_step3_rule.py — шаг 3 генезиса: антропогенный песок (карьеры, отсыпки, площадки, дороги, промзоны).

Вход:  exports/baresand_genesis_step2_v3_split.gpkg (классы шагов 1–2), exports/qc/step3/step3_evidence.csv (61)
Работает на остатке genesis = unassigned (в т.ч. anthro_suspect и сухие части разреза шага 2).

Каскад v3 (первое сработавшее правило даёт метку; DNA §6.5.2 A0–A3; v2 — по итогам QC агентов, v3 — по вердиктам эксперта и
мозаикам Hansen GFC: настоящий A0 «был ли голый песок в ~2000» (bare2000_frac, 66) вместо прокси по яркости Landsat-1985,
и потери леса 2001–2019 (loss_frac) как признак гари/вырубки).
Темпоральные признаки (покрытие 60–70° с.ш.; севернее — откат на Landsat-1985):
  new_sand  = bare2000_frac < NEW_BARE_MAX (не голый в 2000) ∨ l85_dark_frac ≥ DARK_NEW (тёмный в 1985) ∨ bare_s2_frac < S2_NEW_MAX
              (не голый на подложке S2 2017–2019, 67 — вся AOI; ТОЛЬКО с --use-s2: на эталоне не помогает, критерий red ≥ 1500 ∧ NDVI < 0.2
              при 10 м считает «отсутствующими» 73 % контуров остатка — мелкие раздувы дают смешанные пиксели); --no-new-union — только Hansen
  old_sand  = bare2000_frac ≥ OLD_BARE_MIN  (голый песок уже в 2000 — природный массив или старый техноген 1970–90-х)
  burn      = loss_frac ≥ LOSS_MIN ∧ tc2000_mean ≥ TC_MIN (потеря леса 2001–2019) → флаг burn_suspect; НЕ исключение: потеря леса —
              это и гари, и расчистка под площадки/дороги (55079, 441073 — техноген в лесной зоне)
Приоритет A0 (DNA «был раньше → природный») — опция --a0-protect: правила близости не срабатывают на old_sand. По умолчанию
ВЫКЛЮЧЕНО: на эталоне эксперта даёт −1 (217→219 с защитой, 220 без): техноген Медвежьего/Уренгоя/Нефтеюганска 1970–90-х
в 2000 уже голый, и эксперт относит к техногену старые площадки и «зону освоения» внутри массивов. old_sand остаётся флагом.
Все расстояния до дорог — только ПОСТРОЕННЫЕ дороги OSM (major/minor/other; d_road_built, osm_overlap_built из 61b):
колеи и зимники (highway=track/winter_road) в тундре давали d_road = 0 у природных раздувов.
  a_net        — сеть дорог/площадок (anthro_suspect шага 2) или «далёкая» сухая часть разреза, ЕСЛИ есть поддержка OSM
                 (дорога ≤ D_NET_SUP / промзона ≤ D_IND_SUP / след ≥ OSM_SUP); сети без поддержки — кластеры раздувов,
                 русла ручьёв, озёрные косы (QC v1: 25 %) → флаг net_unsupported, природный                    → anthropogenic
  a_osm_on     — доля площади в следе OSM ≥ OSM_ON, либо касается промполигона (d_industrial = 0) и след ≥ OSM_ON2 → anthropogenic
  a_net_adj    — примыкает к сети (d_net ≤ D_NET_ADJ) ∧ (след > 0 ∨ дорога ≤ D_ADJ_ROAD); без этого — 21 %       → anthropogenic
  a_near_new   — рядом с построенной инфраструктурой (дорога ≤ D_ROAD, промобъект ≤ D_IND, линия/ж.д. ≤ D_LIN) ∧ тёмный
                 в 1985 (l85_dark_frac ≥ DARK_NEW) ∧ ≥ AREA_MIN_A0 га — DNA A0 ∧ A1                             → anthropogenic
  a_new_infra  — тёмный в 1985 ∧ компактный (ero15 ≥ ERO_COMPACT) ∧ ≥ AREA_NEW_INFRA га ∧ в зоне инфраструктуры (дорога
                 ≤ D_ROAD_ZONE / промзона ≤ D_IND_ZONE) ∧ не бывшая вода (flood_frac0 < FLOOD_MAX_INFRA — днища хасыреев тоже
                 тёмные в 1985) — площадки и карьеры промыслов, не картированные OSM (главный источник пропусков v1: new_far 38 %)                                                          → anthropogenic
  a_thin_net   — тонкая сеть ≥ NET_AREA га: ero50 < NET_ERO ∧ (дорога ≤ D_ROAD_NET ∨ промзона ≤ D_IND_NET), либо сеть с
                 площадками ero50 < NET_ERO2 ∧ след ≥ NET_OSM ∧ касается дороги                                 → anthropogenic
  a_road_small — касается построенной дороги (≤ D_ROAD_TOUCH) ∧ ≤ AREA_SMALL га ∧ след ≥ NET_OSM (обочины, съезды) → anthropogenic
  a_nspd_on    — ЕГРН (НСПД, 70): доля площади в сооружениях ЕГРН ≥ NSPD_ON ∨ в «промышленных» участках (< 500 га) ≥ NSPD_ON
                 — площадки, дороги, трубопроводы как объекты капстроительства и землеотводы под них; там, где OSM пуст → anthropogenic
  ЕГРН также усиливает: поддержку сети (сооружение/участок ≤ D_NET_SUP), зону инфраструктуры для a_new_infra (≤ D_ROAD_ZONE)
                 и близость для a_near_new (сооружение ≤ D_ROAD); --no-nspd — без ЕГРН
  a_near_shape / a_shape / a_linear — выключены (--near-shape, --shape-alone): прямоугольность контуров маски не отличает
                 площадки (0.24–0.64 у аэродрома) от раздувов — лестница пикселей и рваные края
  иначе — остаётся unassigned (природный: эоловый/неопределённый — шаг 4).
Правило DNA «был в 1985 ∧ у дороги → природный» сохранено для близости (a_near_*), но НЕ для следа OSM (a_osm_on):
инфраструктура Медвежьего/Уренгоя/Надыма старше 1985 и на яркости-1985 выглядит «природной».
Флаги: anthro_adjacent — природный контур ≤ D_ADJ от инфраструктуры (раздув с техногенным триггером — решает эксперт);
       new_since_1985 — тёмный в 1985 (≥ AREA_MIN_A0 га); new_far — новый (после 2000 / тёмный в 1985), ≥ AREA_NEW_FAR га, вне зоны
       инфраструктуры; net_unsupported — сеть шага 2 без OSM-поддержки (природный); burn_suspect — потеря леса (гарь/вырубка);
       mixed_suspect — техноген ≥ MIXED_HA га, голый уже в 2000, след OSM < OSM_ON: массив + дороги в одном контуре — резать вручную.
Выход: exports/baresand_genesis_step3_<tag>.gpkg (все классы + anthropogenic, step3_rule, флаги);
       регрессия exports/qc/step3/regression_step3.csv (expected_genesis: anthropogenic | unassigned), если есть.
Запуск: python -u python/62_step3_rule.py --tag v3   (--no-hansen = v2; --use-s2 — эксперимент с подложкой S2)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import argparse
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC3 = EXPORTS / 'qc' / 'step3'
SRC = EXPORTS / 'baresand_genesis_step2_v3_split.gpkg'
EVID = QC3 / 'step3_evidence.csv'
REGRESSION = QC3 / 'regression_step3.csv'
SAMPLE_GEOMS = QC3 / 'visual_sample_geoms_step3.gpkg'
EA_CRS = 'EPSG:3576'

# пороги по умолчанию (калибруются на эталоне; все — параметры CLI)
DEFAULTS = dict(
    osm_on=0.30, osm_on2=0.10, d_net_adj=30.0, d_adj_road=300.0,
    d_net_sup=2000.0, d_ind_sup=3000.0, osm_sup=0.10,
    d_road=150.0, d_ind=300.0, d_lin=100.0, dark_new=0.60, area_min_a0=1.0,
    d_road_zone=2000.0, d_ind_zone=3000.0, area_new_infra=2.0, ero_compact=0.30, flood_max_infra=0.50,
    net_area=20.0, net_ero=0.15, d_road_net=500.0, d_ind_net=1000.0, net_ero2=0.25, net_osm=0.10,
    d_road_touch=40.0, area_small=1.0,
    rect_near=0.70, elong_max=6.0, area_min_near=0.3,
    rect_alone=0.85, convex_alone=0.90, nv_alone=22.0, area_shape_min=1.0, area_shape_max=30.0,
    ero_lin=0.02, len_lin=1000.0, elong_lin=12.0, d_water_lin=200.0,
    d_adj=100.0, area_new_far=5.0,
    new_bare_max=0.30, old_bare_min=0.70, loss_min=0.50, tc_min=10.0, mixed_ha=50.0,
    s2_new_max=0.15, s2_present_min=0.50,
    nspd_on=0.30, nspd_any=0.50,
    nspd_lic_frac=1.00, nspd_lic_road=1000.0, nspd_lic_bare=0.50, nspd_lic_area=10.0,
)
# nspd_lic_*: подобрано на эталоне 581 (2026-09-07, перебор 8 вариантов): лицензионный ВРИ ∧ отвод ≥ 10 га ∧ дороги OSM > 1 км ∧ голый в 2000 ≥ 0.5
# (доля в отводе любая) — 477/581 против 474 у варианта «доля < 0.5, любая площадь»; мелкие лицензионные отводы 1–3 га — одиночные скважины (техноген)
# ВРИ участка: объектный (площадка, куст, карьер, трубопровод…) — след надёжен; лицензионный (недропользование, геологическое изучение,
# разведка и добыча) — отвод 30–300 га может накрыть природный раздув: по списку эксперта (NSPD.shp, 114 конт) ошибки — лицензионные
# отводы, задетые краем (доля < 0.5), вдали от дорог OSM (> 1 км), на песке, голом уже в 2000; объектные ВРИ — 25/25 верно
VRI_OBJECT = ('куст', 'скважин', 'трубопровод', 'карьер', 'площадк', 'дорог', 'производств', 'промышлен', 'склад', 'размещени', 'строительств',
              'обустройств', 'объект', 'эксплуатац', 'линейн', 'транспорт', 'энергет', 'коммунальн', 'связи', 'газ', 'нефт', 'аэро', 'укпг',
              'установк', 'станци', 'полигон', 'вахтов', 'база', 'завод')
VRI_LICENSE = ('недропольз', 'геологическ', 'разведка и добыча', 'разработка месторожд', 'полезных ископаемых', 'добыч')


def vri_kind(v) -> str:
    v = (v if isinstance(v, str) else '').lower()
    if any(w in v for w in VRI_OBJECT):
        return 'object'
    if any(w in v for w in VRI_LICENSE):
        return 'license'
    return 'other' if v else 'empty'
RULES = ('a_net', 'a_osm_on', 'a_nspd_on', 'a_net_adj', 'a_near_new', 'a_new_infra', 'a_thin_net', 'a_road_small', 'a_near_shape', 'a_shape', 'a_linear')


def regression(g: gpd.GeoDataFrame, tag: str) -> None:
    if not REGRESSION.exists():
        print('\n  регрессионного набора шага 3 пока нет')
        return
    reg = pd.read_csv(REGRESSION)
    m = reg.merge(g[['id', 'genesis']], on='id', how='left')
    m['by_geom'] = False
    missing = m['genesis'].isna()
    unscored = []
    if missing.any() and SAMPLE_GEOMS.exists():
        sg = gpd.read_file(SAMPLE_GEOMS, layer='sample').to_crs(EA_CRS).set_index('id')
        sidx = g.sindex
        for i in m.index[missing]:
            cid = int(m.at[i, 'id'])
            if cid not in sg.index:
                unscored.append(cid)               # строка эталона без геометрии — не терять молча
                continue
            geom = sg.at[cid, 'geometry']
            hits = g.iloc[sidx.query(geom, predicate='intersects')]
            u = hits.loc[hits['genesis'] == 'anthropogenic', 'geometry']
            f = geom.intersection(u.union_all()).area / geom.area if len(u) and geom.area > 0 else 0.0
            m.at[i, 'genesis'] = 'anthropogenic' if f >= 0.5 else 'unassigned'
            m.at[i, 'by_geom'] = True
    got = m['genesis'].fillna('unassigned')
    got_n = got.where(got == 'anthropogenic', 'unassigned')      # все природные классы = «не антропоген»
    ok = m['expected_genesis'] == got_n
    print(f'\n  РЕГРЕССИЯ [{tag}]: {int(ok.sum())}/{len(m)} ({100 * ok.mean():.0f}%)')
    if unscored:
        print(f'    ВНИМАНИЕ: {len(unscored)} строк эталона не оценены (нет ни в продукте, ни в слое геометрий): {unscored[:10]}'
              f'{" …" if len(unscored) > 10 else ""} — засчитаны как unassigned')
    whole = ~m['by_geom']
    print(f'    по целым контурам: {int((ok & whole).sum())}/{int(whole.sum())} ({100 * ok[whole].mean():.0f}%), '
          f'по частям разрезов эксперта: {int((ok & ~whole).sum())}/{int((~whole).sum())} ({100 * ok[~whole].mean():.0f}%)')
    lost_p = EXPORTS / 'nspd' / 'nspd_36048_lost.gpkg'
    if lost_p.exists():                                          # дыры выгрузки ЕГРН: точность отдельно вне дыр
        lost = gpd.read_file(lost_p).to_crs(EA_CRS).geometry.union_all()
        gi = g.set_index('id')
        sg = gpd.read_file(SAMPLE_GEOMS, layer='sample').to_crs(EA_CRS).set_index('id') if SAMPLE_GEOMS.exists() else None
        hole = []
        for cid in m['id']:
            geom = gi.geometry.get(cid) if cid in gi.index else (sg.geometry.get(cid) if sg is not None and cid in sg.index else None)
            hole.append(bool(geom is not None and geom.centroid.within(lost)))
        m['nspd_hole'] = hole
        h = m['nspd_hole']
        print(f'    вне дыр выгрузки ЕГРН: {int((ok & ~h).sum())}/{int((~h).sum())} ({100 * ok[~h].mean():.0f}%); в дырах: {int((ok & h).sum())}/{int(h.sum())}')
    for _, r in m[~ok].iterrows():
        print(f'    {int(r.id)} → {r.expected_genesis} / {r.genesis} [{r.get("stratum", "")}]')
    m.to_csv(QC3 / f'regression_report_step3_{tag}.csv', index=False, encoding='utf-8')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='v1')
    for k, v in DEFAULTS.items():
        ap.add_argument(f'--{k.replace("_", "-")}', type=float, default=v)
    ap.add_argument('--shape-alone', action='store_true', help='включить a_shape и a_linear (форма без OSM)')
    ap.add_argument('--near-shape', action='store_true', help='включить a_near_shape (рядом ∧ правильная форма)')
    ap.add_argument('--no-hansen', action='store_true', help='не использовать Hansen-2000/lossyear (как v2)')
    ap.add_argument('--a0-protect', action='store_true', help='защищать old_sand (голый в 2000) от правил близости; по умолчанию выкл.: −1 на эталоне — старый техноген 1970–90-х тоже голый в 2000')
    ap.add_argument('--no-new-union', action='store_true', help='new_sand только по Hansen-2000 (без объединения с тёмным-1985)')
    ap.add_argument('--no-net-new', action='store_true', help='не считать новизну поддержкой сети')
    ap.add_argument('--no-nspd', action='store_true', help='не использовать улики ЕГРН (НСПД): сооружения и промышленные участки')
    ap.add_argument('--use-s2', action='store_true', help='использовать подложку S2 2017–2019 как срез новизны (по умолчанию выкл.: на эталоне 0, а «отсутствовал» получают 73 % контуров — смешанные пиксели 10 м)')
    ap.add_argument('--burn-exclude', action='store_true', help='исключать контуры с потерей леса из техногена (по умолчанию только флаг burn_suspect)')
    a = ap.parse_args()
    P = {k: getattr(a, k) for k in DEFAULTS}
    t0 = time.time()
    out_gpkg = EXPORTS / f'baresand_genesis_step3_{a.tag}.gpkg'

    print('═══════════════════════════════════════')
    print(f'ШАГ 3 [{a.tag}] {"v2" if a.no_hansen else ("v3(Hansen-2000 + S2 2017-19)" if a.use_s2 else "v3(Hansen-2000)")}{"" if a.no_nspd else " + ЕГРН(НСПД)"}: net(с OSM-поддержкой) ∨ osm_on≥{P["osm_on"]} ∨ net_adj ∨ near_new(built) ∨ '
          f'new_infra[dark85≥{P["dark_new"]} ∧ ≥{P["area_new_infra"]:.0f} га ∧ ero15≥{P["ero_compact"]} ∧ (road≤{P["d_road_zone"]:.0f} ∨ ind≤{P["d_ind_zone"]:.0f})] ∨ '
          f'thin_net ∨ road_small{" ∨ near_shape" if a.near_shape else ""}{" ∨ shape/linear" if a.shape_alone else ""}')
    print('═══════════════════════════════════════')

    g = gpd.read_file(SRC).to_crs(EA_CRS)
    ev = pd.read_csv(EVID, low_memory=False)
    ev_cols = [c for c in ev.columns if c not in g.columns or c == 'id']
    g = g.merge(ev[ev_cols], on='id', how='left', validate='1:1')
    cand = (g['genesis'] == 'unassigned') & g['d_road_any'].notna()
    print(f'контуров: {len(g):,} | unassigned: {(g.genesis == "unassigned").sum():,} | с уликами шага 3: {cand.sum():,}')

    if 'd_road_built' not in g.columns:            # без 61b — старые колонки (все дороги)
        g['d_road_built'] = g['d_road_any']
        g['osm_overlap_built'] = g['osm_overlap']
    ov = g['osm_overlap_built']
    use_nspd = (not a.no_nspd) and ('nspd_struct_frac' in g.columns or 'nspd_parcel_ind_frac' in g.columns)
    d_struct = g['d_struct_m'] if ('d_struct_m' in g.columns and use_nspd) else pd.Series(1e9, index=g.index)
    d_pind = g['d_parcel_ind_m'] if ('d_parcel_ind_m' in g.columns and use_nspd) else pd.Series(1e9, index=g.index)
    f_struct = g['nspd_struct_frac'].fillna(0) if ('nspd_struct_frac' in g.columns and use_nspd) else pd.Series(0.0, index=g.index)
    f_pind = g['nspd_parcel_ind_frac'].fillna(0) if ('nspd_parcel_ind_frac' in g.columns and use_nspd) else pd.Series(0.0, index=g.index)
    f_pany = g['nspd_parcel_any_frac'].fillna(0) if ('nspd_parcel_any_frac' in g.columns and use_nspd) else pd.Series(0.0, index=g.index)
    d_pany = g['d_parcel_any_m'] if ('d_parcel_any_m' in g.columns and use_nspd) else pd.Series(1e9, index=g.index)
    kind = g['parcel_vri'].apply(vri_kind) if ('parcel_vri' in g.columns and use_nspd) else pd.Series('empty', index=g.index)
    # лицензионный отвод задел краем природный раздув вдали от дорог на старом песке — не техноген (флаг nspd_lic_suspect)
    p_area = g['parcel_area_ha'].fillna(0) if 'parcel_area_ha' in g.columns else pd.Series(0.0, index=g.index)
    lic_suspect = ((kind == 'license') & (f_pind <= P['nspd_lic_frac']) & (g['d_road_built'] > P['nspd_lic_road'])
                   & (g['bare2000_frac'].fillna(0) >= P['nspd_lic_bare']) & (p_area >= P['nspd_lic_area'])) if use_nspd else pd.Series(False, index=g.index)
    near = ((g['d_road_built'] <= P['d_road']) | (g['d_industrial'] <= P['d_ind']) | (g['d_linear'] <= P['d_lin']) | (g['d_rail'] <= P['d_lin'])
            | (d_struct <= P['d_road']))
    # зона/поддержка — только промышленные участки и сооружения; «любой землеотвод» в зоне давал ложные new_infra (372207) → только прямое перекрытие
    zone = (g['d_road_built'] <= P['d_road_zone']) | (g['d_industrial'] <= P['d_ind_zone']) | (d_struct <= P['d_road_zone']) | (d_pind <= P['d_road_zone'])
    support_osm = ((g['d_road_built'] <= P['d_net_sup']) | (g['d_industrial'] <= P['d_ind_sup']) | (ov >= P['osm_sup'])
                   | (d_struct <= P['d_net_sup']) | (d_pind <= P['d_net_sup']))
    regular = (g['rect'] >= P['rect_near']) & (g['elong'] <= P['elong_max']) & (g['area_ha'] >= P['area_min_near'])
    dark85 = (g['l85_dark_frac'] >= P['dark_new']) & (g['area_ha'] >= P['area_min_a0'])
    use_h = (not a.no_hansen) and ('bare2000_frac' in g.columns)
    covered = g['bare2000_frac'].notna() if use_h else pd.Series(False, index=g.index)
    new_sand = np.where(covered, g['bare2000_frac'] < P['new_bare_max'], g['l85_dark_frac'] >= P['dark_new']) if use_h else (g['l85_dark_frac'] >= P['dark_new']).values
    new_sand = pd.Series(new_sand, index=g.index).fillna(False).astype(bool)
    if use_h and not a.no_new_union:      # «новый» = не голый в 2000 ИЛИ тёмный в 1985 (построено между 1985 и 2000 — тоже техноген)
        new_sand = new_sand | (g['l85_dark_frac'] >= P['dark_new']).fillna(False)
    use_s2 = a.use_s2 and ('bare_s2_frac' in g.columns)
    absent_s2 = (g['bare_s2_frac'].notna() & (g['bare_s2_frac'] < P['s2_new_max'])) if use_s2 else pd.Series(False, index=g.index)
    if use_s2:                            # «новый» также = отсутствует на подложке S2 2017–2019 (появился после 2019)
        new_sand = new_sand | absent_s2
    old_sand = (covered & (g['bare2000_frac'] >= P['old_bare_min'])) if use_h else pd.Series(False, index=g.index)
    burn = (covered & (g['loss_frac'] >= P['loss_min']) & (g['tc2000_mean'] >= P['tc_min'])) if use_h else pd.Series(False, index=g.index)
    protect = (~old_sand) if a.a0_protect else pd.Series(True, index=g.index)
    cand_nb = cand & ~burn if a.burn_exclude else cand      # потеря леса = и гари, и расчистка под площадки → по умолчанию только флаг
    new_a0 = new_sand & (g['area_ha'] >= P['area_min_a0'])
    # поддержка сети: OSM рядом ИЛИ сеть новая (появилась после 1985/2000 — природные «сети» раздувов старые): 32738 (210 га, эксперт: техноген)
    support = support_osm | (new_sand if (use_h and not a.no_net_new) else pd.Series(False, index=g.index))
    r = {
        'a_net': cand_nb & (g['is_net'] == 1) & support,
        'a_osm_on': cand_nb & ((ov >= P['osm_on']) | ((g['d_industrial'] <= 0) & (ov >= P['osm_on2']))),
        'a_net_adj': cand_nb & protect & (g['d_net'] <= P['d_net_adj']) & ((ov > 0) | (g['d_road_built'] <= P['d_adj_road'])),
        'a_near_new': cand_nb & protect & near & new_a0,
        'a_new_infra': cand_nb & protect & new_sand & (g['area_ha'] >= P['area_new_infra']) & (g['ero15'] >= P['ero_compact']) & zone
                       & (g['flood_frac0'].fillna(0) < P['flood_max_infra']),
        'a_thin_net': cand_nb & protect & (g['area_ha'] >= P['net_area']) & (
            ((g['ero50'] < P['net_ero']) & ((g['d_road_built'] <= P['d_road_net']) | (g['d_industrial'] <= P['d_ind_net'])))
            | ((g['ero50'] < P['net_ero2']) & (ov >= P['net_osm']) & (g['d_road_built'] <= P['d_road_touch']))),
        'a_road_small': cand_nb & protect & (g['d_road_built'] <= P['d_road_touch']) & (g['area_ha'] <= P['area_small']) & (ov >= P['net_osm']),
        'a_nspd_on': cand_nb & ((f_struct >= P['nspd_on']) | (f_pind >= P['nspd_on']) | (f_pany >= P['nspd_any'])) & ~lic_suspect,
        'a_near_shape': cand_nb & near & regular if a.near_shape else cand & False,
        'a_shape': (cand_nb & (g['rect'] >= P['rect_alone']) & (g['convex'] >= P['convex_alone']) & (g['nv_km'] <= P['nv_alone'])
                    & g['area_ha'].between(P['area_shape_min'], P['area_shape_max'])) if a.shape_alone else cand & False,
        'a_linear': (cand_nb & (g['ero15'] <= P['ero_lin']) & (g['mrr_long_m'] >= P['len_lin']) & (g['elong'] >= P['elong_lin'])
                     & (g['dist_water_m'].fillna(1e6) > P['d_water_lin'])) if a.shape_alone else cand & False,
    }
    g['step3_rule'] = ''
    taken = pd.Series(False, index=g.index)
    for name in RULES:
        hit = r[name] & ~taken
        g.loc[hit, 'step3_rule'] = f'{a.tag}_{name}'
        taken |= hit
    g['genesis_step2'] = g['genesis']
    g.loc[taken, 'genesis'] = 'anthropogenic'
    g['anthro_adjacent'] = (cand & ~taken & ((g['d_road_built'] <= P['d_adj']) | (g['d_industrial'] <= P['d_adj']) | (ov > 0))).astype('int16')
    g['new_since_1985'] = (cand & dark85).astype('int16')
    g['new_far'] = (cand & ~taken & ~zone & new_sand & (g['area_ha'] >= P['area_new_far'])).astype('int16')
    g['net_unsupported'] = (cand & (g['is_net'] == 1) & ~support).astype('int16')
    g['burn_suspect'] = (cand & burn).astype('int16')
    g['old_sand_2000'] = (cand & old_sand).astype('int16')
    g['hansen_covered'] = covered.astype('int16')
    g['nspd_lic_suspect'] = (cand & lic_suspect).astype('int16')
    g['absent_s2'] = (cand & absent_s2).astype('int16')
    g['present_s2'] = (cand & g['bare_s2_frac'].notna() & (g['bare_s2_frac'] >= P['s2_present_min'])).astype('int16') if use_s2 else 0
    # смешанные гиганты: 1 — техноген на старом песке с малым следом OSM; 2 — природный массив, задетый инфраструктурой (резать вручную)
    g['mixed_suspect'] = np.where(taken & (g['area_ha'] >= P['mixed_ha']) & old_sand & (ov < P['osm_on']), 1,
                                  np.where(cand & ~taken & (g['area_ha'] >= P['mixed_ha']) & ((ov >= 0.02) | (g['d_road_built'] <= 50)), 2, 0)).astype('int16')

    L = []
    for name in RULES:
        s = g[g['step3_rule'] == f'{a.tag}_{name}']
        L.append(f'  {name:13s}: {len(s):7,} конт | {s.area_km2.sum():7.1f} км² | медиана {s.area_ha.median() if len(s) else 0:.2f} га')
    s = g[g['genesis'] == 'anthropogenic']
    L.append(f'  {"anthropogenic":13s}: {len(s):7,} конт | {s.area_km2.sum():7.1f} км²')
    rest = g[g['genesis'] == 'unassigned']
    L.append(f'  {"unassigned":13s}: {len(rest):7,} конт | {rest.area_km2.sum():7.1f} км² | из них anthro_adjacent: '
             f'{int(rest.anthro_adjacent.sum()):,} ({rest.loc[rest.anthro_adjacent == 1, "area_km2"].sum():.1f} км²), '
             f'new_since_1985: {int(rest.new_since_1985.sum()):,} ({rest.loc[rest.new_since_1985 == 1, "area_km2"].sum():.1f} км²), '
             f'new_far (≥{P["area_new_far"]:.0f} га, вдали): {int(rest.new_far.sum()):,} ({rest.loc[rest.new_far == 1, "area_km2"].sum():.1f} км²), '
             f'net_unsupported: {int(rest.net_unsupported.sum()):,} ({rest.loc[rest.net_unsupported == 1, "area_km2"].sum():.1f} км²), '
             f'burn_suspect: {int(rest.burn_suspect.sum()):,} ({rest.loc[rest.burn_suspect == 1, "area_km2"].sum():.1f} км²)')
    L.append(f'  Hansen-2000: покрыто {int(g.loc[cand, "hansen_covered"].sum()):,} из {int(cand.sum()):,} кандидатов; old_sand защищено от правил близости: '
             f'{int((cand & old_sand & ~taken).sum()):,}; mixed_suspect (техноген ≥ {P["mixed_ha"]:.0f} га на старом песке, след < {P["osm_on"]}): '
             f'{int((g.mixed_suspect == 1).sum()):,}; природные гиганты с инфраструктурой внутри (mixed_suspect = 2): {int((g.mixed_suspect == 2).sum()):,}')
    if use_nspd:
        cov = g['nspd_parcel_cov'].fillna(1) if 'nspd_parcel_cov' in g.columns else pd.Series(1.0, index=g.index)
        L.append(f'  ЕГРН(НСПД): сооружения ≥ {P["nspd_on"]}: {int((cand & (f_struct >= P["nspd_on"])).sum()):,}; промышленные участки ≥ {P["nspd_on"]}: '
                 f'{int((cand & (f_pind >= P["nspd_on"])).sum()):,}; любой землеотвод ≥ {P["nspd_any"]}: {int((cand & (f_pany >= P["nspd_any"])).sum()):,}; '
                 f'кандидатов в дырах выгрузки участков (покрытие < 0.5): {int((cand & (cov < 0.5)).sum()):,}; '
                 f'лицензионный отвод краем вдали от дорог на старом песке (nspd_lic_suspect, не техноген): {int((cand & lic_suspect).sum()):,} '
                 f'({g.loc[cand & lic_suspect, "area_km2"].sum():.1f} км²)')
    if use_s2:
        L.append(f'  S2 2017–19: с данными {int(g.loc[cand, "bare_s2_frac"].notna().sum()):,}; отсутствовал на подложке (absent_s2): '
                 f'{int(g.absent_s2.sum()):,} конт | {g.loc[g.absent_s2 == 1, "area_km2"].sum():.1f} км², из них техноген {int((g.absent_s2 == 1).sum() and ((g.absent_s2 == 1) & taken).sum()):,}')
    print('\n'.join(L))
    regression(g, a.tag)

    keep = [c for c in ['id', 'parent_id', 'area_ha', 'area_km2', 'genesis', 'genesis_step2', 'shoal_rule', 'step2_rule', 'step3_rule',
                        'anthro_adjacent', 'new_since_1985', 'new_far', 'net_unsupported', 'burn_suspect', 'old_sand_2000', 'mixed_suspect', 'hansen_covered', 'nspd_lic_suspect', 'absent_s2', 'present_s2', 'anthro_suspect', 'khasyrei_suspect', 'split_n', 'split_from', 'part_kind',
                        'd_road_any', 'd_road_built', 'd_road_major', 'd_industrial', 'd_linear', 'd_building', 'd_place', 'place_type', 'osm_overlap', 'osm_overlap_built', 'track_touch',
                        'd_net', 'ero50', 'rect', 'elong', 'convex', 'compact', 'ero15', 'nv_km', 'mrr_long_m', 'mrr_short_m',
                        'l85_mean', 'l85_dark_frac', 'l85_bright_frac', 'bare2000_frac', 'red2000_mean', 'loss_frac', 'tc2000_mean', 'bare_s2_frac', 'red_s2_mean', 'ndvi_s2_mean', 's2_cov', 'nspd_struct_frac', 'd_struct_m', 'nspd_struct_cov', 'nspd_parcel_ind_frac', 'd_parcel_ind_m', 'nspd_parcel_any_frac', 'd_parcel_any_m', 'nspd_parcel_cov', 'parcel_category', 'parcel_vri', 'parcel_area_ha', 'parcel_kind', 'dist_sea_m', 'dist_water_m', 'flood_frac0', 'geometry']
            if c in g.columns]
    g[keep].to_file(out_gpkg, layer='genesis', driver='GPKG')
    (QC3 / f'step3_rule_summary_{a.tag}.txt').write_text('\n'.join(L), encoding='utf-8')
    print(f'\nСохранено: {out_gpkg}\nВремя: {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
