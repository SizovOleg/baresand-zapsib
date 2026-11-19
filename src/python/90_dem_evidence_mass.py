"""
90_dem_evidence_mass.py — массовый расчёт улик рельефа (ArcticDEM V4 + MERIT Hydro) для зоны путаницы каскада.

Что считается на каждый контур (все высоты — РАЗНОСТИ, DNA §3.6 в редакции 2026-09-13):
  h_cont, h_p10, h_p90, n_dem  — отметки самого контура (медиана, 10/90-й процентили, число пикселей 10 м)
  local600_p5, local1200_p5    — 5-й процентиль отметок в круге 600 / 1200 м: локальный базис эрозии
  chan600_p5, chan2500_p5 (+_n)— 5-й процентиль отметок в коридоре 150 м вокруг русел MERIT (upa ≥ 5 км²)
                                 в буферах 600 / 2500 м: тальвег ближайшей реки, работает и для малых рек
  upa_in_max, chan_in_frac     — водосбор русла MERIT внутри контура (+45 м) и доля контура под русловым коридором:
                                 вычислимая форма признака эксперта «пересекается руслом»
  water_in_frac                — доля контура под постоянной водой GSW (occurrence ≥ 50 %)
Производные (считаются потребителем): h_local600 = h_cont − local600_p5, h_chan = h_cont − chan600_p5 (или 2500).

Область: класс undefined целиком + эоловые ближе D_CHAN м к руслу (зона путаницы с побочнями). Остальные эоловые
сидят вдали от воды, путаницы с отмелями там нет — не считаем.

Устройство: контуры делятся на N воркеров по id; каждый воркер идёт чанками по CHUNK контуров, каждый готовый чанк
сразу дописывается в свой CSV. Перезапуск подхватывает уже посчитанное. Ошибочный чанк логируется и пропускается,
чтобы доработать его отдельным прогоном (--retry-failed).

Вход:  exports/baresand_genesis_step4_v2e.gpkg, GEE.
Выход: exports/qc/dem/mass/part_<k>.csv, failed_<k>.txt; сборка — exports/qc/dem/dem_evidence_mass.csv (--merge)
Запуск: python -u python/90_dem_evidence_mass.py --workers 4 --chunk 400          (сам поднимает подпроцессы)
        python -u python/90_dem_evidence_mass.py --merge                          (собрать части в один файл)
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import subprocess
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
EXPORTS = ROOT / 'exports'
PRODUCT = EXPORTS / 'baresand_genesis_step4_v2e.gpkg'
OUT = EXPORTS / 'qc' / 'dem' / 'mass'
DEM_ID = 'UMN/PGC/ArcticDEM/V4/2m_mosaic'
GSW_ID = 'JRC/GSW1_4/GlobalSurfaceWater'
MERIT_ID = 'MERIT/Hydro/v1_0_1'
SIMPLIFY_M = 5.0
WATER_OCC = 50
UPA_MIN = 5.0           # км²: русло MERIT для тальвега
CORR_M = 150            # полуширина коридора вокруг русла
IN_BUF_M = 45           # полпикселя MERIT: чтобы русло «внутри контура» ловилось на сетке 90 м
D_CHAN = 400            # эоловые ближе этого к руслу — зона путаницы, считаем
SCALE_C = 10
SCALE_B = 30


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def select_ids() -> pd.DataFrame:
    """Зона расчёта: весь undefined + эоловые у русла."""
    import pyogrio
    g = pyogrio.read_dataframe(PRODUCT, layer='genesis', columns=['id', 'genesis', 'dist_channel_m', 'area_ha'],
                               read_geometry=False)
    m = (g['genesis'] == 'undefined') | ((g['genesis'] == 'aeolian') & (g['dist_channel_m'].fillna(9e9) <= D_CHAN))
    # undefined первым: фронт A стартует, не дожидаясь эоловых
    sel = g.loc[m, ['id', 'genesis', 'area_ha']]
    sel = sel.assign(_o=(sel['genesis'] != 'undefined').astype(int)).sort_values(['_o', 'id']).drop(columns='_o')
    return sel.reset_index(drop=True)


# ─────────────────────────────────────────── воркер ───────────────────────────────────────────
def worker(k: int, n_workers: int, chunk: int, retry_failed: bool) -> None:
    import ee
    try:
        ee.Initialize()
    except Exception:
        ee.Initialize(project='ee-author-project')
    OUT.mkdir(parents=True, exist_ok=True)
    part = OUT / f'part_{k}.csv'
    failed = OUT / f'failed_{k}.txt'

    sel = select_ids()
    mine = sel.iloc[k::n_workers]
    done = set(pd.read_csv(part, usecols=['id'])['id']) if part.exists() else set()
    if retry_failed and failed.exists():
        want = set(int(x) for x in failed.read_text().split() if x.strip())
        mine = mine[mine['id'].isin(want)]
        failed.unlink()
    todo = mine[~mine['id'].isin(done)]
    log(f'воркер {k}: моих {len(mine)}, готово {len(done)}, осталось {len(todo)}')
    if not len(todo):
        return

    dem = ee.Image(DEM_ID)
    elev = dem.select('elevation').updateMask(dem.select('datamask'))
    upa = ee.Image(MERIT_ID).select('upa').unmask(0)
    chan = upa.gte(UPA_MIN)
    corr = chan.focal_max(radius=CORR_M, units='meters')
    chan_elev = elev.updateMask(corr)
    water = ee.Image(GSW_ID).select('occurrence').gte(WATER_OCC).unmask(0)
    inside_img = upa.rename('upa').addBands(chan.rename('chan')).addBands(water.rename('water'))

    red_c = ee.Reducer.median().combine(ee.Reducer.percentile([10, 90]), '', True).combine(ee.Reducer.count(), '', True)
    red_p5 = ee.Reducer.percentile([5]).combine(ee.Reducer.count(), '', True)
    red_in = ee.Reducer.max().combine(ee.Reducer.mean(), '', True)

    def rr(img, fc, buf, red, scale):
        fcb = fc if buf <= 0 else fc.map(lambda f: f.buffer(buf))
        st = img.reduceRegions(collection=fcb, reducer=red, scale=scale)
        return {int(f['properties']['id']): f['properties'] for f in st.getInfo()['features']}

    ids_all = todo['id'].tolist()
    t0 = time.time()
    n_done = 0
    for i0 in range(0, len(ids_all), chunk):
        ids = ids_all[i0:i0 + chunk]
        tc = time.time()
        try:
            g = gpd.read_file(PRODUCT, layer='genesis', columns=['id'], where=f"id IN ({','.join(map(str, ids))})")
            g['geometry'] = g.geometry.simplify(SIMPLIFY_M)
            gw = g.to_crs(4326)
            feats = [ee.Feature(ee.Geometry(json.loads(gpd.GeoSeries([geom]).to_json())['features'][0]['geometry']),
                                {'id': int(i)}) for i, geom in zip(gw['id'], gw.geometry)]
            fc = ee.FeatureCollection(feats)
            rows = {int(i): {'id': int(i)} for i in gw['id']}
            for i, p in rr(elev, fc, 0, red_c, SCALE_C).items():
                rows[i].update(h_cont=p.get('median'), h_p10=p.get('p10'), h_p90=p.get('p90'), n_dem=p.get('count'))
            for i, p in rr(inside_img, fc, IN_BUF_M, red_in, SCALE_B).items():
                rows[i].update(upa_in_max=p.get('upa_max'), chan_in_frac=p.get('chan_mean'),
                               water_in_frac=p.get('water_mean'))
            for buf in (600, 1200):
                for i, p in rr(elev, fc, buf, red_p5, SCALE_B).items():
                    rows[i][f'local{buf}_p5'] = p.get('p5')
            for buf in (600, 2500):
                for i, p in rr(chan_elev, fc, buf, red_p5, SCALE_B).items():
                    rows[i][f'chan{buf}_p5'] = p.get('p5')
                    rows[i][f'chan{buf}_n'] = p.get('count')
            df = pd.DataFrame(list(rows.values()))
            df.to_csv(part, mode='a', header=not part.exists(), index=False, encoding='utf-8')
            n_done += len(df)
            rate = (time.time() - t0) / max(n_done, 1)
            log(f'воркер {k}: {n_done}/{len(ids_all)} | чанк {time.time() - tc:.0f} с | '
                f'{rate:.2f} с/контур | осталось ~{rate * (len(ids_all) - n_done) / 3600:.1f} ч')
        except Exception as e:
            log(f'воркер {k}: чанк {i0 // chunk} НЕ ПРОШЁЛ ({str(e)[:120]}) — записан в failed')
            with failed.open('a') as fh:
                fh.write('\n'.join(map(str, ids)) + '\n')
    log(f'воркер {k}: готово | {(time.time() - t0) / 60:.1f} мин')


# ─────────────────────────────────────────── сборка ───────────────────────────────────────────
def merge() -> None:
    parts = sorted(OUT.glob('part_*.csv'))
    d = pd.concat([pd.read_csv(p) for p in parts], ignore_index=True).drop_duplicates('id')
    d['h_local600'] = d['h_cont'] - d['local600_p5']
    d['h_local1200'] = d['h_cont'] - d['local1200_p5']
    # тальвег: ближний буфер, если русло в нём есть, иначе дальний
    near = d['chan600_n'].fillna(0) >= 3
    d['h_chan'] = np.where(near, d['h_cont'] - d['chan600_p5'], d['h_cont'] - d['chan2500_p5'])
    d['chan_radius_m'] = np.where(near, 600, np.where(d['chan2500_n'].fillna(0) >= 3, 2500, np.nan))
    d.loc[d['chan_radius_m'].isna(), 'h_chan'] = np.nan
    sel = select_ids()
    d = sel.merge(d, on='id', how='left')
    out = OUT.parent / 'dem_evidence_mass.csv'
    d.to_csv(out, index=False, encoding='utf-8')
    fails = sum(len(f.read_text().split()) for f in OUT.glob('failed_*.txt'))
    log(f'→ {out}: {len(d)} контуров, с h_cont {d["h_cont"].notna().sum()}, с h_local600 {d["h_local600"].notna().sum()}, '
        f'с h_chan {d["h_chan"].notna().sum()}; в failed: {fails}')
    print(d.groupby('genesis')[['h_local600', 'h_chan']].median().round(2).to_string())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--chunk', type=int, default=400)
    ap.add_argument('--worker-id', type=int, default=None, help='служебный: запуск одного воркера')
    ap.add_argument('--retry-failed', action='store_true')
    ap.add_argument('--merge', action='store_true')
    ap.add_argument('--dry', action='store_true', help='только показать объём зоны расчёта')
    a = ap.parse_args()
    if a.merge:
        merge()
        return
    if a.dry:
        sel = select_ids()
        print(sel.groupby('genesis')['area_ha'].agg(['count', 'sum']).assign(km2=lambda t: (t['sum'] / 100).round(1)))
        return
    if a.worker_id is not None:
        worker(a.worker_id, a.workers, a.chunk, a.retry_failed)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    procs = []
    for k in range(a.workers):
        logf = (OUT / f'worker_{k}.log').open('a', encoding='utf-8')
        cmd = [sys.executable, '-u', __file__, '--worker-id', str(k), '--workers', str(a.workers),
               '--chunk', str(a.chunk)] + (['--retry-failed'] if a.retry_failed else [])
        procs.append(subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT))
        time.sleep(3)
    log(f'запущено {len(procs)} воркеров, логи в {OUT}/worker_<k>.log')
    for p in procs:
        p.wait()
    log('все воркеры завершились')
    merge()


if __name__ == '__main__':
    main()
