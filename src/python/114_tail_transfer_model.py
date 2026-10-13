"""
114_tail_transfer_model.py - модель переноса меток на хвост, версия для проверки владельцем (2026-09-27).

Выбрано по 113 (групповая CV по блокам 5 км, оценка на метках владельца): среднее трёх моделей, обученных на всех метках
(владелец + агенты):
  1) бустинг на полях продукта; 2) логистическая регрессия на AlphaEarth внутри контура и в кольце 30 м;
  3) бустинг на полях продукта + AlphaEarth.
Укрупнённый класс: shoal / aeolian / anthropogenic / not_sand. Для shoal тип отмели (lake_shoal / river_shoal / shoal)
даёт отдельная модель того же вида, обученная на метках с точным типом.
Выход: exports/qc/alphaearth/tail_pred_<версия>.csv (id, area_ha, p_*, pred, pmax, fine, p_fine),
       owner_click/transfer_pop[_<версия>].csv (совокупность для партии проверки: плечи tr_<класс>_<S|L> при pmax >= THR),
       alphaearth/transfer_model[_<версия>].md (для E2 без суффикса).
Запуск: PYTHONIOENCODING=utf-8 python -u python/114_tail_transfer_model.py --version E3 (E2 заморожена, не перезапускать)
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

ROOT = Path(r'D:\test\baresand_zapsib')
spec = importlib.util.spec_from_file_location('m113', ROOT / 'python' / '113_tail_transfer_eval.py')
m113 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m113)
AE = m113.AE
QC = m113.QC
CLASSES = m113.CLASSES
FINE = ['lake_shoal', 'river_shoal', 'shoal']
THR = 0.8
RU = {'shoal': 'отмель', 'aeolian': 'эоловый', 'anthropogenic': 'техноген', 'not_sand': 'не песок',
      'lake_shoal': 'озёрная отмель', 'river_shoal': 'речная отмель'}


def ensemble(Xs: list[np.ndarray], y: np.ndarray, makers: list, Xt: list[np.ndarray], classes: list[str]) -> np.ndarray:
    """Среднее вероятностей моделей makers, обученных на Xs, для Xt."""
    P = np.zeros((len(Xt[0]), len(classes)))
    for X, make, T in zip(Xs, makers, Xt):
        mdl = make().fit(X, y)
        p = mdl.predict_proba(T)
        cl = list(mdl.classes_)
        P += np.column_stack([p[:, cl.index(c)] if c in cl else np.zeros(len(T)) for c in classes])
    return P / len(makers)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', default='E2', help='имя версии модели; E2 заморожена (перенос O5), повторно не запускать')
    a = ap.parse_args()
    sfx = '' if a.version == 'E2' else f'_{a.version}'
    lab = pd.read_csv(AE / 'labels.csv')
    ae = pd.read_csv(AE / 'ae_2024.csv')
    seen = set(lab['id']) | set(pd.read_csv(QC / 'disputed' / 'multireader.csv')['id']) \
        | set(pd.read_csv(QC / 'owner_click' / 'owner_gold.csv')['id'])
    und = pyogrio.read_dataframe(m113.PRODUCT, layer='genesis', columns=['id', 'genesis', 'step6_rule', 'area_ha'], read_geometry=False)
    tail_ids = und.loc[und['genesis'].eq('undefined') & und['step6_rule'].isna() & ~und['id'].isin(seen), 'id'].to_numpy()
    feat, num = m113.product_numeric(np.concatenate([lab['id'].to_numpy(), tail_ids]))
    ai = [f'ai_{k:02d}' for k in range(64)]
    ar = [f'ar_{k:02d}' for k in range(64)]
    d = lab.merge(feat, on='id', how='left').merge(ae, on='id', how='left').reset_index(drop=True)
    t = feat[feat['id'].isin(tail_ids)].merge(ae, on='id', how='left').reset_index(drop=True)
    sets = [num, ai + ar, num + ai + ar]
    mk = [m113.models('product')['hgb'], m113.models('ae_in_ring')['logreg'], m113.models('product+ae')['hgb']]
    y = d['coarse'].to_numpy()
    Pt = ensemble([d[c].astype(float).to_numpy() for c in sets], y, mk, [t[c].astype(float).to_numpy() for c in sets], CLASSES)
    # тип отмели: только метки с точным типом
    fd = d[d['fine'].isin(FINE)].reset_index(drop=True)
    yf = fd['fine'].to_numpy()
    # проверка типа: групповая CV, оценка на метках владельца
    Pf_oof = np.zeros((len(fd), len(FINE)))
    for c_set, make in zip(sets, mk):
        Pf_oof += m113.cv_oof_classes(fd[c_set].astype(float).to_numpy(), yf, fd['block'].to_numpy(), make, FINE, reps=2) / len(sets)
    pf = np.array(FINE)[Pf_oof.argmax(1)]
    ow = fd['tier'].eq('owner').to_numpy()
    Pft = ensemble([fd[c].astype(float).to_numpy() for c in sets], yf, mk, [t[c].astype(float).to_numpy() for c in sets], FINE)
    out = t[['id', 'area_ha']].assign(**{f'p_{c}': Pt[:, j] for j, c in enumerate(CLASSES)},
                                     pred=np.array(CLASSES)[Pt.argmax(1)], pmax=Pt.max(1),
                                     fine=np.array(FINE)[Pft.argmax(1)], p_fine=Pft.max(1))
    out['final'] = np.where(out['pred'] == 'shoal', out['fine'], out['pred'])
    out.to_csv(AE / f'tail_pred_{a.version}.csv', index=False, encoding='utf-8')
    L = [f'# Модель переноса меток на хвост ({a.version}), 2026-09-27', '',
         f'Обучение: {len(d)} меток (владелец {int(d["tier"].eq("owner").sum())}, агенты {int(d["tier"].eq("agent").sum())}); '
         f'тип отмели: {len(fd)} меток с точным типом.', '',
         f'Тип отмели, групповая CV, на метках владельца: верно {int((pf[ow] == yf[ow]).sum())} из {int(ow.sum())}; '
         f'на всех: {int((pf == yf).sum())} из {len(fd)}.', '',
         pd.crosstab(pd.Series(yf[ow], name='владелец'), pd.Series(pf[ow], name='модель')).to_markdown(), '',
         f'## Хвост: {len(out)} контуров, {out["area_ha"].sum() / 100:.1f} км2', '']
    rows = []
    for c in CLASSES:
        for th in (0.7, 0.8, 0.9):
            s = out[(out['pred'] == c) & (out['pmax'] >= th)]
            rows.append({'класс': RU[c], 'порог': th, 'контуров': len(s), 'км2': round(s['area_ha'].sum() / 100, 2),
                         'из них < 1 га': int((s['area_ha'] < 1).sum())})
    L += [pd.DataFrame(rows).to_markdown(index=False), '']
    s = out[(out['pred'] == 'shoal') & (out['pmax'] >= THR)]
    L += [f'Отмели при p >= {THR} по типу: ' + ', '.join(f'{RU.get(k, k)} {v}' for k, v in s['fine'].value_counts().items()), '']
    # совокупность для партии проверки: уверенные предсказания, плечи класс x размер
    pop = out[(out['pmax'] >= THR) & out['pred'].isin(['shoal', 'anthropogenic', 'aeolian'])].copy()
    pop['arm'] = 'tr_' + pop['pred'] + '_' + np.where(pop['area_ha'] >= 1, 'L', 'S')
    pop[['id', 'area_ha', 'arm', 'pred', 'fine', 'final', 'pmax']].to_csv(QC / 'owner_click' / f'transfer_pop{sfx}.csv',
                                                                         index=False, encoding='utf-8')
    L += ['Совокупность для проверки (плечи): ' + ', '.join(f'{k} {v}' for k, v in pop['arm'].value_counts().sort_index().items()), '']
    (AE / f'transfer_model{sfx}.md').write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
