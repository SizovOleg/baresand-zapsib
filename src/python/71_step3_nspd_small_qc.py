"""
71_step3_nspd_small_qc.py — визуальная проверка МЕЛКИХ (< 20 га) срабатываний кадастра ЕГРН в правиле v4 (a_nspd_on) и контроль
флага nspd_lic_suspect. Крупные (≥ 20 га, 114 конт) эксперт проверил вручную (NSPD.shp); мелкие — половина площади прироста —
проверяются по стратам агентами-дешифровщиками по снимкам Esri, как в 63/64.

Страты (stratum):
  obj_near   — объектный ВРИ (куст, карьер, площадка, трубопровод…), дорога OSM ≤ 300 м — контроль: точно техноген?
  obj_far    — объектный ВРИ, дорога OSM > 1 км — некартированный промысел (техноген) или отвод на природном песке?
  lic_near   — лицензионный ВРИ (недропользование, геологическое изучение…), дорога ≤ 300 м
  lic_far    — лицензионный ВРИ, дорога > 1 км — главный риск: отвод накрыл раздув
  any_only   — сработало только «любой землеотвод ≥ 0.5» (пром. участок < 0.3): обособленные части отводов без ВРИ, дачи…
  struct_only— только сооружение ЕГРН ≥ 0.3 (без участков)
  lic_off    — снято флагом nspd_lic_suspect (лицензионный отвод краем, вдали от дорог, старый песок) → природный: верно ли сняли?
Секторы: KMeans по центроидам пула (запад → восток). Файлы отдельные от 63/64 (эталон и старая выборка не трогаются):
  exports/qc/step3/visual_sample_step3_nspd.csv / .json, visual_sample_geoms_step3_nspd.gpkg (слой sample), overlay_step3_nspd.gpkg,
  thumbs_nspd/<id>_esri.png; агенты пишут agents_nspd/review_S<n>.json + verify_S<n>.json.
Режимы: sample [--render] — выборка и рендер; synthesize — сборка вердиктов агентов → verdicts_step3_nspd.csv, дописать в
  regression_step3.csv (только подтверждённые), список эксперту final_check_step3_nspd.gpkg/.csv, сводка точности правила по стратам.
Запуск: python -u python/71_step3_nspd_small_qc.py sample --render [--per-sector 18 --sectors 6]
        python -u python/71_step3_nspd_small_qc.py synthesize
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import argparse
import importlib.util
import json
import subprocess
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC3 = EXPORTS / 'qc' / 'step3'
DRIVER = Path(r'D:\test\baresand_zapsib\python\qc_render_parallel.py')
PRODUCT = EXPORTS / 'baresand_genesis_step3_v4.gpkg'            # чистое правило v4
REGRESSION = QC3 / 'regression_step3.csv'
SAMPLE_CSV = QC3 / 'visual_sample_step3_nspd.csv'
SAMPLE_JSON = QC3 / 'visual_sample_step3_nspd.json'
SAMPLE_GEOMS = QC3 / 'visual_sample_geoms_step3_nspd.gpkg'
OVERLAY = QC3 / 'overlay_step3_nspd.gpkg'
THUMBS = QC3 / 'thumbs_nspd'
AGENTS = QC3 / 'agents_nspd'
OUT_VERDICTS = QC3 / 'verdicts_step3_nspd.csv'
OUT_CHECK_GPKG = QC3 / 'final_check_step3_nspd.gpkg'
OUT_CHECK_CSV = QC3 / 'final_check_step3_nspd.csv'
EA_CRS = 'EPSG:3576'
SEED = 42
MAX_HA = 20.0
D_NEAR, D_FAR = 300.0, 1000.0
PER_STRATUM = {'obj_near': 3, 'obj_far': 3, 'lic_near': 3, 'lic_far': 3, 'any_only': 3, 'struct_only': 1, 'lic_off': 2}   # на сектор
CONTROL_PER_STRATUM = 2
EV_COLS = ['id', 'sector', 'stratum', 'genesis', 'step3_rule', 'area_ha', 'd_road_built', 'd_road_any', 'd_industrial', 'osm_overlap_built',
           'nspd_parcel_ind_frac', 'nspd_parcel_any_frac', 'nspd_struct_frac', 'parcel_kind', 'vri_kind', 'parcel_vri', 'parcel_area_ha',
           'd_parcel_ind_m', 'bare2000_frac', 'l85_dark_frac', 'nspd_lic_suspect', 'lat', 'lon']
RU = {'anthropogenic': 'техноген', 'natural': 'природный', 'mixed': 'смешанный', 'unclear': 'неясно'}

spec = importlib.util.spec_from_file_location('r62', Path(__file__).with_name('62_step3_rule.py'))
r62 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r62)


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def build_sample(a) -> None:
    t0 = time.time()
    log(f'читаю {PRODUCT.name}...')
    cols = ['id', 'genesis', 'step3_rule', 'area_ha', 'd_road_built', 'd_road_any', 'd_industrial', 'osm_overlap_built', 'nspd_parcel_ind_frac',
            'nspd_parcel_any_frac', 'nspd_struct_frac', 'parcel_kind', 'parcel_vri', 'parcel_area_ha', 'd_parcel_ind_m', 'bare2000_frac',
            'l85_dark_frac', 'nspd_lic_suspect']
    g = gpd.read_file(PRODUCT, columns=cols, where=f"(step3_rule = 'v4_a_nspd_on' AND area_ha < {MAX_HA}) OR nspd_lic_suspect = 1").to_crs(EA_CRS)
    done = set(pd.read_csv(REGRESSION)['id'].astype(int)) if REGRESSION.exists() else set()
    g = g[~g['id'].isin(done)].copy()
    g['vri_kind'] = g['parcel_vri'].apply(r62.vri_kind)
    hit = g['step3_rule'] == 'v4_a_nspd_on'
    ind = g['nspd_parcel_ind_frac'].fillna(0) >= 0.3
    st = g['nspd_struct_frac'].fillna(0) >= 0.3
    near, far = g['d_road_built'] <= D_NEAR, g['d_road_built'] > D_FAR
    g['stratum'] = ''
    g.loc[hit & ind & (g['vri_kind'] == 'object') & near, 'stratum'] = 'obj_near'
    g.loc[hit & ind & (g['vri_kind'] == 'object') & far, 'stratum'] = 'obj_far'
    g.loc[hit & ind & (g['vri_kind'] == 'license') & near, 'stratum'] = 'lic_near'
    g.loc[hit & ind & (g['vri_kind'] == 'license') & far, 'stratum'] = 'lic_far'
    g.loc[hit & ~ind & ~st, 'stratum'] = 'any_only'
    g.loc[hit & ~ind & st, 'stratum'] = 'struct_only'
    g.loc[(g['genesis'] != 'anthropogenic') & (g['nspd_lic_suspect'] == 1), 'stratum'] = 'lic_off'
    pool = g[g['stratum'] != ''].copy()
    log(f'пул: {len(pool):,} контуров; по стратам: {pool["stratum"].value_counts().to_dict()}')
    pool['x'], pool['y'] = pool.geometry.centroid.x, pool.geometry.centroid.y
    km = KMeans(n_clusters=a.sectors, random_state=SEED, n_init=10).fit(pool[['x', 'y']].values)
    pool['cl'] = km.labels_
    order = pool.groupby('cl')['x'].mean().sort_values().index.tolist()
    pool['sector'] = pool['cl'].map({cl: i + 1 for i, cl in enumerate(order)})
    rng = np.random.default_rng(SEED)
    picks = []
    for s in range(1, a.sectors + 1):
        ps = pool[pool['sector'] == s]
        for stname, n in PER_STRATUM.items():
            cand = ps[ps['stratum'] == stname]
            if len(cand):
                picks.append(cand.sample(n=min(len(cand), n), random_state=int(rng.integers(1e9))))
    sample = pd.concat(picks).drop_duplicates('id').copy()
    ll = sample.geometry.centroid.to_crs('EPSG:4326')
    sample['lat'], sample['lon'] = ll.y.round(4), ll.x.round(4)
    sample['parcel_vri'] = sample['parcel_vri'].fillna('').str.slice(0, 80)
    ev = [c for c in EV_COLS if c in sample.columns]
    sample[ev].sort_values(['sector', 'stratum', 'area_ha'], ascending=[True, True, False]).to_csv(SAMPLE_CSV, index=False, encoding='utf-8')
    gpd.GeoDataFrame(sample[['id', 'genesis', 'stratum', 'area_ha', 'geometry']], geometry='geometry', crs=EA_CRS) \
        .to_file(SAMPLE_GEOMS, layer='sample', driver='GPKG')
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
        log('оверлей из продукта v4e...')
        full = gpd.read_file(EXPORTS / 'baresand_genesis_step3_v4e.gpkg', columns=['id', 'genesis'])
        full[['id', 'genesis', 'geometry']].to_file(OVERLAY, layer='overlay', driver='GPKG')
        cmd = [sys.executable, str(DRIVER), '--workers', '6', '--batch', '12', '--samples', str(SAMPLE_JSON), '--out', str(THUMBS),
               '--overlay', str(OVERLAY), '--field', 'genesis', '--sample', str(SAMPLE_GEOMS), '--evidence', str(SAMPLE_CSV)]
        log('рендер: ' + ' '.join(cmd[1:]))
        subprocess.run(cmd, check=False)
        log(f'миниатюр: {len(list(THUMBS.glob("*_esri.png")))}')
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


def synthesize() -> None:
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
        contested = (r['err_tag'] != '') or r['verdict'] in ('mixed', 'unclear') or r['confidence'] == 'low'
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
    rule_anthro = df['genesis'] == 'anthropogenic'
    fv = df['final_verdict']
    df['rule_correct'] = np.where(fv == 'anthropogenic', rule_anthro, np.where(fv == 'natural', ~rule_anthro, np.nan))
    df.to_csv(OUT_VERDICTS, index=False, encoding='utf-8')

    # эталон: дописать подтверждённые (без дублей)
    reg = pd.read_csv(REGRESSION)
    add = df[fv.isin(['anthropogenic', 'natural'])][['id', 'final_verdict', 'stratum', 'sector']].copy()
    add['expected_genesis'] = add['final_verdict'].replace({'natural': 'unassigned'})
    add = add[~add['id'].isin(reg['id'])][['id', 'expected_genesis', 'stratum', 'sector']]
    reg = pd.concat([reg, add], ignore_index=True)
    reg.to_csv(REGRESSION, index=False, encoding='utf-8')

    # эксперту: сомнения + контроль по стратам
    df['agents'] = np.where(df['status'] == 'confirmed', df['final_verdict'].map(RU).fillna('сомнение'), 'сомнение')
    rng = np.random.default_rng(SEED)
    need = df[df['agents'] == 'сомнение'].copy()
    ctrl = [grp.sample(n=min(CONTROL_PER_STRATUM, len(grp)), random_state=int(rng.integers(1e9)))
            for _, grp in df[df['status'] == 'confirmed'].groupby('stratum')]
    check = pd.concat([need] + ctrl).drop_duplicates('id')
    check['note'] = np.where(check['status'] == 'disputed', 'дешифровщик: ' + check['reason'].fillna('') + ' || скептик: ' + check['reason2'].fillna(''),
                             check['reason'].fillna(''))
    check['expert'] = ''
    check = check[['id', 'agents', 'expert', 'note', 'stratum', 'genesis', 'step3_rule', 'area_ha', 'parcel_vri', 'lat', 'lon']]
    check.to_csv(OUT_CHECK_CSV, index=False, encoding='utf-8')
    geoms = gpd.read_file(SAMPLE_GEOMS, layer='sample')[['id', 'geometry']]
    geoms.merge(check, on='id', how='inner').to_file(OUT_CHECK_GPKG, layer='final_check', driver='GPKG')

    L = [f'Проверка мелких срабатываний кадастра: {len(df)} контуров, статусы: {df["status"].value_counts().to_dict()}',
         f'подтверждённых вердиктов: {int(fv.isin(["anthropogenic", "natural"]).sum())}; добавлено в эталон: {len(add)} (всего строк {len(reg)})', '',
         'страта          | всего | подтв. | правило верно | ошибок правила (техноген→природа / природа→техноген)']
    for stname, grp in df.groupby('stratum'):
        c = grp[grp['status'] == 'confirmed']
        ok = c['rule_correct'].astype(float)
        fp = int(((c['final_verdict'] == 'natural') & (c['genesis'] == 'anthropogenic')).sum())
        fn = int(((c['final_verdict'] == 'anthropogenic') & (c['genesis'] != 'anthropogenic')).sum())
        L.append(f'{stname:15s} | {len(grp):5d} | {len(c):6d} | {ok.sum():.0f}/{len(c)} ({(100 * ok.mean()) if len(c) else 0:.0f}%) | {fp} / {fn}')
    c = df[df['status'] == 'confirmed']
    L += ['', f'ИТОГО правило верно: {c["rule_correct"].astype(float).sum():.0f}/{len(c)} ({100 * c["rule_correct"].astype(float).mean():.0f}%)']
    tags = df.loc[df['err_tag'] != '', 'err_tag'].value_counts()
    if len(tags):
        L += ['', 'err_tag: ' + ', '.join(f'{k} {v}' for k, v in tags.items())]
    if hints:
        L += ['', 'rule_hints агентов:'] + [f'  S{s}: {h}' for s, h in hints]
    L += ['', f'Эксперту: {OUT_CHECK_GPKG.name} — {len(check)} контуров ({int((check.agents == "сомнение").sum())} сомнений + контроль).']
    txt = '\n'.join(L)
    print(txt)
    (QC3 / 'summary_step3_nspd_small.txt').write_text(txt, encoding='utf-8')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['sample', 'synthesize'])
    ap.add_argument('--sectors', type=int, default=6)
    ap.add_argument('--render', action='store_true')
    a = ap.parse_args()
    if a.mode == 'sample':
        build_sample(a)
    else:
        synthesize()


if __name__ == '__main__':
    main()
