"""
110_disputed_class.py - список контуров класса «спорный» (disputed), 2026-09-26 (просьба владельца), ред. 2026-09-27.

Определение v1: контур просмотрен по снимку, и классу нет надёжного решения:
  ambiguous - итоговая метка «смешанный», «не понять» или спор трёх независимых прочтений (big: disputed3);
  readers   - два независимых прочтения разошлись в укрупнённом классе (отмели любого типа вместе), и расхождение не снято
              большинством независимых прочтений (в fit и audit спор снимал супервайзер, а его разборы совпали с владельцем
              лишь в 3 из 8, поэтому они не считаются решением);
  owner     - владелец отметил «смешанный», «не понять» или «спорный» (окно проверки, пакеты).
Определение v2 (сужение по O3/prereg.md, если владелец уверенно классифицирует большинство спорных v1): только owner и
  спор трёх прочтений (big: disputed3).
В обоих определениях решает последняя метка владельца (эталон проекта): уверенная метка (класс или «не песок») снимает
спорность, метка «смешанный / не понять / спорный» делает контур спорным. Порядок свежести: окно проверки (owner_gold, по
партиям) > вердикты пакетов (expert_big) > owner30 (укрупнённые метки).
Не относится: «нечитаемо» (unclear: снимок не читается; это не свойство объекта, контур остаётся undefined).
Почему только по наблюдениям: 109_disputed_analysis.py показал, что поля продукта спорность не предсказывают
(групповая CV: AUC 0.55-0.61), поэтому для непросмотренного остатка спорность не выводится.
Выход: exports/qc/disputed/disputed_<определение>.csv и disputed_current.csv (его читает 104; только для undefined),
       disputed_resolved.csv (агенты спорили, владелец решил). Запуск: PYTHONIOENCODING=utf-8 python -u python/110_disputed_class.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
OUT = ROOT / 'exports' / 'qc' / 'disputed'
DEFINITION = 'v2'   # сужение по правилу O3/prereg.md: владелец уверенно определил 19 из 20 спорных v1 (2026-09-27)
AMBIG = {'mixed', 'unresolved', 'disputed3', 'disputed'}
OWNER_AMBIG = {'mixed', 'unresolved', 'disputed', 'смешанный', 'неразрешимо'}
O30_MAP = {'отмель': 'shoal_any', 'раздув': 'aeolian', 'техноген': 'anthropogenic', 'не песок': 'not_sand',
           'смешанный': 'mixed', 'неразрешимо': 'unresolved'}


def owner_last() -> pd.DataFrame:
    """Последняя метка владельца по каждому контуру (id, label, src)."""
    parts = []
    o30_p = ROOT / 'exports' / 'qc' / 'lake' / 'owner30' / 'owner30_compare.csv'
    if o30_p.exists():
        o = pd.read_csv(o30_p)
        parts.append(pd.DataFrame({'id': o['id'], 'label': o['owner'].map(O30_MAP).fillna(o['owner']), 'src': 'owner30', 'rank': 0}))
    ex_p = ROOT / 'exports' / 'qc' / 'lake' / 'big' / 'expert_big.csv'
    if ex_p.exists():
        e = pd.read_csv(ex_p)
        parts.append(pd.DataFrame({'id': e['id'], 'label': e['verdict'], 'src': 'expert_big', 'rank': 1}))
    gold_p = ROOT / 'exports' / 'qc' / 'owner_click' / 'owner_gold.csv'
    if gold_p.exists():
        g = pd.read_csv(gold_p)
        # партии O1 < O2 < O3 ... по номеру
        num = g['batch'].astype(str).str.extract(r'(\d+)')[0].astype(float).fillna(0)
        parts.append(pd.DataFrame({'id': g['id'], 'label': g['label'], 'src': 'owner_click:' + g['batch'].astype(str),
                                   'rank': 2 + num / 1000}))
    if not parts:
        return pd.DataFrame(columns=['id', 'label', 'src'])
    a = pd.concat(parts, ignore_index=True).sort_values('rank')
    return a.groupby('id').last().reset_index()[['id', 'label', 'src']]


def main() -> None:
    m = pd.read_csv(OUT / 'multireader.csv')
    rows = []
    for r in m.itertuples():
        if r.source in ('fit', 'audit', 'big'):
            if r.final in AMBIG and (DEFINITION == 'v1' or r.final == 'disputed3'):
                rows.append((r.id, 'ambiguous', r.source))
            elif DEFINITION == 'v1' and r.disagree_coarse and r.source in ('fit', 'audit'):
                rows.append((r.id, 'readers', r.source))
    d = pd.DataFrame(rows, columns=['id', 'reason', 'source'])
    own = owner_last()
    amb = own[own['label'].isin(OWNER_AMBIG)]
    d = pd.concat([d, pd.DataFrame({'id': amb['id'], 'reason': 'owner', 'source': amb['src']})], ignore_index=True)
    prio = {'owner': 0, 'ambiguous': 1, 'readers': 2}
    d = (d.assign(p=d['reason'].map(prio)).sort_values('p')
         .groupby('id').agg(reason=('reason', 'first'), sources=('source', lambda s: ','.join(sorted(set(s))))).reset_index())
    # уверенная последняя метка владельца снимает спорность
    sure = own[~own['label'].isin(OWNER_AMBIG)]
    resolved = d[d['id'].isin(sure['id']) & d['reason'].ne('owner')].merge(sure, on='id')
    d = d[~d['id'].isin(resolved['id'])]
    d = d.assign(definition=DEFINITION)
    d.to_csv(OUT / f'disputed_{DEFINITION}.csv', index=False, encoding='utf-8')
    d.to_csv(OUT / 'disputed_current.csv', index=False, encoding='utf-8')
    resolved.to_csv(OUT / 'disputed_resolved.csv', index=False, encoding='utf-8')
    print(f'спорных ({DEFINITION}): {len(d)} контуров; по причине {d["reason"].value_counts().to_dict()}; '
          f'снято уверенной меткой владельца: {len(resolved)} ({resolved["label"].value_counts().to_dict()})')


if __name__ == '__main__':
    main()
