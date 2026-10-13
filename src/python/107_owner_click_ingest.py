"""
107_owner_click_ingest.py - приём меток владельца из окна проверки (105) и выводы по партии (2026-09-26).

Вход: exports/qc/owner_click/<name>/labels.json (содержимое localStorage страницы: {id: {label, note, t}}),
      <name>/batch.csv (группа, страта, размер страты), продукт v4.
Считает:
  burn - доля эолового (решение владельца «гари в эоловый») среди контуров с подписью гари: по числу (Клоппер-Пирсон)
         и по площади с весами страт размера (бутстрэп внутри страт); вывод по планке: точечная >= 0.90 и нижняя граница >= 0.85
         (принятый допуск), отдельно строгая: нижняя граница >= 0.90;
  v4   - совпадение класса v4 с меткой владельца (по числу и по площади).
Дописывает метки в exports/qc/owner_click/owner_gold.csv (эталон проекта; повторный приём той же партии заменяет её строки).
Выход: <name>/report.md. Запуск: PYTHONIOENCODING=utf-8 python -u python/107_owner_click_ingest.py --name O1 [--dry]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
from scipy.stats import beta

ROOT = Path(r'D:\test\baresand_zapsib')
OUT_ROOT = ROOT / 'exports' / 'qc' / 'owner_click'
PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
GOLD = OUT_ROOT / 'owner_gold.csv'
NONCLASS = {'mixed', 'unresolved', 'disputed'}
SHOALS = {'lake_shoal', 'river_shoal', 'shoal'}
RU = {'lake_shoal': 'озёрная отмель', 'river_shoal': 'речная отмель', 'shoal': 'морская отмель', 'aeolian': 'эоловый',
      'anthropogenic': 'техноген', 'not_sand': 'не песок', 'mixed': 'смешанный', 'unresolved': 'не понять', 'disputed': 'спорный'}


def cp(k: int, n: int) -> tuple[float, float]:
    """Двусторонний 95 % интервал Клоппера-Пирсона."""
    return (float(beta.ppf(0.025, k, n - k + 1)) if k else 0.0, float(beta.ppf(0.975, k + 1, n - k)) if k < n else 1.0)


def strat_area_share(d: pd.DataFrame, ok: pd.Series, B: int = 4000, seed: int = 1) -> tuple[float, float, float]:
    """Доля площади «ok» с весами страт: sum_h A_h * (площадь ok / площадь в выборке страты); бутстрэп внутри страт."""
    rng = np.random.default_rng(seed)
    groups = {s: g.index.to_numpy() for s, g in d.groupby('stratum')}
    A = d.groupby('stratum')['A_stratum_km2'].first()

    def est(idx_by_s: dict) -> float:
        num = den = 0.0
        for s, idx in idx_by_s.items():
            a = d.loc[idx, 'area_ha'].to_numpy()
            o = ok.loc[idx].to_numpy()
            if a.sum() <= 0:
                continue
            num += A[s] * a[o].sum() / a.sum()
            den += A[s]
        return num / den if den else np.nan

    point = est(groups)
    bs = [est({s: rng.choice(idx, len(idx), replace=True) for s, idx in groups.items()}) for _ in range(B)]
    return point, float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5))


def rule_block(d: pd.DataFrame, grp: str, target: str, title: str) -> list[str]:
    """Чистота правила «группа -> класс target» по меткам владельца: по числу и по площади с весами страт."""
    x = d[(d['group'] == grp) & d['label'].notna()].copy()
    if not len(x):
        return []
    L = [f'## {title}', '', 'Метки владельца: ' + ', '.join(f'{RU.get(k, k)} {v}' for k, v in x['label'].value_counts().items()), '']
    cls = x[~x['label'].isin(NONCLASS)]
    ok = cls['label'].eq(target)
    k, n = int(ok.sum()), len(cls)
    lo, hi = cp(k, n)
    pa, plo, phi = strat_area_share(cls, ok)
    passed = pa >= 0.90 and plo >= 0.85
    L += [f'«{RU[target]}» среди классовых меток: по числу {k}/{n} = {k / n:.2f} (95 % ДИ {lo:.2f}-{hi:.2f}); по площади с весами '
          f'страт {pa:.2f} (95 % ДИ {plo:.2f}-{phi:.2f}).',
          f'Допуск (точечная >= 0.90, нижняя граница >= 0.85): {"ПРОХОДИТ" if passed else "НЕ проходит"}; '
          f'строгая планка (нижняя граница >= 0.90): {"проходит" if plo >= 0.90 else "не проходит"}.', '']
    if x['stratum'].nunique() > 1:
        L += ['По стратам:', '', x.groupby('stratum')['label'].value_counts().unstack(fill_value=0).to_markdown(), '']
    return L


def hard_block(d: pd.DataFrame) -> list[str]:
    """Группа disputed_v1 (O3/prereg.md): доля меток «спорный / смешанный» среди ВСЕХ меток владельца; по причине
    спорности; повторяемость владельца на контурах, которые он уже видел в owner30 (укрупнённые классы)."""
    x = d[(d['group'] == 'disputed_v1') & d['label'].notna()].copy()
    if not len(x):
        return []
    hard = x['label'].isin(NONCLASS)
    k, n = int(hard.sum()), len(x)
    lo, hi = cp(k, n)
    pa, plo, phi = strat_area_share(x, hard)
    L = ['## Класс «спорный» v1: считает ли владелец эти контуры трудными', '',
         'Метки владельца: ' + ', '.join(f'{RU.get(k_, k_)} {v}' for k_, v in x['label'].value_counts().items()), '',
         f'Спорный или смешанный: по числу {k}/{n} = {k / n:.2f} (95 % ДИ {lo:.2f}-{hi:.2f}); по площади {pa:.2f} '
         f'(95 % ДИ {plo:.2f}-{phi:.2f}).',
         f'Правило из prereg (уверенный класс у большинства -> определение v1 слишком широкое, сузить): '
         f'{"СУЗИТЬ" if n - k > n / 2 else "оставить v1"} (уверенный класс {n - k} из {n}).', '']
    dp_p = ROOT / 'exports' / 'qc' / 'disputed' / 'disputed_v1_orig_2026-09-26.csv'   # список, из которого отбиралась O3
    if dp_p.exists():
        r = x.merge(pd.read_csv(dp_p)[['id', 'reason']], on='id', how='left')
        t = pd.crosstab(r['reason'].fillna('нет в v1'), r['label'].map(lambda s: RU.get(s, s)))
        L += ['По причине спорности v1 (ambiguous: итог агентов «смешанный / не понять / спор трёх»; readers: два прочтения '
              'разошлись):', '', t.to_markdown(), '']
    o30_p = ROOT / 'exports' / 'qc' / 'lake' / 'owner30' / 'owner30_compare.csv'
    if o30_p.exists():
        o30 = pd.read_csv(o30_p)[['id', 'owner']]
        rr = x.merge(o30, on='id')
        if len(rr):
            coarse = {'lake_shoal': 'отмель', 'river_shoal': 'отмель', 'shoal': 'отмель', 'aeolian': 'раздув',
                      'anthropogenic': 'техноген', 'not_sand': 'не песок', 'mixed': 'смешанный', 'disputed': 'спорный',
                      'unresolved': 'спорный'}
            rr['now'] = rr['label'].map(coarse)
            same = int(rr['now'].eq(rr['owner']).sum())
            L += [f'Повторный просмотр (эти контуры владелец уже видел в owner30, укрупнённо): совпало {same} из {len(rr)}.', '',
                  *[f'- {i}: owner30 {o}, O3 {RU.get(l, l)}' for i, o, l in zip(rr['id'], rr['owner'], rr['label'])], '']
    return L


def transfer_block(d: pd.DataFrame) -> list[str]:
    """Плечи tr*_ (O4-O7 prereg.md): совпадение класса модели переноса (114, поле final: тип отмели для shoal) с меткой
    владельца. Неклассовые метки (смешанный, спорный) считаются несовпадением. Площадь с весами страт.
    С 2026-09-27 (решение владельца после O6) планка применяется к ОСНОВНОМУ классу (отмель любого типа = один класс, DNA
    раздел 2); совпадение типа отмели второстепенно и только публикуется. В O4-O6 заранее записанное решение было по типу."""
    x = d[d['group'].astype(str).str.match(r'^tr\d*_') & d['label'].notna()].copy()
    if not len(x) or 'final' not in x:
        return []
    x['cls'] = x['group'].str.replace(r'_(S|L)$', '', regex=True)
    main_cls = lambda s: 'shoal' if s in SHOALS else s
    L = ['## Перенос меток на хвост (модели E2/E3, 114): совпадает ли класс модели с меткой владельца', '',
         'Неклассовые метки владельца считаются несовпадением; планка по основному классу (отмель любого типа как один класс):',
         'по площади >= 0.90 и нижняя граница >= 0.85. Тип отмели второстепенный: только оценка.', '']
    for c, xc in x.groupby('cls'):
        ok = xc['label'].map(main_cls).eq(xc['final'].map(main_cls))
        k, n = int(ok.sum()), len(xc)
        lo, hi = cp(k, n)
        pa, plo, phi = strat_area_share(xc, ok)
        L += [f'### {c}', '', 'Метки владельца: ' + ', '.join(f'{RU.get(a, a)} {v}' for a, v in xc['label'].value_counts().items()), '',
              f'Основной класс совпал с моделью: по числу {k}/{n} = {k / n:.2f} (95 % ДИ {lo:.2f}-{hi:.2f}); по площади {pa:.2f} '
              f'(95 % ДИ {plo:.2f}-{phi:.2f}). Планка: {"ПРОХОДИТ" if pa >= 0.90 and plo >= 0.85 else "НЕ проходит"}.', '']
        if xc['final'].isin(SHOALS).any():
            okf = xc['label'].eq(xc['final'])
            pf, pflo, pfhi = strat_area_share(xc, okf)
            L += [f'С типом отмели (второстепенно): {int(okf.sum())}/{n}; по площади {pf:.2f} (95 % ДИ {pflo:.2f}-{pfhi:.2f}).', '']
        L += [pd.crosstab(xc['final'].map(lambda s: RU.get(s, s)).rename('модель'),
                          xc['label'].map(lambda s: RU.get(s, s)).rename('владелец')).to_markdown(), '',
              'По стратам (основной класс): ' + '; '.join(
                  f'{s} {int(g_["label"].map(main_cls).eq(g_["final"].map(main_cls)).sum())}/{len(g_)}' for s, g_ in xc.groupby('stratum')), '']
    return L


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', default='O1')
    ap.add_argument('--dry', action='store_true', help='не дописывать эталон')
    a = ap.parse_args()
    out = OUT_ROOT / a.name
    raw = json.loads((out / 'labels.json').read_text(encoding='utf-8'))
    lab = pd.DataFrame([{'id': int(k), **v} for k, v in raw.items()])
    b = pd.read_csv(out / 'batch.csv')
    v4 = pyogrio.read_dataframe(PRODUCT, layer='genesis', columns=['id', 'genesis'], read_geometry=False,
                                where=f"id IN ({','.join(map(str, b['id']))})").rename(columns={'genesis': 'v4_class'})
    d = b.drop(columns=['genesis'], errors='ignore').merge(v4, on='id', how='left').merge(lab, on='id', how='left')
    n_lab = int(d['label'].notna().sum())
    L = [f'# Партия {a.name}: метки владельца', '', f'Контуров {len(d)}, размечено {n_lab}.', '']

    RULES = {'burn': ('aeolian', 'Гари (подпись tc2000 >= 10 %, потеря леса >= 0.3): правило «гари в эоловый»'),
             'arm_clear': ('anthropogenic', 'Подпись без пожара по MODIS: гипотеза «техноген»'),
             'arm_burn': ('not_sand', 'Подпись с пожаром по MODIS: гипотеза «не песок» (флаг)')}
    for grp, (target, title) in RULES.items():
        L += rule_block(d, grp, target, title)
    L += hard_block(d)
    L += transfer_block(d)
    for grp in sorted(g_ for g_ in set(d['group'].dropna()) - set(RULES) - {'v4', 'disputed_v1'} if not re.match(r'^tr\d*_', str(g_))):
        x = d[(d['group'] == grp) & d['label'].notna()]
        if len(x):
            sh = (x.groupby('label')['area_ha'].sum() / x['area_ha'].sum()).round(2)
            L += [f'## Состав группы {grp} по меткам владельца', '',
                  'По числу: ' + ', '.join(f'{RU.get(k, k)} {v}' for k, v in x['label'].value_counts().items()),
                  'Доли площади в выборке: ' + ', '.join(f'{RU.get(k, k)} {v}' for k, v in sh.sort_values(ascending=False).items()), '']
            hard = x['label'].isin(NONCLASS)
            k, n = int(hard.sum()), len(x)
            lo, hi = cp(k, n)
            if 'N_stratum' in x and x['N_stratum'].notna().all():
                N, A = int(x['N_stratum'].iloc[0]), float(x['A_stratum_km2'].iloc[0])
                pa = x.loc[hard, 'area_ha'].sum() / x['area_ha'].sum()
                L += [f'Спорных или смешанных по владельцу: {k}/{n} = {k / n:.2f} (95 % ДИ {lo:.2f}-{hi:.2f}); на всю группу '
                      f'({N} конт., {A:.1f} км2) это около {k / n * N:.0f} конт. (ДИ {lo * N:.0f}-{hi * N:.0f}) и {pa * A:.1f} км2 '
                      f'по доле площади в выборке.', '']
    burn = pd.DataFrame()
    if len(burn):
        L += ['## Гари (подпись tc2000 >= 10 %, потеря леса >= 0.3): правило «гари в эоловый»', '',
              'Метки владельца: ' + ', '.join(f'{RU.get(k, k)} {v}' for k, v in burn['label'].value_counts().items()), '']
        cls = burn[~burn['label'].isin(NONCLASS)]
        ok = cls['label'].eq('aeolian')
        k, n = int(ok.sum()), len(cls)
        lo, hi = cp(k, n)
        pa, plo, phi = strat_area_share(cls, ok)
        passed = pa >= 0.90 and plo >= 0.85
        strict = plo >= 0.90
        L += [f'Эоловый среди классовых меток: по числу {k}/{n} = {k / n:.2f} (95 % ДИ {lo:.2f}-{hi:.2f}); по площади с весами '
              f'страт {pa:.2f} (95 % ДИ {plo:.2f}-{phi:.2f}).',
              f'Допуск (точечная >= 0.90, нижняя граница >= 0.85): {"ПРОХОДИТ" if passed else "НЕ проходит"}; '
              f'строгая планка (нижняя граница >= 0.90): {"проходит" if strict else "не проходит"}.', '']
        L += ['По стратам размера:', '', burn.groupby('stratum')['label'].value_counts().unstack(fill_value=0).to_markdown(), '']

    ver = d[(d['group'] == 'v4') & d['label'].notna()].copy()
    if len(ver):
        cls = ver[~ver['label'].isin(NONCLASS)]
        ok = cls['label'].eq(cls['v4_class'])
        k, n = int(ok.sum()), len(cls)
        lo, hi = cp(k, n) if n else (np.nan, np.nan)
        L += ['## Правки пилота в v4', '',
              f'Совпадение класса v4 с владельцем: {k}/{n} = {k / n:.2f} (95 % ДИ {lo:.2f}-{hi:.2f}); по площади '
              f'{cls.loc[ok, "area_ha"].sum() / cls["area_ha"].sum():.2f}; неклассовых меток {len(ver) - n}.', '',
              pd.crosstab(ver['v4_class'], ver['label']).to_markdown(), '']
        bad = ver[~ver['label'].eq(ver['v4_class'])]
        if len(bad):
            L += ['Расхождения: ' + ', '.join(f'{i} v4 {c} -> владелец {RU.get(l, l)}' for i, c, l in zip(bad['id'], bad['v4_class'], bad['label'])), '']

    notes = d[d['note'].fillna('').ne('')]
    if len(notes):
        L += ['## Заметки владельца', ''] + [f'- {i}: {t}' for i, t in zip(notes['id'], notes['note'])] + ['']
    (out / 'report.md').write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))

    if not a.dry:
        g = d[d['label'].notna()][['id', 'label', 'note', 't', 'group', 'stratum', 'area_ha', 'v4_class']].assign(batch=a.name)
        if GOLD.exists():
            old = pd.read_csv(GOLD)
            g = pd.concat([old[old['batch'] != a.name], g], ignore_index=True)
        g.to_csv(GOLD, index=False, encoding='utf-8')
        print(f'эталон: {GOLD} ({len(g)} меток)')


if __name__ == '__main__':
    main()
