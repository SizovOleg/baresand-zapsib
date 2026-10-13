"""
119_validation_v4.py - итоговая точность продукта v4 по основным классам по независимой выборке V1 (2026-09-27).

План: exports/qc/owner_click/V1/prereg.md. Карта: класс на момент отбора (V1/batch.csv: genesis_main, final);
эталон: метка владельца (owner_gold, партия V1). Страты: основной класс x размер (118).
Оценка площадная стратифицированная: в страте h с площадью карты A_h доля эталонного класса j = площадь выборки с меткой j /
площадь выборки страты; площадь ячейки (класс карты, класс эталона) = сумма A_h * доля. Из матрицы площадей: общая
точность (для отмели, эолового, техногена и с неопределённым), точность пользователя и производителя, F1, каппа,
площади классов по эталону, доля не песка. 95 % ДИ бутстрэпом внутри страт (2 000 повторов).
Второстепенно: тип отмели среди отмелей карты; справочно доля верных по числу контуров.
Выход: exports/qc/owner_click/V1/accuracy[_<партии>].md. Запуск: PYTHONIOENCODING=utf-8 python -u python/119_validation_v4.py [--batches V1,V1b]

Класс карты по другому продукту (2026-10-06, для v7): строка матрицы берётся по классу карты каждого контура, а не
страты, поэтому в одной страте могут быть контуры разных классов карты (страты и веса остаются от отбора V1).
--product PATH: класс карты по продукту (чтение только атрибутов). Круговые контуры (step6_rule v4_expert или
v5_mixed_owner, либо контур разрезан владельцем на части owner_split) сохраняют класс на момент отбора: их метка
владельца из этой же выборки уже перенесена в продукт, сравнение было бы эталона с самим собой. Остальные берут
genesis_main и genesis продукта; если правило v7_* изменило контур выборки, скрипт останавливается.
--cf-map CSV (id,map; map из shoal, aeolian, anthro, undef): контрфактический класс карты для перечисленных контуров
(после --product). --out-dir: папка отчёта (по умолчанию V1). Имя отчёта получает суффикс _<имя продукта> и _cf.
Без новых ключей поведение и отчёты прежние.
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

ROOT = Path(r'D:\test\baresand_zapsib')
QC = ROOT / 'exports' / 'qc'
OC = QC / 'owner_click'
V = OC / 'V1'
MAP = {'alluvial_littoral': 'shoal', 'aeolian': 'aeolian', 'anthropogenic': 'anthro', 'undefined': 'undef'}
REF = {'lake_shoal': 'shoal', 'river_shoal': 'shoal', 'shoal': 'shoal', 'aeolian': 'aeolian', 'anthropogenic': 'anthro',
       'not_sand': 'not_sand', 'mixed': 'mixed', 'disputed': 'mixed', 'unresolved': 'mixed'}
ROWS = ['shoal', 'aeolian', 'anthro', 'undef']
COLS = ['shoal', 'aeolian', 'anthro', 'not_sand', 'mixed']
RU = {'shoal': 'отмель', 'aeolian': 'эоловый', 'anthro': 'техноген', 'undef': 'неопределённый', 'not_sand': 'не песок',
      'mixed': 'смешанный / спорный'}
B = 2000
# класс продукта (genesis) для контрфактического класса карты; для отмели тип неизвестен, берётся общий 'shoal'
FINAL = {'shoal': 'shoal', 'aeolian': 'aeolian', 'anthro': 'anthropogenic', 'undef': 'undefined'}
# правила, которыми метка владельца из самой выборки V1 перенесена в продукт (104, 132): такие контуры круговые
CIRCULAR_RULES = {'v4_expert', 'v5_mixed_owner'}
PRODUCT_COLS = ['id', 'genesis', 'genesis_main', 'step6_rule', 'parent_id', 'part_kind']


def area_matrix(d: pd.DataFrame, A: pd.Series) -> np.ndarray:
    """Матрица площадей (строки ROWS, столбцы COLS), км2.

    Строка берётся по классу карты каждого контура (после замены класса карты по --product / --cf-map в страте могут
    быть контуры разных классов). Вес контура i страты h: A_h * площадь_i / площадь выборки страты h.
    """
    M = np.zeros((len(ROWS), len(COLS)))
    codes, strata = pd.factorize(d['stratum'])
    ar = d['area_ha'].to_numpy(dtype=float)
    tot = np.bincount(codes, weights=ar)[codes]
    ok = tot > 0   # страты с нулевой площадью выборки пропускаются
    w = A.loc[strata].to_numpy(dtype=float)[codes][ok] * ar[ok] / tot[ok]
    r = d['map'].map({c: i for i, c in enumerate(ROWS)}).to_numpy()[ok].astype(int)
    j = d['ref'].map({c: i for i, c in enumerate(COLS)}).to_numpy()[ok].astype(int)
    np.add.at(M, (r, j), w)
    return M


def apply_product(d: pd.DataFrame, product: Path) -> tuple[pd.DataFrame, list[str]]:
    """Класс карты по продукту для некруговых контуров выборки; возвращает таблицу и строки для заголовка отчёта.

    Страта и площадь контура всегда остаются от отбора (у разрезанных владельцем контуров id сохраняет крупнейшая
    часть, её класс и площадь не относятся к отобранному контуру; такие контуры круговые).
    """
    have = set(pyogrio.read_info(product, layer='genesis')['fields'])
    miss = [c for c in PRODUCT_COLS if c not in have]
    if miss:
        raise ValueError(f'в продукте {product} нет полей {miss}')
    p = pyogrio.read_dataframe(product, layer='genesis', read_geometry=False, columns=PRODUCT_COLS)
    if p['id'].duplicated().any():
        raise ValueError(f'в продукте {product} повторяются id')
    split_parents = set(p.loc[p['part_kind'].eq('owner_split'), 'parent_id'])
    p = p.set_index('id')
    lost = ~d['id'].isin(p.index)
    if lost.any():
        raise ValueError(f'контуры выборки отсутствуют в продукте {product.name}: {sorted(d.loc[lost, "id"])}')
    q = p.loc[d['id'].to_numpy()]
    rule = q['step6_rule'].fillna('').astype(str).to_numpy()
    v7 = np.char.startswith(rule.astype(str), 'v7_')
    if v7.any():
        raise ValueError(f'правило v7_* изменило контуры выборки (по построению их быть не должно): '
                         f'{dict(zip(d.loc[v7, "id"], rule[v7]))}')
    circ = np.isin(rule, list(CIRCULAR_RULES)) | d['id'].isin(split_parents).to_numpy()
    new_map = q['genesis_main'].map(MAP).to_numpy()
    bad = ~circ & pd.isna(new_map)
    if bad.any():
        raise ValueError(f'класс продукта вне {list(MAP)} у некруговых контуров: '
                         f'{dict(zip(d.loc[bad, "id"], q["genesis_main"].to_numpy()[bad]))}')
    old_map = d['map'].to_numpy()
    changed = ~circ & (new_map != old_map)
    circ_diff = circ & (new_map != old_map)   # справочно: у круговых класс продукта отличается от класса отбора
    d = d.copy()
    d.loc[~circ, 'map'] = new_map[~circ]
    d.loc[~circ, 'final'] = q['genesis'].to_numpy()[~circ]
    d.loc[~circ, 'step6_rule'] = q['step6_rule'].to_numpy()[~circ]
    note = [f'Класс карты: продукт {product.name}. Круговые контуры (step6_rule {" / ".join(sorted(CIRCULAR_RULES))} '
            f'или разрезаны владельцем на части owner_split: метка владельца из этой выборки уже в продукте): '
            f'{int(circ.sum())}, у них класс на момент отбора (в продукте другой основной класс у {int(circ_diff.sum())}). '
            f'Некруговые: {int((~circ).sum())}, класс по продукту, изменился у {int(changed.sum())}'
            + (': ' + ', '.join(f'{i} {RU[o]} -> {RU[n]}' for i, o, n in
                                 zip(d.loc[changed, 'id'], old_map[changed], new_map[changed])) if changed.any() else '')
            + '.', '']
    return d, note


def apply_cf(d: pd.DataFrame, path: Path) -> tuple[pd.DataFrame, list[str]]:
    """Контрфактический класс карты (словарь ROWS) для перечисленных контуров; возвращает таблицу и строки заголовка."""
    cf = pd.read_csv(path)
    if not {'id', 'map'} <= set(cf.columns):
        raise ValueError(f'{path}: нужны столбцы id,map')
    if cf['id'].duplicated().any():
        raise ValueError(f'{path}: повторяются id')
    bad = ~cf['map'].isin(ROWS)
    if bad.any():
        raise ValueError(f'{path}: класс карты вне {ROWS}: {cf.loc[bad].to_dict("records")}')
    unknown = ~cf['id'].isin(d['id'])
    if unknown.any():
        raise ValueError(f'{path}: id нет среди размеченных контуров выборки: {sorted(cf.loc[unknown, "id"])}')
    new = dict(zip(cf['id'], cf['map']))
    d = d.copy()
    parts = []
    for i in d.index[d['id'].isin(cf['id'])]:
        uid, old, m = d.at[i, 'id'], d.at[i, 'map'], new[d.at[i, 'id']]
        if m != old:
            d.at[i, 'final'] = FINAL[m]
        d.at[i, 'map'] = m
        d.at[i, 'step6_rule'] = 'cf_map'
        parts.append(f'{uid} {RU[old]} -> {RU[m]}')
    note = [f'Контрфактический класс карты ({path.name}), контуров {len(cf)}: ' + ', '.join(parts) + '.', '']
    return d, note


def stats(M: np.ndarray) -> dict:
    """Показатели из матрицы площадей."""
    k3 = [0, 1, 2]
    out = {}
    cls = M[np.ix_(k3, range(len(COLS)))]
    out['OA3'] = np.trace(M[np.ix_(k3, k3)]) / cls.sum()
    out['OA4'] = np.trace(M[np.ix_(k3, k3)]) / M.sum()
    for i, c in enumerate(['shoal', 'aeolian', 'anthro']):
        ua = M[i, i] / M[i].sum() if M[i].sum() else np.nan
        pa = M[i, i] / M[:, i].sum() if M[:, i].sum() else np.nan
        out[f'UA_{c}'], out[f'PA_{c}'] = ua, pa
        out[f'F1_{c}'] = 2 * ua * pa / (ua + pa) if ua + pa else np.nan
    # каппа по 4 категориям: три класса и «прочее» (карта: неопределённый; эталон: не песок, смешанный)
    K = np.zeros((4, 4))
    K[:3, :3] = M[:3, :3]
    K[:3, 3] = M[:3, 3:].sum(axis=1)
    K[3, :3] = M[3, :3]
    K[3, 3] = M[3, 3:].sum()
    p = K / K.sum()
    po, pe = np.trace(p), (p.sum(axis=1) * p.sum(axis=0)).sum()
    out['kappa'] = (po - pe) / (1 - pe)
    for j, c in enumerate(COLS):
        out[f'area_{c}'] = M[:, j].sum()
    out['not_sand_share'] = M[:, 3].sum() / M.sum()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--batches', default='V1', help='партии выборки через запятую (V1 и добор V1b из тех же страт)')
    ap.add_argument('--split-ha', type=float, default=None,
                    help='послестратификация: страты крупных (L) делятся на L1 < порога и XL >= порога (V1/prereg.md, дополнение 2)')
    ap.add_argument('--domain', choices=['U', 'all'], default='U',
                    help='веса страт: U - проверяемый домен без контуров, исключённых из отбора до V1 (по умолчанию); all - вся карта')
    ap.add_argument('--product', default=None,
                    help='GeoPackage продукта (слой genesis): класс карты некруговых контуров по продукту, круговые по отбору')
    ap.add_argument('--cf-map', default=None,
                    help='CSV id,map (map: shoal, aeolian, anthro, undef): контрфактический класс карты перечисленных контуров')
    ap.add_argument('--out-dir', default=None, help='папка отчёта (по умолчанию exports/qc/owner_click/V1)')
    a = ap.parse_args()
    names = a.batches.split(',')
    b = pd.concat([pd.read_csv(OC / n / 'batch.csv').assign(src_batch=n) for n in names], ignore_index=True)
    if b['id'].duplicated().any():
        raise ValueError('контур попал в две партии выборки')
    if (b.groupby('stratum')['A_stratum_km2'].nunique() > 1).any():
        raise ValueError('площади страт в партиях не совпадают: партии не из одной совокупности')
    # площади страт берутся из совокупности (карта на момент отбора V1), при делении крупных пересчитываются
    pop = pd.read_csv(OC / 'validation_v4_pop.csv').rename(columns={'arm': 'stratum'})
    big = {'v_shoal_L', 'v_anthro_L', 'v_aeolian_L'}
    if a.split_ha:
        for t in (b, pop):
            m = t['stratum'].isin(big)
            t.loc[m, 'stratum'] = np.where(t.loc[m, 'area_ha'] >= a.split_ha, t.loc[m, 'stratum'].str.replace('_L', '_XL'),
                                           t.loc[m, 'stratum'].str.replace('_L', '_L1'))
    # домен E: контуры, размеченные до V1 и поэтому исключённые из отбора (как labelled() в 105 на момент V1);
    # вероятность их отбора нулевая, поэтому оценка относится к домену U, а влияние E показывается пределами
    E_src = {}   # источник -> id (источники могут пересекаться)
    for p in (QC / 'final' / 'validation_sample.csv', QC / 'target' / 'target_sample.csv', QC / 'lake' / 'lake_fit.csv',
              QC / 'lake' / 'lake_audit.csv', QC / 'lake' / 'big' / 'big_sample.csv'):
        E_src[f'{p.parent.name}/{p.name}'] = set(pd.read_csv(p, usecols=['id'])['id'])
    gold_all = pd.read_csv(OC / 'owner_gold.csv')
    E_src['owner_gold.csv, окно O1-O8'] = set(gold_all.loc[gold_all['batch'].astype(str).str.match(r'^O\d+$'), 'id'])
    E = set().union(*E_src.values())
    pop['in_E'] = pop['id'].isin(E) & ~pop['id'].isin(b['id'])
    A_all = pop.groupby('stratum')['area_ha'].sum() / 100
    A_U = pop[~pop['in_E']].groupby('stratum')['area_ha'].sum() / 100
    A_E = pop[pop['in_E']].groupby('stratum')['area_ha'].sum() / 100
    N_U = pop[~pop['in_E']].groupby('stratum').size()
    A_pop = A_U if a.domain == 'U' else A_all
    unsampled = set(A_pop.index) - set(b['stratum'])
    if unsampled:
        print(f'внимание: страты без выборки, их площадь не оценивается: {sorted(unsampled)}', flush=True)
    missing = set(b['stratum']) - set(A_pop.index)
    if missing:
        raise ValueError(f'страты выборки без площади в совокупности: {missing} (для V1c нужен --split-ha 100)')
    gold = pd.read_csv(OC / 'owner_gold.csv')
    lab = gold[gold['batch'].isin(names)][['id', 'label']]
    d = b.merge(lab, on='id', how='left')
    n_skip = int(d['label'].isna().sum())
    d = d[d['label'].notna()].copy()
    d['map'] = d['genesis_main'].map(MAP)
    d['ref'] = d['label'].map(REF)
    for col, src, voc in (('map', 'genesis_main', MAP), ('ref', 'label', REF)):
        if d[col].isna().any():
            raise ValueError(f'{src} вне {list(voc)}: {dict(zip(d.loc[d[col].isna(), "id"], d.loc[d[col].isna(), src]))}')
    head = []   # строки заголовка о замене класса карты (только с --product / --cf-map)
    if a.product:
        d, note = apply_product(d, Path(a.product))
        head += note
    if a.cf_map:
        d, note = apply_cf(d, Path(a.cf_map))
        head += note
    A = A_pop
    M = area_matrix(d, A)
    S = stats(M)
    rng = np.random.default_rng(7)
    groups = {h: x for h, x in d.groupby('stratum')}
    census = {h for h, x in groups.items() if len(x) >= N_U.get(h, 0)}   # страта обследована сплошь: не пересэмплировать
    boot = []
    for _ in range(B):
        bd = pd.concat([x if h in census else x.sample(len(x), replace=True, random_state=int(rng.integers(0, 2**31)))
                        for h, x in groups.items()])
        boot.append(stats(area_matrix(bd, A)))
    bt = pd.DataFrame(boot)
    ci = lambda k: f'{S[k]:.3f} ({np.nanpercentile(bt[k], 2.5):.3f}-{np.nanpercentile(bt[k], 97.5):.3f})'
    cia = lambda k: f'{S[k]:.1f} ({np.nanpercentile(bt[k], 2.5):.1f}-{np.nanpercentile(bt[k], 97.5):.1f})'
    Mdf = pd.DataFrame(M, index=[RU[r] for r in ROWS], columns=[RU[c] for c in COLS]).round(1)
    Mdf['итого карта'] = Mdf.sum(axis=1)
    map_area = {r: M[i].sum() for i, r in enumerate(ROWS)}
    prod = Path(a.product).stem if a.product else 'v4'
    cf_t = ', контрфактический класс карты' if a.cf_map else ''
    L = [f'# Итоговая точность продукта {prod} по основным классам (выборка {" + ".join(names)}, 2026-09-27{cf_t})', '',
         f'Размечено {len(d)} контуров (пропущено без метки {n_skip}); эталон: метка владельца в слепом окне.', '',
         *head,
         '## Матрица площадей, км2 (строки: карта, столбцы: эталон)', '', Mdf.to_markdown(), '',
         '## Главные показатели (по площади, 95 % ДИ бутстрэпом внутри страт)', '',
         f'- Общая точность для отмели, эолового и техногена: {ci("OA3")}',
         f'- Общая точность с учётом неопределённого: {ci("OA4")}',
         f'- Каппа (три класса и «прочее»): {ci("kappa")}',
         f'- Доля не песка в продукте: {ci("not_sand_share")}', '']
    # домены: U (проверяемый) и E (исключён из отбора); пределы влияния E на общую точность трёх классов по всей карте
    k3 = ['v_shoal', 'v_aeolian', 'v_anthro']
    aU3 = sum(v for h, v in A_U.items() if h.startswith(tuple(k3)))
    aE3 = sum(v for h, v in A_E.items() if h.startswith(tuple(k3)))
    lo_all, hi_all = S['OA3'] * aU3 / (aU3 + aE3), (S['OA3'] * aU3 + aE3) / (aU3 + aE3)
    L += [f'Веса страт: {"домен U" if a.domain == "U" else "вся карта"}. Домен U {A_U.sum():,.1f} км2; исключённый из отбора '
          f'домен E (размечен до V1: отложенная выборка, целевая выборка шага 5, озёрный проход, пилот, окно O1-O8) '
          f'{int(pop["in_E"].sum())} контуров, {A_E.sum():.1f} км2 ({A_E.sum() / A_all.sum():.1%} карты). Если в E все '
          f'контуры трёх классов верны или все неверны, общая точность трёх классов по всей карте {lo_all:.3f}-{hi_all:.3f}. '
          f'Сплошные страты (не пересэмплируются): {sorted(census) or "нет"}.', '',
          '| Класс | Точность пользователя | Точность производителя | F1 |', '|---|---|---|---|']
    for c in ['shoal', 'aeolian', 'anthro']:
        L.append(f'| {RU[c]} | {ci("UA_" + c)} | {ci("PA_" + c)} | {ci("F1_" + c)} |')
    L += ['', '## Площади классов, км2: карта и оценка по эталону (95 % ДИ)', '', '| Класс | Карта | Оценка по эталону |', '|---|---|---|']
    for c in COLS:
        m = f'{map_area[c]:.1f}' if c in map_area else '-'
        L.append(f'| {RU[c]} | {m} | {cia("area_" + c)} |')
    L.append(f'| неопределённый | {map_area["undef"]:.1f} | - |')
    # при нуле или единицах событий бутстрэп вырождается: интервал Клоппера-Пирсона для эффективного объёма выборки
    # (Киш: веса страт по площади карты и неравные площади контуров внутри страты); доля трактуется как доля площади
    from scipy.stats import beta
    W = A / A.sum()
    inv = 0.0
    for h, x in d.groupby('stratum'):
        ar = x['area_ha'].to_numpy()
        inv += W[h] ** 2 / (ar.sum() ** 2 / (ar ** 2).sum())
    n_eff = 1 / inv
    L += ['', f'Редкие категории эталона (ОРИЕНТИРОВОЧНО, не строгая граница для стратифицированной отношенческой оценки): '
          f'эффективный объём по неравенству весов {n_eff:.1f} контура (Киш); верхняя граница двустороннего 95 % интервала '
          f'Клоппера-Пирсона для доли площади:']
    for c in ('not_sand', 'mixed'):
        share = S[f'area_{c}'] / M.sum()
        k = share * n_eff
        lo = float(beta.ppf(0.025, k, n_eff - k + 1)) if k > 0 else 0.0
        hi = float(beta.ppf(0.975, k + 1, n_eff - k)) if k < n_eff else 1.0
        L.append(f'- {RU[c]}: в выборке {int((d["ref"] == c).sum())} из {len(d)}; доля площади {share:.3f} '
                 f'(ДИ {lo:.3f}-{hi:.3f}, то есть {lo * M.sum():.0f}-{hi * M.sum():.0f} км2)')
    und = d[d['map'] == 'undef']
    if len(und):
        L += ['', '## Состав неопределённого класса (по выборке, число контуров)', '',
              ', '.join(f'{RU.get(k, k)} {v}' for k, v in und['ref'].value_counts().items())]
    sh = d[(d['map'] == 'shoal') & d['label'].isin(['lake_shoal', 'river_shoal', 'shoal'])]
    if len(sh):
        ok = sh['label'].eq(sh['final'])
        # условная точность типа с весами страт: площадь верного типа / площадь отмелей карты, подтверждённых как отмель
        num = den = 0.0
        for h, x in d[d['map'] == 'shoal'].groupby('stratum'):
            # знаменатель: площадь выборки всей страты (после --product / --cf-map в страте бывают не только отмели карты)
            tot = d.loc[d['stratum'] == h, 'area_ha'].sum()
            s_ok = x[x['label'].isin(['lake_shoal', 'river_shoal', 'shoal'])]
            num += A[h] * s_ok.loc[s_ok['label'].eq(s_ok['final']), 'area_ha'].sum() / tot
            den += A[h] * s_ok['area_ha'].sum() / tot
        L += ['', '## Тип отмели (второстепенно)', '',
              f'Среди отмелей карты, которые владелец тоже назвал отмелью: тип совпал у {int(ok.sum())} из {len(sh)}; '
              f'доля площади проверенных отмелей {sh.loc[ok, "area_ha"].sum() / sh["area_ha"].sum():.2f}; с весами страт '
              f'{num / den:.3f}.', '',
              pd.crosstab(sh['final'].rename('карта'), sh['label'].rename('владелец')).to_markdown()]
    ok_n = (d['map'] == d['ref'])
    # таблица страт для дополнительных материалов: совокупность по доменам, объёмы партий, верные и ошибки
    popE = pop[pop['in_E']]
    st = pd.DataFrame({'N_U': N_U, 'A_U, км2': A_U, 'N_E': popE.groupby('stratum').size(), 'A_E, км2': A_E}).fillna(0)
    for n in names:
        st[f'n {n}'] = d[d['src_batch'] == n].groupby('stratum').size()
    st['n'] = d.groupby('stratum').size()
    st['верно'] = d.assign(ok=ok_n).groupby('stratum')['ok'].sum()
    st = st.fillna(0)
    st.loc['всего'] = st.sum()
    int_cols = [c for c in st.columns if not c.startswith('A_')]
    st[int_cols] = st[int_cols].astype(int)
    st = st.round(1)
    L += ['', '## Страты (домен U: веса; домен E: исключён из отбора)', '', st.to_markdown(), '',
          '## Домен E по источникам (контуры могут входить в несколько источников)', '',
          '| Источник | Контуров | км2 |', '|---|---|---|']
    for k, ids in E_src.items():
        x = popE[popE['id'].isin(ids)]
        L.append(f'| {k} | {len(x)} | {x["area_ha"].sum() / 100:.1f} |')
    L += ['', '## Справочно', '',
          f'Доля верных по числу контуров в выборке (без весов): {int(ok_n.sum())} из {len(d)}.', '',
          'По стратам (верно / размечено): ' + '; '.join(f'{h} {int((x["map"] == x["ref"]).sum())}/{len(x)}' for h, x in d.groupby('stratum')), '',
          'По источнику класса карты (step6_rule; пусто = правила каскада): ' +
          '; '.join(f'{k} {int((x["map"] == x["ref"]).sum())}/{len(x)}' for k, x in d.assign(src=d['step6_rule'].fillna('каскад')).groupby('src'))]
    dom = '_U' if a.domain == 'U' else ''   # файлы без суффикса: прежние расчёты с весами по всей карте
    stem = (f'accuracy{dom}' if names == ['V1'] and not a.split_ha
            else f'accuracy_{"+".join(names)}{f"_split{int(a.split_ha)}" if a.split_ha else ""}{dom}')
    # суффиксы не дают перезаписать отчёты статьи (класс на момент отбора)
    sfx = (f'_{Path(a.product).stem}' if a.product else '') + ('_cf' if a.cf_map else '')
    out_dir = Path(a.out_dir) if a.out_dir else V
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f'{stem}{sfx}.md'
    out.write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
