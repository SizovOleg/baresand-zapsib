"""
98_lake_verdicts.py — сборка вердиктов озёрного прохода и оценка предрегистрированных правил (редакция 2, 2026-09-18).

Два набора (--set): fit — выборка настройки (97, сектора L<n>), audit — аудит замороженного правила (99, сектора A<n>).
Статусы контура: confirmed — вердикты дешифровщика (review) и скептика (own, записан ДО чтения review) совпали;
disputed — не совпали; unresolved / unclear / mixed — по совпавшим вердиктам этих типов; resolved — снят супервайзером или
владельцем через --resolve <csv: id,ref>. В расчёт чистоты идут confirmed + resolved с классовой истиной; площадь остальных
отчитывается отдельно.

Веса: пост-стратификация как в 86 — площадь страты A_h раскладывается по контурам выборки пропорционально их площади
(w_i = A_h / Σ a_i по страте); чистота по площади = Σ w a [сработало ∧ истина lake_shoal] / Σ w a [сработало].
Правила (docs/genesis_lake_pass_plan.md §5): L1a–L1d для undef_lake, R1 для river_lake. --freeze L1b:0.2:2 R1:0.2 пишет
exports/qc/lake/rules_frozen.json; в режиме audit правило читается оттуда и считается с бутстрэп-ДИ по стратам.

Запуск: python -u python/98_lake_verdicts.py --set fit [--resolve exports/qc/lake/resolve_fit.csv] [--freeze L1b:0.2:2 R1:0.2]
        python -u python/98_lake_verdicts.py --set audit [--resolve exports/qc/lake/resolve_audit.csv] [--boot 2000]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
QCL = ROOT / 'exports' / 'qc' / 'lake'
RULES = QCL / 'rules_frozen.json'
SEED = 20260918
OBS = ['water_seen', 'position', 'transition', 'stream', 'shape', 'hue', 'brightness', 'anthro_signs']
CLASSES = ['lake_shoal', 'river_shoal', 'shoal', 'aeolian', 'anthropogenic', 'not_sand']
NONCLASS = ['mixed', 'unresolved', 'unclear']
T_C = (0.10, 0.20, 0.30, 0.50)
T_H = (1.0, 2.0, 3.0)


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def read_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8-sig'))
    except Exception as e:
        log(f'  {p.name}: не читается ({e})')
        return None


def collect(sectors: list[str]) -> pd.DataFrame:
    rows = []
    for s in sectors:
        rev = read_json(QCL / 'agents' / f'review_{s}.json') or {}
        own = read_json(QCL / 'agents' / f'own_{s}.json') or {}
        ver = read_json(QCL / 'agents' / f'verify_{s}.json') or {}
        r1 = {int(v['id']): v for v in rev.get('verdicts', [])}
        r2 = {int(v['id']): v for v in own.get('verdicts', [])}
        chk = {int(c['id']): c for c in ver.get('checks', [])}
        for i in sorted(set(r1) | set(r2)):
            a, b, c = r1.get(i, {}), r2.get(i, {}), chk.get(i, {})
            row = {'id': i, 'sector': s, 'verdict1': a.get('verdict'), 'conf1': a.get('confidence'), 'reason1': a.get('reason', ''),
                   'verdict_own': b.get('verdict'), 'conf_own': b.get('confidence'), 'reason_own': b.get('reason', ''),
                   'agree': c.get('agree'), 'own_in_verify': c.get('own_verdict'), 'reason_v': c.get('reason', '')}
            for f in OBS:
                row[f'{f}1'] = a.get(f)
                row[f'{f}_own'] = b.get(f)
            rows.append(row)
    return pd.DataFrame(rows)


def status_of(r) -> str:
    v1, v2 = r['verdict1'], r['verdict_own']
    if v1 is None or v2 is None or pd.isna(v1) or pd.isna(v2):
        return 'incomplete'
    if v1 == v2:
        return v1 if v1 in NONCLASS else 'confirmed'
    return 'disputed'


def weights(df: pd.DataFrame, strata: pd.DataFrame) -> pd.Series:
    """w_i = A_h / Σ a_i по страте (пост-стратификация); страты без пригодных контуров дают вес 0."""
    a_km2 = strata.set_index('stratum')['A_km2']
    tot = df.groupby('stratum')['area_ha'].sum() / 100
    w = df['stratum'].map(a_km2) / df['stratum'].map(tot)
    return w.fillna(0.0)


def rule_mask(df: pd.DataFrame, fam: str, p: list[float]) -> pd.Series:
    ever_bare = (df['bare_s2_frac'].fillna(0) > 0.05) | (df['bare2000_frac'].fillna(0) > 0.05)
    clean = ever_bare & (df['loss_frac'].fillna(0) < 0.1) & (df['d_road_built'].fillna(9e9) > 500)
    h = df['h_dry600']
    c30, c60 = df['c30'].fillna(0), df['c60'].fillna(0)
    und, riv = df['pop'] == 'undef_lake', df['pop'] == 'river_lake'
    if fam == 'L1a':
        return und & clean & (c30 >= p[0])
    if fam == 'L1b':
        return und & clean & (c30 >= p[0]) & (h <= p[1])
    if fam == 'L1c':
        return und & clean & (c60 >= p[0]) & (h <= p[1])
    if fam == 'L1d':
        return und & clean & ((c30 >= p[0]) | (df['y21_dry'].fillna(0) >= 0.3)) & (h <= p[1])
    # L1e/L1f — без условия истории поверхности: у 4 из 6 известных озёрных отмелей bare_s2 = bare2000 = 0 (переменный урез);
    # добавлены 2026-09-18 07:06 до появления первого вердикта (agents/ пуст) — см. план §5
    if fam == 'L1e':
        return und & (c30 >= p[0])
    if fam == 'L1f':
        return und & (c30 >= p[0]) & (h <= p[1])
    # L1g — поправка №2 (2026-09-18, после сетки на fit, ДО аудита): контакт ∧ НЕТ устойчивой истории обнажённости ∧ нет дороги.
    # Ложные срабатывания контакта на fit — побочни проток (bare2000 0.5–0.8 или bare_s2 0.4) и площадка у дороги (61 м);
    # озёрные пляжи переменного уреза имеют bare_s2 ≤ 0.11 и bare2000 = 0. Знак истории — обратный пре-регистрированному clean.
    if fam == 'L1g':
        no_hist = (df['bare_s2_frac'].fillna(0) < 0.3) & (df['bare2000_frac'].fillna(0) < 0.3)
        return und & (c30 >= p[0]) & no_hist & (df['d_road_built'].fillna(9e9) > 500)
    if fam == 'R1':
        return riv & (c30 >= p[0]) & (df['dist_channel_m'].fillna(9e9) > 400) & (df['upa_in_max'].fillna(0) < 5)
    raise ValueError(fam)


def grid() -> list[tuple[str, list[float]]]:
    out: list[tuple[str, list[float]]] = [('L1a', [t]) for t in T_C]
    for fam in ('L1b', 'L1c', 'L1d'):
        out += [(fam, [t, h]) for t in T_C for h in T_H]
    out += [('L1e', [t]) for t in T_C]
    out += [('L1f', [t, h]) for t in T_C for h in T_H]
    out += [('L1g', [t]) for t in T_C]
    out += [('R1', [t]) for t in T_C]
    return out


def evaluate(ok: pd.DataFrame, fam: str, p: list[float]) -> dict:
    m = rule_mask(ok, fam, p)
    lake = ok['ref'] == 'lake_shoal'
    wa = ok['w'] * ok['area_ha'] / 100
    fired, hit = wa[m].sum(), wa[m & lake].sum()
    pop_lake = wa[lake & (ok['pop'] == ('river_lake' if fam == 'R1' else 'undef_lake'))].sum()
    return {'rule': fam, 'params': ':'.join(map(str, p)), 'n_fired': int(m.sum()), 'n_lake': int((m & lake).sum()),
            'purity_n': round((m & lake).sum() / m.sum(), 3) if m.sum() else np.nan,
            'purity_area': round(hit / fired, 3) if fired > 0 else np.nan,
            'extracted_km2': round(hit, 1), 'fired_km2': round(fired, 1),
            'recall_area': round(hit / pop_lake, 3) if pop_lake > 0 else np.nan}


def bootstrap_purity(ok: pd.DataFrame, m: pd.Series, strata: pd.DataFrame, B: int, seed: int = SEED) -> tuple[float, float]:
    """Бутстрэп по стратам: в каждой страте контуры выборки тянутся с возвращением, веса пересчитываются."""
    rng = np.random.default_rng(seed)
    vals = []
    groups = {st: s.index.to_numpy() for st, s in ok.groupby('stratum')}
    a_km2 = strata.set_index('stratum')['A_km2']
    lake = (ok['ref'] == 'lake_shoal').to_numpy()
    area = ok['area_ha'].to_numpy() / 100
    mm = m.to_numpy()
    pos = {idx: k for k, idx in enumerate(ok.index)}
    for _ in range(B):
        num = den = 0.0
        for st, idx in groups.items():
            take = rng.choice(idx, size=len(idx), replace=True)
            k = np.array([pos[i] for i in take])
            tot = area[k].sum()
            if tot <= 0:
                continue
            w = a_km2.get(st, 0.0) / tot
            den += w * area[k][mm[k]].sum()
            num += w * area[k][mm[k] & lake[k]].sum()
        vals.append(num / den if den > 0 else np.nan)
    v = np.array(vals, dtype=float)
    v = v[~np.isnan(v)]
    return (float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))) if len(v) else (np.nan, np.nan)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', choices=['fit', 'audit'], default='fit')
    ap.add_argument('--resolve', default=None, help='csv id,ref — решения супервайзера/владельца по спорным')
    ap.add_argument('--freeze', nargs='*', default=None, help='например L1b:0.2:2 R1:0.2 — заморозить правила')
    ap.add_argument('--boot', type=int, default=2000)
    a = ap.parse_args()
    pref = 'lake_fit' if a.set == 'fit' else 'lake_audit'
    sample = pd.read_csv(QCL / f'{pref}.csv')
    strata = pd.read_csv(QCL / f'strata_{pref}.csv')
    sectors = [f'{"L" if a.set == "fit" else "A"}{s}' for s in sorted(sample['sector'].unique())]
    v = collect(sectors)
    log(f'{a.set}: контуров в выборке {len(sample)}, вердиктов собрано {len(v)}')
    df = sample.merge(v.drop(columns=['sector']), on='id', how='left')   # сектор уже есть в выборке
    df['status'] = df.apply(status_of, axis=1)
    df['ref'] = np.where(df['status'] == 'confirmed', df['verdict1'], '')
    if a.resolve and Path(a.resolve).exists():
        res = pd.read_csv(a.resolve)
        for _, r in res.iterrows():
            sel = df['id'] == int(r['id'])
            if sel.any():
                df.loc[sel, 'ref'] = str(r['ref'])
                df.loc[sel, 'status'] = 'resolved' if str(r['ref']) in CLASSES else str(r['ref'])
        log(f'решений по спорным: {len(res)}')
    df.to_csv(QCL / f'{pref}_verdicts.csv', index=False, encoding='utf-8')

    both = df['verdict1'].notna() & df['verdict_own'].notna()
    n_agree = int((df.loc[both, 'verdict1'] == df.loc[both, 'verdict_own']).sum())
    lines = [f'# Озёрный проход — вердикты набора {a.set} ({date.today().isoformat()})', '',
             f'Контуров {len(df)}; с обоими вердиктами {int(both.sum())}; согласие дешифровщика и скептика {n_agree} из {int(both.sum())}; '
             f'статусы: {df["status"].value_counts().to_dict()}.', '']
    df['w'] = weights(df, strata)
    df['wa'] = df['w'] * df['area_ha'] / 100
    lab = np.where(df['status'].isin(['confirmed', 'resolved']), df['ref'], df['status'])
    comp = pd.crosstab(df['pop'], lab, values=df['wa'], aggfunc='sum').fillna(0)
    comp = comp.div(comp.sum(axis=1), axis=0).round(3)
    lines += ['## Состав совокупностей (доли площади, пост-стратификация)', '', comp.to_markdown(), '']
    lines += ['## То же по числу контуров', '', pd.crosstab(df['pop'], lab).to_markdown(), '']

    ok = df[df['status'].isin(['confirmed', 'resolved']) & df['ref'].isin(CLASSES)].copy()
    ok['w'] = weights(ok, strata)
    if a.set == 'fit':
        table = pd.DataFrame([evaluate(ok, fam, p) for fam, p in grid()])
        table.to_csv(QCL / 'rule_grid_fit.csv', index=False, encoding='utf-8')
        passed = table[(table['purity_area'] >= 0.9) & (table['n_fired'] >= 5)]
        lines += [f'## Сетка предрегистрированных правил на fit (пригодных контуров {len(ok)})', '', table.to_markdown(index=False), '',
                  f'Прошли порог чистоты 0.90 по площади (и ≥ 5 срабатываний): {len(passed)} вариантов.', '']
        if len(passed):
            best = passed.sort_values(['extracted_km2', 'n_fired'], ascending=False)
            lines += ['Лучшие по извлечённой площади:', '', best.head(8).to_markdown(index=False), '']
        if a.freeze:
            frozen = {'frozen_at': date.today().isoformat(), 'set': 'fit', 'n_fit_ok': int(len(ok)), 'rules': {}}
            for spec in a.freeze:
                fam, *pp = spec.split(':')
                p = [float(x) for x in pp]
                frozen['rules'][fam[0] + '1'] = {'family': fam, 'params': p, 'fit_stats': evaluate(ok, fam, p)}
            RULES.write_text(json.dumps(frozen, ensure_ascii=False, indent=1), encoding='utf-8')
            lines += [f'**Заморожено** в `{RULES.name}`: ' + '; '.join(f'{k}: {v["family"]} {v["params"]}' for k, v in frozen['rules'].items()), '']
            log(f'заморожено: {[(k, v["family"], v["params"]) for k, v in frozen["rules"].items()]}')
    else:
        frozen = json.loads(RULES.read_text(encoding='utf-8'))
        lines += ['## Аудит замороженных правил', '']
        for key, r in frozen['rules'].items():
            m = rule_mask(ok, r['family'], r['params'])
            st = evaluate(ok, r['family'], r['params'])
            lo, hi = bootstrap_purity(ok, m, strata, a.boot)
            verdict = 'ДОПУЩЕНО' if (st['purity_area'] >= 0.9 and lo >= 0.85) else 'НЕ ДОПУЩЕНО'
            lines += [f'### {key}: {r["family"]} {r["params"]} — {verdict}', '',
                      f'Срабатываний среди пригодных: {st["n_fired"]}, из них озёрных отмелей {st["n_lake"]}; чистота по числу {st["purity_n"]}; '
                      f'чистота по площади {st["purity_area"]} (95 % ДИ {lo:.3f}–{hi:.3f}); извлечённая площадь {st["extracted_km2"]} км² '
                      f'из {st["fired_km2"]} км² срабатываний.', '']
            popm = ok['pop'] == ('river_lake' if r['family'] == 'R1' else 'undef_lake')
            miss = ok[popm & ~m]
            if len(miss):
                wa = miss['w'] * miss['area_ha'] / 100
                share = wa[miss['ref'] == 'lake_shoal'].sum() / wa.sum() if wa.sum() > 0 else np.nan
                lines += [f'Среди несрабатываний ({len(miss)} контуров) озёрных отмелей по площади: {share:.3f}.', '']
        for key, r in frozen['rules'].items():
            fired = df[rule_mask(df, r['family'], r['params'])]
            if len(fired) and fired['wa'].sum() > 0:
                sh = fired.groupby(fired['status'])['wa'].sum() / fired['wa'].sum()
                lines += [f'{key}: доли площади срабатываний по статусам: ' + ', '.join(f'{k} {v:.3f}' for k, v in sh.round(3).items()), '']
    disp = df[df['status'].isin(['disputed', 'incomplete'])]
    if len(disp):
        lines += ['## Спорные и неполные (на слепую проверку)', '',
                  disp[['id', 'sector', 'area_ha', 'verdict1', 'verdict_own', 'reason1', 'reason_own']].to_markdown(index=False), '']
        disp[['id', 'sector', 'area_ha', 'lat', 'lon', 'verdict1', 'verdict_own']].to_csv(QCL / f'{pref}_disputed.csv', index=False, encoding='utf-8')
    (QCL / f'{pref}_report.md').write_text('\n'.join(lines), encoding='utf-8')
    log(f'→ {pref}_verdicts.csv, {pref}_report.md; спорных {len(disp)}')
    print('\n'.join(lines[:6]))


if __name__ == '__main__':
    main()
