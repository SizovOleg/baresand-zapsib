"""
137_small_techno_candidates.py - мелкие кандидаты «техноген в эоловых» (меньше 5 га) и снимки для слепой разметки (2026-10-06).

Продолжение 134 по решению владельца 2026-10-06 («такое нельзя так оставлять чисто визуально, надо внести»): на карте
остаются полосы вдоль дорог и обрывки площадок, отнесённые к эоловым. Отбор как в 134 (эоловые v6 у техногенного контура
или построенной дороги OSM ближе 20 м, без меток владельца), но площадь меньше 5 га.
Снимок на контур: одно окно Esri World Imagery (max(2.5 охвата, 500 м), не меньше 900 px), только красная граница цели,
масштаб, сенсор и дата снимка. Одно окно вместо двух: у мелких контуров крупный план уже содержит окружение, а тайлов
в 8-10 раз меньше (241 снимок 134 шёл 41 мин).
Выход: exports/qc/aeolian_techno_small/img/<id>.jpg, batch.csv, chunks/chunk_<k>.txt (по CHUNK id, порядок перемешан).
Запуск: PYTHONIOENCODING=utf-8 python -u python/137_small_techno_candidates.py [--workers 12]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import importlib.util
import math
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import ModuleType

import geopandas as gpd
import shapely

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
OUT = ROOT / 'exports' / 'qc' / 'aeolian_techno_small'
MAX_HA, CHUNK, SEED = 5.0, 40, 20261006
MIN_SIDE_M, PAD = 500.0, 2.5


_M134: ModuleType | None = None


def load_134() -> ModuleType:
    """Модуль 134 (отбор, окно Esri); один раз на процесс."""
    global _M134
    if _M134 is None:
        spec = importlib.util.spec_from_file_location('techno134', ROOT / 'python' / '134_aeolian_techno_candidates.py')
        _M134 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_M134)
    return _M134


def render(args: tuple) -> str:
    cid, wkb, lat, lon = args
    out = OUT / 'img' / f'{cid}.jpg'
    if out.exists():
        return str(out)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    m = load_134()
    try:
        g = shapely.from_wkb(wkb)
        g3857 = gpd.GeoSeries([g], crs=3576).to_crs(3857).iloc[0]
        k = 1.0 / math.cos(math.radians(lat))
        b = g3857.bounds
        span = max(b[2] - b[0], b[3] - b[1]) / k            # истинные метры
        fig, ax = plt.subplots(1, 1, figsize=(9, 9.4))
        meta = m.panel(ax, g3857, lat, lon, max(span * PAD, MIN_SIDE_M))
        fig.suptitle(f'контур {cid}: {lat:.4f}° с. ш., {lon:.4f}° в. д.; снимок {meta}', fontsize=10)
        fig.tight_layout()
        fig.savefig(out, dpi=100, pil_kwargs={'quality': 88})
        plt.close(fig)
        return str(out)
    except Exception:
        traceback.print_exc()
        plt.close('all')
        return f'ОШИБКА {cid}'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=12)
    ap.add_argument('--cores', type=int, default=0, help='ядер (разрешение владельца 2026-10-06: 12); 0 = cpu_limit.apply()')
    a = ap.parse_args()
    if a.cores:
        print(f'ядер: {cpu_limit.apply_cores(a.cores)}', flush=True)
    else:
        cpu_limit.apply()
    t0 = time.time()
    (OUT / 'img').mkdir(parents=True, exist_ok=True)
    (OUT / 'chunks').mkdir(exist_ok=True)
    m = load_134()
    m.MIN_HA = 0.0
    c = m.candidates()
    c = c[c['area_ha'] < MAX_HA].reset_index(drop=True)
    print(f'кандидатов меньше {MAX_HA} га: {len(c)}, {c.area_ha.sum() / 100:.2f} км2; у техногенного {int(c.near_anthro.sum())}, '
          f'у дороги {int(c.near_road.sum())}', flush=True)
    c.drop(columns=['geometry']).to_csv(OUT / 'batch.csv', index=False, encoding='utf-8')
    order = c['id'].sample(frac=1, random_state=SEED).tolist()
    for k in range(0, len(order), CHUNK):
        (OUT / 'chunks' / f'chunk_{k // CHUNK + 1}.txt').write_text('\n'.join(str(i) for i in order[k:k + CHUNK]) + '\n',
                                                                     encoding='utf-8')
    print(f'кусков: {math.ceil(len(order) / CHUNK)}', flush=True)
    tasks = [(int(r.id), shapely.to_wkb(r.geometry), float(r.lat), float(r.lon)) for r in c.itertuples()]
    done = bad = 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(render, tasks, chunksize=4):
            done += 1
            bad += r.startswith('ОШИБКА')
            if done % 200 == 0:
                print(f'[{time.strftime("%H:%M:%S")}] снимков {done}/{len(tasks)}, ошибок {bad}', flush=True)
    print(f'ГОТОВО: снимков {done - bad}, ошибок {bad} | {(time.time() - t0) / 60:.1f} мин', flush=True)


if __name__ == '__main__':
    main()
