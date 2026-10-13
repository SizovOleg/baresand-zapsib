"""
81_step4_rule.py — шаг 4 генезиса: остаток после шага 3 → «эоловый» (aeolian) или «неопределённый» (undefined). DNA §6.5.4–6.5.5.

Вход:  exports/baresand_genesis_step3_v4e.gpkg (весь продукт; меняются только контуры genesis = 'unassigned'),
       exports/qc/step4/step4_evidence.csv (80: кластерность, ближайший крупный, ориентация, поля шага 2).
Три страты по размеру (методобзор): гиганты и средние (≥ SMALL_HA) — контурные правила с конъюнкциями; мелочь (< SMALL_HA) —
наследует метку ближайшего крупного (≥ BIG_HA) соседа в D_INHERIT, иначе по кластерности, иначе undefined.
Исключения (undefined, проверяются первыми): u_mmu — площадь < MMU; u_burn — потеря леса (гарь/вырубка, ошибка маски); u_khasyrei —
днище спущенного озера; u_veg — контур ≥ SMALL_HA, зарос на подложке S2 2017–19 (NDVI ≥ VEG_NDVI, голого < VEG_BARE) — свежее
нарушение или ошибка маски; u_wet — затопляется по GSW (flood_frac0 ≥ WET_FLOOD), не отмель шага 2 и не доказан старым → конфликт.
Положительные признаки E2 (для ≥ SMALL_HA): e_stable — голый уже в 2000 (bare2000 ≥ STABLE_BARE; севернее 70° без Hansen: виден на
подложке S2 2017–19 ≥ STABLE_S2 или светлый в 1985); e_dry — вне поймы (flood_frac0 < DRY_FLOOD ∧ русло дальше D_CHANNEL);
e_far — дороги/промзоны OSM дальше D_FAR; e_cluster — ≥ N_CLUSTER других контуров в 2 км; e_orient — ось в секторе ветров (слабый).
Решение: aeolian при score = e_stable + e_dry + e_far + e_cluster ≥ SCORE_MIN; confidence high (score ≥ 3 ∧ e_stable), medium (иначе);
затопляемый, но старый (flood ≥ WET_FLOOD ∧ e_stable) — aeolian с флагом hist_floodplain (DNA §6.5.3: «историческая пойма»).
Выход: exports/baresand_genesis_step4_<tag>.gpkg (+ step4_rule, genesis_confidence, флаги), сводка exports/qc/step4/step4_rule_summary_<tag>.txt,
регрессия по exports/qc/step4/regression_step4.csv (id, expected_genesis: aeolian | всё остальное = не эоловый → ожидается undefined).
Запуск: python -u python/81_step4_rule.py --tag v1 [--параметр значение ...]
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
QC4 = EXPORTS / 'qc' / 'step4'
SRC = EXPORTS / 'baresand_genesis_step3_v4e.gpkg'
EVID = QC4 / 'step4_evidence.csv'
REGRESSION = QC4 / 'regression_step4.csv'
SAMPLE_GEOMS = QC4 / 'visual_sample_geoms_step4.gpkg'
EA_CRS = 'EPSG:3576'

DEFAULTS = dict(
    mmu_ha=0.09, small_ha=1.0, big_ha=5.0, d_inherit=2000.0,
    stable_bare=0.50, stable_s2=0.30, stable_l85_dark=0.40,
    dry_flood=0.10, wet_flood=0.20, d_channel=200.0,
    d_far=500.0, n_cluster=3, score_min=2,
    veg_ndvi=0.50, veg_bare=0.05,
    burn_loss=0.20, shoal_channel=-1.0, shoal_flood=0.50, lin_ero15=0.02, lin_elong=4.0, small_bare_s2=0.0,
)
# Калибровка на эталоне 190 строк (QC шага 4, 2026-09-07; перебор 23 вариантов):
#   shoal_channel = -1 — отсечка «контур на русле → не эоловый» ОТКЛЮЧЕНА: приречные дюнные массивы и раздувы на бровке террасы
#     стоят в 0–100 м от русла, и она рубила их (гиганты 40/57 против 56/57). Пропущенные шагом 2 побочни ловятся только по затоплению.
#   shoal_flood = 0.5 — в undefined уходит контур у самого уреза, заливаемый более чем наполовину площади.
#   small_bare_s2 = 0 — требование «мелочь видна голой на подложке 2017–19» ухудшало результат (мелкие раздувы дают смешанные пиксели 10 м).
#   e_far вне суммы баллов, burn_loss = 0.2, наследование улик частями разрезов — все три правки улучшают результат.
RULES = ('undef_mmu', 'undef_noev', 'undef_burn', 'undef_khasyrei', 'undef_shoal', 'undef_lin', 'undef_veg', 'undef_wet',
         'aeolian_high', 'aeolian_medium', 'undef_few', 'inherit_aeolian', 'inherit_undef', 'cluster_small', 'undef_isolated')


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def regression(g: gpd.GeoDataFrame, tag: str) -> None:
    if not REGRESSION.exists():
        print('\n  регрессионного набора шага 4 пока нет')
        return
    reg = pd.read_csv(REGRESSION)
    m = reg.merge(g[['id', 'genesis']], on='id', how='left')
    missing = m['genesis'].isna()
    unscored = []
    if missing.any() and SAMPLE_GEOMS.exists():                       # синтетические id частей — по геометрии
        sg = gpd.read_file(SAMPLE_GEOMS, layer='sample').to_crs(EA_CRS).set_index('id')
        sidx = g.sindex
        for i in m.index[missing]:
            cid = int(m.at[i, 'id'])
            if cid not in sg.index:
                unscored.append(cid)                                  # строки эталона без геометрии — молча не терять
                continue
            geom = sg.at[cid, 'geometry']
            hits = g.iloc[sidx.query(geom, predicate='intersects')]
            u = hits.loc[hits['genesis'] == 'aeolian', 'geometry']
            f = geom.intersection(u.union_all()).area / geom.area if len(u) and geom.area > 0 else 0.0
            m.at[i, 'genesis'] = 'aeolian' if f >= 0.5 else 'undefined'
    got = m['genesis'].fillna('undefined')
    want_aeol = m['expected_genesis'] == 'aeolian'
    ok = np.where(want_aeol, got == 'aeolian', got == 'undefined')
    m['ok'] = ok
    print(f'\n  РЕГРЕССИЯ [{tag}]: {int(ok.sum())}/{len(m)} ({100 * ok.mean():.0f}%) | эоловые: {int((ok & want_aeol).sum())}/{int(want_aeol.sum())}, '
          f'не эоловые → undefined: {int((ok & ~want_aeol).sum())}/{int((~want_aeol).sum())}')
    if unscored:
        print(f'    ВНИМАНИЕ: {len(unscored)} строк эталона не оценены (нет ни в продукте, ни в слое геометрий): {unscored[:10]}'
              f'{" …" if len(unscored) > 10 else ""} — они засчитаны как undefined')
    if 'stratum' in m.columns:
        t = m.groupby('stratum')['ok'].agg(['sum', 'size'])
        print('   ' + ' | '.join(f'{s}: {int(r["sum"])}/{int(r["size"])}' for s, r in t.iterrows()))
    m.to_csv(QC4 / f'regression_report_step4_{tag}.csv', index=False, encoding='utf-8')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='v1')
    for k, v in DEFAULTS.items():
        ap.add_argument(f'--{k.replace("_", "-")}', type=type(v), default=v)
    ap.add_argument('--use-far', action='store_true', help='считать e_far (дороги OSM > 500 м) слагаемым score; по умолчанию нет: у 79 % '
                                                           'контуров дорог OSM нет в 5 км — балл давался даром (QC шага 4)')
    ap.add_argument('--no-shoal-guard', action='store_true', help='не отправлять контуры у русла/в зоне затопления в undefined')
    ap.add_argument('--no-lin-guard', action='store_true', help='не отправлять ленты (тонкие вытянутые: дороги/русла) в undefined')
    ap.add_argument('--no-parent-evidence', action='store_true', help='не наследовать улики от родителя для частей разрезов (id 800000+)')
    a = ap.parse_args()
    P = {k: getattr(a, k) for k in DEFAULTS}
    t0 = time.time()
    QC4.mkdir(parents=True, exist_ok=True)
    out_gpkg = EXPORTS / f'baresand_genesis_step4_{a.tag}.gpkg'
    print('═══════════════════════════════════════')
    print(f'ШАГ 4 [{a.tag}]: undefined ← mmu<{P["mmu_ha"]} ∨ burn ∨ khasyrei ∨ veg(NDVI≥{P["veg_ndvi"]}) ∨ wet(flood≥{P["wet_flood"]} ∧ ¬stable); '
          f'aeolian ← score(stable,dry,far,cluster≥{P["n_cluster"]}) ≥ {P["score_min"]}; мелочь < {P["small_ha"]} га наследует от соседа ≥ {P["big_ha"]} га в {P["d_inherit"]:.0f} м')
    print('═══════════════════════════════════════')

    log('читаю продукт шага 3...')
    g = gpd.read_file(SRC).to_crs(EA_CRS)
    ev = pd.read_csv(EVID, low_memory=False)
    ev_cols = [c for c in ev.columns if c not in g.columns or c == 'id']
    g = g.merge(ev[ev_cols], on='id', how='left', validate='1:1')
    cand = g['genesis'] == 'unassigned'
    log(f'контуров {len(g):,}; остаток (кандидаты шага 4): {int(cand.sum()):,} | {g.loc[cand, "area_km2"].sum():,.0f} км²')

    # части разрезов эксперта (id 800000+) не имеют улик шага 3 — берём улики родителя, иначе балл давался «по умолчанию» (QC шага 4)
    EVCOLS = ['flood_frac0', 'dist_water_m', 'dist_channel_m', 'd_road_built', 'd_industrial', 'bare2000_frac', 'l85_dark_frac',
              'bare_s2_frac', 'ndvi_s2_mean', 's2_cov', 'loss_frac', 'tc2000_mean', 'ero15', 'elong', 'rect', 'n_nb_2km']
    noev = cand & g['flood_frac0'].isna() & g['bare2000_frac'].isna() & g['d_road_built'].isna()
    if not a.no_parent_evidence and noev.any():
        # родителей нет в слое (их заменили части) — улики берём из таблицы улик шага 3 по parent_id
        ev3 = pd.read_csv(EXPORTS / 'qc' / 'step3' / 'step3_evidence.csv', usecols=lambda c: c == 'id' or c in EVCOLS, low_memory=False).set_index('id')
        pid = g.loc[noev, 'parent_id']
        for c in EVCOLS:
            if c in g.columns and c in ev3.columns:
                g.loc[noev, c] = g.loc[noev, c].fillna(pd.Series(pid.map(ev3[c]).values, index=g.index[noev]))
        still = cand & g['flood_frac0'].isna() & g['bare2000_frac'].isna() & g['d_road_built'].isna()
        log(f'  без улик шага 3: {int(noev.sum())} (части разрезов); унаследовано от родителя: {int(noev.sum() - still.sum())}, осталось без улик: {int(still.sum())}')
        noev = still

    A = g['area_ha']
    f0 = g['flood_frac0'].fillna(0)
    bare = g['bare2000_frac']
    hansen = bare.notna()
    stable = np.where(hansen, bare >= P['stable_bare'],
                      (g['bare_s2_frac'].fillna(0) >= P['stable_s2']) | (g['l85_dark_frac'].fillna(1) <= P['stable_l85_dark']))
    e_stable = pd.Series(stable, index=g.index).astype(bool)
    e_dry = (f0 < P['dry_flood']) & (g['dist_channel_m'].fillna(1e9) > P['d_channel'])
    e_far = (g['d_road_built'].fillna(1e9) > P['d_far']) & (g['d_industrial'].fillna(1e9) > P['d_far'])
    e_cluster = g['n_nb_2km'].fillna(0) >= P['n_cluster']
    e_orient = g['orient_ok'].fillna(-1) == 1
    score = e_stable.astype(int) + e_dry.astype(int) + e_cluster.astype(int) + (e_far.astype(int) if a.use_far else 0)
    hist_flood = (f0 >= P['wet_flood']) & e_stable

    u_mmu = A < P['mmu_ha']
    # гарь/вырубка: порог потери леса ниже, чем burn_suspect шага 3 (0.5) — QC шага 4 нашёл гарь при loss 0.48
    u_burn = (g['burn_suspect'].fillna(0) == 1) | ((g['loss_frac'].fillna(0) >= P['burn_loss']) & (g['tc2000_mean'].fillna(0) >= 10))
    u_khas = g['khasyrei_suspect'].fillna(0) == 1
    # пропущенная отмель (ошибка шага 2): контур на русле или заливается — конфликт правил, DNA §6.5.5 → undefined
    u_shoal = pd.Series(False, index=g.index) if a.no_shoal_guard else (
        (g['dist_channel_m'].fillna(1e9) <= P['shoal_channel']) | ((g['dist_water_m'].fillna(1e9) <= 1) & (f0 >= P['shoal_flood'])))
    # лента: тонкий вытянутый контур (полотно дороги, коса вдоль русла) — не эоловая форма
    u_lin = pd.Series(False, index=g.index) if a.no_lin_guard else ((g['ero15'].fillna(1) <= P['lin_ero15']) & (g['elong'].fillna(1) >= P['lin_elong']))
    u_veg = (A >= P['small_ha']) & (g['s2_cov'].fillna(0) > 0) & (g['ndvi_s2_mean'] >= P['veg_ndvi']) & (g['bare_s2_frac'].fillna(0) < P['veg_bare'])
    u_wet = (f0 >= P['wet_flood']) & ~e_stable
    small = A < P['small_ha']

    r = {
        'undef_mmu': cand & u_mmu,
        'undef_noev': cand & noev,
        'undef_burn': cand & u_burn,
        'undef_khasyrei': cand & u_khas,
        'undef_shoal': cand & u_shoal,
        'undef_lin': cand & u_lin,
        'undef_veg': cand & u_veg,
        'undef_wet': cand & u_wet,
        'aeolian_high': cand & ~small & (score >= 3) & e_stable,
        'aeolian_medium': cand & ~small & (score >= P['score_min']),
        'undef_few': cand & ~small,
    }
    genesis = g['genesis'].copy()
    rule = pd.Series('', index=g.index)
    conf = pd.Series('', index=g.index)
    taken = pd.Series(False, index=g.index)
    for name in ('undef_mmu', 'undef_noev', 'undef_burn', 'undef_khasyrei', 'undef_shoal', 'undef_lin', 'undef_veg', 'undef_wet',
                 'aeolian_high', 'aeolian_medium', 'undef_few'):
        hit = r[name] & ~taken
        rule[hit] = f'{a.tag}_{name}'
        genesis[hit] = 'aeolian' if name.startswith('aeolian') else 'undefined'
        conf[hit] = {'aeolian_high': 'high', 'aeolian_medium': 'medium'}.get(name, 'none')
        taken |= hit
    # мелочь: наследование от ближайшего крупного соседа, иначе кластер, иначе undefined
    rest = cand & ~taken
    big_cls = g.set_index('id')['genesis']                       # временно — до присвоения мелочи; крупные уже размечены выше
    big_cls = genesis.groupby(g['id']).first()
    nb = g['big_id'].fillna(-1).astype(int)
    nb_cls = nb.map(big_cls).where(g['dist_big_m'].fillna(1e9) <= P['d_inherit'])
    inh_a = rest & (nb_cls == 'aeolian')
    inh_u = rest & (nb_cls == 'undefined')
    # мелочь без крупного соседа: кластер + сухость + видна голой на подложке S2 (иначе ягельник/светлая тундра — QC шага 4)
    clus = rest & nb_cls.isna() & e_cluster & (f0 < P['dry_flood']) & (g['bare_s2_frac'].fillna(0) >= P['small_bare_s2'])
    for name, m, gen, cf in (('inherit_aeolian', inh_a, 'aeolian', 'low'), ('inherit_undef', inh_u, 'undefined', 'none'),
                             ('cluster_small', clus, 'aeolian', 'low')):
        hit = m & ~taken
        rule[hit] = f'{a.tag}_{name}'
        genesis[hit] = gen
        conf[hit] = cf
        taken |= hit
    hit = cand & ~taken
    rule[hit] = f'{a.tag}_undef_isolated'
    genesis[hit] = 'undefined'
    conf[hit] = 'none'

    g['genesis_step3'] = g['genesis']
    g['genesis'] = genesis
    g['step4_rule'] = rule
    g['genesis_confidence'] = conf
    for name, s in (('e_stable', e_stable), ('e_dry', e_dry), ('e_far', e_far), ('e_cluster', e_cluster), ('e_orient', e_orient), ('hist_floodplain', hist_flood)):
        g[name] = (cand & s).astype('int16')
    g['e_score'] = np.where(cand, score, -1).astype('int16')

    L = [f'ШАГ 4 [{a.tag}] — остаток {int(cand.sum()):,} конт / {g.loc[cand, "area_km2"].sum():,.0f} км²']
    for name in RULES:
        s = g[g['step4_rule'] == f'{a.tag}_{name}']
        L.append(f'  {name:16s}: {len(s):7,} конт | {s.area_km2.sum():7.1f} км² | медиана {s.area_ha.median() if len(s) else 0:.2f} га')
    for cls in ('aeolian', 'undefined'):
        s = g[g['genesis'] == cls]
        L.append(f'  {cls:16s}: {len(s):7,} конт | {s.area_km2.sum():7.1f} км² ({100 * len(s) / cand.sum():.0f} % числа, {100 * s.area_km2.sum() / g.loc[cand, "area_km2"].sum():.0f} % площади остатка)')
    ae = g['genesis'] == 'aeolian'
    L.append(f'  hist_floodplain (затопляется по GSW, но старый): {int((ae & (g.hist_floodplain == 1)).sum()):,} конт | {g.loc[ae & (g.hist_floodplain == 1), "area_km2"].sum():.1f} км²')
    L.append(f'  севернее 70° (без Hansen): aeolian {int((ae & ~hansen & cand).sum()):,} / undefined {int(((g.genesis == "undefined") & ~hansen & cand).sum()):,}; '
             f'confidence по остатку: {g.loc[cand, "genesis_confidence"].value_counts().to_dict()}')
    L.append(f'  ориентация в секторе ветров среди вытянутых эоловых ≥ 1 га: {100 * g.loc[ae & (A >= 1) & (g.orient_ok >= 0), "orient_ok"].mean():.0f} % (случайно было бы {100 * 80 / 180:.0f} %)')
    print('\n'.join(L))
    regression(g, a.tag)

    drop = [c for c in ('lat', 'lon') if c in g.columns and c not in ('id',)]
    g.drop(columns=drop).to_file(out_gpkg, layer='genesis', driver='GPKG')
    (QC4 / f'step4_rule_summary_{a.tag}.txt').write_text('\n'.join(L), encoding='utf-8')
    print(f'\nСохранено: {out_gpkg}\nВремя: {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
