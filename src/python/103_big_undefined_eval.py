"""
103_big_undefined_eval.py - независимая проверка пилота по 180 крупнейшим undefined (2026-09-26).

Метки: два независимых слепых агента (L_a, L_b), не видевших описаний пилота и предложений модели; при расхождении третий
слепой агент; итог по большинству, иначе disputed3. Вход: exports/qc/lake/big/labels/labels_raw.json (результат workflow
wf_dcf27e38-dba), big_proposed_audit.csv (предложения 102), expert_big.csv (вердикты владельца).
Считает чистоту предложений по числу (Клоппер-Пирсон) и по площади (бутстрэп по контурам) для трёх правил:
p_max >= 0.9 и совпадение с вердиктом описателя (принятое), только p_max >= 0.9 (описание без вердикта), только вердикт описателя.
Выход: big/big_labels.csv, big/big_eval.md.
Запуск: PYTHONIOENCODING=utf-8 python -u python/103_big_undefined_eval.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import beta

BIG = Path(r'D:\test\baresand_zapsib\exports\qc\lake\big')
NONCLASS = {'mixed', 'unresolved', 'unclear', 'disputed3'}
SEED = 20260926


def cp_interval(k: int, n: int) -> tuple[float, float]:
    """Двусторонний 95 % интервал Клоппера-Пирсона."""
    lo = beta.ppf(0.025, k, n - k + 1) if k > 0 else 0.0
    hi = beta.ppf(0.975, k + 1, n - k) if k < n else 1.0
    return float(lo), float(hi)


def labels() -> pd.DataFrame:
    raw = json.loads((BIG / 'labels' / 'labels_raw.json').read_text(encoding='utf-8'))
    rows = []
    for r in raw:
        va = {v['id']: v['verdict'] for v in (r.get('a') or {}).get('verdicts', [])}
        vb = {v['id']: v['verdict'] for v in (r.get('b') or {}).get('verdicts', [])}
        vt = {v['id']: v['verdict'] for v in (r.get('tie') or {}).get('verdicts', [])} if r.get('tie') else {}
        for i in sorted(set(va) | set(vb)):
            a, b, t = va.get(i), vb.get(i), vt.get(i)
            if a == b:
                final = a
            elif t is not None and t in (a, b):
                final = t
            else:
                final = 'disputed3'
            rows.append({'id': i, 'sector': r['sector'], 'label_a': a, 'label_b': b, 'label_tie': t, 'final': final})
    return pd.DataFrame(rows)


def score(d: pd.DataFrame, mask: pd.Series, name: str, rng: np.random.Generator) -> list[str]:
    s = d[mask].copy()
    cls = s[~s['final'].isin(NONCLASS)]
    k, n = int((cls['final'] == cls['proposed_rule']).sum()), len(cls)
    lo, hi = cp_interval(k, n) if n else (np.nan, np.nan)
    a_ok = cls.loc[cls['final'] == cls['proposed_rule'], 'area_ha'].sum()
    a_all = cls['area_ha'].sum()
    boots = []
    arr_ok = (cls['final'] == cls['proposed_rule']).to_numpy()
    arr_a = cls['area_ha'].to_numpy()
    for _ in range(2000):
        idx = rng.integers(0, n, n)
        boots.append(arr_a[idx][arr_ok[idx]].sum() / arr_a[idx].sum())
    blo, bhi = np.percentile(boots, [2.5, 97.5]) if n else (np.nan, np.nan)
    nc_area = s.loc[s['final'].isin(NONCLASS), 'area_ha'].sum()
    err = cls.loc[cls['final'] != cls['proposed_rule']]
    return [f'### {name}', '',
            f'Принято {len(s)} контуров, {s["area_ha"].sum() / 100:.2f} км2; с классовой меткой {n}.',
            f'Чистота по числу {k}/{n} = {k / n:.3f} (95 % ДИ {lo:.3f}-{hi:.3f}); по площади {a_ok / a_all:.3f} '
            f'(бутстрэп 95 % ДИ {blo:.3f}-{bhi:.3f}).',
            f'Площадь с неклассовой меткой (mixed/unresolved/спор): {nc_area / 100:.2f} км2.',
            'Ошибки (предложено -> по меткам): ' + (', '.join(f'{i} {p}->{f} ({a:.1f} га)' for i, p, f, a in
                                                           zip(err['id'], err['proposed_rule'], err['final'], err['area_ha'])) or 'нет'), '']


def main() -> None:
    lab = labels()
    p = pd.read_csv(BIG / 'big_proposed_audit.csv')
    d = p.merge(lab, on='id', how='left')
    ex = pd.read_csv(BIG / 'expert_big.csv')
    d = d.merge(ex[['id', 'verdict']].rename(columns={'verdict': 'expert'}), on='id', how='left')
    d.to_csv(BIG / 'big_labels.csv', index=False, encoding='utf-8')
    rng = np.random.default_rng(SEED)
    both = d['label_a'].notna() & d['label_b'].notna()
    lines = ['# Пилот по крупнейшим undefined: независимая проверка (2026-09-26)', '',
             f'Контуров 180; с двумя метками {int(both.sum())}; согласие L_a и L_b {int((d.loc[both, "label_a"] == d.loc[both, "label_b"]).sum())} '
             f'из {int(both.sum())}; спор решён третьим слепым {int(d["label_tie"].notna().sum())}; итоговые метки: '
             f'{d["final"].value_counts().to_dict()}.', '',
             'Согласие независимых меток с описателем пилота (его вердикт): '
             f'{int((d["final"] == d["verdict"]).sum())} из {len(d)}.', '']
    d['proposed_rule'] = d['class_nb']
    lines += score(d, d['accept'].astype(bool), 'Правило пилота: p_max >= 0.9 и совпадение с вердиктом описателя', rng)
    lines += score(d, d['p_max'] >= 0.9, 'Только модель: p_max >= 0.9 (описание без вердикта)', rng)
    d['proposed_rule'] = d['verdict']
    cls_v = ~d['verdict'].isin(NONCLASS | {'shoal'})
    lines += score(d, cls_v, 'Только вердикт описателя (классовые, без shoal)', rng)
    tab = pd.crosstab(d['class_nb'].where(d['accept'].astype(bool), 'undefined'), d['final'])
    lines += ['## Предложение модели (строки) против итоговой метки (столбцы), контуры', '', tab.to_markdown(), '']
    lines += ['## Площадь, км2', '', pd.crosstab(d['class_nb'].where(d['accept'].astype(bool), 'undefined'), d['final'],
                                                 values=d['area_ha'] / 100, aggfunc='sum').fillna(0).round(2).to_markdown(), '']
    (BIG / 'big_eval.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
