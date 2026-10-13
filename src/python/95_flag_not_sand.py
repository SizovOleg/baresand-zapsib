"""
95_flag_not_sand.py — флаг подозрения на ошибку исходной маски (не песок) в продукте шага 5.

Зачем: по независимой оценке 348 км² маски (ДИ 178–593) не являются оголённым песком — снежники, гари, лишайниковые и
медальонные пустоши, вода. Это долг фазы классификации; каскад генезиса его не чинит, рельеф не различает. Удалять контуры
без собственной проверки нельзя, а пометить — можно: флаг обратим и виден читателю.

Критерий: контур не был голым ни в одну опорную эпоху — bare2000_frac < 0.05 (Landsat 2000) и bare_s2_frac < 0.05 (S2 2017–19).
Раздув, будучи раздувом, голым бывает; снежник и лишайник — никогда.

Область: только классы aeolian и undefined. В техногене «не был голым в 2000» означает площадку, построенную позже, — это
не ошибка маски; у отмелей нулевая обнажённость бывает от воды на опорных датах. На отложенной выборке в отмелях критерий
не пометил ни одного контура, в undefined чистота 67 % при охвате 73 % (8 из 12 помеченных — не песок), в aeolian 2 из 4.
Это ПОДОЗРЕНИЕ, не вердикт: примерно половина–две трети помеченных действительно не песок.

Вход/выход: exports/baresand_genesis_step5_<tag>.gpkg — добавляется поле not_sand_suspect (0/1); запись через временный файл.
Запуск: python -u python/95_flag_not_sand.py --tag v3e
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import os
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
BARE_MAX = 0.05
SCOPE = ('aeolian', 'undefined')


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='v3e')
    a = ap.parse_args()
    t0 = time.time()
    src = EXPORTS / f'baresand_genesis_step5_{a.tag}.gpkg'
    tmp = EXPORTS / f'baresand_genesis_step5_{a.tag}.__tmp__.gpkg'
    log(f'читаю {src.name}...')
    g = gpd.read_file(src, layer='genesis')
    never_bare = (g['bare_s2_frac'].fillna(1) < BARE_MAX) & (g['bare2000_frac'].fillna(1) < BARE_MAX)
    g['not_sand_suspect'] = np.where(g['genesis'].isin(SCOPE) & never_bare, 1, 0).astype('int16')
    L = ['| класс | контуров | км² | помечено контуров | помечено км² | доля площади класса |', '|---|---:|---:|---:|---:|---:|']
    for c in ('shoal', 'river_shoal', 'lake_shoal', 'anthropogenic', 'aeolian', 'undefined'):
        s = g[g['genesis'] == c]
        f = s[s['not_sand_suspect'] == 1]
        L.append(f'| {c} | {len(s)} | {s["area_ha"].sum() / 100:.1f} | {len(f)} | {f["area_ha"].sum() / 100:.1f} | '
                 f'{100 * f["area_ha"].sum() / max(s["area_ha"].sum(), 1e-9):.1f} % |')
    tot = g[g['not_sand_suspect'] == 1]
    L.append(f'| **итого** | {len(g)} | {g["area_ha"].sum() / 100:.1f} | **{len(tot)}** | **{tot["area_ha"].sum() / 100:.1f}** | '
             f'{100 * tot["area_ha"].sum() / g["area_ha"].sum():.1f} % |')
    print('\n'.join(L))
    (EXPORTS / 'qc' / 'target' / f'not_sand_suspect_{a.tag}.md').write_text(
        f'# Флаг not_sand_suspect в {src.name}\n\nКритерий: bare2000_frac < {BARE_MAX} ∧ bare_s2_frac < {BARE_MAX}, только классы {SCOPE}.\n\n'
        + '\n'.join(L) + '\n', encoding='utf-8')
    log('пишу во временный файл...')
    g.to_file(tmp, layer='genesis', driver='GPKG')
    os.replace(tmp, src)
    log(f'{src.name} обновлён: поле not_sand_suspect | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
