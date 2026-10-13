"""
92_target_verdicts.py — сборка вердиктов агентов по целевой выборке и подбор порогов для правил рельефа.

Вход:  exports/qc/target/agents/review_T<n>.json (дешифровщик), verify_T<n>.json (скептик), target_sample.csv (улики),
       strata_target.csv (веса), при наличии — слой эксперта (--expert <файл в exports/qc/target>, поле expert/verdict).
Выход: exports/qc/target/target_verdicts.csv — вердикты со статусом и уликами;
       target_check.gpkg / .csv — спорные контуры эксперту;
       target_report.md — согласие, состав классов по фронтам, AUC улик, сетка порогов, оценка переезда площади.
Запуск: python -u python/92_target_verdicts.py [--expert Target.shp]

Правила-кандидаты (пороги подбираются ЗДЕСЬ и только здесь):
  A1  undefined ∧ h_local600 > T_A ∧ ¬crossed              → aeolian
  A2  undefined ∧ |h_local600| ≤ T_W ∧ nearest=lake ∧ ...  → lake_shoal
  B1  aeolian(у русла) ∧ crossed ∧ h_chan ≤ T_B            → river_shoal
crossed = upa_in_max ≥ 20 км² ∧ русловой коридор MERIT внутри контура (вычислимая форма «пересекается руслом»).
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
QCT = ROOT / 'exports' / 'qc' / 'target'
AGENTS = QCT / 'agents'
CLASSES = ['shoal', 'river_shoal', 'lake_shoal', 'anthropogenic', 'aeolian', 'not_sand']
RUS2EN = {'морская отмель': 'shoal', 'речная отмель': 'river_shoal', 'отмель речная': 'river_shoal', 'озёрная отмель': 'lake_shoal',
          'озерная отмель': 'lake_shoal', 'отмель озерная': 'lake_shoal', 'техноген': 'anthropogenic', 'антропоген': 'anthropogenic',
          'эоловый': 'aeolian', 'эоловое': 'aeolian', 'эоловая': 'aeolian', 'раздув': 'aeolian', 'не песок': 'not_sand',
          'лишайник': 'not_sand', 'снег': 'not_sand', 'гарь': 'not_sand', 'вода': 'not_sand', 'хасырей': 'lake_shoal',
          'антропогенный': 'anthropogenic', 'техногенный': 'anthropogenic'}


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def auc(x: pd.Series, y: pd.Series) -> float:
    x, y = x.dropna(), y.dropna()
    if len(x) < 5 or len(y) < 5:
        return float('nan')
    b = np.concatenate([x.values, y.values])
    lb = np.concatenate([np.ones(len(x)), np.zeros(len(y))])
    o = np.argsort(b)
    rk = np.empty(len(b))
    rk[o] = np.arange(1, len(b) + 1)
    return (rk[lb == 1].sum() - len(x) * (len(x) + 1) / 2) / (len(x) * len(y))


def collect() -> pd.DataFrame:
    rows = []
    for rf in sorted(AGENTS.glob('review_T*.json')):
        n = int(rf.stem.split('_T')[1])
        rev = json.loads(rf.read_text(encoding='utf-8'))
        vf = AGENTS / f'verify_T{n}.json'
        ver = json.loads(vf.read_text(encoding='utf-8')) if vf.exists() else {'checks': []}
        checks = {int(c['id']): c for c in (ver.get('checks') or [])}
        for v in rev.get('verdicts') or []:
            c = checks.get(int(v['id']))
            rows.append({'id': int(v['id']), 'sector': n, 'verdict': v.get('verdict', ''), 'position': v.get('position', ''),
                         'channel_crosses': v.get('channel_crosses', ''), 'confidence': v.get('confidence', 'low'),
                         'sign': v.get('sign', ''), 'reason': v.get('reason', ''), 'note': v.get('note', ''),
                         'checked': c is not None, 'agree': (c.get('agree') if c else None),
                         'verdict2': (c.get('verdict', '') if c else ''), 'position2': (c.get('position', '') if c else ''),
                         'crosses2': (c.get('channel_crosses', '') if c else ''), 'reason2': (c.get('reason', '') if c else '')})
    return pd.DataFrame(rows).drop_duplicates('id')


def status(r) -> str:
    if pd.isna(r['verdict']) or r['verdict'] == '':
        return 'not_reviewed'
    if r['verdict'] == 'unclear':
        return 'unclear'
    if r['checked'] and r['agree'] is False:
        return 'disputed'
    if r['verdict'] == 'mixed':
        return 'mixed'
    return 'confirmed'


def w_est(df: pd.DataFrame, strata: pd.DataFrame, mask: pd.Series) -> float:
    """Площадь (км²) в генеральной совокупности для контуров, где mask=True: отношенческая оценка по стратам."""
    W = dict(zip(strata['stratum'], strata['A_km2']))
    tot = 0.0
    for h, g in df.groupby('stratum'):
        a = g['area_ha'].sum()
        if a > 0 and h in W:
            tot += W[h] * g.loc[mask.reindex(g.index, fill_value=False), 'area_ha'].sum() / a
    return tot


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--expert', default=None)
    a = ap.parse_args()
    t0 = time.time()
    sample = pd.read_csv(QCT / 'target_sample.csv')
    strata = pd.read_csv(QCT / 'strata_target.csv')
    # гарь нужна для фильтра A1; в ранней выборке A колонки не было, при --append она осталась пустой у строк A
    if 'loss_frac' not in sample.columns or sample['loss_frac'].isna().any():
        import pyogrio
        ex = pyogrio.read_dataframe(ROOT / 'exports' / 'baresand_genesis_step4_v2e.gpkg', layer='genesis',
                                    columns=['id', 'loss_frac'], read_geometry=False,
                                    where=f"id IN ({','.join(map(str, sample['id'].astype(int)))})")
        ex = ex.rename(columns={'loss_frac': 'loss_frac_prod'})
        sample = sample.merge(ex, on='id', how='left')
        sample['loss_frac'] = sample['loss_frac'].fillna(sample['loss_frac_prod']) if 'loss_frac' in sample.columns else sample['loss_frac_prod']
        sample = sample.drop(columns=['loss_frac_prod'])
    vd = collect()
    if not len(vd):
        raise SystemExit('нет review_T*.json')
    df = sample.merge(vd, on='id', how='left')
    df['status'] = df.apply(status, axis=1)
    df['ref'] = np.where(df['status'] == 'confirmed', df['verdict'], '')

    if a.expert:
        ex = gpd.read_file(QCT / a.expert)
        fld = 'expert' if 'expert' in ex.columns else 'verdict'
        ex['_cls'] = [RUS2EN.get(t, t if t in CLASSES else None)
                      for t in ex[fld].fillna('').astype(str).str.strip().str.lower()]
        n_ex, n_mixed = 0, 0
        for i, s_ in ex.groupby(ex['id'].astype(int)):
            cls = set(c for c in s_['_cls'] if c)
            if len(cls) == 1:            # один класс на контур (в т.ч. если он разрезан на части одного класса)
                df.loc[df['id'] == i, ['ref', 'status']] = [cls.pop(), 'confirmed']
                n_ex += 1
            elif len(cls) > 1:           # эксперт разрезал контур на части разных классов — для выборки это mixed
                df.loc[df['id'] == i, ['ref', 'status']] = ['', 'mixed']
                n_mixed += 1
        log(f'вердиктов эксперта применено: {n_ex}, разрезано на разные классы (исключено как mixed): {n_mixed}')

    df.to_csv(QCT / 'target_verdicts.csv', index=False, encoding='utf-8')
    ok = df[df['ref'] != ''].copy()
    ok['is_ae'] = ok['ref'] == 'aeolian'
    ok['is_shoal'] = ok['ref'].isin(['river_shoal', 'lake_shoal', 'shoal'])
    log(f'контуров {len(df)}, проверено {int(df["checked"].sum())}, статусы {df["status"].value_counts().to_dict()}')

    L = ['# Целевая выборка: вердикты и подбор порогов', '',
         f'Контуров {len(df)}; дешифровано {int((df["status"] != "not_reviewed").sum())}; '
         f'перепроверено скептиком {int(df["checked"].sum())}; согласие {int((df["agree"] == True).sum())} из '
         f'{int(df["checked"].sum())}; статусы: {df["status"].value_counts().to_dict()}.', '']

    for fr in ('A', 'B'):
        s = ok[ok['front'] == fr]
        if not len(s):
            continue
        L += [f'## Фронт {fr}: {"undefined" if fr == "A" else "эоловые у русла"} — что там на самом деле', '',
              s['ref'].value_counts().rename('контуров').to_frame().assign(
                  доля_площади=lambda t: [f'{100 * w_est(s, strata, s["ref"] == c) / max(w_est(s, strata, s["ref"] != "__"), 1e-9):.0f} %' for c in t.index]).to_markdown(), '']

    L += ['## Улики против истины', '']
    ae, sh = ok[ok['is_ae']], ok[ok['is_shoal']]
    for v in ('h_local600', 'h_local1200', 'h_chan'):
        L.append(f'- `{v}`: эоловый против отмелей AUC **{auc(ae[v], sh[v]):.3f}** (n {len(ae)}/{len(sh)}); '
                 f'медианы {ae[v].median():.2f} / {sh[v].median():.2f} м')
    # признаки агентов против вычисленных
    L += ['', '### Глаз против прибора', '']
    pos = ok[ok['position'].isin(['at_water', 'above_water', 'below_water'])]
    if len(pos):
        L.append(pos.groupby('position')['h_local600'].describe(percentiles=[.25, .5, .75])[['count', '25%', '50%', '75%']].round(2).to_markdown())
    cr = ok[ok['channel_crosses'].isin(['yes', 'no'])]
    if len(cr):
        L += ['', 'Пересечение руслом: глаз агента (строки) против MERIT `crossed` (столбцы):', '',
              pd.crosstab(cr['channel_crosses'], cr['crossed']).to_markdown()]
        L += ['', 'Истина для тех, где агент видит пересечение:', '',
              cr[cr['channel_crosses'] == 'yes']['ref'].value_counts().to_frame('контуров').to_markdown()]

    # ── сетка порогов, фронт A
    A = ok[ok['front'] == 'A']
    if len(A):
        # рельеф отделяет раздувы от отмелей, но не от снежников/гарей/техногена — те тоже сидят высоко.
        # их отсекает история поверхности: раздув был голым хоть в одну опорную эпоху, снег и лишайник — никогда
        ever_bare = (A['bare_s2_frac'].fillna(0) > 0.05) | (A['bare2000_frac'].fillna(0) > 0.05)
        clean = ever_bare & (A['loss_frac'].fillna(0) < 0.1) & (A['d_road_built'].fillna(9e9) > 500) \
            if 'loss_frac' in A.columns else ever_bare & (A['d_road_built'].fillna(9e9) > 500)
        L += ['', '## Фронт A: правило A1  `h_local600 > T ∧ был_голым ∧ не_гарь ∧ дорога>500 → aeolian`', '',
              '| T, м | выбрано | из них эоловых | чистота | охват эоловых | переедет км² (оценка) | без фильтров: чистота |',
              '|---:|---:|---:|---:|---:|---:|---:|']
        for T in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
            m0 = A['h_local600'] > T
            m = m0 & clean
            n, k = int(m.sum()), int((m & A['is_ae']).sum())
            k0, n0 = int((m0 & A['is_ae']).sum()), int(m0.sum())
            L.append(f'| {T} | {n} | {k} | {100 * k / max(n, 1):.0f} % | {100 * k / max(int(A["is_ae"].sum()), 1):.0f} % | '
                     f'{w_est(A, strata, m):.0f} | {100 * k0 / max(n0, 1):.0f} % |')
        L += ['', '## Фронт A: правило A3  `h_local600 ≤ T → river_shoal` (низкие контуры — побочни малых рек, невидимых GSW)', '',
              '| T, м | выбрано | из них речных | чистота | охват речных | зря: эоловых | переедет км² |', '|---:|---:|---:|---:|---:|---:|---:|']
        rv = A['ref'] == 'river_shoal'
        for T in (0.3, 0.5, 0.75, 1.0):
            m = A['h_local600'] <= T
            n, k = int(m.sum()), int((m & rv).sum())
            L.append(f'| {T} | {n} | {k} | {100 * k / max(n, 1):.0f} % | {100 * k / max(int(rv.sum()), 1):.0f} % | '
                     f'{int((m & A["is_ae"]).sum())} | {w_est(A, strata, m):.0f} |')
        L += ['', '## Фронт A: правило A2  `water_in_frac ≥ W ∧ nearest=lake → lake_shoal` (осушки стоят в воде, DEM там пуст)', '',
              '| W | выбрано | из них озёрных | чистота | охват озёрных | переедет км² |', '|---:|---:|---:|---:|---:|---:|']
        lk = A['ref'] == 'lake_shoal'
        for W in (0.3, 0.5, 0.7, 0.9):
            m = (A['water_in_frac'].fillna(0) >= W) & (A['nearest_type'] == 'lake')
            n, k = int(m.sum()), int((m & lk).sum())
            L.append(f'| {W} | {n} | {k} | {100 * k / max(n, 1):.0f} % | {100 * k / max(int(lk.sum()), 1):.0f} % | {w_est(A, strata, m):.0f} |')
        L += ['', f'Озёрных отмелей в выборке {int(lk.sum())}, из них без отметки DEM (стоят в воде): {int((lk & A["h_local600"].isna()).sum())}.']

    # ── сетка порогов, фронт B
    B = ok[ok['front'] == 'B']
    if len(B):
        rv = B['ref'] == 'river_shoal'
        L += ['', f'## Фронт B: эоловые у русла — истинно речных отмелей {int(rv.sum())} из {len(B)}', '',
              '## Правило B1  `crossed ∧ h_chan ≤ T → river_shoal`', '',
              '| T, м | выбрано | из них речных | чистота | охват речных | зря снято эоловых | переедет км² |', '|---:|---:|---:|---:|---:|---:|---:|']
        for T in (0.5, 1.0, 1.5, 2.0, 3.0, 99):
            m = B['crossed'].astype(bool) & (B['h_chan'].fillna(99) <= T)
            n, k = int(m.sum()), int((m & rv).sum())
            L.append(f'| {T if T < 99 else "без порога"} | {n} | {k} | {100 * k / max(n, 1):.0f} % | {100 * k / max(int(rv.sum()), 1):.0f} % | '
                     f'{int((m & B["is_ae"]).sum())} | {w_est(B, strata, m):.0f} |')
        L += ['', '## Правило B2  `h_local600 ≤ T ∧ position≈at_water (по прибору) → river_shoal`, без пересечения', '',
              '| T, м | выбрано | из них речных | чистота | охват речных | зря снято эоловых |', '|---:|---:|---:|---:|---:|---:|']
        for T in (0.3, 0.5, 1.0):
            m = (B['h_local600'] <= T)
            n, k = int(m.sum()), int((m & rv).sum())
            L.append(f'| {T} | {n} | {k} | {100 * k / max(n, 1):.0f} % | {100 * k / max(int(rv.sum()), 1):.0f} % | {int((m & B["is_ae"]).sum())} |')
        L += ['', '## Объединение B1 ∪ B2', '',
              '| B1: h_chan ≤ | B2: h_local600 ≤ | выбрано | из них речных | чистота | охват речных | зря снято эоловых | переедет км² |',
              '|---:|---:|---:|---:|---:|---:|---:|---:|']
        for tb in (0.5, 1.0, 1.5):
            for tl in (0.3, 0.5):
                m = (B['crossed'].astype(bool) & (B['h_chan'].fillna(99) <= tb)) | (B['h_local600'] <= tl)
                n, k = int(m.sum()), int((m & rv).sum())
                L.append(f'| {tb} | {tl} | {n} | {k} | {100 * k / max(n, 1):.0f} % | {100 * k / max(int(rv.sum()), 1):.0f} % | '
                         f'{int((m & B["is_ae"]).sum())} | {w_est(B, strata, m):.0f} |')

    need = df[df['status'].isin(['disputed', 'unclear', 'mixed'])]
    if len(need):
        geoms = gpd.read_file(QCT / 'target_geoms.gpkg', layer='sample')[['id', 'geometry']]
        cols = ['id', 'front', 'genesis', 'verdict', 'verdict2', 'position', 'channel_crosses', 'status', 'sign', 'reason', 'reason2',
                'h_local600', 'h_chan', 'crossed', 'area_ha', 'lat', 'lon']
        out = geoms.merge(need[cols], on='id', how='inner')
        out['expert'] = ''
        out.to_file(QCT / 'target_check.gpkg', layer='check', driver='GPKG')
        need[cols].to_csv(QCT / 'target_check.csv', index=False, encoding='utf-8')
        L += ['', f'## Спорные и неясные: {len(need)} контуров → `target_check.gpkg`', '']
    (QCT / 'target_report.md').write_text('\n'.join(L), encoding='utf-8')
    log(f'→ target_report.md | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
