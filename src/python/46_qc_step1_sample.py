"""
BareSand — Стратифицированная выборка для визуальной валидации шага 1 v2 агентами.

Страты (что именно проверяем):
  kept      — shoal в v1 И в v2 (подтвердить, что действительно морская отмель)
  added     — не было в v1, стало shoal в v2 (главный источник +км²: пляжи вне 100 м от линии AOI)
  dropped   — было shoal в v1, в v2 нет (должны быть террасы/суходол/реки — подтвердить)
  split     — прибрежные части разрезанных гигантов (качество разреза)
  remainder — остатки гигантов (должны быть НЕ отмель)
  border    — пограничные по расстоянию (dist_sea в [SEA_DIST_MAX, 2×SEA_DIST_MAX]) — калибровка порога
  rejected  — гиганты, отвергнутые как inland (все)

Секторы: KMeans(k=N_SECTORS) по центроидам (EPSG:3576), нумерация с запада на восток.
Выход:
  exports/qc/visual_sample_step1.csv     — выборка с атрибутами
  exports/qc/visual_sample_step1.json    — {sector: {name, center, ids:[...]}} для воркфлоу
  exports/qc/thumbs/<id>_esri.png        — предрендер снимков (через qc_thumb_xyz.py)

Запуск: python -u python/46_qc_step1_sample.py [--per-sector 40] [--sectors 6] [--no-render]
"""
import sys
import json
import argparse
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from sklearn.cluster import KMeans

sys.stdout.reconfigure(encoding='utf-8')

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC = EXPORTS / 'qc'
V2 = EXPORTS / 'baresand_genesis_step1_v2.gpkg'
OUT_CSV = QC / 'visual_sample_step1.csv'
OUT_JSON = QC / 'visual_sample_step1.json'
THUMB = Path(r'D:\test\baresand_zapsib\python\qc_thumb_xyz.py')
SEA_DIST_MAX_M = 400.0
EA_CRS = 'EPSG:3576'
SEED = 42

# доли страт в выборке сектора (нормируются); split/remainder — топ-CAP_FULL по площади, rejected — целиком
STRATA_WEIGHTS = {'added': 0.40, 'kept': 0.20, 'dropped': 0.25, 'border': 0.15}
CAP_FULL = 10


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--per-sector', type=int, default=50)
    ap.add_argument('--sectors', type=int, default=6)
    ap.add_argument('--no-render', action='store_true')
    a = ap.parse_args()
    t0 = time.time()
    rng = np.random.default_rng(SEED)

    g = gpd.read_file(V2)
    coastal = g[g['dist_sea_m'].notna()].copy()
    cen = coastal.geometry.centroid.set_crs(EA_CRS, allow_override=True)
    coastal['x'], coastal['y'] = cen.x, cen.y
    wgs = cen.to_crs('EPSG:4326')
    coastal['lat'], coastal['lon'] = wgs.y.round(4), wgs.x.round(4)

    # страты
    def stratum(r) -> str:
        if r['shoal_rule'] == 'v2_sea_adjacent_split':
            return 'split'
        if r['shoal_rule'] == 'v2_split_remainder':
            return 'remainder'
        if r['shoal_rule'] == 'v2_rejected_inland_giant':
            return 'rejected'
        v1, v2 = r['genesis_v1'] == 'shoal', r['genesis'] == 'shoal'
        if v1 and v2:
            return 'kept'
        if (not v1) and v2:
            return 'added'
        if v1 and not v2:
            return 'dropped'
        if SEA_DIST_MAX_M < r['dist_sea_m'] <= 2 * SEA_DIST_MAX_M:
            return 'border'
        return 'other'
    coastal['stratum'] = coastal.apply(stratum, axis=1)
    pool = coastal[coastal['stratum'] != 'other'].copy()
    print('Пул по стратам:')
    print(pool.groupby('stratum').agg(n=('id', 'size'), km2=('area_km2', 'sum')).round(1).to_string())

    # секторы: только по контурам класса/кандидатам (пул), с запада на восток
    km = KMeans(n_clusters=a.sectors, random_state=SEED, n_init=10).fit(pool[['x', 'y']].values)
    pool['cl'] = km.labels_
    order = pool.groupby('cl')['lon'].mean().sort_values().index.tolist()
    remap = {cl: i + 1 for i, cl in enumerate(order)}
    pool['sector'] = pool['cl'].map(remap)

    # выборка
    picks = []
    for s in range(1, a.sectors + 1):
        ps = pool[pool['sector'] == s]
        # rejected — целиком; split/remainder — топ-CAP_FULL по площади (это ~90% км² класса)
        full = pd.concat([
            ps[ps['stratum'] == 'rejected'],
            ps[ps['stratum'] == 'split'].nlargest(CAP_FULL, 'area_ha'),
            ps[ps['stratum'] == 'remainder'].nlargest(CAP_FULL, 'area_ha'),
        ])
        picks.append(full)
        budget = max(a.per_sector - len(full), int(a.per_sector * 0.6))
        for st, w in STRATA_WEIGHTS.items():
            cand = ps[ps['stratum'] == st]
            n = min(len(cand), max(1, int(round(budget * w)))) if len(cand) else 0
            if n:
                # крупные важнее: половина — топ по площади, половина — случайно
                top = cand.nlargest(n // 2, 'area_ha')
                rest = cand.drop(top.index)
                rnd = rest.sample(n=min(len(rest), n - len(top)), random_state=int(rng.integers(1e9))) if len(rest) else rest
                picks.append(pd.concat([top, rnd]))
    sample = pd.concat(picks).drop_duplicates('id')
    cols = ['id', 'sector', 'stratum', 'genesis_v1', 'genesis', 'shoal_rule', 'parent_id',
            'area_ha', 'dist_sea_m', 'hnd_min', 'gsw_occ_max', 'dist_aoi_boundary_m', 'lat', 'lon']
    sample[cols].sort_values(['sector', 'stratum', 'area_ha'], ascending=[True, True, False]) \
        .to_csv(OUT_CSV, index=False, encoding='utf-8')

    sectors = {}
    for s in range(1, a.sectors + 1):
        ss = sample[sample['sector'] == s]
        if len(ss) == 0:
            continue
        sectors[str(s)] = {
            'name': f'S{s}',
            'center_lat': round(float(ss['lat'].mean()), 3),
            'center_lon': round(float(ss['lon'].mean()), 3),
            'lat_range': [round(float(ss['lat'].min()), 2), round(float(ss['lat'].max()), 2)],
            'lon_range': [round(float(ss['lon'].min()), 2), round(float(ss['lon'].max()), 2)],
            'n': int(len(ss)),
            'by_stratum': ss['stratum'].value_counts().to_dict(),
            'ids': [int(i) for i in ss['id'].tolist()],
        }
    OUT_JSON.write_text(json.dumps(sectors, ensure_ascii=False, indent=1), encoding='utf-8')

    print(f'\nВыборка: {len(sample):,} контуров в {len(sectors)} секторах')
    for s, d in sectors.items():
        print(f"  S{s}: {d['n']:3d} | {d['center_lat']}N {d['center_lon']}E | {d['by_stratum']}")
    print(f'Сохранено: {OUT_CSV}\n           {OUT_JSON}')

    if not a.no_render:
        thumbs_dir = QC / 'thumbs'
        ids = [int(i) for i in sample['id'].tolist() if not (thumbs_dir / f'{int(i)}_esri.png').exists()]
        print(f'\nПредрендер {len(ids)} снимков (Esri XYZ; уже готовых: {len(sample) - len(ids)})...', flush=True)
        # порциями, чтобы не держать всё в одном процессе
        for i in range(0, len(ids), 40):
            chunk = ids[i:i + 40]
            r = subprocess.run([sys.executable, str(THUMB), '--ids', *map(str, chunk)],
                               capture_output=True, text=True, encoding='utf-8')
            try:
                res = json.loads(r.stdout)
                errs = [x for x in res if 'error' in x]
            except Exception:  # noqa: BLE001
                errs = [{'id': 'batch', 'error': r.stderr[-300:]}]
            print(f'  {min(i+40, len(ids))}/{len(ids)} готово; ошибок: {len(errs)}', flush=True)
            for e in errs[:5]:
                print('   ', e)
    print(f'Время: {(time.time()-t0)/60:.1f} мин')


if __name__ == '__main__':
    main()
