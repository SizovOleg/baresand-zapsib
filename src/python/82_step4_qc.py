"""
82_step4_qc.py — визуальная верификация шага 4 (эоловый / неопределённый): выборка по стратам + рендер; сборка вердиктов агентов.

Страты (stratum) — по правилу 81 и размеру:
  giant          — ≥ 50 га (все или верх по площади): дюнные массивы / поля раздувов — эоловые? или пропущенный техноген/отмель/гарь?
  aeolian_high   — 1–50 га, score ≥ 3 ∧ старый песок — контроль
  aeolian_medium — 1–50 га, score 2 (нет доказательства стабильности или у русла) — раздув? или свежее нарушение / ошибка маски?
  undef_few      — 1–50 га, признаков не хватило — что это?
  undef_wet      — затопляется по GSW, не отмель шага 2, не старый — пропущенная отмель / хасырей / раздув у воды?
  undef_veg      — ≥ 1 га, зарос на подложке S2 2017–19 — свежее нарушение или ошибка маски (лишайник, гарь, торф)?
  undef_burn     — потеря леса 2001–2019 — гарь (ошибка маски) или раздув после пожара?
  inherit        — мелочь < 1 га, унаследовала «эоловый» от крупного соседа — действительно пятно развеивания?
  cluster_small  — мелочь без крупного соседа, но в кластере — раздув или шум маски?
  undef_isolated — мелочь одиночная — шум маски (лишайник, торф, снег) или одиночный раздув?
  north          — севернее 70° (без Hansen), ≥ 1 га, любой класс — раздувы морских террас Ямала/Гыдана?
Секторы: KMeans по центроидам (запад → восток). Файлы: exports/qc/step4/visual_sample_step4.csv/.json, visual_sample_geoms_step4.gpkg
(слой sample), overlay_step4.gpkg, thumbs_step4/; агенты → agents_step4/review_S<n>.json + verify_S<n>.json.
synthesize: verdicts_step4.csv, regression_step4.csv (дописывает подтверждённые; expected_genesis = aeolian | undefined + err_tag),
final_check_step4.gpkg/.csv эксперту, summary_step4.txt.
Запуск: python -u python/82_step4_qc.py sample --tag v1 [--render] [--sectors 6 --giants 60]
        python -u python/82_step4_qc.py synthesize --tag v1
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import subprocess
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC4 = EXPORTS / 'qc' / 'step4'
DRIVER = Path(r'D:\test\baresand_zapsib\python\qc_render_parallel.py')
REGRESSION = QC4 / 'regression_step4.csv'
SAMPLE_CSV = QC4 / 'visual_sample_step4.csv'
SAMPLE_JSON = QC4 / 'visual_sample_step4.json'
SAMPLE_GEOMS = QC4 / 'visual_sample_geoms_step4.gpkg'
OVERLAY = QC4 / 'overlay_step4.gpkg'
THUMBS = QC4 / 'thumbs_step4'
AGENTS = QC4 / 'agents_step4'
OUT_VERDICTS = QC4 / 'verdicts_step4.csv'
OUT_CHECK_GPKG = QC4 / 'final_check_step4.gpkg'
OUT_CHECK_CSV = QC4 / 'final_check_step4.csv'
EA_CRS = 'EPSG:3576'
SEED = 42
PER_SECTOR = {'aeolian_high': 3, 'aeolian_medium': 4, 'undef_few': 2, 'undef_wet': 3, 'undef_veg': 3, 'undef_burn': 1,
              'inherit': 3, 'cluster_small': 2, 'undef_isolated': 3, 'north': 3}
CONTROL_PER_STRATUM = 2
EV_COLS = ['id', 'sector', 'stratum', 'genesis', 'step4_rule', 'genesis_confidence', 'e_score', 'e_stable', 'e_dry', 'e_far', 'e_cluster', 'hist_floodplain',
           'area_ha', 'n_nb_2km', 'dist_big_m', 'dist_water_m', 'dist_channel_m', 'nearest_type', 'flood_frac0', 'd_road_built', 'd_industrial',
           'bare2000_frac', 'hansen_covered', 'loss_frac', 'tc2000_mean', 'l85_dark_frac', 'bare_s2_frac', 'ndvi_s2_mean', 'rect', 'elong', 'ero50', 'lat', 'lon']
# вердикт агента → ожидание для регрессии (в шаге 4 достижимы только aeolian / undefined)
TO_EXPECTED = {'aeolian': 'aeolian', 'not_sand': 'undefined', 'shoal': 'undefined', 'anthropogenic': 'undefined', 'khasyrei': 'undefined'}
RU = {'aeolian': 'эоловый', 'not_sand': 'не песок', 'shoal': 'отмель', 'anthropogenic': 'техноген', 'khasyrei': 'хасырей', 'mixed': 'смешанный', 'unclear': 'неясно'}


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def build_sample(a) -> None:
    t0 = time.time()
    src = EXPORTS / f'baresand_genesis_step4_{a.tag}.gpkg'
    log(f'читаю {src.name} (остаток шага 3)...')
    g = gpd.read_file(src, where="genesis_step3 = 'unassigned'").to_crs(EA_CRS)
    done = set(pd.read_csv(REGRESSION)['id'].astype(int)) if REGRESSION.exists() else set()
    g = g[~g['id'].isin(done)].copy()
    ll = g.geometry.centroid.to_crs('EPSG:4326')
    g['lat'], g['lon'] = ll.y.round(4).values, ll.x.round(4).values
    rule = g['step4_rule'].str.replace(f'{a.tag}_', '', regex=False)
    g['stratum'] = ''
    big = g['area_ha'] >= 50
    mid = (g['area_ha'] >= 1) & ~big
    for name in ('aeolian_high', 'aeolian_medium', 'undef_few', 'undef_wet', 'undef_veg', 'undef_burn'):
        g.loc[mid & (rule == name), 'stratum'] = name
    g.loc[(rule == 'inherit_aeolian') | (rule == 'inherit_undef'), 'stratum'] = 'inherit'
    g.loc[rule == 'cluster_small', 'stratum'] = 'cluster_small'
    g.loc[rule == 'undef_isolated', 'stratum'] = 'undef_isolated'
    north = (g['lat'] > 70) & mid & g['stratum'].isin(['aeolian_high', 'aeolian_medium', 'undef_few'])
    g.loc[north, 'stratum'] = 'north'                       # север без Hansen — отдельная страта поверх правила
    g.loc[big, 'stratum'] = 'giant'
    pool = g[g['stratum'] != ''].copy()
    log(f'пул: {len(pool):,}; по стратам: {pool["stratum"].value_counts().to_dict()}')
    pool['x'], pool['y'] = pool.geometry.centroid.x, pool.geometry.centroid.y
    km = KMeans(n_clusters=a.sectors, random_state=SEED, n_init=10).fit(pool[['x', 'y']].values)
    pool['cl'] = km.labels_
    order = pool.groupby('cl')['x'].mean().sort_values().index.tolist()
    pool['sector'] = pool['cl'].map({cl: i + 1 for i, cl in enumerate(order)})
    rng = np.random.default_rng(SEED)
    picks = [pool[pool['stratum'] == 'giant'].sort_values('area_ha', ascending=False).head(a.giants)]
    for s in range(1, a.sectors + 1):
        ps = pool[pool['sector'] == s]
        for stname, n in PER_SECTOR.items():
            cand = ps[ps['stratum'] == stname]
            if len(cand):
                picks.append(cand.sample(n=min(len(cand), n), random_state=int(rng.integers(1e9))))
    sample = pd.concat(picks).drop_duplicates('id').copy()
    ev = [c for c in EV_COLS if c in sample.columns]
    sample[ev].sort_values(['sector', 'stratum', 'area_ha'], ascending=[True, True, False]).to_csv(SAMPLE_CSV, index=False, encoding='utf-8')
    sg = gpd.GeoDataFrame(sample[['id', 'genesis', 'stratum', 'area_ha', 'geometry']], geometry='geometry', crs=EA_CRS)
    bad = ~sg.geometry.is_valid          # части ручных разрезов бывают с самопересечением кольца (пиксельная граница маски)
    if bad.any():
        sg.loc[bad, 'geometry'] = sg.loc[bad, 'geometry'].make_valid()
        log(f'починено невалидных геометрий в выборке: {int(bad.sum())}')
    if SAMPLE_GEOMS.exists():            # НЕ перезаписывать: слой хранит геометрии строк эталона (в т.ч. частей разрезов эксперта)
        old = gpd.read_file(SAMPLE_GEOMS, layer='sample').to_crs(EA_CRS)
        keep = old[~old['id'].isin(sg['id'])]
        sg = gpd.GeoDataFrame(pd.concat([keep, sg], ignore_index=True), geometry='geometry', crs=EA_CRS)
        log(f'слой sample: сохранено прежних строк {len(keep)}, добавлено/обновлено {len(sample)} → всего {len(sg)}')
    sg.to_file(SAMPLE_GEOMS, layer='sample', driver='GPKG')
    sectors = {}
    for s in range(1, a.sectors + 1):
        ss = sample[sample['sector'] == s]
        if len(ss) == 0:
            continue
        sectors[str(s)] = {'name': f'S{s}', 'center_lat': round(float(ss['lat'].mean()), 3), 'center_lon': round(float(ss['lon'].mean()), 3),
                           'lat_range': [round(float(ss['lat'].min()), 2), round(float(ss['lat'].max()), 2)],
                           'lon_range': [round(float(ss['lon'].min()), 2), round(float(ss['lon'].max()), 2)],
                           'n': int(len(ss)), 'by_stratum': ss['stratum'].value_counts().to_dict(), 'ids': [int(i) for i in ss['id'].tolist()]}
    SAMPLE_JSON.write_text(json.dumps(sectors, ensure_ascii=False, indent=1), encoding='utf-8')
    log(f'выборка: {len(sample)} контуров в {len(sectors)} секторах; по стратам: {sample["stratum"].value_counts().to_dict()}')
    for s, d in sectors.items():
        print(f"  S{s}: {d['n']:3d} | {d['center_lat']}N {d['center_lon']}E | {d['by_stratum']}")
    if a.render:
        log('оверлей из продукта шага 4...')
        full = gpd.read_file(src, columns=['id', 'genesis'])
        full[['id', 'genesis', 'geometry']].to_file(OVERLAY, layer='overlay', driver='GPKG')
        cmd = [sys.executable, str(DRIVER), '--workers', '6', '--batch', '12', '--samples', str(SAMPLE_JSON), '--out', str(THUMBS),
               '--overlay', str(OVERLAY), '--field', 'genesis', '--sample', str(SAMPLE_GEOMS), '--evidence', str(SAMPLE_CSV)]
        log('рендер: ' + ' '.join(cmd[1:]))
        subprocess.run(cmd, check=False)
        log(f'миниатюр: {len(list(THUMBS.glob("*_esri.png")))}')
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


def synthesize(a) -> None:
    sample = pd.read_csv(SAMPLE_CSV)
    rows, hints = [], []
    for rf in sorted(AGENTS.glob('review_S*.json')):
        n = int(rf.stem.split('_S')[1])
        rev = json.loads(rf.read_text(encoding='utf-8'))
        vf = AGENTS / f'verify_S{n}.json'
        ver = json.loads(vf.read_text(encoding='utf-8')) if vf.exists() else {'checks': []}
        checks = {int(c['id']): c for c in (ver.get('checks') or [])}
        hints += [(n, h) for h in (rev.get('rule_hints') or [])]
        for v in rev.get('verdicts') or []:
            c = checks.get(int(v['id']))
            rows.append({'id': int(v['id']), 'verdict': v['verdict'], 'err_tag': (v.get('err_tag') or '').strip(), 'confidence': v.get('confidence', 'low'),
                         'reason': v.get('reason', ''), 'rule_hint': v.get('rule_hint', ''), 'checked': c is not None,
                         'agree': (c['agree'] if c else None), 'verdict2': (c['verdict'] if c else ''), 'reason2': (c.get('reason', '') if c else '')})
    if not rows:
        print('нет файлов агентов в', AGENTS)
        return
    vd = pd.DataFrame(rows).drop_duplicates('id')
    df = sample.merge(vd, on='id', how='left')

    def status(r) -> str:
        if pd.isna(r['verdict']):
            return 'not_reviewed'
        contested = r['verdict'] in ('mixed', 'unclear') or r['confidence'] == 'low'
        if r['verdict'] == 'unclear' and (not r['checked'] or r['verdict2'] in ('', 'unclear')):
            return 'unclear'
        if contested and not r['checked']:
            return 'unverified'
        if r['checked'] and r['agree'] is False:
            return 'disputed'
        if r['checked'] and r['verdict2'] == 'unclear':
            return 'unclear'
        return 'confirmed'
    df['status'] = df.apply(status, axis=1)
    df['final_verdict'] = np.where(df['status'] == 'confirmed', df['verdict'], '')
    df['expected'] = df['final_verdict'].map(TO_EXPECTED).fillna('')
    df['rule_correct'] = np.where(df['expected'] == '', np.nan, df['expected'] == df['genesis'])
    df.to_csv(OUT_VERDICTS, index=False, encoding='utf-8')

    reg = pd.read_csv(REGRESSION) if REGRESSION.exists() else pd.DataFrame(columns=['id', 'expected_genesis', 'stratum', 'sector', 'verdict'])
    add = df[df['expected'] != ''][['id', 'expected', 'stratum', 'sector', 'final_verdict']].rename(columns={'expected': 'expected_genesis', 'final_verdict': 'verdict'})
    add = add[~add['id'].isin(reg['id'])]
    reg = pd.concat([reg, add], ignore_index=True)
    reg.to_csv(REGRESSION, index=False, encoding='utf-8')

    df['agents'] = np.where(df['status'] == 'confirmed', df['final_verdict'].map(RU).fillna('сомнение'), 'сомнение')
    rng = np.random.default_rng(SEED)
    need = df[df['agents'] == 'сомнение'].copy()
    ctrl = [grp.sample(n=min(CONTROL_PER_STRATUM, len(grp)), random_state=int(rng.integers(1e9))) for _, grp in df[df['status'] == 'confirmed'].groupby('stratum')]
    check = pd.concat([need] + ctrl).drop_duplicates('id')
    check['note'] = np.where(check['status'] == 'disputed', 'дешифровщик: ' + check['reason'].fillna('') + ' || скептик: ' + check['reason2'].fillna(''), check['reason'].fillna(''))
    check['expert'] = ''
    check = check[['id', 'agents', 'expert', 'note', 'stratum', 'genesis', 'step4_rule', 'area_ha', 'lat', 'lon']]
    check.to_csv(OUT_CHECK_CSV, index=False, encoding='utf-8')
    geoms = gpd.read_file(SAMPLE_GEOMS, layer='sample')[['id', 'geometry']]
    geoms.merge(check, on='id', how='inner').to_file(OUT_CHECK_GPKG, layer='final_check', driver='GPKG')

    L = [f'Шаг 4 [{a.tag}] — проверка агентами: {len(df)} контуров, статусы: {df["status"].value_counts().to_dict()}',
         f'подтверждённых: {int((df["expected"] != "").sum())}; добавлено в эталон: {len(add)} (всего строк {len(reg)})', '',
         'вердикты (подтверждённые): ' + str(df.loc[df['expected'] != '', 'final_verdict'].value_counts().to_dict()), '',
         'страта          | всего | подтв. | правило верно | эоловый→undef / не эоловый→aeolian']
    for stname, grp in df.groupby('stratum'):
        c = grp[grp['expected'] != '']
        ok = c['rule_correct'].astype(float)
        fn = int(((c['expected'] == 'aeolian') & (c['genesis'] == 'undefined')).sum())
        fp = int(((c['expected'] == 'undefined') & (c['genesis'] == 'aeolian')).sum())
        L.append(f'{stname:15s} | {len(grp):5d} | {len(c):6d} | {ok.sum():.0f}/{len(c)} ({(100 * ok.mean()) if len(c) else 0:.0f}%) | {fn} / {fp}')
    c = df[df['expected'] != '']
    L += ['', f'ИТОГО правило верно: {c["rule_correct"].astype(float).sum():.0f}/{len(c)} ({100 * c["rule_correct"].astype(float).mean():.0f}%)']
    tags = df.loc[df['err_tag'] != '', 'err_tag'].value_counts()
    if len(tags):
        L += ['', 'err_tag: ' + ', '.join(f'{k} {v}' for k, v in tags.items())]
    if hints:
        L += ['', 'rule_hints агентов:'] + [f'  S{s}: {h}' for s, h in hints]
    L += ['', f'Эксперту: {OUT_CHECK_GPKG.name} — {len(check)} контуров ({int((check.agents == "сомнение").sum())} сомнений + контроль).']
    txt = '\n'.join(L)
    print(txt)
    (QC4 / f'summary_step4_{a.tag}.txt').write_text(txt, encoding='utf-8')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['sample', 'synthesize'])
    ap.add_argument('--tag', default='v1')
    ap.add_argument('--sectors', type=int, default=6)
    ap.add_argument('--giants', type=int, default=60)
    ap.add_argument('--render', action='store_true')
    a = ap.parse_args()
    if a.mode == 'sample':
        build_sample(a)
    else:
        synthesize(a)


if __name__ == '__main__':
    main()
