"""
115_small_eval.py - модель E3 (ансамбль как E2, обучение на метках с O4 и O5) и её точность на МЕЛКИХ контурах (2026-09-27).

Вопрос: можно ли переносить метки на мелкие контуры хвоста (< 1 га, ~20 тыс., ~60 км2). E2 на мелких в O4: 41/50.
Проверка: групповая CV по блокам 5 км (5 частей x REPS повторов) ансамбля трёх моделей (как в 114) и модели типа отмели;
итоговый класс = тип отмели для отмелей, иначе укрупнённый. Оценка на метках владельца: все мелкие и «хвостовые» мелкие
(O3 undef_S - случайные, O4 S - там, где E2 была уверена). По каждому итоговому классу и порогу уверенности.
Выход: exports/qc/alphaearth/small_eval.md, oof_E3.csv. Запуск: PYTHONIOENCODING=utf-8 python -u python/115_small_eval.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
spec = importlib.util.spec_from_file_location('m113', ROOT / 'python' / '113_tail_transfer_eval.py')
m113 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m113)
AE = m113.AE
QC = m113.QC
CLASSES = m113.CLASSES
FINE = ['lake_shoal', 'river_shoal', 'shoal']
REPS = 2   # повторов групповой CV (5 частей каждый)
RU = {'lake_shoal': 'озёрная', 'river_shoal': 'речная', 'shoal': 'морская', 'aeolian': 'эоловый',
      'anthropogenic': 'техноген', 'not_sand': 'не песок'}


def main() -> None:
    lab = pd.read_csv(AE / 'labels.csv')
    ae = pd.read_csv(AE / 'ae_2024.csv')
    feat, num = m113.product_numeric(lab['id'].to_numpy())
    ai = [f'ai_{k:02d}' for k in range(64)]
    ar = [f'ar_{k:02d}' for k in range(64)]
    d = lab.merge(feat, on='id', how='left').merge(ae, on='id', how='left').reset_index(drop=True)
    gold = pd.read_csv(QC / 'owner_click' / 'owner_gold.csv')
    last = gold.assign(n=gold['batch'].str.extract(r'(\d+)')[0].astype(int)).sort_values('n').groupby('id').last()
    d['batch'] = d['id'].map(last['batch'])
    d['bgroup'] = d['id'].map(last['group'])
    sets = [num, ai + ar, num + ai + ar]
    mk = [m113.models('product')['hgb'], m113.models('ae_in_ring')['logreg'], m113.models('product+ae')['hgb']]
    y = d['coarse'].to_numpy()
    grp = d['block'].to_numpy()
    P = sum(m113.cv_oof_classes(d[c].astype(float).to_numpy(), y, grp, mk_, CLASSES, reps=REPS) for c, mk_ in zip(sets, mk)) / 3
    yf = d['fine'].where(d['fine'].isin(FINE), 'none').to_numpy()
    tmf = np.isin(yf, FINE)
    Pf = sum(m113.cv_oof_classes(d[c].astype(float).to_numpy(), yf, grp, mk_, FINE, tmf, reps=REPS) for c, mk_ in zip(sets, mk)) / 3
    coarse = np.array(CLASSES)[P.argmax(1)]
    fine = np.array(FINE)[Pf.argmax(1)]
    d['pred'] = coarse
    d['pmax'] = P.max(1)
    d['final_pred'] = np.where(coarse == 'shoal', fine, coarse)
    # истинный итоговый класс: точный тип, если известен; иначе укрупнённый (для отмелей без типа сравнение только укрупнённо)
    d['truth'] = np.where(d['fine'].notna(), d['fine'], d['coarse'])
    d['ok'] = np.where(d['truth'].eq('shoal_any') | (d['coarse'].eq('shoal') & d['fine'].isna()),
                       d['pred'].eq('shoal'), d['final_pred'].eq(d['truth']))
    d[['id', 'tier', 'src', 'batch', 'bgroup', 'area_ha', 'coarse', 'fine', 'pred', 'final_pred', 'pmax', 'ok']].to_csv(
        AE / 'oof_E3.csv', index=False, encoding='utf-8')
    own = d['tier'].eq('owner')
    small = d['area_ha'] < 1
    tail_s = own & small & (d['bgroup'].eq('undef_S') | d['batch'].eq('O4'))
    L = ['# E3 на мелких контурах: групповая CV (2026-09-27)', '',
         f'Меток {len(d)} (владелец {int(own.sum())}); мелких меток владельца {int((own & small).sum())}, из них хвостовых '
         f'(O3 undef_S + O4 < 1 га) {int(tail_s.sum())}.', '',
         'Для сравнения: E2 на мелких в O4 (новые контуры, не CV) 41/50.', '']
    for name, sel0 in (('все мелкие метки владельца', own & small), ('хвостовые мелкие (O3 undef_S + O4 < 1 га)', tail_s),
                       ('крупные метки владельца', own & ~small)):
        L += [f'## {name}: верно {int(d.loc[sel0, "ok"].sum())} из {int(sel0.sum())}', '']
        rows = []
        for c in ['river_shoal', 'lake_shoal', 'aeolian', 'anthropogenic', 'not_sand']:
            for th in (0.6, 0.7, 0.8, 0.9):
                s = sel0 & d['final_pred'].eq(c) & (d['pmax'] >= th)
                rows.append({'класс модели': RU[c], 'порог': th, 'выбрано': int(s.sum()), 'верно': int(d.loc[s, 'ok'].sum()),
                             'точность': round(d.loc[s, 'ok'].mean(), 3) if s.any() else np.nan})
        L += [pd.DataFrame(rows).to_markdown(index=False), '']
    (AE / 'small_eval.md').write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
