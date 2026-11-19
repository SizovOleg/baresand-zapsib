"""
89_dem_baselevel_compare.py — от чего отсчитывать превышение: три способа задать локальный базис, один эталон.

Зачем: пилот 88 показал сигнал (AUC 0.86), но урез брался из GSW, а GSW видит воду от 30 м шириной. Побочни малых рек
для него невидимы, и именно они дают ошибки эолового класса. Нужен базис, который есть и там, где GSW пусто.

Сравниваются три способа (все — РАЗНОСТИ, абсолютная высота не используется, DNA §3.6 в редакции 2026-09-08):
  h_shore — медиана ArcticDEM в полосе суши 90 м вдоль воды GSW (текущий способ, 88).
  h_chan  — 5-й процентиль ArcticDEM в коридоре вокруг русловой сети MERIT (upa ≥ UPA_MIN): тальвег.
            Работает для малых рек: сеть MERIT задана везде, оптическая видимость воды не нужна.
  h_local — 5-й процентиль ArcticDEM в круге радиуса R вокруг самого контура: локальный базис эрозии.
            Гидрография не нужна вовсе. ВНИМАНИЕ: формально это НЕ «превышение над урезом», а превышение
            над местным минимумом рельефа. Для продакшена требует расширения формулировки DNA §3.6.

Вход:  exports/qc/step{2,3,4}/regression_step*.csv (метки), exports/baresand_genesis_step4_v2e.gpkg, GEE.
Выход: exports/qc/dem/baselevel_compare.csv, baselevel_compare_report.md
Запуск: python -u python/89_dem_baselevel_compare.py [--chunk 20] [--limit 0]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import time
from pathlib import Path

import ee
import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
EXPORTS = ROOT / 'exports'
PRODUCT = EXPORTS / 'baresand_genesis_step4_v2e.gpkg'
OUT = EXPORTS / 'qc' / 'dem'
DEM_ID = 'UMN/PGC/ArcticDEM/V4/2m_mosaic'
GSW_ID = 'JRC/GSW1_4/GlobalSurfaceWater'
MERIT_ID = 'MERIT/Hydro/v1_0_1'
SIMPLIFY_M = 5.0
WATER_OCC = 50
SHORE_M = 90            # полоса суши вдоль воды для замера уреза
UPA_MIN = 5.0           # км²: с какого водосбора считать сеть MERIT руслом (ниже — ложные ложбины)
CORR_M = 150            # полуширина коридора вокруг русла для замера тальвега
SCALE_C = 10
SCALE_B = 30
RADII = (150, 300, 600, 1200, 2500)     # адаптивный поиск базиса: первый радиус, где он определён
LOCAL_R = (300, 600, 1200)              # радиусы для h_local


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def init_ee() -> None:
    try:
        ee.Initialize()
    except Exception:
        ee.Initialize(project='ee-author-project')
    log('GEE инициализирован')


def elevation() -> ee.Image:
    dem = ee.Image(DEM_ID)
    return dem.select('elevation').updateMask(dem.select('datamask'))


def shore_image() -> ee.Image:
    """Отметки суши в полосе SHORE_M вдоль постоянной воды GSW."""
    water = ee.Image(GSW_ID).select('occurrence').gte(WATER_OCC).unmask(0)
    shore = water.focal_max(radius=SHORE_M, units='meters').And(water.Not())
    return elevation().updateMask(shore)


def channel_image() -> ee.Image:
    """Отметки в коридоре CORR_M вокруг русловой сети MERIT (upa ≥ UPA_MIN)."""
    chan = ee.Image(MERIT_ID).select('upa').gte(UPA_MIN).unmask(0)
    corr = chan.focal_max(radius=CORR_M, units='meters')
    return elevation().updateMask(corr)


def reduce_over(img: ee.Image, fc: ee.FeatureCollection, radius_m: int, reducer, scale: int) -> dict:
    fcb = fc if radius_m <= 0 else fc.map(lambda f: f.buffer(radius_m))
    st = img.reduceRegions(collection=fcb, reducer=reducer, scale=scale)
    return {int(f['properties']['id']): f['properties'] for f in st.getInfo()['features']}


def adaptive(img: ee.Image, fc: ee.FeatureCollection, ids: list, key: str, min_px: int = 3) -> dict:
    """Берёт значение из наименьшего радиуса, где источник вообще определён."""
    red = ee.Reducer.percentile([5]).combine(ee.Reducer.median(), '', True).combine(ee.Reducer.count(), '', True)
    out = {i: {} for i in ids}
    for r in RADII:
        pend = [i for i in ids if not out[i]]
        if not pend:
            break
        sub = fc.filter(ee.Filter.inList('id', pend))
        for i, p in reduce_over(img, sub, r, red, SCALE_B).items():
            if (p.get('count') or 0) >= min_px:
                out[i] = {f'{key}_p5': p.get('p5'), f'{key}_med': p.get('median'),
                          f'{key}_n': p.get('count'), f'{key}_r': r}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--chunk', type=int, default=20)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    init_ee()

    parts = []
    for s in ('step2', 'step3', 'step4'):
        f = EXPORTS / 'qc' / s / f'regression_{s}.csv'
        if f.exists():
            parts.append(pd.read_csv(f)[['id', 'expected_genesis']])
    lab = pd.concat(parts).drop_duplicates('id')
    lab = lab[~lab['expected_genesis'].isin(['unassigned', 'undefined'])].rename(columns={'expected_genesis': 'truth'})
    lab['id'] = lab['id'].astype(int)
    if a.limit:
        lab = lab.groupby('truth', group_keys=False).head(max(1, a.limit // lab['truth'].nunique()))
    log(f'меток: {len(lab)} | {lab["truth"].value_counts().to_dict()}')

    g = gpd.read_file(PRODUCT, layer='genesis',
                      columns=['id', 'area_ha', 'genesis', 'dist_channel_m', 'dist_water_m', 'flood_frac0',
                               'nearest_type', 'upa_max' if False else 'comp_upa_km2'],
                      where=f"id IN ({','.join(map(str, lab['id']))})")
    g['geometry'] = g.geometry.simplify(SIMPLIFY_M)
    gw = g.to_crs(4326)
    log(f'геометрий: {len(gw)}')

    elev, shore, chan = elevation(), shore_image(), channel_image()
    red_c = ee.Reducer.median().combine(ee.Reducer.percentile([10, 90]), '', True).combine(ee.Reducer.count(), '', True)
    red_l = ee.Reducer.percentile([5]).combine(ee.Reducer.count(), '', True)

    rows = []
    chunks = [gw.iloc[i:i + a.chunk] for i in range(0, len(gw), a.chunk)]
    for k, ch in enumerate(chunks, 1):
        feats = [ee.Feature(ee.Geometry(json.loads(gpd.GeoSeries([geom]).to_json())['features'][0]['geometry']),
                            {'id': int(i)}) for i, geom in zip(ch['id'], ch.geometry)]
        fc = ee.FeatureCollection(feats)
        ids = [int(i) for i in ch['id']]
        try:
            base = {i: {'id': i} for i in ids}
            for i, p in reduce_over(elev, fc, 0, red_c, SCALE_C).items():
                base[i].update(h_cont=p.get('median'), h_p10=p.get('p10'), h_p90=p.get('p90'), n_dem=p.get('count'))
            for key, img in (('shore', shore), ('chan', chan)):
                for i, v in adaptive(img, fc, ids, key).items():
                    base[i].update(v)
            for r in LOCAL_R:
                for i, p in reduce_over(elev, fc, r, red_l, SCALE_B).items():
                    base[i][f'local{r}_p5'] = p.get('p5')
            rows.extend(base.values())
        except Exception as e:
            log(f'  чанк {k} не прошёл: {str(e)[:130]}')
        log(f'чанк {k}/{len(chunks)} ({len(rows)} замеров)')

    d = pd.DataFrame(rows).merge(lab, on='id', how='left').merge(pd.DataFrame(gw.drop(columns='geometry')),
                                                                 on='id', how='left')
    d['h_shore'] = d['h_cont'] - d.get('shore_med')
    d['h_chan'] = d['h_cont'] - d.get('chan_p5')
    for r in LOCAL_R:
        d[f'h_local{r}'] = d['h_cont'] - d[f'local{r}_p5']
    d.to_csv(OUT / 'baselevel_compare.csv', index=False, encoding='utf-8')
    log(f'→ {OUT / "baselevel_compare.csv"} ({len(d)} строк)')

    def auc(x: pd.Series, y: pd.Series) -> float:
        x, y = x.dropna(), y.dropna()
        if len(x) < 4 or len(y) < 4:
            return float('nan')
        both = np.concatenate([x.values, y.values])
        lb = np.concatenate([np.ones(len(x)), np.zeros(len(y))])
        o = np.argsort(both)
        rk = np.empty(len(both))
        rk[o] = np.arange(1, len(both) + 1)
        return (rk[lb == 1].sum() - len(x) * (len(x) + 1) / 2) / (len(x) * len(y))

    VARS = ['h_shore', 'h_chan'] + [f'h_local{r}' for r in LOCAL_R]
    ae = d[d['truth'] == 'aeolian']
    riv = d[d['truth'] == 'river_shoal']
    lak = d[d['truth'] == 'lake_shoal']
    # контуры, где GSW воду не видит: там текущий способ бессилен, а болит именно здесь
    blind = d['dist_water_m'].fillna(9e9) > 200
    L = ['# От чего отсчитывать превышение: сравнение трёх базисов', '',
         f'Эталон шагов 2–4, {len(d)} контуров. Все величины — разности отметок, абсолютная высота не используется.', '',
         '| базис | что это | покрытие | AUC эол/реч | AUC эол/озёр | AUC эол/реч там, где GSW слеп |',
         '|---|---|---:|---:|---:|---:|']
    NAMES = {'h_shore': 'берег GSW (текущий)', 'h_chan': f'тальвег MERIT (upa≥{UPA_MIN})',
             **{f'h_local{r}': f'локальный минимум, R={r} м' for r in LOCAL_R}}
    for v in VARS:
        if v not in d.columns:
            continue
        L.append(f'| `{v}` | {NAMES[v]} | {100 * d[v].notna().mean():.0f} % | '
                 f'{auc(ae[v], riv[v]):.3f} | {auc(ae[v], lak[v]):.3f} | '
                 f'{auc(ae.loc[ae.index.isin(d[blind].index), v], riv.loc[riv.index.isin(d[blind].index), v]):.3f} |')
    L += ['', '## Медианы по классам, м', '']
    L.append(d.groupby('truth')[[v for v in VARS if v in d.columns]].median().round(2).to_markdown())
    L += ['', f'Контуров, где GSW воду не видит (dist_water > 200 м): {int(blind.sum())} из {len(d)}; '
          f'из них эоловых {int((blind & (d["truth"] == "aeolian")).sum())}, '
          f'речных отмелей {int((blind & (d["truth"] == "river_shoal")).sum())}.', '',
          'Пороги здесь НЕ фиксируются: эталон использовался при настройке правил шагов 2–4.']
    (OUT / 'baselevel_compare_report.md').write_text('\n'.join(L), encoding='utf-8')
    log(f'→ {OUT / "baselevel_compare_report.md"}')
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
