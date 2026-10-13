"""
BareSand — Свод визуальной верификации шага 2 → регрессия + список финальной проверки эксперта.

Вход:  exports/qc/step2/visual_qc_step2_result.json (воркфлоу: sectors[].review.verdicts[], sectors[].verify.checks[])
       exports/qc/step2/visual_sample_step2.csv, visual_sample_geoms_step2.gpkg
Выход: exports/qc/step2/visual_qc_step2_verdicts.csv
       exports/qc/step2/regression_step2.csv            (id, expected_genesis: river_shoal|lake_shoal|unassigned)
       exports/qc/step2/final_check_step2.gpkg / .csv   (agents: речная / озёрная / не отмель / сомнение; expert: пусто)
       exports/qc/step2/visual_qc_step2_report.md

Статус контура: confirmed (не спорный или скептик согласен) | disputed | unverified (спорный, скептика нет) | unclear.
Запуск: python -u python/53_step2_synthesize.py
"""
import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

sys.stdout.reconfigure(encoding='utf-8')

QC2 = Path(r'D:\test\baresand_zapsib\exports\qc\step2')
RESULT = QC2 / 'visual_qc_step2_result.json'
SAMPLE = QC2 / 'visual_sample_step2.csv'
GEOMS = QC2 / 'visual_sample_geoms_step2.gpkg'
OUT_VERDICTS = QC2 / 'visual_qc_step2_verdicts.csv'
OUT_REG = QC2 / 'regression_step2.csv'
OUT_CHECK_GPKG = QC2 / 'final_check_step2.gpkg'
OUT_CHECK_CSV = QC2 / 'final_check_step2.csv'
OUT_REPORT = QC2 / 'visual_qc_step2_report.md'
SEED = 42
CONTROL_PER_STRATUM = 3
RU = {'river_shoal': 'речная отмель', 'lake_shoal': 'озёрная отмель', 'not_shoal': 'не отмель'}


def main() -> None:
    res = json.loads(RESULT.read_text(encoding='utf-8'))
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
    df['rule_correct'] = np.where(fv.isin(['river_shoal', 'lake_shoal']), fv == rule,
                                  np.where(fv == 'not_shoal', rule == 'unassigned', np.nan))
    df.to_csv(OUT_VERDICTS, index=False, encoding='utf-8')

    reg = df[fv.isin(['river_shoal', 'lake_shoal', 'not_shoal'])][['id', 'final_verdict', 'stratum', 'sector']].copy()
    reg['expected_genesis'] = reg['final_verdict'].replace({'not_shoal': 'unassigned'})
    reg[['id', 'expected_genesis', 'stratum', 'sector']].to_csv(OUT_REG, index=False, encoding='utf-8')

    # ── список эксперту: 4-значная колонка agents ──
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
    check = check[['id', 'agents', 'expert', 'note', 'stratum', 'genesis', 'area_ha', 'lat', 'lon']]
    check.to_csv(OUT_CHECK_CSV, index=False, encoding='utf-8')
    geoms = gpd.read_file(GEOMS)[['id', 'geometry']]
    geoms.merge(check, on='id', how='inner').to_file(OUT_CHECK_GPKG, layer='final_check', driver='GPKG')

    # ── отчёт ──
    conf = df[df['status'] == 'confirmed']
    L = ['# Визуальная верификация шага 2 — свод', '',
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
    L += ['', '## Системные наблюдения дешифровщиков', ''] + [f'- S{s}: {h}' for s, h in hints]
    L += ['', f'Эксперту: `{OUT_CHECK_GPKG.name}` — {len(check)} контуров ({int((check.agents == "сомнение").sum())} сомнений + контроль).']
    OUT_REPORT.write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
