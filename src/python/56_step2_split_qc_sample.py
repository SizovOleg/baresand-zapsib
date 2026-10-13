"""
56_step2_split_qc_sample.py — выборка сухих частей, отрезанных скриптом 55, для визуальной проверки разреза, и рендер снимков.

Страты (по результату <tag>_split.gpkg): сухие части (step2_rule *_split_dry) — вид ядра part_kind (blob — широкое тело,
far — далеко от воды, mixed) × размер (small 2–5 га, mid 5–20, big > 20) × исходный класс (river/lake); плюс контуры
со снятым классом целиком (*_whole_dry) — страта whole_dry;
по N_PER_STRATUM из каждой непустой страты, случайно (SEED), по всей AOI.
Рендер: qc_thumb_xyz.py; красный контур — сухая часть (цель), оверлей — результат разреза: синий/бирюзовый — отмель,
оставшаяся после разреза, оранжевый — другие сухие части; окно KM_WIN км.
Выход: exports/qc/step2/split_qc_sample_<tag>.csv, снимки exports/qc/step2/thumbs_split/<part_id>_esri.png.
Запуск: python -u python/56_step2_split_qc_sample.py --tag v3 [--n 3] [--render]
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import argparse
import subprocess
from pathlib import Path

import geopandas as gpd
import pandas as pd

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC2 = EXPORTS / 'qc' / 'step2'
PY = Path(r'D:\test\baresand_zapsib\python')
N_PER_STRATUM = 3
SEED = 7
KM_WIN = 3.0
SIZE_BINS = [(2, 5, 'small'), (5, 20, 'mid'), (20, 1e9, 'big')]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='v3', help='тег результата 51 (разрез: baresand_genesis_step2_<tag>_split.gpkg)')
    ap.add_argument('--n', type=int, default=N_PER_STRATUM)
    ap.add_argument('--km', type=float, default=KM_WIN)
    ap.add_argument('--render', action='store_true')
    a = ap.parse_args()
    split_gpkg = EXPORTS / f'baresand_genesis_step2_{a.tag}_split.gpkg'
    parts = gpd.read_file(split_gpkg, where="step2_rule LIKE '%_split_dry'", read_geometry=False)
    parts = parts[['id', 'parent_id', 'split_from', 'part_kind', 'area_ha', 'ero50']].copy()
    parts['size'] = pd.cut(parts['area_ha'], [b[0] for b in SIZE_BINS] + [SIZE_BINS[-1][1]], labels=[b[2] for b in SIZE_BINS], right=False)
    parts['stratum'] = parts['part_kind'] + '_' + parts['size'].astype(str) + '_' + parts['split_from'].str.replace('_shoal', '')
    whole = gpd.read_file(split_gpkg, where="step2_rule LIKE '%_whole_dry'", read_geometry=False)
    whole = whole[['id', 'parent_id', 'split_from', 'area_ha', 'ero50']].assign(part_kind='whole', stratum='whole_dry')
    parts = pd.concat([parts, whole], ignore_index=True)
    print(f'сухих частей: {len(parts):,} | {parts.area_ha.sum() / 100:.1f} км²')
    print(parts.groupby('stratum').agg(n=('id', 'size'), km2=('area_ha', lambda s: round(s.sum() / 100, 1))).to_string())
    smp = parts.groupby('stratum', group_keys=False).apply(lambda d: d.sample(min(len(d), a.n), random_state=SEED))
    smp = smp.sort_values(['stratum', 'area_ha'])
    out_csv = QC2 / f'split_qc_sample_{a.tag}.csv'
    smp.to_csv(out_csv, index=False, encoding='utf-8')
    print(f'\nвыборка: {len(smp)} частей → {out_csv.name}')
    print(smp[['id', 'parent_id', 'split_from', 'part_kind', 'area_ha', 'ero50', 'stratum']].to_string(index=False))
    if a.render:
        thumbs = QC2 / 'thumbs_split'
        thumbs.mkdir(exist_ok=True)
        cmd = [sys.executable, '-u', str(PY / 'qc_thumb_xyz.py'), '--ids', *map(str, smp['id'].astype(int)),
               '--overlay', str(split_gpkg), '--field', 'genesis', '--sample', str(split_gpkg), '--km', str(a.km),
               '--out', str(thumbs)]
        subprocess.run(cmd, check=True)
        print(f'снимки: {thumbs}')


if __name__ == '__main__':
    main()
