"""
102_big_undefined_model.py - вероятности классов по описанию снимка для пилота на крупнейших контурах undefined (2026-09-26).

Модель: категориальный наивный Байес (сглаживание Лапласа) на 8 полях наблюдений. Обучение: наблюдения СКЕПТИКА (*_own)
по размеченным контурам озёрного прохода (fit + audit, status confirmed/resolved, классы ниже); применение: наблюдения
дешифровщика пилота. Это конфигурация «own -> 1», проверенная в exports/qc/jev/baseline_report.md (раздел A).
Априорные доли классов: не частоты обучающей выборки (она обогащена озёрными), а доли площади остатка по аудиту
(--prior audit) или равные (--prior flat) для проверки устойчивости.
Правило принятия: p_max >= 0.9 И класс модели совпадает с вердиктом дешифровщика. Остальное остаётся undefined.

Вход: exports/qc/lake/lake_fit_verdicts.csv, lake_audit_verdicts.csv, big/big_sample.csv, big/agents/review_B*.json.
Выход: big/big_proposed.csv, big/big_proposed.gpkg (для просмотра в QGIS), таблица в stdout.
Запуск: python -u python/102_big_undefined_model.py [--prior audit|flat|train]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
QCL = ROOT / 'exports' / 'qc' / 'lake'
BIG = QCL / 'big'
OBS = ['water_seen', 'position', 'transition', 'stream', 'shape', 'hue', 'brightness', 'anthro_signs']
CLASSES = ['lake_shoal', 'aeolian', 'not_sand', 'river_shoal', 'anthropogenic']
# доли площади остатка undef_lake по аудиту (lake_audit_report.md), без неклассовых
AUDIT_PRIOR = {'aeolian': 0.239, 'anthropogenic': 0.163, 'lake_shoal': 0.076, 'not_sand': 0.181, 'river_shoal': 0.195}
P_ACCEPT = 0.9


def train_rows() -> pd.DataFrame:
    d = pd.concat([pd.read_csv(QCL / 'lake_fit_verdicts.csv'), pd.read_csv(QCL / 'lake_audit_verdicts.csv')], ignore_index=True)
    d = d[d['status'].isin(['confirmed', 'resolved']) & d['ref'].isin(CLASSES)].copy()
    return d


def fit_nb(X: pd.DataFrame, y: pd.Series, prior: dict[str, float]) -> dict:
    """Условные частоты P(значение | класс) со сглаживанием Лапласа по каждому полю."""
    model = {'prior': prior, 'cond': {}}
    for f in OBS:
        vals = sorted(set(X[f].dropna().astype(str)) | {'__other__'})
        tab = {}
        for c in CLASSES:
            xc = X.loc[y == c, f].astype(str)
            cnt = xc.value_counts()
            tot = len(xc) + len(vals)
            tab[c] = {v: (cnt.get(v, 0) + 1) / tot for v in vals}
        model['cond'][f] = tab
    return model


def predict(model: dict, X: pd.DataFrame) -> pd.DataFrame:
    logp = np.zeros((len(X), len(CLASSES)))
    for j, c in enumerate(CLASSES):
        lp = np.full(len(X), np.log(model['prior'][c]))
        for f in OBS:
            tab = model['cond'][f][c]
            lp += np.log([tab.get(str(v), tab['__other__']) for v in X[f]])
        logp[:, j] = lp
    p = np.exp(logp - logp.max(axis=1, keepdims=True))
    p /= p.sum(axis=1, keepdims=True)
    return pd.DataFrame(p, columns=[f'p_{c}' for c in CLASSES], index=X.index)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--prior', choices=['audit', 'flat', 'train'], default='audit')
    a = ap.parse_args()
    tr = train_rows()
    if a.prior == 'audit':
        s = sum(AUDIT_PRIOR.values())
        prior = {c: AUDIT_PRIOR[c] / s for c in CLASSES}
    elif a.prior == 'flat':
        prior = {c: 1 / len(CLASSES) for c in CLASSES}
    else:
        prior = (tr['ref'].value_counts(normalize=True)).reindex(CLASSES).fillna(1e-3).to_dict()
    Xtr = tr[[f'{f}_own' for f in OBS]].rename(columns=lambda c: c[:-4])
    model = fit_nb(Xtr, tr['ref'], prior)
    print(f'обучение: {len(tr)} контуров, классы {tr["ref"].value_counts().to_dict()}; prior={a.prior}')

    # контроль на размеченных: обучено на наблюдениях скептика, применено к наблюдениям дешифровщика (верхняя оценка, круговая)
    X1 = tr[[f'{f}1' for f in OBS]].rename(columns=lambda c: c[:-1])
    p1 = predict(model, X1)
    cls1 = p1.idxmax(axis=1).str[2:]
    acc = (p1.max(axis=1) >= P_ACCEPT) & (cls1 == tr['verdict1'])
    print(f'контроль (круговой, верхняя оценка): принято {int(acc.sum())} из {len(tr)}, верно {int((cls1[acc] == tr["ref"][acc]).sum())}')

    sample = pd.read_csv(BIG / 'big_sample.csv')
    rows = []
    for f in sorted(BIG.glob('agents/review_B*.json')):
        for v in json.loads(f.read_text(encoding='utf-8-sig'))['verdicts']:
            rows.append({'id': int(v['id']), **{k: v.get(k) for k in OBS}, 'verdict': v.get('verdict'),
                         'confidence': v.get('confidence'), 'reason': v.get('reason', '')})
    rv = pd.DataFrame(rows, columns=['id', *OBS, 'verdict', 'confidence', 'reason'])
    if rv.empty:
        print('описаний пилота пока нет (big/agents/review_B*.json)')
        return
    d = sample.merge(rv, on='id', how='left')
    have = d['verdict'].notna()
    print(f'пилот: контуров {len(d)}, с описанием {int(have.sum())}')
    p = predict(model, d.loc[have, OBS].fillna('unclear'))
    d = d.join(p)
    pc = [f'p_{c}' for c in CLASSES]
    d['class_nb'] = d[pc].idxmax(axis=1).str[2:].where(have)
    d['p_max'] = d[pc].max(axis=1)
    d['accept'] = have & (d['p_max'] >= P_ACCEPT) & (d['class_nb'] == d['verdict'])
    d['proposed'] = np.where(d['accept'], d['class_nb'], 'undefined')
    d.to_csv(BIG / f'big_proposed_{a.prior}.csv', index=False, encoding='utf-8')

    tot = d['area_ha'].sum() / 100
    print(f'\nвердикты дешифровщика (контуров / км2):')
    print(d.groupby(d['verdict'].fillna('нет')).agg(n=('id', 'size'), km2=('area_ha', lambda x: round(x.sum() / 100, 2))).to_string())
    print(f'\nпредложение (p_max >= {P_ACCEPT} и совпадение с вердиктом), из {tot:.1f} км2:')
    print(d.groupby('proposed').agg(n=('id', 'size'), km2=('area_ha', lambda x: round(x.sum() / 100, 2))).to_string())
    print(f'снято с undefined: {d["accept"].sum()} контуров, {d.loc[d["accept"], "area_ha"].sum() / 100:.2f} км2 '
          f'({d.loc[d["accept"], "area_ha"].sum() / 100 / tot * 100:.0f} % площади пилота)')

    g = gpd.read_file(BIG / 'big_geoms.gpkg', layer='sample')[['id', 'geometry']]
    out = g.merge(d[['id', 'area_ha', 'verdict', 'confidence', 'class_nb', 'p_max', 'accept', 'proposed', 'reason'] + pc], on='id')
    out['accept'] = out['accept'].astype(int)
    out.to_file(BIG / f'big_proposed_{a.prior}.gpkg', layer='proposed', driver='GPKG')
    print(f'-> {BIG / f"big_proposed_{a.prior}.gpkg"}')


if __name__ == '__main__':
    main()
