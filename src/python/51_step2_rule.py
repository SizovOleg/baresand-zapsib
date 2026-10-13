"""
BareSand — Генезис, ШАГ 2: правило «речные и озёрные отмели» (v2 — после визуальной QC v1).

Изменения v2 (по наблюдениям дешифровщиков):
  1. Узкие реки: fallback на русловую сеть MERIT — dist_channel_m (UPA ≥ 20 км²) ≤ D_CHANNEL ∧ flood ≥ F_FLOOD.
  2. HND починен (берётся из улик шага 2, а не из файла шага 1, где он только у берега). Ветка HND — опция --use-hnd.
  3. Хасыреи: компонента «озеро» с сезонностью GSW-2021 = 0 → спущенное озеро → flood по истории не считается.
  4. Пляжи Обской губы (GSW обрезан AOI): кандидаты ≤ MARINE_M от морского берега → genesis 'shoal' (шаг 1).
  5. Проточные озёра: компонента «река» с малой вытянутостью (comp_elong < ELONG_RIVER) и площадью ≥ 1 км² → озеро.
  6. Мелкие (< 1 га) озёрные контуры: требовать flood_frac10 > 0 или flood_frac0 ≥ 0.5 (раздувы на уступе, касающиеся воды).
  7. Антропогенный пре-фильтр по тесту эрозией (--anthro-prefilter): ≥ 20 га ∧ ero50 < 0.15 ∧ flood < 0.5.

Правило:
  river_shoal ⇐ cand ∧ [ (river ∧ dist_water ≤ D_RIVER ∧ wet_or_low) ∨ (dist_channel ≤ D_CHANNEL ∧ flood ≥ F_FLOOD) ]
  lake_shoal  ⇐ cand ∧ lake ∧ comp_area ≥ LAKE_MIN ∧ comp_seas_max ≥ SEAS_MIN ∧ dist_water ≤ D_LAKE ∧ wet_or_low_lake
  wet_or_low  = flood_frac0 ≥ F_FLOOD ∨ (use_hnd ∧ hnd_min ≤ H)

Вход:  exports/baresand_genesis_step1_v3.gpkg, exports/qc/step2/step2_evidence.gpkg, step2_evidence_extra.csv,
       exports/qc/coastal_zone_evidence.csv (dist_sea_m), exports/qc/step2/giants_erosion.csv
Выход: exports/baresand_genesis_step2_<tag>.gpkg; регрессия exports/qc/step2/regression_step2.csv
Запуск: python -u python/51_step2_rule.py --tag v2 --anthro-prefilter [--use-hnd] [--d-river 200] [--d-channel 150] ...
"""
import sys
import time
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

sys.stdout.reconfigure(encoding='utf-8')

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC = EXPORTS / 'qc'
QC2 = QC / 'step2'
STEP1 = EXPORTS / 'baresand_genesis_step1_v3.gpkg'
EVID = QC2 / 'step2_evidence.gpkg'
EXTRA = QC2 / 'step2_evidence_extra.csv'
COASTAL = QC / 'coastal_zone_evidence.csv'
EROSION = QC2 / 'giants_erosion.csv'
REGRESSION = QC2 / 'regression_step2.csv'
OVERRIDES = EXPORTS / 'qc' / 'expert_overrides.csv'
NEARWATER = QC2 / 'giants_nearwater.csv'
SAMPLE_GEOMS = QC2 / 'visual_sample_geoms_step2.gpkg'
EA_CRS = 'EPSG:3576'
GIANT_MIN_HA = 20.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='v2')
    ap.add_argument('--d-river', type=float, default=200.0)
    ap.add_argument('--d-channel', type=float, default=150.0)
    ap.add_argument('--d-lake', type=float, default=200.0)
    ap.add_argument('--flood', type=float, default=0.2)
    ap.add_argument('--flood-touch', type=float, default=None,
                    help='порог flood для контуров, касающихся воды (dist_water ≤ 60 м): узкие пляжи 20–40 м не набирают 0.2 на 30-м GSW')
    ap.add_argument('--use-hnd', action='store_true')
    ap.add_argument('--h-river', type=float, default=3.0)
    ap.add_argument('--h-lake', type=float, default=2.0)
    ap.add_argument('--upa-min', type=float, default=50.0)
    ap.add_argument('--lake-min', type=float, default=1.0)
    ap.add_argument('--seas-min', type=float, default=1.0, help='сезонность GSW-2021 компоненты озера ≥ → живое озеро')
    ap.add_argument('--elong-river', type=float, default=20.0, help='вытянутость компоненты ниже → проточное озеро, не река')
    ap.add_argument('--marine-m', type=float, default=1000.0)
    ap.add_argument('--anthro-prefilter', action='store_true')
    ap.add_argument('--khasyrei-exclude', action='store_true', help='днища спущенных озёр НЕ считать озёрными отмелями (до вердикта эксперта 23040 — по умолчанию)')
    ap.add_argument('--net-area', type=float, default=20.0)
    ap.add_argument('--net-ero', type=float, default=0.15)
    ap.add_argument('--net-flood', type=float, default=0.5)
    ap.add_argument('--net-near', type=float, default=0.7, help='гигант с долей площади ближе 100 м от воды/русла ≥ этого — цепочка баров, не сеть (giants_nearwater.csv, 50c)')
    a = ap.parse_args()
    t0 = time.time()
    out_gpkg = EXPORTS / f'baresand_genesis_step2_{a.tag}.gpkg'

    print('═══════════════════════════════════════')
    print(f'ШАГ 2 [{a.tag}]: river ⇐ (река ∧ d≤{a.d_river:.0f} ∧ wet/low) ∨ (русло UPA≥20 d≤{a.d_channel:.0f} ∧ flood≥{a.flood}); '
          f'lake ⇐ озеро≥{a.lake_min} км² живое(seas≥{a.seas_min:.0f}) ∧ d≤{a.d_lake:.0f} ∧ wet/low; HND {"ON" if a.use_hnd else "OFF"}; '
          f'anthro-prefilter {"ON" if a.anthro_prefilter else "OFF"}')
    print('═══════════════════════════════════════')

    base = gpd.read_file(STEP1).to_crs(EA_CRS)
    base = base.drop(columns=[c for c in ('hnd_min', 'upa_max', 'gsw_seas_max', 'gsw_occ_mean', 'gsw_occ_max') if c in base.columns])
    ev = gpd.read_file(EVID, ignore_geometry=True)[['id', 'dist_water_m', 'nearest_type', 'comp_area_km2', 'comp_upa_km2',
                                                    'flood_frac0', 'flood_frac10', 'hnd_min', 'upa_max', 'gsw_seas_max']]
    g = base.merge(ev, on='id', how='left', validate='1:1')
    if EXTRA.exists():
        ex = pd.read_csv(EXTRA)[['id', 'dist_channel_m', 'comp_elong', 'comp_seas_max']]
        g = g.merge(ex, on='id', how='left', validate='1:1')
    else:
        g['dist_channel_m'] = np.nan; g['comp_elong'] = np.nan; g['comp_seas_max'] = np.nan
        print('  ! нет step2_evidence_extra.csv — без русловой сети/хасыреев/вытянутости')
    if 'dist_sea_m' not in g.columns:
        if COASTAL.exists():
            g = g.merge(pd.read_csv(COASTAL)[['id', 'dist_sea_m']], on='id', how='left', validate='1:1')
        else:
            g['dist_sea_m'] = np.nan
    cand = g['genesis'] == 'unassigned'
    print(f'контуров: {len(g):,} | unassigned: {cand.sum():,} | с уликами: {g.dist_water_m.notna().sum():,} | HND известен: {g.hnd_min.notna().sum():,}')

    # ── антропогенный пре-фильтр (сети дорог/площадок) ──
    g['anthro_suspect'] = 0
    if a.anthro_prefilter:
        if not EROSION.exists():
            gi = g[cand & (g['area_ha'] >= a.net_area)]
            pd.DataFrame({'id': gi['id'], 'ero50': (gi.geometry.buffer(-50).area / gi.geometry.area).round(3)}).to_csv(EROSION, index=False)
        g = g.merge(pd.read_csv(EROSION)[['id', 'ero50']], on='id', how='left')
        net = cand & (g['area_ha'] >= a.net_area) & (g['ero50'] < a.net_ero) & (g['flood_frac0'] < a.net_flood)
        if NEARWATER.exists():
            nw = pd.read_csv(NEARWATER)[['id', 'near100_frac']]
            g = g.merge(nw, on='id', how='left')
            chain = net & (g['near100_frac'] >= a.net_near)
            net = net & ~chain
            print(f'  из пре-фильтра освобождены цепочки баров у русла (near100 ≥ {a.net_near}): {int(chain.sum()):,} конт | {g.loc[chain, "area_km2"].sum():.1f} км²')
        g['anthro_suspect'] = net.astype('int16')
        cand = cand & ~net
        print(f'  пре-фильтр техногена: {int(net.sum()):,} конт | {g.loc[net, "area_km2"].sum():.1f} км² → ждут шаг 3')
    else:
        g['ero50'] = np.nan

    # ── тип водоёма v2 ──
    wtype = g['nearest_type'].copy()
    through_lake = (wtype == 'river') & (g['comp_elong'] < a.elong_river) & (g['comp_area_km2'] >= 1.0)
    wtype = wtype.mask(through_lake, 'lake')
    live_lake = g['comp_seas_max'].isna() | (g['comp_seas_max'] >= a.seas_min)
    g['khasyrei_suspect'] = (cand & (wtype == 'lake') & ~live_lake & (g['flood_frac0'] >= a.flood)).astype('int16')

    fl_thr = np.where(g['dist_water_m'] <= 60, (a.flood_touch if a.flood_touch is not None else a.flood), a.flood)
    wet_r = (g['flood_frac0'] >= fl_thr) | (a.use_hnd & (g['hnd_min'] <= a.h_river))
    wet_l = (g['flood_frac0'] >= fl_thr) | (a.use_hnd & (g['hnd_min'] <= a.h_lake))
    small_strict = (g['area_ha'] >= 1.0) | (g['flood_frac10'] > 0) | (g['flood_frac0'] >= 0.5)

    river_a = (wtype == 'river') & (g['comp_upa_km2'] >= a.upa_min) & (g['dist_water_m'] <= a.d_river) & wet_r
    river_b = (g['dist_channel_m'] <= a.d_channel) & (g['flood_frac0'] >= a.flood)
    river = cand & (river_a | river_b)
    lake_live_ok = live_lake if a.khasyrei_exclude else pd.Series(True, index=g.index)
    lake = cand & (wtype == 'lake') & (g['comp_area_km2'] >= a.lake_min) & lake_live_ok & (g['dist_water_m'] <= a.d_lake) & wet_l & small_strict
    marine = cand & (g['dist_sea_m'] <= a.marine_m) & (river | lake | ((g['dist_water_m'] <= 200) & (g['flood_frac0'] >= a.flood)))

    g['genesis'] = np.where(marine, 'shoal', np.where(river, 'river_shoal', np.where(lake, 'lake_shoal', g['genesis'])))
    g['step2_rule'] = np.where(marine, f'{a.tag}_marine_leak', np.where(river & river_b & ~river_a, f'{a.tag}_river_channel',
                       np.where(river, f'{a.tag}_river', np.where(lake, f'{a.tag}_lake', ''))))
    g['needs_split'] = ((river | lake) & (g['area_ha'] >= GIANT_MIN_HA)).astype('int16')

    # ── точечные вердикты эксперта, которых правило не выводит (54_step2_expert_verdicts.py) ──
    if OVERRIDES.exists():
        ov = pd.read_csv(OVERRIDES)
        hit = g['id'].isin(ov['id'])
        g.loc[hit, 'genesis'] = g.loc[hit, 'id'].map(ov.set_index('id')['genesis'])
        g.loc[hit, 'step2_rule'] = 'expert_override'
        print(f'  expert overrides: {int(hit.sum())} конт | {g.loc[hit, "area_km2"].sum():.1f} км² → ' + ', '.join(sorted(set(ov['genesis']))))

    L = []
    for cls in ('river_shoal', 'lake_shoal'):
        s = g[(g['genesis'] == cls) & g['step2_rule'].str.startswith(a.tag)]
        L.append(f'  {cls:12s}: {len(s):7,} конт | {s.area_km2.sum():7.1f} км² | медиана {s.area_ha.median():.2f} га | '
                 f'гигантов ≥{GIANT_MIN_HA:.0f} га: {(s.area_ha >= GIANT_MIN_HA).sum():,} ({s[s.area_ha >= GIANT_MIN_HA].area_km2.sum():.1f} км²)')
    ch = g[g['step2_rule'] == f'{a.tag}_river_channel']
    L.append(f'  из них по русловой сети (узкие реки): {len(ch):,} конт | {ch.area_km2.sum():.1f} км²')
    ml = g[g['step2_rule'] == f'{a.tag}_marine_leak']
    L.append(f'  → в морской класс (пляжи губ у берега шага 1): {len(ml):,} конт | {ml.area_km2.sum():.1f} км²')
    kh = g[g['khasyrei_suspect'] == 1]
    L.append(f'  хасыреи (озеро без воды в 2021, flood по истории): {len(kh):,} конт | {kh.area_km2.sum():.1f} км² — '
             + ('не отмель' if a.khasyrei_exclude else 'озёрная отмель (вердикт эксперта 23040), флаг khasyrei_suspect'))
    rest = g[g['genesis'] == 'unassigned']
    L.append(f'  {"unassigned":12s}: {len(rest):7,} конт | {rest.area_km2.sum():7.1f} км²')
    print('\n'.join(L))

    # ── регрессия ──
    if REGRESSION.exists():
        reg = pd.read_csv(REGRESSION)
        m = reg.merge(g[['id', 'genesis']], on='id', how='left')
        m['by_geom'] = False
        missing = m['genesis'].isna()
        if missing.any() and SAMPLE_GEOMS.exists():
            sg = gpd.read_file(SAMPLE_GEOMS, layer='sample').to_crs(EA_CRS).set_index('id')
            uni = {c: g.loc[g['genesis'] == c, 'geometry'].union_all() for c in ('river_shoal', 'lake_shoal')}
            for i in m.index[missing]:
                cid = int(m.at[i, 'id'])
                if cid in sg.index:
                    geom = sg.at[cid, 'geometry']
                    best, bf = 'unassigned', 0.0
                    for c, u in uni.items():
                        f = geom.intersection(u).area / geom.area if geom.area > 0 else 0
                        if f > bf:
                            best, bf = c, f
                    m.at[i, 'genesis'] = best if bf >= 0.5 else 'unassigned'
                    m.at[i, 'by_geom'] = True
        exp, got = m['expected_genesis'], m['genesis'].fillna('unassigned')
        got_n = got.replace({'shoal': 'unassigned'})   # морской класс = «не отмель шага 2»
        ok = (exp == got_n) | ((exp == 'any_shoal') & got.isin(['river_shoal', 'lake_shoal']))
        print(f'\n  РЕГРЕССИЯ [{a.tag}]: {int(ok.sum())}/{len(m)} ({100 * ok.mean():.0f}%)')
        bad = m[~ok]
        for _, r in bad.iterrows():
            print(f'    {int(r.id)} → {r.expected_genesis} / {r.genesis} [{r.get("stratum", "")}]')
        m.to_csv(QC2 / f'regression_report_step2_{a.tag}.csv', index=False, encoding='utf-8')
    else:
        print('\n  регрессионного набора шага 2 пока нет')

    keep = ['id', 'parent_id', 'area_ha', 'area_km2', 'genesis', 'genesis_v1', 'shoal_rule', 'step2_rule', 'needs_split',
            'anthro_suspect', 'khasyrei_suspect', 'ero50', 'dist_sea_m', 'dist_water_m', 'dist_channel_m', 'nearest_type',
            'comp_area_km2', 'comp_upa_km2', 'comp_elong', 'comp_seas_max', 'flood_frac0', 'flood_frac10',
            'hnd_min', 'upa_max', 'gsw_seas_max', 'geometry']
    g[[c for c in keep if c in g.columns]].to_file(out_gpkg, layer='genesis', driver='GPKG')
    (QC2 / f'step2_rule_summary_{a.tag}.txt').write_text('\n'.join(L), encoding='utf-8')
    print(f'\nСохранено: {out_gpkg}\nВремя: {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
