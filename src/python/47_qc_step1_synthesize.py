"""
BareSand — Свод визуальной верификации шага 1 (v2) в регрессионный набор и список финальной проверки.

Вход:  exports/qc/visual_qc_step1_result.json — результат воркфлоу step1-shoal-visual-qc
       (sectors[].review.verdicts[], sectors[].verify.checks[]), exports/qc/visual_sample_step1_all.csv
Выход:
  exports/qc/visual_qc_step1_verdicts.csv  — все вердикты + перепроверка + итоговый статус
  exports/qc/regression_step1.csv          — id, expected_genesis (только согласованные вердикты)
  exports/qc/final_check_step1.csv         — что смотреть эксперту: спорные + low-confidence + контрольная выборка
  exports/qc/visual_qc_step1_report.md     — отчёт: точность правила v2 по стратам, ошибки по причинам, rule_hints

Итоговый статус контура:
  confirmed  — скептик не привлекался (вердикт не спорный) ИЛИ скептик согласен
  disputed   — скептик не согласен → к эксперту
  unclear    — оба/один не смогли определить → к эксперту

Запуск: python -u python/47_qc_step1_synthesize.py
"""
import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

QC = Path(r'D:\test\baresand_zapsib\exports\qc')
RESULT = QC / 'visual_qc_step1_result.json'
SAMPLE = QC / 'visual_sample_step1_all.csv'
OUT_VERDICTS = QC / 'visual_qc_step1_verdicts.csv'
OUT_REG = QC / 'regression_step1.csv'
OUT_CHECK = QC / 'final_check_step1.csv'
OUT_REPORT = QC / 'visual_qc_step1_report.md'
SEED = 42
CONTROL_PER_STRATUM = 3     # случайные подтверждённые контуры на страту — контроль эксперта


def main() -> None:
    res = json.loads(RESULT.read_text(encoding='utf-8'))
    sectors = res.get('sectors') or res.get('result', {}).get('sectors') or []
    sample = pd.read_csv(SAMPLE)

    rows, hints = [], []
    for s in sectors:
        rev = s.get('review') or {}
        ver = s.get('verify') or {}
        checks = {c['id']: c for c in (ver.get('checks') or [])}
        for h in rev.get('rule_hints') or []:
            hints.append((s['sector'], h))
        for v in rev.get('verdicts') or []:
            c = checks.get(v['id'])
            rows.append({
                'id': v['id'], 'sector': s['sector'], 'stratum_agent': v.get('stratum', ''),
                'verdict': v['verdict'], 'err_tag': (v.get('err_tag') or '').strip(),
                'confidence': v['confidence'], 'reason': v.get('reason', ''), 'rule_hint': v.get('rule_hint', ''),
                'checked': c is not None,
                'agree': (c['agree'] if c else None),
                'verdict2': (c['verdict'] if c else ''), 'err_tag2': ((c.get('err_tag') or '').strip() if c else ''),
                'confidence2': (c['confidence'] if c else ''), 'reason2': (c.get('reason', '') if c else ''),
            })
    vd = pd.DataFrame(rows).drop_duplicates('id')
    df = sample.merge(vd, on='id', how='left', suffixes=('', '_v'))
    df['sector'] = df['sector'].fillna(df.get('sector_v')) if 'sector_v' in df else df['sector']

    # итоговый статус
    def status(r) -> str:
        if pd.isna(r['verdict']):
            return 'not_reviewed'
        contested = (r['err_tag'] != '') or r['verdict'] in ('mixed', 'unclear') or r['confidence'] == 'low'
        if r['verdict'] == 'unclear' and (not r['checked'] or r['verdict2'] in ('', 'unclear')):
            return 'unclear'
        if contested and not r['checked']:
            return 'unverified'          # скептик по сектору не отработал — к эксперту
        if r['checked'] and r['agree'] is False:
            return 'disputed'
        if r['checked'] and r['verdict2'] == 'unclear':
            return 'unclear'
        return 'confirmed'
    df['status'] = df.apply(status, axis=1)

    # итоговый вердикт (при согласии — первый; при споре — пусто)
    df['final_verdict'] = np.where(df['status'] == 'confirmed', df['verdict'], '')
    # ожидаемый генезис для регрессии: shoal / not_shoal (mixed → not в регрессию)
    rule_says_shoal = df['genesis'] == 'shoal'
    df['rule_correct'] = np.where(df['final_verdict'] == 'shoal', rule_says_shoal,
                                  np.where(df['final_verdict'] == 'not_shoal', ~rule_says_shoal, np.nan))

    df.to_csv(OUT_VERDICTS, index=False, encoding='utf-8')

    # регрессионный набор
    reg = df[df['final_verdict'].isin(['shoal', 'not_shoal'])][['id', 'final_verdict', 'stratum', 'sector']].copy()
    reg['expected_genesis'] = np.where(reg['final_verdict'] == 'shoal', 'shoal', 'unassigned')
    reg[['id', 'expected_genesis', 'stratum', 'sector']].to_csv(OUT_REG, index=False, encoding='utf-8')

    # список для эксперта: спорные, неясные, mixed, + контроль по стратам
    rng = np.random.default_rng(SEED)
    need = df[df['status'].isin(['disputed', 'unclear', 'unverified']) | (df['final_verdict'] == 'mixed')].copy()
    need['why'] = np.select(
        [need['status'] == 'disputed', need['status'] == 'unverified', need['final_verdict'] == 'mixed'],
        ['агенты разошлись', 'ошибка найдена, скептик не перепроверил', 'смешанный контур'],
        default='агенты не уверены')
    ctrl_rows = []
    for st, grp in df[df['status'] == 'confirmed'].groupby('stratum'):
        k = min(CONTROL_PER_STRATUM, len(grp))
        ctrl_rows.append(grp.sample(n=k, random_state=int(rng.integers(1e9))).assign(why='контроль (подтверждено агентами)'))
    check = pd.concat([need] + ctrl_rows).drop_duplicates('id')
    cols = ['id', 'sector', 'stratum', 'genesis', 'verdict', 'err_tag', 'confidence', 'verdict2', 'err_tag2',
            'status', 'why', 'reason', 'reason2', 'area_ha', 'dist_sea_m', 'hnd_min', 'gsw_occ_max', 'lat', 'lon']
    check = check[cols].sort_values(['why', 'sector', 'stratum'])
    check.to_csv(OUT_CHECK, index=False, encoding='utf-8')
    # QGIS-слой финальной проверки: геометрии эталонных контуров + вердикты агентов + пустой err_tag эксперта
    geoms_p = QC / 'visual_sample_geoms.gpkg'
    if geoms_p.exists():
        import geopandas as gpd
        sg = gpd.read_file(geoms_p)[['id', 'geometry']]
        chk_g = sg.merge(check, on='id', how='inner')
        chk_g['expert_tag'] = ''
        chk_g.to_file(QC / 'final_check_step1.gpkg', layer='final_check', driver='GPKG')

    # ── отчёт ──
    conf = df[df['status'] == 'confirmed']
    L = ['# Визуальная верификация шага 1 (правило v2) — свод', '']
    L.append(f'Просмотрено: **{int(df["verdict"].notna().sum())}** из {len(df)} контуров выборки; '
             f'перепроверено скептиком: {int(df["checked"].sum())}; подтверждено: {len(conf)}; '
             f'спорных: {int((df.status == "disputed").sum())}; неясных: {int((df.status == "unclear").sum())}.')
    L += ['', '## Точность правила v2 по стратам (только согласованные вердикты)', '',
          '| stratum | n | правило право | ошибок | точность |', '|---|---:|---:|---:|---:|']
    for st, grp in conf[conf['rule_correct'].notna()].groupby('stratum'):
        n = len(grp); ok = int(grp['rule_correct'].sum())
        L.append(f'| {st} | {n} | {ok} | {n - ok} | {100 * ok / n:.0f}% |')
    tot = conf[conf['rule_correct'].notna()]
    if len(tot):
        L.append(f'| **всего** | {len(tot)} | {int(tot.rule_correct.sum())} | {len(tot) - int(tot.rule_correct.sum())} | '
                 f'**{100 * tot.rule_correct.mean():.0f}%** |')
    L += ['', '## Ошибки правила по причинам (err_tag, подтверждённые)', '']
    errs = conf[(conf['rule_correct'] == False) & (conf['err_tag'] != '')]  # noqa: E712
    if len(errs):
        tab = errs.groupby(['stratum', 'err_tag']).agg(n=('id', 'size'), km2=('area_ha', lambda x: x.sum() / 100)).reset_index()
        L += ['| stratum | err_tag | n | км² |', '|---|---|---:|---:|']
        for _, r in tab.sort_values('n', ascending=False).iterrows():
            L.append(f'| {r.stratum} | {r.err_tag} | {int(r.n)} | {r.km2:.2f} |')
    else:
        L.append('_нет подтверждённых ошибок_')
    L += ['', '## Системные наблюдения дешифровщиков (rule_hints)', '']
    for sec, h in hints:
        L.append(f'- S{sec}: {h}')
    L += ['', '## Файлы', '',
          f'- `{OUT_VERDICTS.name}` — все вердикты', f'- `{OUT_REG.name}` — регрессионный набор ({len(reg)} контуров)',
          f'- `{OUT_CHECK.name}` — для финальной проверки эксперта ({len(check)} контуров: '
          f'{int((check.why != "контроль (подтверждено агентами)").sum())} спорных/неясных + контроль)']
    OUT_REPORT.write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))
    print(f'\nСохранено: {OUT_VERDICTS.name}, {OUT_REG.name}, {OUT_CHECK.name}, {OUT_REPORT.name}')


if __name__ == '__main__':
    main()
