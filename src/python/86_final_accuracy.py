"""
86_final_accuracy.py — итоговые оценки по независимой выборке 85: матрица ошибок 6×6, точность, площади классов с доверительными
интервалами.

Метод (Olofsson et al. 2014, адаптация к полигональной единице): выборка стратифицирована по классу карты × размер контура.
Для страты h известны N_h (число контуров) и A_h (площадь, км²) в генеральной совокупности и n_h проверенных контуров.
  * Оценка ПО ЧИСЛУ: доля контуров страты h с истинным классом j → p̂_hj = n_hj / n_h; N̂_j = Σ_h N_h · p̂_hj.
  * Оценка ПО ПЛОЩАДИ (отношенческая): p̂_hj = Σ_{i∈s_h, ref_i=j} a_i / Σ_{i∈s_h} a_i; Â_j = Σ_h A_h · p̂_hj.
    Отношенческая оценка учитывает, что внутри страты контуры разного размера.
  * Доверительные интервалы — бутстрэп: B ресэмплингов контуров внутри каждой страты с возвращением, перцентили 2.5/97.5.
  * Точность пользователя (UA) класса карты j = доля площади (или числа) этого класса, чей истинный класс тоже j.
    Точность производителя (PA) класса j = Â_jj / Â_j(истинная площадь). Общая точность (OA) — по площади и по числу. Каппа.
Матрица ошибок строится и в контурах (сырые счётчики), и в оценённых площадях (км²).

Вход:  exports/qc/final/validation_sample.csv, strata.csv, agents/review_F<n>.json + verify_F<n>.json (+ Expert.shp, если есть).
Выход: exports/qc/final/confusion_counts.csv, confusion_area_km2.csv, accuracy_by_class.csv, area_estimates.csv,
       final_accuracy_report.md, verdicts_final.csv, final_check_final.gpkg (спорные — эксперту).
Запуск: python -u python/86_final_accuracy.py [--boot 2000] [--expert Expert.shp]
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
QCF = ROOT / 'exports' / 'qc' / 'final'
SAMPLE = QCF / 'validation_sample.csv'
STRATA = QCF / 'strata.csv'
GEOMS = QCF / 'validation_geoms.gpkg'
AGENTS = QCF / 'agents'
CLASSES = ['shoal', 'river_shoal', 'lake_shoal', 'anthropogenic', 'aeolian', 'undefined']
REF_EXTRA = ['not_sand']                       # истинный класс, которого нет на карте: ошибка исходной маски
RU = {'shoal': 'морская отмель', 'river_shoal': 'речная отмель', 'lake_shoal': 'озёрная отмель',
      'anthropogenic': 'антропогенный', 'aeolian': 'эоловый', 'undefined': 'неопределённый', 'not_sand': 'не песок (ошибка маски)'}
SEED = 20260908
# «не песок» на карте не может быть отдельным классом — контуры, где эксперт увидел не песок, для расчёта точности карты
# приравниваются к «неопределённый», если карта дала undefined, и считаются ошибкой в остальных случаях (см. --strict-notsand)


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def collect_verdicts() -> pd.DataFrame:
    rows = []
    for rf in sorted(AGENTS.glob('review_F*.json')):
        n = int(rf.stem.split('_F')[1])
        rev = json.loads(rf.read_text(encoding='utf-8'))
        vf = AGENTS / f'verify_F{n}.json'
        ver = json.loads(vf.read_text(encoding='utf-8')) if vf.exists() else {'checks': []}
        checks = {int(c['id']): c for c in (ver.get('checks') or [])}
        for v in rev.get('verdicts') or []:
            c = checks.get(int(v['id']))
            rows.append({'id': int(v['id']), 'verdict': v['verdict'], 'confidence': v.get('confidence', 'low'),
                         'reason': v.get('reason', ''), 'note': v.get('note', ''),
                         'checked': c is not None, 'agree': (c.get('agree') if c else None),
                         'verdict2': (c.get('verdict', '') if c else ''), 'reason2': (c.get('reason', '') if c else '')})
    return pd.DataFrame(rows).drop_duplicates('id')


def status(r) -> str:
    if pd.isna(r['verdict']):
        return 'not_reviewed'
    if r['verdict'] in ('unclear',) or r['confidence'] == 'low':
        if not r['checked'] or r['verdict2'] in ('', 'unclear'):
            return 'unclear'
    if r['checked'] and r['agree'] is False:
        return 'disputed'
    if r['checked'] and r['verdict2'] == 'unclear':
        return 'unclear'
    return 'confirmed'


def ratio_estimates(df: pd.DataFrame, strata: pd.DataFrame, ref_classes, by='area'):
    """Оценка Â_j (или N̂_j) по стратам. Возвращает Series по классам и матрицу вкладов страта×класс."""
    out = {c: 0.0 for c in ref_classes}
    for _, h in strata.iterrows():
        s = df[df['stratum'] == h['stratum']]
        if not len(s):
            continue
        tot = s['area_ha'].sum() if by == 'area' else len(s)
        if tot <= 0:
            continue
        for c in ref_classes:
            m = s['ref'] == c
            share = (s.loc[m, 'area_ha'].sum() / tot) if by == 'area' else (m.sum() / tot)
            out[c] += (h['A_km2'] if by == 'area' else h['N_conts']) * share
    return pd.Series(out)


def bootstrap_ci(df, strata, ref_classes, by='area', B=2000, seed=SEED):
    rng = np.random.default_rng(seed)
    keys = strata['stratum'].tolist()
    groups = {k: df[df['stratum'] == k] for k in keys}
    acc = []
    for _ in range(B):
        parts = []
        for k in keys:
            s = groups[k]
            if len(s):
                parts.append(s.iloc[rng.integers(0, len(s), len(s))])
        if not parts:
            continue
        acc.append(ratio_estimates(pd.concat(parts), strata, ref_classes, by))
    if not acc:
        return None
    A = pd.DataFrame(acc)
    return A.quantile(0.025), A.quantile(0.975)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--boot', type=int, default=2000)
    ap.add_argument('--expert', default=None, nargs='+',
                    help='слои эксперта (перекрывают вердикты агентов): имя файла в exports/qc/final или путь от корня проекта; можно несколько')
    ap.add_argument('--product', default=None, help='gpkg другой версии продукта: метка карты берётся из него (одноразовый тест v3)')
    ap.add_argument('--suffix', default='', help='суффикс выходных файлов, чтобы не затирать результаты v2e')
    a = ap.parse_args()
    t0 = time.time()
    sample = pd.read_csv(SAMPLE)
    if a.product:
        import pyogrio
        ids = ','.join(map(str, sample['id'].astype(int).tolist()))
        lab = pyogrio.read_dataframe(a.product, layer='genesis', columns=['id', 'genesis'], read_geometry=False,
                                     where=f'id IN ({ids})')
        m = dict(zip(lab['id'].astype(int), lab['genesis']))
        sample['genesis_v2e'] = sample['genesis']
        sample['genesis'] = sample['id'].astype(int).map(m).fillna(sample['genesis'])
        log(f'метка карты взята из {a.product}: изменилась у {int((sample["genesis"] != sample["genesis_v2e"]).sum())} из {len(sample)} контуров')
    strata = pd.read_csv(STRATA)
    vd = collect_verdicts()
    if not len(vd):
        print('нет файлов агентов в', AGENTS)
        return
    df = sample.merge(vd, on='id', how='left')
    df['status'] = df.apply(status, axis=1)
    df['ref'] = np.where(df['status'] == 'confirmed', df['verdict'], '')

    if a.expert:
        RUS2EN = {'морская отмель': 'shoal', 'отмель морская': 'shoal', 'речная отмель': 'river_shoal', 'отмель речная': 'river_shoal',
                  'речная': 'river_shoal', 'озёрная отмель': 'lake_shoal', 'озерная отмель': 'lake_shoal', 'отмель озёрная': 'lake_shoal',
                  'отмель озерная': 'lake_shoal', 'хасырей': 'lake_shoal', 'отмель': 'river_shoal',
                  'техноген': 'anthropogenic', 'антропоген': 'anthropogenic', 'антропогенный': 'anthropogenic', 'техногенный': 'anthropogenic',
                  'эоловый': 'aeolian', 'эоловое': 'aeolian', 'эоловая': 'aeolian', 'раздув': 'aeolian',
                  'не песок': 'not_sand', 'не_песок': 'not_sand', 'лишайник': 'not_sand', 'снег': 'not_sand', 'гарь': 'not_sand',
                  'торф': 'not_sand', 'вода': 'not_sand', 'неопределённый': 'undefined'}
        for lay in a.expert:
            path = Path(lay) if (Path(lay).is_absolute() or '/' in lay or '\\' in lay) else QCF / lay
            if not path.is_absolute():
                path = ROOT / path
            ex = gpd.read_file(path)
            fld = 'expert' if 'expert' in ex.columns and ex['expert'].fillna('').astype(str).str.strip().ne('').any() else 'verdict'
            n_ex, n_mix = 0, 0
            for i, sub in ex.groupby(ex['id'].astype(int)):
                cls = {RUS2EN.get(t, t if t in CLASSES + REF_EXTRA else None)
                       for t in sub[fld].fillna('').astype(str).str.strip().str.lower()} - {None}
                if len(cls) == 1:
                    df.loc[df['id'] == i, ['ref', 'status']] = [cls.pop(), 'confirmed']
                    n_ex += 1
                elif len(cls) > 1:      # разрезан на части разных классов — для контура целиком истина смешанная
                    df.loc[df['id'] == i, ['ref', 'status']] = ['', 'mixed']
                    n_mix += 1
            log(f'эксперт {path.name}: применено {n_ex}, смешанных {n_mix}')

    # перепроверка контуров, у которых на первых слепых снимках оставался оверлей шага 1 (жёлтый = морская отмель):
    # вердикт с ЧИСТОГО снимка считается основным, совпадение с прежним измеряет влияние подсказки
    rec = {}
    for rf in sorted(AGENTS.glob('recheck_*.json')):
        for v in json.loads(rf.read_text(encoding='utf-8')).get('verdicts') or []:
            rec[int(v['id'])] = v['verdict']
    if rec:
        sub = df[df['id'].isin(rec)]
        old = sub['ref'].where(sub['ref'] != '', sub['verdict'])
        new = sub['id'].map(rec)
        same = int((old.values == new.values).sum())
        log(f'перепроверка на чистых снимках: {len(rec)} контуров, совпало с прежним вердиктом {same} ({100 * same / max(len(rec), 1):.0f} %)')
        df.loc[df['id'].isin(rec), 'ref_prev'] = old.values
        df.loc[df['id'].isin(rec), 'ref'] = new.values
        df.loc[df['id'].isin(rec), 'status'] = 'confirmed'
        df.loc[df['id'].isin(rec), 'source'] = 'recheck_clean'
    df.to_csv(QCF / f'verdicts_final{a.suffix}.csv', index=False, encoding='utf-8')
    ok = df[df['ref'].isin(CLASSES + REF_EXTRA)].copy()
    log(f'проверено {len(df)} контуров; пригодных вердиктов {len(ok)}; статусы: {df["status"].value_counts().to_dict()}')

    ref_classes = CLASSES + REF_EXTRA
    # --- матрица ошибок в контурах
    cm = pd.crosstab(ok['genesis'], ok['ref']).reindex(index=CLASSES, columns=ref_classes, fill_value=0)
    cm.index = [RU[c] for c in cm.index]
    cm.columns = [RU[c] for c in cm.columns]
    cm.to_csv(QCF / f'confusion_counts{a.suffix}.csv', encoding='utf-8')

    # --- оценки площади и числа с ДИ
    est_a = ratio_estimates(ok, strata, ref_classes, by='area')
    est_n = ratio_estimates(ok, strata, ref_classes, by='count')
    lo_a, hi_a = bootstrap_ci(ok, strata, ref_classes, 'area', a.boot)
    if a.product:   # площади карты — из проверяемого продукта, а не из страт (те несут классы v2e)
        import pyogrio
        prod = pyogrio.read_dataframe(a.product, layer='genesis', columns=['genesis', 'area_ha'], read_geometry=False)
        map_area = prod.groupby('genesis')['area_ha'].sum() / 100.0
        map_n = prod.groupby('genesis').size()
    else:
        map_area = strata.groupby(strata['stratum'].str.rsplit('_', n=1).str[0])['A_km2'].sum()
        map_n = strata.groupby(strata['stratum'].str.rsplit('_', n=1).str[0])['N_conts'].sum()

    rows = []
    for c in ref_classes:
        rows.append({'класс': RU[c], 'карта_км2': round(float(map_area.get(c, 0.0)), 1),
                     'оценка_км2': round(float(est_a[c]), 1),
                     'ДИ95_низ': round(float(lo_a[c]), 1) if lo_a is not None else None,
                     'ДИ95_верх': round(float(hi_a[c]), 1) if hi_a is not None else None,
                     'карта_контуров': int(map_n.get(c, 0)), 'оценка_контуров': int(round(float(est_n[c])))})
    area_tab = pd.DataFrame(rows)
    area_tab.to_csv(QCF / f'area_estimates{a.suffix}.csv', index=False, encoding='utf-8')

    # --- матрица в оценённых площадях: вклад каждой страты распределяем по истинным классам
    # страты — это дизайн выборки (класс v2e × размер), их веса не меняются; метка карты берётся у каждого контура
    # (при --product она уже новая), поэтому площадь страты раскладывается по парам (метка, истина) — пост-стратификация
    cells = []
    for _, h in strata.iterrows():
        s = ok[ok['stratum'] == h['stratum']]
        tot = s['area_ha'].sum()
        if not len(s) or tot <= 0:
            continue
        for (m, c), ar in s.groupby(['genesis', 'ref'])['area_ha'].sum().items():
            cells.append({'map': m, 'ref': c, 'km2': h['A_km2'] * ar / tot})
    cma = pd.DataFrame(cells).pivot_table(index='map', columns='ref', values='km2', aggfunc='sum').reindex(index=CLASSES, columns=ref_classes).fillna(0.0)
    cma_ru = cma.copy(); cma_ru.index = [RU[c] for c in cma_ru.index]; cma_ru.columns = [RU[c] for c in cma_ru.columns]
    cma_ru.round(1).to_csv(QCF / f'confusion_area_km2{a.suffix}.csv', encoding='utf-8')

    # --- точность по площади
    tot_area = cma.values.sum()
    oa = float(np.trace(cma.reindex(index=CLASSES, columns=CLASSES).values)) / tot_area if tot_area else 0.0
    acc_rows = []
    for c in CLASSES:
        ua_den = cma.loc[c].sum()
        pa_den = cma[c].sum() if c in cma.columns else 0.0
        tp = cma.loc[c, c] if c in cma.columns else 0.0
        ua = tp / ua_den if ua_den else np.nan
        pa = tp / pa_den if pa_den else np.nan
        f1 = 2 * ua * pa / (ua + pa) if (ua and pa and not np.isnan(ua) and not np.isnan(pa) and (ua + pa) > 0) else np.nan
        n_h = int((ok['genesis'] == c).sum())
        acc_rows.append({'класс': RU[c], 'проверено_контуров': n_h, 'UA_точность_пользователя_%': round(100 * ua, 1) if ua == ua else None,
                         'PA_точность_производителя_%': round(100 * pa, 1) if pa == pa else None,
                         'F1_%': round(100 * f1, 1) if f1 == f1 else None})
    acc = pd.DataFrame(acc_rows)
    acc.to_csv(QCF / f'accuracy_by_class{a.suffix}.csv', index=False, encoding='utf-8')
    # каппа по площади
    p = cma.reindex(index=CLASSES, columns=CLASSES).fillna(0).values / tot_area if tot_area else np.zeros((len(CLASSES), len(CLASSES)))
    pe = float((p.sum(axis=0) * p.sum(axis=1)).sum())
    kappa = (oa - pe) / (1 - pe) if pe < 1 else np.nan

    # --- отчёт
    L = ['# Итоговая точность каскада генезиса (независимая выборка)', '',
         f'Выборка набрана после фиксации всех порогов и не пересекается с эталонами шагов 2–4. Проверено {len(df)} контуров, '
         f'пригодных вердиктов {len(ok)}; страт {len(strata)}.', '',
         f'**Общая точность по площади: {100 * oa:.1f} %**, каппа {kappa:.2f}.', '',
         '## Точность по классам (по площади)', '', acc.to_markdown(index=False), '',
         '## Оценка площадей с доверительными интервалами (бутстрэп, 95 %)', '', area_tab.to_markdown(index=False), '',
         '## Матрица ошибок, контуров (строки — карта, столбцы — истина)', '', cm.to_markdown(), '',
         '## Матрица ошибок, км² (оценка по стратам)', '', cma_ru.round(1).to_markdown(), '',
         '`не песок (ошибка маски)` — истинный класс, которого нет на карте: контуры, где на снимке нет оголённого песка. '
         'Его площадь — оценка загрязнения всей маски, а не ошибка атрибуции генезиса.']
    (QCF / f'final_accuracy_report{a.suffix}.md').write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L[:12]))
    print('\n', acc.to_string(index=False))
    print('\n', area_tab.to_string(index=False))

    # --- спорные эксперту
    need = df[df['status'].isin(['disputed', 'unclear', 'not_reviewed'])].copy()
    if len(need):
        need['expert'] = ''
        geoms = gpd.read_file(GEOMS, layer='sample')[['id', 'geometry']]
        cols = [c for c in ['id', 'genesis', 'verdict', 'verdict2', 'status', 'expert', 'reason', 'reason2', 'stratum', 'area_ha', 'lat', 'lon'] if c in need.columns]
        geoms.merge(need[cols], on='id', how='inner').to_file(QCF / f'final_check_final{a.suffix}.gpkg', layer='final_check', driver='GPKG')
        need[cols].to_csv(QCF / f'final_check_final{a.suffix}.csv', index=False, encoding='utf-8')
        log(f'спорных эксперту: {len(need)} → final_check_final.gpkg')
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
