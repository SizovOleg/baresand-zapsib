"""
142_control_estimates.py - оценки по контрольной партии T3 (план: exports/qc/control_v7/prereg.md), 2026-10-06.

По каждой группе g1-g5 доля площади с меткой автора «техноген» (отношенческая оценка по стратам; 95 % интервал
бутстрэпом внутри страт, сплошные страты не пересэмплируются) и по числу контуров. g1, g2: доля правильно переведённой
площади и состав ошибок. g3-g5: остаточный техноген (нижняя оценка по «техноген», верхняя по «техноген» + «смешанный»)
в долях и км², сумма по g3-g5 с общим бутстрэпом. «Спорный» и «не понять»: в знаменателе, не техноген.

Добавлено после разметки (отступление от плана, оговаривается в отчёте):
- исправления промахов клавиш из просмотра всех 150 контуров (143, exports/qc/owner_click/T3r/labels.json):
  основные оценки по исправленным меткам, оценки по исходным приводятся рядом;
- бутстрэп вырождается, если в выборочной страте все контуры одного класса (интервал нулевой ширины). Поэтому рядом
  интервал с поправкой: для таких страт доля заменяется точной границей Клоппера-Пирсона по числу контуров
  (все верные: нижняя 0,025^(1/n); ни одного: верхняя 1 - 0,025^(1/n)).
Вход: exports/qc/owner_click/T3/labels.json, batch.csv; T3r/labels.json (если есть); exports/qc/control_v7/strata.csv.
Выход: exports/qc/control_v7/report.md, estimates.csv, corrections.csv.
Запуск: PYTHONIOENCODING=utf-8 python -u python/142_control_estimates.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
OC = ROOT / 'exports' / 'qc' / 'owner_click'
T3, T3R = OC / 'T3', OC / 'T3r'
CTRL = ROOT / 'exports' / 'qc' / 'control_v7'
B, SEED = 4000, 7
RU = {'lake_shoal': 'озёрная отмель', 'river_shoal': 'речная отмель', 'shoal': 'морская отмель', 'aeolian': 'эоловый',
      'anthropogenic': 'техноген', 'not_sand': 'не песок', 'mixed': 'смешанный', 'disputed': 'спорный',
      'unresolved': 'не понять'}
TITLE = {'g1_agent_large': 'крупные, переведены по двум запускам (v7_agent_techno)',
         'g2_agent_small': 'мелкие, переведены по двум запускам (v7_agent_small)',
         'g3_natural_small': 'мелкие «природные», оставлены эоловыми',
         'g4_ambiguous_small': 'мелкие неоднозначные, оставлены эоловыми',
         'g5_natural_large': 'крупные «природные», оставлены эоловыми'}
AGENT = ('g1_agent_large', 'g2_agent_small')
RESID = ('g3_natural_small', 'g4_ambiguous_small', 'g5_natural_large')
MEASURES = ('techno', 'techno_mixed')


def ratio(d: pd.DataFrame, ok: np.ndarray, st: pd.DataFrame, fixed: dict[str, float] | None = None) -> float:
    """sum_h A_h * p_h / sum_h A_h; p_h = площадь ok в выборке страты / площадь выборки страты или fixed[страта]."""
    num = den = 0.0
    for r in st.itertuples():
        m = (d['stratum'] == r.stratum).to_numpy()
        a = d.loc[m, 'area_ha'].to_numpy()
        if a.sum() > 0:
            p = fixed[r.stratum] if fixed and r.stratum in fixed else a[ok[m]].sum() / a.sum()
            num += r.A_h_ha * p
            den += r.A_h_ha
    return num / den if den else np.nan


def homogeneous(d: pd.DataFrame, ok: np.ndarray, st: pd.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    """Выборочные страты, где все контуры ok (-> нижняя граница К-П) или ни одного (-> верхняя граница К-П)."""
    lo, hi = {}, {}
    for r in st.itertuples():
        m = (d['stratum'] == r.stratum).to_numpy()
        n = int(m.sum())
        if r.census or n == 0:
            continue
        k = int(ok[m].sum())
        if k == n:
            lo[r.stratum] = 0.025 ** (1 / n)
        elif k == 0:
            hi[r.stratum] = 1 - 0.025 ** (1 / n)
    return lo, hi


def group_estimates(d: pd.DataFrame, st: pd.DataFrame, rng: np.random.Generator) -> tuple[list[dict], dict]:
    """Оценки группы по обеим мерам; бутстрэп парный (одни и те же повторы для обеих мер и поправок)."""
    idx = {r.stratum: np.flatnonzero((d['stratum'] == r.stratum).to_numpy()) for r in st.itertuples()}
    cen = dict(zip(st['stratum'], st['census']))
    oks = {c: d[c].to_numpy() for c in MEASURES}
    fx = {c: homogeneous(d, oks[c], st) for c in MEASURES}
    bs = {(c, kind): np.empty(B) for c in MEASURES for kind in ('raw', 'lo', 'hi')}
    for b in range(B):
        sel = np.concatenate([ix if cen[s] else rng.choice(ix, len(ix), replace=True) for s, ix in idx.items() if len(ix)])
        db = d.iloc[sel].reset_index(drop=True)
        for c in MEASURES:
            ok = oks[c][sel]
            bs[(c, 'raw')][b] = ratio(db, ok, st)
            bs[(c, 'lo')][b] = ratio(db, ok, st, fx[c][0])
            bs[(c, 'hi')][b] = ratio(db, ok, st, fx[c][1])
    A_km2 = st['A_h_ha'].sum() / 100
    rows = []
    for c in MEASURES:
        p = ratio(d, oks[c], st)
        q = lambda kind, pc: float(np.nanpercentile(bs[(c, kind)], pc))
        r = {'measure': c, 'n': len(d), 'k': int(oks[c].sum()), 'share_area': p, 'lo': q('raw', 2.5),
             'hi': q('raw', 97.5), 'lo_adj': min(q('lo', 2.5), q('raw', 2.5)), 'hi_adj': max(q('hi', 97.5), q('raw', 97.5)),
             'A_group_km2': A_km2, 'cp_strata': ';'.join(sorted(fx[c][0]) + sorted(fx[c][1]))}
        for k in ('share_area', 'lo', 'hi', 'lo_adj', 'hi_adj'):
            r['km2' if k == 'share_area' else 'km2_' + k] = r[k] * A_km2
        rows.append(r)
    # «техноген + смешанный» не может иметь верхнюю границу ниже «техноген»: поправка К-П есть только у однородных страт
    if rows[1]['hi_adj'] < rows[0]['hi_adj']:
        rows[1]['hi_adj'], rows[1]['km2_hi_adj'] = rows[0]['hi_adj'], rows[0]['km2_hi_adj']
    bs[('techno_mixed', 'hi')] = np.maximum(bs[('techno_mixed', 'hi')], bs[('techno', 'hi')])
    return rows, {k: v * A_km2 for k, v in bs.items()}


def estimate(d_all: pd.DataFrame, st_all: pd.DataFrame, tag: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Все группы и сумма остаточного техногена g3-g5 (повторы групп независимы, складываются по номеру повтора)."""
    rng = np.random.default_rng(SEED)
    rows, boots = [], {}
    for g in TITLE:
        d = d_all[(d_all['group'] == g) & d_all['label'].notna()].reset_index(drop=True)
        rr, bb = group_estimates(d, st_all[st_all['group'] == g], rng)
        rows += [{'labels': tag, 'group': g, **r} for r in rr]
        boots[g] = bb
    est = pd.DataFrame(rows)
    tot = []
    for name, gs in (('g1-g2', AGENT), ('g3-g5', RESID)):
        for c in MEASURES:
            sub = est[est['group'].isin(gs) & (est['measure'] == c)]
            s = {kind: sum(boots[g][(c, kind)] for g in gs) for kind in ('raw', 'lo', 'hi')}
            A = sub['A_group_km2'].sum()
            r = {'labels': tag, 'group': name, 'measure': c, 'n': int(sub['n'].sum()), 'k': int(sub['k'].sum()),
                 'A_group_km2': A, 'km2': sub['km2'].sum(),
                 'km2_lo': float(np.nanpercentile(s['raw'], 2.5)), 'km2_hi': float(np.nanpercentile(s['raw'], 97.5)),
                 'km2_lo_adj': min(float(np.nanpercentile(s['lo'], 2.5)), float(np.nanpercentile(s['raw'], 2.5))),
                 'km2_hi_adj': max(float(np.nanpercentile(s['hi'], 97.5)), float(np.nanpercentile(s['raw'], 97.5)))}
            for k in ('', '_lo', '_hi', '_lo_adj', '_hi_adj'):
                r[('share_area' if k == '' else k[1:])] = r['km2' + k] / A
            tot.append(r)
    return est, pd.DataFrame(tot)


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Партия с исходными метками (label_orig) и исправленными (label); таблица исправлений."""
    lab = json.loads((T3 / 'labels.json').read_text(encoding='utf-8'))
    L = pd.DataFrame([{'id': int(k), 'label_orig': v['label'], 'note': v.get('note', '')} for k, v in lab.items()])
    d = pd.read_csv(T3 / 'batch.csv').merge(L, on='id', how='left')
    d['label'] = d['label_orig']
    fixes = pd.DataFrame(columns=['id', 'group', 'area_ha', 'was', 'now', 'note', 't'])
    if (T3R / 'labels.json').exists():
        fx = json.loads((T3R / 'labels.json').read_text(encoding='utf-8'))
        F = pd.DataFrame([{'id': int(k), 'now': v['label'], 'fix_note': v.get('note', ''), 't': v.get('t', '')}
                          for k, v in fx.items()])
        if len(F):
            if not set(F['id']) <= set(d['id']):
                raise ValueError('в исправлениях есть id не из партии T3')
            d = d.merge(F, on='id', how='left')
            ch = d['now'].notna() & (d['now'] != d['label_orig'])
            d.loc[ch, 'label'] = d.loc[ch, 'now']
            fixes = d.loc[ch, ['id', 'group', 'area_ha', 'label_orig', 'now', 'fix_note', 't']].rename(
                columns={'label_orig': 'was', 'fix_note': 'note'})
            d = d.drop(columns=['now', 'fix_note', 't'])
    return d, fixes


def main() -> None:
    d_all, fixes = load()
    st_all = pd.read_csv(CTRL / 'strata.csv')
    miss = int(d_all['label'].isna().sum())
    res = {}
    for tag, col in (('corrected', 'label'), ('original', 'label_orig')):
        d = d_all.assign(label=d_all[col])
        d['techno'] = d['label'].eq('anthropogenic')
        d['techno_mixed'] = d['label'].isin(['anthropogenic', 'mixed'])
        res[tag] = estimate(d, st_all, tag)
    est = pd.concat([res['corrected'][0], res['corrected'][1], res['original'][0], res['original'][1]], ignore_index=True)
    est.to_csv(CTRL / 'estimates.csv', index=False, encoding='utf-8')
    fixes.to_csv(CTRL / 'corrections.csv', index=False, encoding='utf-8')
    E, T = res['corrected']
    pct = lambda x: f'{100 * x:.1f}'.replace('.', ',')
    kmf = lambda x: f'{x:.2f}'.replace('.', ',')
    get = lambda e, g, c: e[(e['group'] == g) & (e['measure'] == c)].iloc[0]
    R = ['# Контрольная партия T3: оценки по площади (142)', '',
         f'План: exports/qc/control_v7/prereg.md. Размечено {len(d_all) - miss} из {len(d_all)}. Бутстрэп {B} повторов '
         'внутри страт. Автор просмотрел все 150 контуров, сгруппированных по меткам, на промахи клавиш (143): '
         + (f'{len(fixes)} исправлений (список ниже); основные оценки по исправленным меткам.' if len(fixes)
            else 'промахов не найдено, метки не менялись.'), '',
         'Интервалы: «бутстрэп» по плану; «с поправкой» добавлен после разметки: если в выборочной страте все контуры '
         'одного класса, бутстрэп не даёт разброса, и для такой страты доля заменена точной границей Клоппера-Пирсона '
         'по числу контуров (грубая, консервативная граница).', '',
         '## Переводы по двум запускам модели: доля правильно переведённой площади (метка автора «техноген»)', '',
         '| Группа | «техноген» по числу | доля площади, % | 95 % ДИ бутстрэп | 95 % ДИ с поправкой | км² (ДИ с поправкой) |',
         '|---|---|---|---|---|---|']
    for g, r in [(TITLE[g], get(E, g, 'techno')) for g in AGENT] + [('всего g1-g2', get(T, 'g1-g2', 'techno'))]:
        R.append(f'| {g} | {r.k} из {r.n} | {pct(r.share_area)} | {pct(r.lo)}-{pct(r.hi)} | '
                 f'{pct(r.lo_adj)}-{pct(r.hi_adj)} | {kmf(r.km2)} из {kmf(r.A_group_km2)} ({kmf(r.km2_lo_adj)}-{kmf(r.km2_hi_adj)}) |')
    r2 = get(T, 'g1-g2', 'techno_mixed')
    R += ['', f'С «смешанными» как техногенными: всего g1-g2 {pct(r2.share_area)} % ({pct(r2.lo_adj)}-{pct(r2.hi_adj)}).']
    R += ['', '## Остаточный техноген в эоловом классе вблизи инфраструктуры', '',
          '| Группа | площадь группы, км² | «техноген» по числу | доля, % (ДИ бутстрэп; с поправкой) | км² (ДИ с поправкой) '
          '| с «смешанными», км² (ДИ с поправкой) |', '|---|---|---|---|---|---|']
    for g in RESID:
        r, r2 = get(E, g, 'techno'), get(E, g, 'techno_mixed')
        R.append(f'| {TITLE[g]} | {kmf(r.A_group_km2)} | {r.k} из {r.n} | {pct(r.share_area)} ({pct(r.lo)}-{pct(r.hi)}; '
                 f'{pct(r.lo_adj)}-{pct(r.hi_adj)}) | {kmf(r.km2)} ({kmf(r.km2_lo_adj)}-{kmf(r.km2_hi_adj)}) | '
                 f'{kmf(r2.km2)} ({kmf(r2.km2_lo_adj)}-{kmf(r2.km2_hi_adj)}) |')
    t, t2 = get(T, 'g3-g5', 'techno'), get(T, 'g3-g5', 'techno_mixed')
    R.append(f'| всего g3-g5 | {kmf(t.A_group_km2)} | {t.k} из {t.n} | | {kmf(t.km2)} ({kmf(t.km2_lo_adj)}-{kmf(t.km2_hi_adj)}) '
             f'| {kmf(t2.km2)} ({kmf(t2.km2_lo_adj)}-{kmf(t2.km2_hi_adj)}) |')
    R += ['', 'Страты с поправкой (однородная выборка): '
          + '; '.join(f'{r.group}/{r.measure}: {r.cp_strata}' for r in E.itertuples() if r.cp_strata) + '.', '']
    Eo, To = res['original']
    if len(fixes):
        R += ['## По исходным меткам (до исправления промахов)', '',
              '| Группа | «техноген» по числу | доля площади, % (ДИ с поправкой) | км² |', '|---|---|---|---|']
        for g in TITLE:
            r = get(Eo, g, 'techno')
            R.append(f'| {TITLE[g]} | {r.k} из {r.n} | {pct(r.share_area)} ({pct(r.lo_adj)}-{pct(r.hi_adj)}) | {kmf(r.km2)} |')
        to = get(To, 'g3-g5', 'techno')
        R += [f'| всего g3-g5 | {to.k} из {to.n} | | {kmf(to.km2)} ({kmf(to.km2_lo_adj)}-{kmf(to.km2_hi_adj)}) |', '']
    R += ['## Исправления автора (143, просмотр по группам меток)', '']
    if len(fixes):
        R += ['| id | группа | га | было | стало | заметка |', '|---|---|---|---|---|---|']
        R += [f'| {r.id} | {r.group} | {r.area_ha:.2f} | {RU.get(r.was, r.was)} | {RU.get(r.now, r.now)} | {r.note or ""} |'
              for r in fixes.itertuples()]
    else:
        R.append('Исправлений нет.')
    R += ['', '## Метки автора по группам (число контуров, после исправлений)', '',
          pd.crosstab(d_all['group'].map(TITLE), d_all['label'].map(lambda s: RU.get(s, s)).fillna('без метки')).to_markdown(), '']
    notes = d_all[d_all['note'].fillna('') != '']
    if len(notes):
        R += ['## Заметки автора', ''] + [f'- {i}: {t}' for i, t in zip(notes['id'], notes['note'])] + ['']
    R += ['Метки автора в итоговый слой не вносились (prereg): оценки относятся к exports/final/baresand_genesis_v7.gpkg.']
    (CTRL / 'report.md').write_text('\n'.join(R), encoding='utf-8')
    print('\n'.join(R))


if __name__ == '__main__':
    main()
