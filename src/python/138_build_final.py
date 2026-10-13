"""
138_build_final.py - классы итоговой версии v7: старый техноген, отнесённый к эоловым (2026-10-06).

Решение владельца 2026-10-06: «такое нельзя так оставлять чисто визуально, надо внести, сделать итоговую версию».
Вход: exports/baresand_genesis_step6_v6.gpkg (v5 + поля кадастра) и решения проверок:
  - метка владельца «техноген» в окне проверки (owner_click/T1, T2 и далее: --owner-batches) -> step6_rule v7_owner_techno;
  - крупные кандидаты (exports/qc/aeolian_techno/merged.csv, decision = anthropogenic, оба слепых читателя «техноген»),
    которые владелец не размечал -> v7_agent_techno (отступление от prereg п. 4 по решению владельца, result_T1.md);
  - мелкие кандидаты меньше 5 га (exports/qc/aeolian_techno_small/merged.csv) -> v7_agent_small, только с --small
    (после выборочной проверки по exports/qc/aeolian_techno_small/prereg.md п. 4).
Метка владельца важнее метки агентов: «эоловый», «смешанный» и другие метки владельца оставляют класс.
Меняются только эоловые контуры v6 (иначе ошибка): genesis и genesis_main -> anthropogenic, step6_rule, expert_note.
Новое поле genesis_v6: класс до этой правки у всех строк (v6 восстанавливается из v7). Поля cad_* у новых техногенных
пустые: их пересчитывает 133 (--src этого файла), он же пишет итоговый продукт и слои техногена.
Выход: exports/qc/final_build/v7_classes.gpkg (промежуточный, удаляется после 133), отчёт build_v7.md, decisions_v7.csv.
Запуск: PYTHONIOENCODING=utf-8 python -u python/138_build_final.py [--owner-batches T1,T2] [--small]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import time
from pathlib import Path

import pandas as pd
import pyogrio

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
SRC = ROOT / 'exports' / 'baresand_genesis_step6_v6.gpkg'
OUT_DIR = ROOT / 'exports' / 'qc' / 'final_build'
OC = ROOT / 'exports' / 'qc' / 'owner_click'
LARGE = ROOT / 'exports' / 'qc' / 'aeolian_techno' / 'merged.csv'
SMALL = ROOT / 'exports' / 'qc' / 'aeolian_techno_small' / 'merged.csv'
NOTE = {'v7_owner_techno': 'техноген: метка владельца (окно проверки {batch})',
        'v7_agent_techno': 'техноген: два слепых читателя, крупные кандидаты (владелец принял 2026-10-06)',
        'v7_agent_small': 'техноген: два слепых читателя, мелкие кандидаты (выборочная проверка владельцем)'}


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def owner_labels(batches: list[str]) -> pd.DataFrame:
    """Метки владельца из окна проверки: id, label, batch; при повторе id берётся последняя партия в списке."""
    rows = []
    for b in batches:
        raw = json.loads((OC / b / 'labels.json').read_text(encoding='utf-8'))
        rows += [{'id': int(k), 'label': v['label'], 'batch': b} for k, v in raw.items()]
    return pd.DataFrame(rows, columns=['id', 'label', 'batch']).drop_duplicates('id', keep='last')


def decisions(batches: list[str], small: bool) -> pd.DataFrame:
    own = owner_labels(batches)
    d = own.loc[own['label'] == 'anthropogenic', ['id', 'batch']].assign(rule='v7_owner_techno')
    big = pd.read_csv(LARGE)
    a = big.loc[(big['decision'] == 'anthropogenic') & ~big['id'].isin(own['id']), ['id']].assign(rule='v7_agent_techno', batch='')
    parts = [d, a]
    if small:
        sm = pd.read_csv(SMALL)
        parts.append(sm.loc[(sm['decision'] == 'anthropogenic') & ~sm['id'].isin(own['id']), ['id']]
                     .assign(rule='v7_agent_small', batch=''))
    out = pd.concat(parts, ignore_index=True)
    if out['id'].duplicated().any():
        raise ValueError(f'id в нескольких решениях: {out.loc[out["id"].duplicated(), "id"].tolist()[:10]}')
    log(f'решения: {out["rule"].value_counts().to_dict()}; меток владельца {len(own)} '
        f'({own["label"].value_counts().to_dict()})')
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--owner-batches', default='T1', help='партии окна проверки с метками владельца, через запятую')
    ap.add_argument('--small', action='store_true', help='применить мелких кандидатов (после выборочной проверки)')
    a = ap.parse_args()
    cpu_limit.apply()
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dec = decisions([b.strip() for b in a.owner_batches.split(',') if b.strip()], a.small)
    g = pyogrio.read_dataframe(SRC, layer='genesis')
    log(f'v6: {len(g)} контуров')
    if 'genesis_v6' in g.columns:
        raise ValueError('во входе уже есть genesis_v6: вход должен быть v6')
    g.insert(g.columns.get_loc('step6_rule'), 'genesis_v6', g['genesis'])
    # прежние метки владельца (v4_expert, разрез v5, expert_override шага 4) важнее меток агентов
    owner_rows = set(g.loc[g['step6_rule'].isin(['v4_expert', 'v5_mixed_owner']) | g['step4_rule'].eq('expert_override'), 'id'])
    drop = dec['rule'].ne('v7_owner_techno') & dec['id'].isin(owner_rows)
    if drop.any():
        log(f'метка владельца важнее агентов, не меняются: {dec.loc[drop, "id"].tolist()}')
        dec = dec[~drop]
    cls = g.set_index('id')['genesis']
    miss = sorted(set(dec['id']) - set(cls.index))
    if miss:
        raise ValueError(f'нет в v6: {miss[:10]}')
    bad = dec[cls.reindex(dec['id']).to_numpy() != 'aeolian']
    if len(bad):
        raise ValueError(f'не эоловые в v6: {bad.merge(cls.rename("genesis"), left_on="id", right_index=True).to_dict("records")[:10]}')
    before = g.groupby('genesis')['area_ha'].agg(['size', 'sum'])
    m = g['id'].map(dec.set_index('id')['rule'])
    ch = m.notna()
    g.loc[ch, 'genesis'] = 'anthropogenic'
    g.loc[ch, 'genesis_main'] = 'anthropogenic'
    g.loc[ch, 'step6_rule'] = m[ch]
    batch = g['id'].map(dec.set_index('id')['batch']).fillna('')
    g.loc[ch, 'expert_note'] = [NOTE[r].format(batch=b) for r, b in zip(m[ch], batch[ch])]
    cad = [c for c in g.columns if c.startswith('cad_')]
    g.loc[ch, cad] = None
    after = g.groupby('genesis')['area_ha'].agg(['size', 'sum'])
    out = OUT_DIR / 'v7_classes.gpkg'
    if out.exists():
        out.unlink()
    pyogrio.write_dataframe(g, out, layer='genesis', driver='GPKG')
    log(f'-> {out}')
    d = dec.merge(g[['id', 'area_ha']], on='id')
    d.to_csv(OUT_DIR / 'decisions_v7.csv', index=False, encoding='utf-8')
    t = pd.concat({'до': before, 'после': after}, axis=1).fillna(0)
    t.columns = [f'{x} {"контуров" if y == "size" else "км2"}' for x, y in t.columns]
    for c in t.columns:
        t[c] = (t[c] / 100).round(2) if c.endswith('км2') else t[c].astype(int)
    r = d.groupby('rule')['area_ha'].agg(['size', 'sum'])
    L = ['# Итоговая версия v7: классы (138)', '',
         f'Вход {SRC.name}; партии владельца {a.owner_batches}; мелкие кандидаты {"применены" if a.small else "не применены"}.', '',
         'Переведено из эоловых в техногенные:', '',
         '| Правило | Контуров | км2 |', '|---|---|---|',
         *[f'| {k} | {int(v["size"])} | {v["sum"] / 100:.2f} |' for k, v in r.iterrows()],
         f'| всего | {len(d)} | {d["area_ha"].sum() / 100:.2f} |', '',
         'Классы до и после:', '', t.to_markdown(), '',
         f'Поля cad_* обнулены у {int(ch.sum())} новых техногенных контуров: их пересчитывает 133 (--src {out.name}).']
    (OUT_DIR / 'build_v7.md').write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
