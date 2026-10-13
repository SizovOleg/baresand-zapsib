"""
64_step3_synthesize.py — свод визуальной верификации шага 3 (антропоген) → регрессия + список финальной проверки эксперта.

Вход:  exports/qc/step3/agents/review_S<n>.json + verify_S<n>.json (файлы агентов воркфлоу) → собираются в
       exports/qc/step3/visual_qc_step3_result.json (sectors[].review.verdicts[], sectors[].verify.checks[])
       exports/qc/step3/visual_sample_step3.csv, visual_sample_geoms_step3.gpkg
Выход: exports/qc/step3/visual_qc_step3_verdicts.csv
       exports/qc/step3/regression_step3.csv            (id, expected_genesis: anthropogenic | unassigned)
       exports/qc/step3/final_check_step3.gpkg / .csv   (agents: техноген / природный / сомнение; expert: пусто)
       exports/qc/step3/visual_qc_step3_report.md
Статус контура: confirmed (не спорный или скептик согласен) | disputed | unverified (спорный, скептика нет) | unclear.
Запуск: python -u python/64_step3_synthesize.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

QC3 = Path(r'D:\test\baresand_zapsib\exports\qc\step3')
RESULT = QC3 / 'visual_qc_step3_result.json'
SAMPLE = QC3 / 'visual_sample_step3.csv'
GEOMS = QC3 / 'visual_sample_geoms_step3.gpkg'
OUT_VERDICTS = QC3 / 'visual_qc_step3_verdicts.csv'
OUT_REG = QC3 / 'regression_step3.csv'
OUT_CHECK_GPKG = QC3 / 'final_check_step3.gpkg'
OUT_CHECK_CSV = QC3 / 'final_check_step3.csv'
OUT_REPORT = QC3 / 'visual_qc_step3_report.md'
SEED = 42
CONTROL_PER_STRATUM = 3
RU = {'anthropogenic': 'техноген', 'natural': 'природный'}


def assemble_from_agents() -> dict:
    """Собрать результат из файлов агентов exports/qc/step3/agents/review_S<n>.json + verify_S<n>.json."""
    sectors = []
    for rf in sorted((QC3 / 'agents').glob('review_S*.json')):
        n = int(rf.stem.split('_S')[1])
        rev = json.loads(rf.read_text(encoding='utf-8'))
        vf = QC3 / 'agents' / f'verify_S{n}.json'
        ver = json.loads(vf.read_text(encoding='utf-8')) if vf.exists() else {'checks': []}
        sectors.append({'sector': n, 'review': rev, 'verify': ver})
    res = {'sectors': sectors}
    RESULT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'собрано из файлов агентов: {len(sectors)} секторов → {RESULT.name}')
    return res


def main() -> None:
    res = assemble_from_agents() if (QC3 / 'agents').exists() else json.loads(RESULT.read_text(encoding='utf-8'))
    sectors = res.get('sectors') or res.get('result', {}).get('sectors') or []
    sample = pd.read_csv(SAMPLE)

    rows, hints = [], []
    for s in sectors:
        rev = s.get('review') or {}
        ver = s.get('verify') or {}
        checks = {c['id']: c for c in (ver.get('checks') or [])}
        hints += [(s['sector'], h) for h in (rev.get('rule_hints') or [])]
        for v in rev.get('verdicts') or []:
            c = checks.get(v['id'])
            rows.append({'id': v['id'], 'verdict': v['verdict'], 'err_tag': (v.get('err_tag') or '').strip(),
                         'confidence': v['confidence'], 'reason': v.get('reason', ''), 'rule_hint': v.get('rule_hint', ''),
                         'checked': c is not None, 'agree': (c['agree'] if c else None),
                         'verdict2': (c['verdict'] if c else ''), 'reason2': (c.get('reason', '') if c else '')})
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
    rule = df['genesis'].fillna('unassigned')
    fv = df['final_verdict']
    df['rule_correct'] = np.where(fv == 'anthropogenic', rule == 'anthropogenic',
                                  np.where(fv == 'natural', rule != 'anthropogenic', np.nan))
    df.to_csv(OUT_VERDICTS, index=False, encoding='utf-8')

    reg = df[fv.isin(['anthropogenic', 'natural'])][['id', 'final_verdict', 'stratum', 'sector']].copy()
    reg['expected_genesis'] = reg['final_verdict'].replace({'natural': 'unassigned'})
    reg[['id', 'expected_genesis', 'stratum', 'sector']].to_csv(OUT_REG, index=False, encoding='utf-8')

    def agents(r) -> str:
        if r['status'] != 'confirmed':
            return 'сомнение'
        return RU.get(r['final_verdict'], 'сомнение')
    df['agents'] = df.apply(agents, axis=1)
    rng = np.random.default_rng(SEED)
    need = df[df['agents'] == 'сомнение'].copy()
    ctrl = []
    for st, grp in df[df['status'] == 'confirmed'].groupby('stratum'):
        ctrl.append(grp.sample(n=min(CONTROL_PER_STRATUM, len(grp)), random_state=int(rng.integers(1e9))))
    check = pd.concat([need] + ctrl).drop_duplicates('id')
    check['note'] = np.where(check['status'] == 'disputed',
                             'дешифровщик: ' + check['reason'].fillna('') + ' || скептик: ' + check['reason2'].fillna(''),
                             check['reason'].fillna(''))
    check['expert'] = ''
    check = check[['id', 'agents', 'expert', 'note', 'stratum', 'genesis', 'step3_rule', 'area_ha', 'lat', 'lon']]
    check.to_csv(OUT_CHECK_CSV, index=False, encoding='utf-8')
    geoms = gpd.read_file(GEOMS, layer='sample')[['id', 'geometry']]
    geoms.merge(check, on='id', how='inner').to_file(OUT_CHECK_GPKG, layer='final_check', driver='GPKG')

    conf = df[df['status'] == 'confirmed']
    L = ['# Визуальная верификация шага 3 — свод', '',
         f'Просмотрено: **{int(df["verdict"].notna().sum())}** из {len(df)}; перепроверено: {int(df["checked"].sum())}; '
         f'подтверждено: {len(conf)}; спорных: {int((df.status == "disputed").sum())}; неясных: {int((df.status == "unclear").sum())}; '
         f'не перепроверено: {int((df.status == "unverified").sum())}.', '',
         '## Точность правила по стратам (согласованные вердикты)', '',
         '| stratum | n | право | ошибок | точность |', '|---|---:|---:|---:|---:|']
    cc = conf[conf['rule_correct'].notna()]
    for st, grp in cc.groupby('stratum'):
        n, ok = len(grp), int(grp['rule_correct'].sum())
        L.append(f'| {st} | {n} | {ok} | {n - ok} | {100 * ok / n:.0f}% |')
    if len(cc):
        L.append(f'| **всего** | {len(cc)} | {int(cc.rule_correct.sum())} | {len(cc) - int(cc.rule_correct.sum())} | **{100 * cc.rule_correct.mean():.0f}%** |')
    L += ['', '## Ошибки правила по причинам', '']
    errs = cc[(cc['rule_correct'] == False) & (cc['err_tag'] != '')]  # noqa: E712
    if len(errs):
        tab = errs.groupby(['stratum', 'err_tag']).agg(n=('id', 'size'), km2=('area_ha', lambda x: x.sum() / 100)).reset_index()
        L += ['| stratum | err_tag | n | км² |', '|---|---|---:|---:|']
        for _, r in tab.sort_values('n', ascending=False).iterrows():
            L.append(f'| {r.stratum} | {r.err_tag} | {int(r.n)} | {r.km2:.2f} |')
    adj = cc[cc['err_tag'] == 'раздув_у_дороги']
    L += ['', f'Раздувы у дорог (природные с техногенным триггером): {len(adj)} — политика класса решается экспертом.']
    L += ['', '## Системные наблюдения дешифровщиков', ''] + [f'- S{s}: {h}' for s, h in hints]
    L += ['', f'Эксперту: `{OUT_CHECK_GPKG.name}` — {len(check)} контуров ({int((check.agents == "сомнение").sum())} сомнений + контроль).']
    OUT_REPORT.write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
