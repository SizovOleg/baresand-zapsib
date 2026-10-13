"""
88_dem_pilot.py — пилот: разделяет ли превышение над урезом воды побочни и раздувы (ArcticDEM V4, 2 м).

Зачем: валидация 2026-09-08 показала, что плановые улики (расстояние до русла, доля заливаемости) не разделяют речные
отмели и эоловые формы: 229 км² побочней сидит в эоловом классе, 141 км² эоловых — в неопределённом, а порог по
расстоянию до русла режет верное вместе с ошибочным. Единственный признак, который называют дешифровщики, — положение
относительно уреза: побочень на уровне воды, раздув выше бровки. DNA §3.6 пересмотрен 2026-09-08 и разрешает ровно эту
величину на фазе 3 (относительное превышение; абсолютная высота, уклон и экспозиция остаются запрещёнными).

ЭТО ПИЛОТ, А НЕ ПРАВИЛО. Он отвечает на один вопрос: есть ли вообще сигнал. Считается на «сожжённом» эталоне
шагов 2–4 (1 031 контур, из них 276 с классом), чтобы не тратить отложенную выборку. Порог здесь не фиксируется.

Вход:  exports/qc/step{2,3,4}/regression_step*.csv (метки), exports/baresand_genesis_step4_v2e.gpkg (геометрия), GEE.
Выход: exports/qc/dem/dem_pilot.csv (сырые замеры), dem_pilot_report.md (разделимость, ROC-AUC, кандидатные пороги).
Запуск: python -u python/88_dem_pilot.py [--chunk 25] [--buffer 1000] [--limit 0]
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
DEM_ID = 'UMN/PGC/ArcticDEM/V4/2m_mosaic'   # V3 устарел и имеет дыры (проверено: Тазовская губа пустая)
GSW_ID = 'JRC/GSW1_4/GlobalSurfaceWater'
SIMPLIFY_M = 5.0        # упрощение геометрии перед отправкой в GEE (контуры мелкие, деталь не нужна)
WATER_OCC = 50          # порог occurrence GSW для «постоянной воды», %
SCALE_C = 10            # масштаб замера по контуру, м
SCALE_W = 30            # масштаб замера уровня воды, м
SHORE_M = 90            # ширина береговой полосы для замера уреза, м


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def init_ee() -> None:
    try:
        ee.Initialize()
    except Exception:
        ee.Initialize(project='ee-ntcomz18')
    log('GEE инициализирован')


def load_labels() -> pd.DataFrame:
    """Метки «сожжённого» эталона шагов 2–4. unassigned/undefined отбрасываем — класс неизвестен."""
    parts = []
    for s in ('step2', 'step3', 'step4'):
        f = EXPORTS / 'qc' / s / f'regression_{s}.csv'
        if f.exists():
            d = pd.read_csv(f)
            d['src'] = s
            parts.append(d[['id', 'expected_genesis', 'src']])
    t = pd.concat(parts).drop_duplicates('id')
    t = t[~t['expected_genesis'].isin(['unassigned', 'undefined'])]
    t['id'] = t['id'].astype(int)
    return t.rename(columns={'expected_genesis': 'truth'})


def contour_stats(fc: ee.FeatureCollection) -> dict:
    """Высоты по самому контуру."""
    dem = ee.Image(DEM_ID)
    elev = dem.select('elevation').updateMask(dem.select('datamask'))
    red = (ee.Reducer.median()
           .combine(ee.Reducer.percentile([10, 90]), '', True)
           .combine(ee.Reducer.count(), '', True))
    st = elev.reduceRegions(collection=fc, reducer=red, scale=SCALE_C)
    return {f['properties']['id']: f['properties'] for f in st.getInfo()['features']}


def waterline_image(mode: str) -> ee.Image:
    """Высота уреза.

    mode='shore' (по умолчанию): медиана высот в полосе СУШИ шириной SHORE_M вдоль границы воды.
    Так и надо: ArcticDEM строится стереопарами, на гладкой воде сопоставление не сходится, и отметки
    над водоёмами — шум либо пустоты. Берег даёт ту же отметку уреза, но по надёжной поверхности.
    mode='surface': прежний вариант — отметки над самой водой (оставлен для сравнения).
    """
    dem = ee.Image(DEM_ID)
    elev = dem.select('elevation').updateMask(dem.select('datamask'))
    water = ee.Image(GSW_ID).select('occurrence').gte(WATER_OCC).unmask(0)
    if mode == 'surface':
        return elev.updateMask(water)
    shore = water.focal_max(radius=SHORE_M, units='meters').And(water.Not())
    return elev.updateMask(shore)


def water_level(fc: ee.FeatureCollection, radius_m: int, mode: str = 'shore') -> dict:
    """Уровень уреза в буфере заданного радиуса."""
    fcb = fc.map(lambda f: f.buffer(radius_m))
    red = (ee.Reducer.median().combine(ee.Reducer.count(), '', True)
           .combine(ee.Reducer.stdDev(), '', True))
    st = waterline_image(mode).reduceRegions(collection=fcb, reducer=red, scale=SCALE_W)
    return {f['properties']['id']: f['properties'] for f in st.getInfo()['features']}


def measure(fc: ee.FeatureCollection, buffer_m: int, radii=None, min_px: int = 3, mode: str = 'shore') -> list:
    """Превышение контура над локальным урезом.

    Режим 'nearest' (radii задан): уровень воды берётся из НАИМЕНЬШЕГО буфера, где вода вообще есть.
    Так исключается подмена уреза чужим водоёмом на другом уровне — дефект первой версии, из-за которого
    на удалённых от воды контурах превышение уходило в −18…+36 м (физически невозможно на равнине).
    Режим фиксированного буфера (radii=None) оставлен для воспроизведения пилота 2026-09-08.
    """
    c = contour_stats(fc)
    rows = {int(i): {'id': int(i), 'h_cont': p.get('median'), 'h_p10': p.get('p10'), 'h_p90': p.get('p90'),
                     'n_dem': p.get('count'), 'h_water': None, 'n_water': 0, 'water_radius_m': None, 'h_water_sd': None}
            for i, p in c.items()}
    for r in (radii or [buffer_m]):
        pending = [i for i, v in rows.items() if v['n_water'] < min_px]
        if not pending:
            break
        sub = fc.filter(ee.Filter.inList('id', pending))
        for i, q in water_level(sub, r, mode).items():
            i = int(i)
            if (q.get('count') or 0) >= min_px:
                rows[i].update(h_water=q.get('median'), n_water=q.get('count'), water_radius_m=r,
                               h_water_sd=q.get('stdDev'))
    return list(rows.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--chunk', type=int, default=25)
    ap.add_argument('--buffer', type=int, default=1000)
    ap.add_argument('--buffer2', type=int, default=3000, help='повторная попытка, если воды рядом не нашлось')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--ids-csv', default=None, help='CSV с колонкой id: замерить эти контуры вместо эталона')
    ap.add_argument('--out-name', default='dem_pilot', help='имя выходных файлов без расширения')
    ap.add_argument('--water-mode', default='shore', choices=['shore', 'surface'],
                    help='где мерять урез: shore — полоса суши вдоль воды (надёжно), surface — над водой')
    ap.add_argument('--radii', default='150,300,600,1200,2500,5000',
                    help='радиусы поиска уреза, м: берётся первый, где вода есть; пусто = старый режим фикс. буфера')
    a = ap.parse_args()
    t0 = time.time()
    RADII = [int(x) for x in a.radii.split(',') if x.strip()] or None
    OUT.mkdir(parents=True, exist_ok=True)
    init_ee()

    if a.ids_csv:
        src = pd.read_csv(a.ids_csv)
        lab = pd.DataFrame({'id': src['id'].astype(int)})
        lab['truth'] = src['truth'] if 'truth' in src.columns else 'unknown'
        lab['src'] = Path(a.ids_csv).stem
        log(f'контуров из {a.ids_csv}: {len(lab)}')
    else:
        lab = load_labels()
        if a.limit:
            lab = lab.groupby('truth', group_keys=False).head(max(1, a.limit // lab['truth'].nunique()))
        log(f'меток эталона: {len(lab)} | {lab["truth"].value_counts().to_dict()}')

    ids = lab['id'].tolist()
    log('читаю геометрию продукта...')
    g = gpd.read_file(PRODUCT, layer='genesis', columns=['id', 'area_ha', 'genesis', 'dist_channel_m', 'dist_water_m',
                                                         'flood_frac0', 'nearest_type'],
                      where=f"id IN ({','.join(map(str, ids))})")
    log(f'геометрий: {len(g)}')
    g['geometry'] = g.geometry.simplify(SIMPLIFY_M)
    gw = g.to_crs(4326)

    rows = []
    chunks = [gw.iloc[i:i + a.chunk] for i in range(0, len(gw), a.chunk)]
    for k, ch in enumerate(chunks, 1):
        feats = [ee.Feature(ee.Geometry(json.loads(gpd.GeoSeries([geom]).to_json())['features'][0]['geometry']),
                            {'id': int(i)})
                 for i, geom in zip(ch['id'], ch.geometry)]
        fc = ee.FeatureCollection(feats)
        try:
            rows.extend(measure(fc, a.buffer, radii=RADII, mode=a.water_mode))
        except Exception as e:
            log(f'  чанк {k} не прошёл: {str(e)[:130]}')
        log(f'чанк {k}/{len(chunks)} готов ({len(rows)} замеров)')

    d = pd.DataFrame(rows).drop_duplicates('id')
    d = d.merge(lab, on='id', how='left').merge(
        pd.DataFrame(g.drop(columns='geometry')), on='id', how='left')
    d['h_rel'] = d['h_cont'] - d['h_water']          # ГЛАВНАЯ ВЕЛИЧИНА: превышение над локальным урезом
    d['h_range'] = d['h_p90'] - d['h_p10']           # разброс высот внутри контура (разведочно, см. отчёт)
    d.to_csv(OUT / f'{a.out_name}.csv', index=False, encoding='utf-8')
    log(f'→ {OUT / (a.out_name + ".csv")} ({len(d)} строк, с h_rel: {d["h_rel"].notna().sum()})')

    # ── разделимость
    L = ['# Пилот ArcticDEM: разделяет ли превышение над урезом побочни и раздувы', '',
         f'Источник: `{DEM_ID}` (2 м), уровень воды — медиана высот там, где GSW occurrence ≥ {WATER_OCC} %, '
         f'в буфере {a.buffer} м (при отсутствии воды — {a.buffer2} м).', '',
         f'Замерено {len(d)} контуров «сожжённого» эталона, из них с полученным превышением {d["h_rel"].notna().sum()}.',
         '', '## Превышение над урезом по истинным классам', '']
    ok = d[d['h_rel'].notna()]
    tab = ok.groupby('truth')['h_rel'].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9])
    L.append(tab.round(2).to_markdown())
    L += ['', '## Разброс высот внутри контура (h_range) — РАЗВЕДОЧНО', '',
          'Величина за рамками пересмотра DNA §3.6 (там разрешено только превышение над урезом). '
          'Приводится, чтобы понять, стоит ли ставить вопрос о её включении.', '']
    L.append(ok.groupby('truth')['h_range'].describe(percentiles=[0.5]).round(2).to_markdown())

    riv, ae = ok[ok['truth'] == 'river_shoal']['h_rel'], ok[ok['truth'] == 'aeolian']['h_rel']
    if len(riv) > 3 and len(ae) > 3:
        both = np.concatenate([riv.values, ae.values])
        lb = np.concatenate([np.zeros(len(riv)), np.ones(len(ae))])
        order = np.argsort(both)
        rank = np.empty(len(both))
        rank[order] = np.arange(1, len(both) + 1)
        auc = (rank[lb == 1].sum() - len(ae) * (len(ae) + 1) / 2) / (len(ae) * len(riv))
        L += ['', '## Разделимость «речная отмель» против «эоловый»', '',
              f'- медиана превышения: речные **{riv.median():.2f} м**, эоловые **{ae.median():.2f} м**, '
              f'разница **{ae.median() - riv.median():.2f} м**',
              f'- ROC-AUC (эоловый выше речного): **{auc:.3f}** '
              f'({"сигнал есть" if auc > 0.75 else "сигнала мало" if auc > 0.6 else "сигнала нет"})',
              f'- n: речных {len(riv)}, эоловых {len(ae)}', '',
              '### Кандидатные пороги (НЕ фиксировать здесь — только оценка потенциала)', '',
              '| порог h_rel, м | эоловых выше порога | речных выше порога | точность разделения |', '|---:|---:|---:|---:|']
        for thr in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.0):
            a_hi, r_hi = (ae > thr).sum(), (riv > thr).sum()
            prec = 100 * a_hi / max(a_hi + r_hi, 1)
            L.append(f'| {thr:.1f} | {a_hi}/{len(ae)} ({100 * a_hi / len(ae):.0f} %) | '
                     f'{r_hi}/{len(riv)} ({100 * r_hi / len(riv):.0f} %) | {prec:.0f} % |')
    else:
        L += ['', '**Мало замеров для оценки разделимости.**']

    L += ['', '## Качество замера', '',
          f'- контуров без воды в буфере (превышение не получено): {(d["h_rel"].isna()).sum()}',
          f'- медиана числа пикселей DEM на контур: {d["n_dem"].median():.0f}',
          '', 'Порог по этим числам не фиксируется: эталон использовался при настройке правил шагов 2–4. '
          'Настройка — на отдельной целевой выборке, проверка — на отложенной выборке валидации.']
    (OUT / f'{a.out_name}_report.md').write_text('\n'.join(L), encoding='utf-8')
    log(f'→ {OUT / (a.out_name + "_report.md")}')
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
