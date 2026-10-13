"""
96_lake_evidence.py — озёрные улики, редакция 2 (проход по озёрным отмелям, 2026-09-18, после разбора Астры).

Две совокупности (поле pop):
  undef_lake — undefined с ближайшим водным объектом-озером (nearest_type == 'lake'): 20 797 контуров, 96.6 км²
  river_lake — river_shoal, у которых ближайшая водная компонента шага 2 — озеро (comp_type == 'lake'): 51 168 контуров, 592.9 км²

Что исправлено против редакции 1 (замечания Астры, docs/reviews/astra_lake_pass_2026-09-17.md):
  * доля воды считается по самому контуру, без буфера 45 м (water_in_raw; старое water_in_frac в продукте — мера соседства);
  * контакт с водой измеряется отдельно: доля кольца шириной δ (15/30/60 м) вокруг контура, занятая водой GSW (occurrence ≥ 50 —
    c15/c30/c60; occurrence ≥ 5 — c15s/c30s/c60s). Кольцо строится клиентом в EPSG:3576 (buffer(δ) минус контур);
  * GSW YearlyHistory 2021 в буфере 300 м раскладывается на три доли: нет данных (0) / нет воды (1) / вода (2–3);
  * состояние озера берётся из компоненты шага 2 (comp_seas_max, comp_type, comp_km2, comp_upa из
    exports/qc/step2/step2_evidence_extra.csv + water_components.csv), а не из сезонности пикселей контура;
  * h_shore убран (его базис — не урез); превышение над сушей круга 600 м (h_dry600) оставлено — это разность высот, DNA §3.6.

Все высоты — разности (DNA §3.6 в редакции 2026-09-13). Устройство — как в 90/96: воркеры по id, чанки, дозапись в
part_<k>.csv, --merge. Выход: exports/qc/lake/mass2/part_<k>.csv → exports/qc/lake/lake_evidence_v2.csv (+ поля продукта, компоненты, lat/lon).
Запуск: python -u python/96_lake_evidence.py --workers 5 --chunk 400 ; python -u python/96_lake_evidence.py --merge
Проба:  python -u python/96_lake_evidence.py --worker-id 0 --workers 5 --chunk 20 --limit 20 --out-dir exports/qc/lake/mass2_test
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
PRODUCT = EXPORTS / 'baresand_genesis_step5_v3e.gpkg'
STEP2_EXTRA = EXPORTS / 'qc' / 'step2' / 'step2_evidence_extra.csv'
WATER_COMP = EXPORTS / 'qc' / 'step2' / 'water_components.csv'
OUT = EXPORTS / 'qc' / 'lake' / 'mass2'
FINAL = EXPORTS / 'qc' / 'lake' / 'lake_evidence_v2.csv'
DEM_ID = 'UMN/PGC/ArcticDEM/V4/2m_mosaic'
GSW_ID = 'JRC/GSW1_4/GlobalSurfaceWater'
GSW_YEAR_ID = 'JRC/GSW1_4/YearlyHistory'
SIMPLIFY_M = 5.0
RING_M = (15, 30, 60)
NEAR_M = 300
DRY_R_M = 600
SCALE_C, SCALE_B, SCALE_R = 10, 30, 10
NL = chr(10)
PRODUCT_COLS = ['id', 'genesis', 'area_ha', 'nearest_type', 'step2_rule', 'step5_rule', 'dist_channel_m', 'dist_water_m',
                'h_local600', 'h_chan', 'upa_in_max', 'crossed', 'water_in_frac', 'gsw_seas_max', 'flood_frac0',
                'bare2000_frac', 'bare_s2_frac', 'loss_frac', 'd_road_built', 'not_sand_suspect']


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def components() -> pd.DataFrame:
    """Ближайшая водная компонента шага 2 и её свойства (тип, площадь, водосбор, сезонность) на каждый контур."""
    ex = pd.read_csv(STEP2_EXTRA)
    wc = pd.read_csv(WATER_COMP).rename(columns={'comp': 'near_comp', 'type': 'comp_type', 'area_km2': 'comp_km2',
                                                  'max_upa_km2': 'comp_upa'})[['near_comp', 'comp_type', 'comp_km2', 'comp_upa']]
    return ex.merge(wc, on='near_comp', how='left')


def select_ids() -> pd.DataFrame:
    import pyogrio
    g = pyogrio.read_dataframe(PRODUCT, layer='genesis', columns=PRODUCT_COLS, read_geometry=False)
    g = g.merge(components().drop(columns=['dist_channel_m']), on='id', how='left')
    pop1 = (g['genesis'] == 'undefined') & (g['nearest_type'] == 'lake')
    pop2 = (g['genesis'] == 'river_shoal') & (g['comp_type'] == 'lake')
    g['pop'] = np.where(pop1, 'undef_lake', np.where(pop2, 'river_lake', ''))
    return g[g['pop'] != ''].sort_values('id').reset_index(drop=True)


def to_ee_geom(geom, ee):
    return ee.Geometry(json.loads(gpd.GeoSeries([geom]).to_json())['features'][0]['geometry'])


def worker(k: int, n_workers: int, chunk: int, out_dir: Path, limit: int | None) -> None:
    import ee
    try:
        ee.Initialize()
    except Exception:
        ee.Initialize(project='ee-ntcomz18')
    out_dir.mkdir(parents=True, exist_ok=True)
    part, failed = out_dir / f'part_{k}.csv', out_dir / f'failed_{k}.txt'
    mine = select_ids().iloc[k::n_workers]
    if limit:
        mine = mine.iloc[:limit]
    done = set(pd.read_csv(part, usecols=['id'])['id']) if part.exists() else set()
    todo = mine[~mine['id'].isin(done)]
    log(f'воркер {k}: моих {len(mine)}, готово {len(done)}, осталось {len(todo)}')
    if not len(todo):
        return

    dem = ee.Image(DEM_ID)
    elev = dem.select('elevation').updateMask(dem.select('datamask'))
    occ = ee.Image(GSW_ID).select('occurrence').unmask(0)
    w50, w5 = occ.gte(50).rename('w50'), occ.gte(5).rename('w5')
    elev_dry = elev.updateMask(occ.lt(5))
    inside_img = occ.gte(1).rename('ever').addBands(occ.rename('occ')).addBands(w50)
    ring_img = w50.addBands(w5)
    y21 = ee.Image(GSW_YEAR_ID + '/2021').select('waterClass').unmask(0)   # 0 нет данных, 1 нет воды, 2 сезонная, 3 постоянная
    y21_img = y21.eq(0).rename('nodata').addBands(y21.eq(1).rename('dry')).addBands(y21.gte(2).rename('wet'))

    red_med_n = ee.Reducer.median().combine(ee.Reducer.count(), '', True)
    red_p5 = ee.Reducer.percentile([5]).combine(ee.Reducer.count(), '', True)
    red_mean = ee.Reducer.mean()
    red_mean_n = ee.Reducer.mean().combine(ee.Reducer.count(), '', True)

    def rr(img, fc, buf, red, scale):
        fcb = fc if buf <= 0 else fc.map(lambda f: f.buffer(buf))
        st = img.reduceRegions(collection=fcb, reducer=red, scale=scale)
        return {int(f['properties']['id']): f['properties'] for f in st.getInfo()['features']}

    ids_all = todo['id'].tolist()
    t0, n_done = time.time(), 0
    for i0 in range(0, len(ids_all), chunk):
        ids = ids_all[i0:i0 + chunk]
        tc = time.time()
        try:
            g = gpd.read_file(PRODUCT, layer='genesis', columns=['id'], where=f"id IN ({','.join(map(str, ids))})")
            g['geometry'] = g.geometry.simplify(SIMPLIFY_M)
            rings = {d: g.geometry.buffer(d).difference(g.geometry) for d in RING_M}
            gw = g.to_crs(4326)
            fc = ee.FeatureCollection([ee.Feature(to_ee_geom(geom, ee), {'id': int(i)}) for i, geom in zip(gw['id'], gw.geometry)])
            rows = {int(i): {'id': int(i)} for i in gw['id']}
            for i, p in rr(elev, fc, 0, red_med_n, SCALE_C).items():
                rows[i].update(h_cont=p.get('median'), n_dem=p.get('count'))
            for i, p in rr(inside_img, fc, 0, red_mean, SCALE_R).items():
                rows[i].update(ever_water_frac=p.get('ever'), occ_mean=p.get('occ'), water_in_raw=p.get('w50'))
            for i, p in rr(elev_dry, fc, DRY_R_M, red_p5, SCALE_B).items():
                rows[i].update(dry600_p5=p.get('p5'), dry600_n=p.get('count'))
            for i, p in rr(y21_img, fc, NEAR_M, red_mean, SCALE_B).items():
                rows[i].update(y21_nodata=p.get('nodata'), y21_dry=p.get('dry'), y21_wet=p.get('wet'))
            for d in RING_M:
                rw = gpd.GeoSeries(rings[d], crs=g.crs).to_crs(4326)
                fcr = ee.FeatureCollection([ee.Feature(to_ee_geom(geom, ee), {'id': int(i)}) for i, geom in zip(g['id'], rw)])
                for i, p in rr(ring_img, fcr, 0, red_mean_n, SCALE_R).items():
                    rows[i].update({f'c{d}': p.get('w50_mean'), f'c{d}s': p.get('w5_mean'), f'c{d}_n': p.get('w50_count')})
            df = pd.DataFrame(list(rows.values()))
            df.to_csv(part, mode='a', header=not part.exists(), index=False, encoding='utf-8')
            n_done += len(df)
            rate = (time.time() - t0) / max(n_done, 1)
            log(f'воркер {k}: {n_done}/{len(ids_all)} | чанк {time.time() - tc:.0f} с | {rate:.2f} с/контур | осталось ~{rate * (len(ids_all) - n_done) / 60:.0f} мин')
        except Exception as e:
            log(f'воркер {k}: чанк {i0 // chunk} НЕ ПРОШЁЛ ({str(e)[:160]})')
            with failed.open('a') as fh:
                fh.write(NL.join(map(str, ids)) + NL)
    log(f'воркер {k}: готово | {(time.time() - t0) / 60:.1f} мин')


def centroids(ids: pd.Series) -> pd.DataFrame:
    import pyogrio
    gg = pyogrio.read_dataframe(PRODUCT, layer='genesis', columns=['id'], where="genesis IN ('undefined','river_shoal')")
    gg = gg[gg['id'].isin(set(ids))]
    c = gg.geometry.centroid
    w = gpd.GeoSeries(c, crs=gg.crs).to_crs(4326)
    return pd.DataFrame({'id': gg['id'].values, 'x': c.x.values, 'y': c.y.values, 'lon': w.x.values.round(5), 'lat': w.y.values.round(5)})


def merge(out_dir: Path, final: Path) -> None:
    d = pd.concat([pd.read_csv(p) for p in sorted(out_dir.glob('part_*.csv'))], ignore_index=True).drop_duplicates('id')
    d['h_dry600'] = d['h_cont'] - d['dry600_p5']
    base = select_ids()
    d = base.merge(d, on='id', how='left').merge(centroids(base['id']), on='id', how='left')
    d.to_csv(final, index=False, encoding='utf-8')
    fails = sum(len(f.read_text().split()) for f in out_dir.glob('failed_*.txt'))
    log(f'→ {final}: {len(d)} контуров ({d["pop"].value_counts().to_dict()}), с h_dry600 {d["h_dry600"].notna().sum()}, '
        f'с c30 {d["c30"].notna().sum()}; failed {fails}')
    print(d.groupby('pop')[['h_dry600', 'water_in_raw', 'c15', 'c30', 'c60', 'c30s', 'ever_water_frac', 'occ_mean',
                            'y21_wet', 'y21_nodata']].median().round(2).T.to_string())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=5)
    ap.add_argument('--chunk', type=int, default=400)
    ap.add_argument('--worker-id', type=int, default=None)
    ap.add_argument('--limit', type=int, default=None, help='проба: не больше N контуров на воркер')
    ap.add_argument('--out-dir', default=str(OUT))
    ap.add_argument('--final', default=str(FINAL))
    ap.add_argument('--merge', action='store_true')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    out_dir, final = Path(a.out_dir), Path(a.final)
    if a.merge:
        merge(out_dir, final)
        return
    if a.dry:
        s = select_ids()
        print(s.groupby('pop').agg(n=('id', 'size'), km2=('area_ha', lambda x: round(x.sum() / 100, 1))))
        return
    if a.worker_id is not None:
        worker(a.worker_id, a.workers, a.chunk, out_dir, a.limit)
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    procs = []
    for k in range(a.workers):
        logf = (out_dir / f'worker_{k}.log').open('a', encoding='utf-8')
        cmd = [sys.executable, '-u', __file__, '--worker-id', str(k), '--workers', str(a.workers), '--chunk', str(a.chunk),
               '--out-dir', str(out_dir)]
        procs.append(subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT))
        time.sleep(3)
    log(f'запущено {len(procs)} воркеров')
    for p in procs:
        p.wait()
    merge(out_dir, final)


if __name__ == '__main__':
    main()
