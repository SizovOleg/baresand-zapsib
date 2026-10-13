"""
113_tail_transfer_eval.py - можно ли переносить метки на похожие непросмотренные контуры хвоста (2026-09-27).

Вопрос владельца: «логично сразу искать похожее - отмели и техноген - и сразу по ним снимать вопросы».
Данные: exports/qc/alphaearth/labels.csv (112: метки владельца и агентов), ae_<год>.csv (111: AlphaEarth внутри контура и в
кольце 30 м), числовые поля продукта v4.
Классы: укрупнённые shoal (отмель любого типа), aeolian, anthropogenic, not_sand.
Наборы признаков: поля продукта; AlphaEarth внутри; AlphaEarth внутри + кольцо; всё вместе.
Модели: поиск похожих (k ближайших по косинусу, голос с весом сходства), логистическая регрессия, градиентный бустинг.
Проверка: групповая перекрёстная по пространственным блокам 5 км (5 частей, 5 повторов). Обучение на всех метках вне блока,
оценка ТОЛЬКО на метках владельца: точность, и для каждого класса точность при уверенности p >= порога и доля охвата.
Отдельно 39 случайных контуров хвоста из O3 (единственная несмещённая проверка на самом хвосте).
Перенос на хвост: доля и площадь непросмотренных undefined, где лучшая модель уверена (p >= порога).
Выход: exports/qc/alphaearth/transfer_eval.md, tail_pred_<модель>.csv.
Запуск: PYTHONIOENCODING=utf-8 python -u python/113_tail_transfer_eval.py [--year 2024] [--no-ae]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import cpu_limit

warnings.filterwarnings('ignore')
cpu_limit.apply()   # четверть ядер и пониженный приоритет (действует и для 114/115, которые загружают этот модуль)
ROOT = Path(r'D:\test\baresand_zapsib')
QC = ROOT / 'exports' / 'qc'
AE = QC / 'alphaearth'
PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg'
CLASSES = ['shoal', 'aeolian', 'anthropogenic', 'not_sand']
RU = {'shoal': 'отмель', 'aeolian': 'эоловый', 'anthropogenic': 'техноген', 'not_sand': 'не песок'}
THR = [0.6, 0.7, 0.8, 0.9]
# поля продукта, которые являются метками или служебными (не признаки)
SKIP = {'id', 'parent_id', 'big_id', 'split_from', 'split_n', 'not_sand_suspect', 'area_km2', 'mrr_az'}


class KNNCos:
    """Поиск похожих: k ближайших размеченных по косинусному сходству, голос с весом сходства."""

    def __init__(self, k: int = 10) -> None:
        self.k = k

    def fit(self, X: np.ndarray, y: np.ndarray) -> 'KNNCos':
        self.X = X / np.linalg.norm(X, axis=1, keepdims=True).clip(1e-9)
        self.y = y
        self.classes_ = np.unique(y)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        Xn = X / np.linalg.norm(X, axis=1, keepdims=True).clip(1e-9)
        s = Xn @ self.X.T
        idx = np.argsort(-s, axis=1)[:, :self.k]
        P = np.zeros((len(X), len(self.classes_)))
        for j, c in enumerate(self.classes_):
            w = np.where(self.y[idx] == c, np.take_along_axis(s, idx, axis=1).clip(0), 0)
            P[:, j] = w.sum(axis=1)
        return P / P.sum(axis=1, keepdims=True).clip(1e-9)


def product_numeric(ids: np.ndarray) -> tuple[pd.DataFrame, list[str]]:
    info = __import__('pyogrio').read_info(PRODUCT, layer='genesis')
    num = [f for f, t in zip(info['fields'], info['dtypes']) if t in ('float64', 'float32', 'int64', 'int32', 'int16') and f not in SKIP]
    g = gpd.read_file(PRODUCT, layer='genesis', columns=['id', 'genesis', 'step6_rule'] + num,
                      where=f"id IN ({','.join(map(str, ids))})")
    c = g.geometry.centroid
    g['block'] = np.floor(c.x / 5000).astype(int).astype(str) + '_' + np.floor(c.y / 5000).astype(int).astype(str)
    return pd.DataFrame(g.drop(columns='geometry')), num


def models(fs: str) -> dict:
    m = {'logreg': lambda: make_pipeline(SimpleImputer(strategy='median'), StandardScaler(),
                                         LogisticRegression(max_iter=3000, C=0.3)),
         'hgb': lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=250, l2_regularization=1.0)}
    if fs in ('ae_in', 'ae_in_ring'):
        m['knn'] = lambda: KNNCos(10)
    return m


def cv_oof_classes(X: np.ndarray, y: np.ndarray, groups: np.ndarray, make, classes: list[str],
                   train_mask: np.ndarray | None = None, reps: int = 5) -> np.ndarray:
    """Вероятности вне блока, усреднённые по повторам; обучение только на train_mask внутри обучающих блоков."""
    if train_mask is None:
        train_mask = np.ones(len(y), bool)
    P = np.zeros((len(y), len(classes)))
    for seed in range(reps):
        perm = np.random.default_rng(seed).permutation(len(y))
        for tr, te in GroupKFold(n_splits=5).split(X[perm], y[perm], groups[perm]):
            tr, te = perm[tr], perm[te]
            tr = tr[train_mask[tr]]
            mdl = make().fit(X[tr], y[tr])
            p = mdl.predict_proba(X[te])
            cl = list(mdl.classes_)
            for j, c in enumerate(classes):
                if c in cl:
                    P[te, j] += p[:, cl.index(c)] / reps
    return P


def cv_oof(X: np.ndarray, y: np.ndarray, groups: np.ndarray, make, train_mask: np.ndarray, reps: int = 5) -> np.ndarray:
    return cv_oof_classes(X, y, groups, make, CLASSES, train_mask, reps)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, default=2024)
    ap.add_argument('--no-ae', action='store_true')
    a = ap.parse_args()
    lab = pd.read_csv(AE / 'labels.csv')
    ae = None
    if not a.no_ae and (AE / f'ae_{a.year}.csv').exists():
        ae = pd.read_csv(AE / f'ae_{a.year}.csv').drop_duplicates('id')
    # хвост: непросмотренные undefined (как в отчёте O3)
    seen = set(lab['id']) | set(pd.read_csv(QC / 'disputed' / 'multireader.csv')['id']) \
        | set(pd.read_csv(QC / 'owner_click' / 'owner_gold.csv')['id'])
    import pyogrio
    und = pyogrio.read_dataframe(PRODUCT, layer='genesis', columns=['id', 'genesis', 'step6_rule', 'area_ha'], read_geometry=False)
    tail_ids = und.loc[und['genesis'].eq('undefined') & und['step6_rule'].isna() & ~und['id'].isin(seen), 'id'].to_numpy()
    feat, num = product_numeric(np.concatenate([lab['id'].to_numpy(), tail_ids]))
    d = lab.merge(feat, on='id', how='left')
    t = feat[feat['id'].isin(tail_ids)].copy()
    ai = [f'ai_{k:02d}' for k in range(64)]
    ar = [f'ar_{k:02d}' for k in range(64)]
    fsets = {'product': num}
    if ae is not None:
        d = d.merge(ae, on='id', how='left')
        t = t.merge(ae, on='id', how='left')
        ok_ae = d[ai].notna().all(axis=1)
        print(f'AlphaEarth есть у {int(ok_ae.sum())} из {len(d)} размеченных и {int(t[ai].notna().all(axis=1).sum())} из {len(t)} контуров хвоста')
        d = d[ok_ae].reset_index(drop=True)
        fsets.update({'ae_in': ai, 'ae_in_ring': ai + ar, 'product+ae': num + ai + ar})
    y = d['coarse'].to_numpy()
    groups = d['block'].to_numpy()
    owner = d['tier'].eq('owner').to_numpy()
    L = ['# Перенос меток на похожие контуры хвоста: проверка осуществимости (2026-09-27)', '',
         f'Меток {len(d)} (владелец {int(owner.sum())}, агенты {int((~owner).sum())}); классы: ' +
         ', '.join(f'{RU[c]} {int((y == c).sum())}' for c in CLASSES) + '.',
         f'Хвост: {len(t)} непросмотренных undefined, {t["area_ha"].sum() / 100:.1f} км2.', '',
         'Оценка только на метках владельца, групповая CV по блокам 5 км (5 частей x 5 повторов).', '']
    res = []
    oof_all = {}
    for fs, cols in fsets.items():
        X = d[cols].astype(float).to_numpy()
        for mn, make in models(fs).items():
            if mn == 'knn' and np.isnan(X).any():
                continue
            for train_on in ('all', 'owner'):
                tm = np.ones(len(y), bool) if train_on == 'all' else owner
                P = cv_oof(X, y, groups, make, tm)
                pred = np.array(CLASSES)[P.argmax(1)]
                pmax = P.max(1)
                ev = owner
                row = {'features': fs, 'model': mn, 'train': train_on,
                       'acc_owner': round(float((pred[ev] == y[ev]).mean()), 3)}
                o3 = d['o3_random'].to_numpy()
                row['acc_o3'] = round(float((pred[o3] == y[o3]).mean()), 3) if o3.any() else np.nan
                for c in ('shoal', 'anthropogenic', 'aeolian'):
                    for th in (0.8, 0.9):
                        sel = ev & (pred == c) & (pmax >= th)
                        row[f'{c}@{th}'] = f'{int((y[sel] == c).sum())}/{int(sel.sum())}'
                res.append(row)
                oof_all[(fs, mn, train_on)] = P
                print(row, flush=True)
    r = pd.DataFrame(res)
    L += ['## Все варианты', '', 'acc_owner: доля верных на метках владельца; acc_o3: на 39 случайных контурах хвоста из O3;',
          'класс@порог: верных из выбранных среди меток владельца при уверенности >= порога.', '', r.to_markdown(index=False), '']
    best = r.sort_values('acc_owner', ascending=False).iloc[0]
    key = (best['features'], best['model'], best['train'])
    P = oof_all[key]
    pred = np.array(CLASSES)[P.argmax(1)]
    pmax = P.max(1)
    L += [f'## Лучший вариант: признаки {key[0]}, модель {key[1]}, обучение на {key[2]}', '']
    rows = []
    for c in CLASSES:
        for th in THR:
            sel = owner & (pred == c) & (pmax >= th)
            k, n = int((y[sel] == c).sum()), int(sel.sum())
            rows.append({'класс': RU[c], 'порог': th, 'выбрано меток владельца': n, 'верно': k,
                         'точность': round(k / n, 3) if n else np.nan,
                         'охват класса': round(n / max(1, int((owner & (y == c)).sum())), 3)})
    L += [pd.DataFrame(rows).to_markdown(index=False), '']
    # перенос на хвост лучшей моделью, обученной на всех метках выбранного уровня
    cols = fsets[key[0]]
    X = d[cols].astype(float).to_numpy()
    tm = np.ones(len(y), bool) if key[2] == 'all' else owner
    mdl = models(key[0])[key[1]]().fit(X[tm], y[tm])
    tt = t.dropna(subset=[c for c in cols if c.startswith('a')]) if ae is not None and key[0] != 'product' else t
    Pt = mdl.predict_proba(tt[cols].astype(float).to_numpy())
    cl = list(mdl.classes_)
    Pt = np.column_stack([Pt[:, cl.index(c)] if c in cl else np.zeros(len(tt)) for c in CLASSES])
    tt = tt[['id', 'area_ha']].assign(**{f'p_{c}': Pt[:, j] for j, c in enumerate(CLASSES)},
                                     pred=np.array(CLASSES)[Pt.argmax(1)], pmax=Pt.max(1))
    tt.to_csv(AE / f'tail_pred_{key[0]}_{key[1]}_{key[2]}.csv', index=False, encoding='utf-8')
    rows = []
    for c in CLASSES:
        for th in THR:
            s = tt[(tt['pred'] == c) & (tt['pmax'] >= th)]
            rows.append({'класс': RU[c], 'порог': th, 'контуров': len(s), 'км2': round(s['area_ha'].sum() / 100, 2)})
    L += ['## Сколько хвоста модель предлагает снять', '', pd.DataFrame(rows).to_markdown(index=False), '',
          'Это предложение, а не результат: точность на хвосте проверяется только новой случайной партией владельца.', '']
    (AE / 'transfer_eval.md').write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L[-40:]))


if __name__ == '__main__':
    main()
