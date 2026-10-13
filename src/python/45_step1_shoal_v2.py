"""
BareSand — Генезис, ШАГ 1 v2: морские отмели по примыканию к морю.

Правило v2 (взамен «прилегания к границе AOI»):
  shoal  ⇐  dist_sea_m ≤ SEA_DIST_MAX_M  И  (hnd_min ≤ HND_MAX_M  ИЛИ hnd_min неизвестен)
  dist_sea_m — расстояние до постоянной МОРСКОЙ воды (44_qc_step1_sea_distance.py);
  hnd_min    — мягкий вторичный признак: у обрывистых берегов 90-м пиксель MERIT
               захватывает бровку (пляж у подножия даёт HND 5–8 м) — поэтому порог 8, не 2.

Гиганты (area ≥ GIANT_MIN_HA), прошедшие правило, режутся буфером берега:
  часть внутри SHORE_BUFFER → shoal (id сохраняется), остаток → unassigned (новый id,
  parent_id = исходный). Это реализация DNA §6.5.8 п.3 для морского шага.

Вход:
  exports/baresand_genesis_step1.gpkg        — все контуры, метки шага 1 v1
  exports/qc/coastal_zone_evidence.gpkg      — прибрежная зона с dist_sea_m, hnd_min
  exports/qc/sea_shore_buffer.gpkg           — буфер берега (EPSG:3576)
Выход:
  exports/baresand_genesis_step1_v2.gpkg     — все контуры (+ остатки разрезов), genesis v2
  exports/qc/step1_v1_vs_v2_diff.csv         — что изменилось (added / dropped / split)

Запуск: python -u python/45_step1_shoal_v2.py [SEA_DIST_MAX_M] [HND_MAX_M]
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

sys.stdout.reconfigure(encoding='utf-8')

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC = EXPORTS / 'qc'
STEP1_V1 = EXPORTS / 'baresand_genesis_step1.gpkg'
COASTAL = QC / 'coastal_zone_evidence.gpkg'
SHORE = QC / 'sea_shore_buffer.gpkg'
_VAR = 'v3c' if (len(sys.argv) > 3 and sys.argv[3] == 'connect') else 'v3'
OUT_GPKG = EXPORTS / f'baresand_genesis_step1_{_VAR}.gpkg'
OUT_DIFF = QC / f'step1_v1_vs_{_VAR}_diff.csv'
REGRESSION = QC / 'regression_step1.csv'   # id, expected_genesis — накапливается из ревью

SEA_DIST_MAX_M = float(sys.argv[1]) if len(sys.argv) > 1 else 400.0
HND_MAX_M = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
# v3c: связность — контур дальше CORE_M от берега считается shoal только если касается
# (в пределах CONNECT_M) контура, который сам в CORE_M от берега. Отсекает раздувы на низкой
# террасе за пляжем, отделённые от него полосой растительности.
CONNECT = len(sys.argv) > 3 and sys.argv[3] == 'connect'
CORE_M = 100.0
CONNECT_M = 30.0
VARIANT = 'v3c' if CONNECT else 'v3'
SAMPLE_GEOMS = QC / 'visual_sample_geoms.gpkg'   # геометрии эталонных контуров (в т.ч. синтетических остатков)
# v3: для мелочи (< SMALL_HA) HND строже — пятачки на бровке террасы с HND 2–7 м проходили порог 8
SMALL_HA = 0.5
HND_MAX_SMALL_M = 3.0
GIANT_MIN_HA = 20.0
SPLIT_MIN_FRAC = 0.05      # остаток меньше 5% площади не отделяем (шум границы буфера)
EA_CRS = 'EPSG:3576'


def main() -> None:
    t0 = time.time()
    print('═══════════════════════════════════════')
    print(f'ШАГ 1 v2: shoal = dist_sea ≤ {SEA_DIST_MAX_M:.0f} м И hnd ≤ {HND_MAX_M:.0f} м; гиганты ≥ {GIANT_MIN_HA:.0f} га режем буфером берега')
    print('═══════════════════════════════════════')

    base = gpd.read_file(STEP1_V1).to_crs(EA_CRS)
    base = base.rename(columns={'genesis': 'genesis_v1'})
    coastal = gpd.read_file(COASTAL, ignore_geometry=True)[['id', 'dist_sea_m', 'hnd_min', 'upa_max',
                                                            'gsw_occ_mean', 'gsw_occ_max', 'gsw_seas_max']]
    shore = gpd.read_file(SHORE).to_crs(EA_CRS).geometry.union_all()
    g = base.merge(coastal, on='id', how='left', validate='1:1')
    print(f'контуров: {len(g):,} | в прибрежной зоне с уликами: {g.dist_sea_m.notna().sum():,}')

    # строгий HND для мелочи — только если контур НЕ у самой воды (пятачки на бровке в 100–400 м);
    # мелкий контур, касающийся уреза (dist ≤ CORE_M), — пляж под обрывом, HND у него завышен MERIT
    small_far = (g['area_ha'] < SMALL_HA) & (g['dist_sea_m'] > CORE_M)
    hnd_lim = np.where(small_far, HND_MAX_SMALL_M, HND_MAX_M)
    passes = (g['dist_sea_m'] <= SEA_DIST_MAX_M) & ((g['hnd_min'] <= hnd_lim) | g['hnd_min'].isna())
    if CONNECT:
        core = g[passes & (g['dist_sea_m'] <= CORE_M)]
        far = g[passes & (g['dist_sea_m'] > CORE_M)]
        touch = gpd.sjoin(gpd.GeoDataFrame(geometry=far.geometry.buffer(CONNECT_M), index=far.index),
                          core[['geometry']], predicate='intersects', how='inner')
        keep_far = far.index.isin(touch.index.unique())
        dropped_far = far.index[~keep_far]
        passes.loc[dropped_far] = False
        print(f'связность: ядро (≤{CORE_M:.0f} м) {len(core):,}; дальних {len(far):,}, из них касаются ядра '
              f'{int(keep_far.sum()):,}, отсечено {len(dropped_far):,} ({g.loc[dropped_far, "area_km2"].sum():.1f} км²)')
    g['genesis'] = np.where(passes, 'shoal', 'unassigned')
    g['shoal_rule'] = np.where(passes, 'v3_sea_adjacent', '')
    g['parent_id'] = pd.NA

    # ── разрезание гигантов ──
    giants = g[passes & (g['area_ha'] >= GIANT_MIN_HA)]
    print(f'гигантов-shoal ≥ {GIANT_MIN_HA:.0f} га: {len(giants):,} ({giants.area_km2.sum():.1f} км²) — проверяю на смешанность')
    new_rows = []
    next_id = int(g['id'].max()) + 1
    n_split = 0
    for idx, r in giants.iterrows():
        inside = r.geometry.intersection(shore)
        rest = r.geometry.difference(shore)
        if inside.is_empty or rest.is_empty:
            continue
        frac_rest = rest.area / r.geometry.area
        if frac_rest < SPLIT_MIN_FRAC:
            continue
        if inside.area / r.geometry.area < SPLIT_MIN_FRAC:
            # почти целиком вне полосы берега — значит прошёл по касанию краем; весь в остаток
            g.at[idx, 'genesis'] = 'unassigned'
            g.at[idx, 'shoal_rule'] = 'v3_rejected_inland_giant'
            continue
        # прибрежная часть остаётся под исходным id
        g.at[idx, 'geometry'] = inside
        g.at[idx, 'shoal_rule'] = 'v3_sea_adjacent_split'
        g.at[idx, 'area_ha'] = inside.area / 1e4
        g.at[idx, 'area_km2'] = inside.area / 1e6
        # остаток — новый контур
        nr = r.copy()
        nr['id'] = next_id
        nr['geometry'] = rest
        nr['genesis'] = 'unassigned'
        nr['shoal_rule'] = 'v3_split_remainder'
        nr['parent_id'] = int(r['id'])
        nr['area_ha'] = rest.area / 1e4
        nr['area_km2'] = rest.area / 1e6
        new_rows.append(nr)
        next_id += 1
        n_split += 1
    if new_rows:
        g = pd.concat([g, gpd.GeoDataFrame(new_rows, crs=EA_CRS)], ignore_index=True)
        g = gpd.GeoDataFrame(g, geometry='geometry', crs=EA_CRS)
    print(f'  разрезано: {n_split:,}; остатков добавлено: {len(new_rows):,}')

    # ── сводка и diff ──
    v1 = g[g['genesis_v1'] == 'shoal']
    v2 = g[g['genesis'] == 'shoal']
    print('')
    print(f'  v1 shoal: {len(v1):6,} | {v1.area_km2.sum():7.1f} км²')
    print(f'  v2 shoal: {len(v2):6,} | {v2.area_km2.sum():7.1f} км²')
    dropped = g[(g['genesis_v1'] == 'shoal') & (g['genesis'] != 'shoal') & g['parent_id'].isna()]
    added = g[(g['genesis_v1'] != 'shoal') & (g['genesis'] == 'shoal')]
    print(f'  выбыло из класса: {len(dropped):6,} | {dropped.area_km2.sum():7.1f} км²  (террасы/суходол/реки)')
    print(f'  добавлено:        {len(added):6,} | {added.area_km2.sum():7.1f} км²  (пляжи вне 100 м от линии AOI)')

    # широтный контроль
    cen = v2.geometry.centroid.set_crs(EA_CRS, allow_override=True).to_crs('EPSG:4326')
    south = v2[cen.y < 66]
    print(f'  v2 shoal южнее 66°N (должно быть ~0): {len(south):,} | {south.area_km2.sum():.2f} км²')

    diff = pd.concat([
        dropped.assign(change='dropped'),
        added.assign(change='added'),
        g[g['shoal_rule'] == 'v3_sea_adjacent_split'].assign(change='split_kept'),
        g[g['shoal_rule'] == 'v3_split_remainder'].assign(change='split_remainder'),
    ])[['id', 'parent_id', 'change', 'genesis_v1', 'genesis', 'area_ha', 'dist_sea_m', 'hnd_min',
        'gsw_occ_max', 'dist_aoi_boundary_m']]
    diff.to_csv(OUT_DIFF, index=False, encoding='utf-8')

    # регрессия по накопленным ошибкам ревью (если есть)
    if REGRESSION.exists():
        reg = pd.read_csv(REGRESSION)
        m = reg.merge(g[['id', 'genesis']], on='id', how='left')
        # синтетические id (остатки разрезов) от версии к версии не сохраняются →
        # для них оцениваем ПО ГЕОМЕТРИИ: доля площади эталонного полигона внутри shoal текущего прогона
        missing = m['genesis'].isna()
        if missing.any() and SAMPLE_GEOMS.exists():
            sg = gpd.read_file(SAMPLE_GEOMS).to_crs(EA_CRS).set_index('id')
            shoal_u = g.loc[g['genesis'] == 'shoal', 'geometry'].union_all()
            for i in m.index[missing]:
                cid = int(m.at[i, 'id'])
                if cid in sg.index:
                    geom = sg.at[cid, 'geometry']
                    frac = geom.intersection(shoal_u).area / geom.area if geom.area > 0 else 0.0
                    m.at[i, 'genesis'] = 'shoal' if frac >= 0.5 else 'unassigned'
                    m.at[i, 'by_geom'] = True
        m['by_geom'] = m.get('by_geom', pd.Series(False, index=m.index)).fillna(False)
        ok = (m['expected_genesis'] == m['genesis']).sum()
        print(f'\n  РЕГРЕССИЯ [{VARIANT}]: {ok}/{len(m)} эталонных контуров совпали ({100*ok/len(m):.0f}%) '
              f'(по геометрии оценено {int(m["by_geom"].sum())})')
        bad = m[m['expected_genesis'] != m['genesis']]
        if len(bad):
            print(f'  расхождения ({len(bad)}), id → ожидалось / получилось [страта]:')
            for _, r in bad.iterrows():
                print(f'    {int(r.id)} → {r.expected_genesis} / {r.genesis} [{r.get("stratum", "")}]')
        m.to_csv(QC / f'regression_report_{VARIANT}.csv', index=False, encoding='utf-8')
    else:
        print('\n  регрессионного набора пока нет (exports/qc/regression_step1.csv)')

    g.to_file(OUT_GPKG, layer='genesis', driver='GPKG')
    print(f'\nСохранено: {OUT_GPKG}\n           {OUT_DIFF}\nВремя: {(time.time()-t0)/60:.1f} мин')


if __name__ == '__main__':
    main()
