"""
109_disputed_analysis.py - можно ли выделить «спорные» объекты (просьба владельца 2026-09-26: «есть объективно объекты,
которые даже визуально сложно определить»).

Данные: все контуры с двумя и более независимыми прочтениями:
  fit, audit (озёрный проход): дешифровщик и скептик (скептик писал своё мнение до чтения дешифровщика);
  big (пилот по крупным): два независимых слепых агента, при споре третий;
  owner30, O1/O2 (группа v4): владелец против агентов или модели.
Спорность наблюдается как: прочтения разошлись, или итог «смешанный / не понять / спор трёх».
Проверка: предсказывают ли поля продукта (есть у всех 575 тыс. контуров) спорность; групповая перекрёстная проверка по
пространственным блокам 5 км. Если предсказание слабое, спорный класс выводится только из прямых наблюдений.
Выход: exports/qc/disputed/multireader.csv, analysis.md.
Запуск: PYTHONIOENCODING=utf-8 python -u python/109_disputed_analysis.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(r'D:\test\baresand_zapsib')
QCL = ROOT / 'exports' / 'qc' / 'lake'
OUT = ROOT / 'exports' / 'qc' / 'disputed'
PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
AMBIG = {'mixed', 'unresolved', 'disputed3', 'unclear'}
FEATS = ['area_ha', 'e_score', 'h_local600', 'h_chan', 'dist_channel_m', 'dist_water_m', 'flood_frac0', 'water_in_frac',
         'upa_in_max', 'bare2000_frac', 'bare_s2_frac', 'loss_frac', 'tc2000_mean', 'ndvi_s2_mean', 'red_s2_mean',
         'd_road_built', 'n_nb_2km', 'rect', 'elong', 'compact', 'convex', 'gsw_seas_max']
COARSE = {'lake_shoal': 'shoal_any', 'river_shoal': 'shoal_any', 'shoal': 'shoal_any', 'aeolian': 'aeolian',
          'anthropogenic': 'anthropogenic', 'not_sand': 'not_sand'}


def readings() -> pd.DataFrame:
    rows = []
    for name in ('lake_fit_verdicts.csv', 'lake_audit_verdicts.csv'):
        d = pd.read_csv(QCL / name)
        for r in d.itertuples():
            rows.append({'id': r.id, 'source': name.split('_')[1], 'r1': r.verdict1, 'r2': r.verdict_own,
                         'final': r.ref if r.status in ('confirmed', 'resolved') else r.status})
    b = pd.read_csv(QCL / 'big' / 'big_labels.csv')
    for r in b.itertuples():
        rows.append({'id': r.id, 'source': 'big', 'r1': r.label_a, 'r2': r.label_b, 'final': r.final})
    o = pd.read_csv(QCL / 'owner30' / 'owner30_compare.csv')
    for r in o.itertuples():
        rows.append({'id': r.id, 'source': 'owner30', 'r1': r.owner, 'r2': r.final_c, 'final': r.owner, 'coarse': True})
    g = pd.read_csv(ROOT / 'exports' / 'qc' / 'owner_click' / 'owner_gold.csv')
    g = g[g['group'] == 'v4']
    for r in g.itertuples():
        rows.append({'id': r.id, 'source': 'owner_v4', 'r1': r.label, 'r2': r.v4_class, 'final': r.label})
    d = pd.DataFrame(rows)
    d['coarse'] = d.get('coarse', False)
    d['coarse'] = d['coarse'].fillna(False).astype(bool)
    same = np.where(d['coarse'], d['r1'].eq(d['r2']),
                    d['r1'].map(lambda x: COARSE.get(x, x)).eq(d['r2'].map(lambda x: COARSE.get(x, x))))
    d['disagree_fine'] = ~d['r1'].eq(d['r2'])
    d['disagree_coarse'] = ~same
    d['ambig_final'] = d['final'].isin(AMBIG)
    d['hard'] = d['disagree_coarse'] | d['ambig_final']
    return d


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    d = readings()
    ids = sorted(set(d['id']))
    g = gpd.read_file(PRODUCT, layer='genesis', columns=['id', 'genesis', 'genesis_v3e'] + FEATS,
                      where=f"id IN ({','.join(map(str, ids))})")
    c = g.geometry.centroid
    g['block'] = (np.floor(c.x / 5000).astype(int).astype(str) + '_' + np.floor(c.y / 5000).astype(int).astype(str))
    x = d.merge(pd.DataFrame(g.drop(columns='geometry')), on='id', how='left')
    x.to_csv(OUT / 'multireader.csv', index=False, encoding='utf-8')
    L = ['# Спорные объекты: что говорят независимые прочтения (2026-09-26)', '',
         f'Контуров с двумя и более прочтениями: {x["id"].nunique()} (строк {len(x)}).', '']
    t = x.groupby('source').agg(n=('id', 'size'), disagree_fine=('disagree_fine', 'mean'), disagree_coarse=('disagree_coarse', 'mean'),
                                ambig_final=('ambig_final', 'mean'), hard=('hard', 'mean')).round(2)
    L += ['## Доля расхождений по источникам', '', t.to_markdown(), '',
          'disagree_fine: разные классы; disagree_coarse: разные укрупнённые классы (отмели любого типа вместе);',
          'ambig_final: итог «смешанный / не понять / спор трёх / нечитаемо»; hard: coarse или ambig.', '']
    pairs = x[x['disagree_coarse']].apply(lambda r: ' / '.join(sorted([str(COARSE.get(r.r1, r.r1)), str(COARSE.get(r.r2, r.r2))])), axis=1)
    L += ['## Какие классы путают (укрупнённо)', '', pairs.value_counts().head(12).to_markdown(), '']

    # предсказуемость спорности по полям продукта (агентские пары: fit, audit, big)
    y_set = x[x['source'].isin(['fit', 'audit', 'big'])].dropna(subset=['block']).copy()
    y = y_set['hard'].astype(int).to_numpy()
    X = y_set[FEATS].astype(float).to_numpy()
    groups = y_set['block'].to_numpy()
    res = {}
    for name, model in (('logreg', make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), LogisticRegression(max_iter=2000, C=0.5))),
                        ('hgb', HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200))):
        aucs = []
        for seed in range(10):
            perm = np.random.default_rng(seed).permutation(len(y))
            oof = np.zeros(len(y))
            for tr, te in GroupKFold(n_splits=5).split(X[perm], y[perm], groups[perm]):
                m = model.fit(X[perm][tr], y[perm][tr])
                oof[perm[te]] = m.predict_proba(X[perm][te])[:, 1]
            aucs.append(roc_auc_score(y, oof))
        res[name] = (float(np.mean(aucs)), float(np.min(aucs)), float(np.max(aucs)))
    uni = []
    for f in FEATS:
        v = y_set[f].astype(float)
        ok = v.notna()
        if ok.sum() > 30 and y[ok.to_numpy()].std() > 0:
            a = roc_auc_score(y[ok.to_numpy()], v[ok].to_numpy())
            uni.append((f, round(max(a, 1 - a), 3), '+' if a >= 0.5 else '-'))
    uni.sort(key=lambda t: -t[1])
    L += ['## Предсказывают ли поля продукта спорность (пары агентов: fit, audit, big)', '',
          f'Контуров {len(y)}, спорных {int(y.sum())} ({y.mean():.2f}). Групповая CV по блокам 5 км, 10 повторов:', '',
          *[f'- {k}: AUC {v[0]:.3f} (разброс {v[1]:.3f}-{v[2]:.3f})' for k, v in res.items()], '',
          'Одиночные поля (AUC, знак: + больше значение, чаще спор):', '',
          *[f'- {f}: {a} ({s})' for f, a, s in uni[:10]], '']
    (OUT / 'analysis.md').write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
