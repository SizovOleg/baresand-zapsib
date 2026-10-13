"""
87_undef_review_package.py — пакет контуров класса «неопределённый» для просмотра экспертом глазами.

Зачем: полнота эолового класса упирается в контуры, ушедшие в undefined (валидация 2026-09-08: 18 контуров выборки,
141 км² по оценке, PA 92.8 % вместо потолка 98.5 %). Существующие плановые улики их не отделяют от речных отмелей,
сидящих в том же undefined: e_score внутри класса работает даже в обратную сторону. Разделить их может только человек
или новая улика. Скрипт собирает такие контуры в один пакет: геометрия, признаки, готовая миниатюра, форма для вердикта.

Задача эксперту не «назвать класс» (для выборки валидации он уже назван агентами и проверен), а СФОРМУЛИРОВАТЬ ПРИЗНАК:
что на снимке отличает эти контуры от речных отмелей. Ответ становится кандидатом в правило шага 4.

Вход:  exports/baresand_genesis_step4_v2e.gpkg (продукт), exports/qc/final/verdicts_final.csv (вердикты валидации),
       exports/qc/final/thumbs_final/<id>_esri.png (готовые миниатюры выборки).
Выход: exports/qc/undef_review/<tag>/ — geoms.gpkg (слой review), review.csv, thumbs/, README_REVIEW.md
Запуск: python -u python/87_undef_review_package.py --tag aeolian18
        python -u python/87_undef_review_package.py --tag yamal --source map --region yamal --n 60 --render
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
EXPORTS = ROOT / 'exports'
QCF = EXPORTS / 'qc' / 'final'
PRODUCT = EXPORTS / 'baresand_genesis_step4_v2e.gpkg'
OUTROOT = EXPORTS / 'qc' / 'undef_review'
DRIVER = ROOT / 'python' / 'qc_render_parallel.py'
SEED = 20260908

# признаки, которые эксперт видит рядом со снимком (без метки карты — она тут и так известна: undefined)
SHOW = ['id', 'area_ha', 'step4_rule', 'e_score', 'dist_water_m', 'dist_channel_m', 'dist_sea_m', 'nearest_type',
        'flood_frac0', 'gsw_seas_max', 'bare_s2_frac', 'bare2000_frac', 'ndvi_s2_mean', 'loss_frac',
        'n_nb_2km', 'dist_big_m', 'elong', 'lat', 'lon']


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def pick_from_validation(ref: str = 'aeolian', map_cls: str = 'undefined') -> list:
    """Контуры валидационной выборки: карта дала map_cls, дешифрирование — ref (по умолчанию 18 эоловых в undefined)."""
    v = pd.read_csv(QCF / 'verdicts_final.csv')
    m = (v['genesis'] == map_cls) & (v['ref'] == ref)
    return v.loc[m, 'id'].astype(int).tolist()


def pick_from_map(region: str, n: int, rule: str | None) -> list:
    """Случайная выборка undefined с карты (для регионального разбора)."""
    g = gpd.read_file(PRODUCT, layer='genesis', columns=['id', 'genesis', 'step4_rule', 'area_ha'])
    g = g[g['genesis'] == 'undefined']
    if rule:
        g = g[g['step4_rule'].astype(str).str.contains(rule, na=False)]
    c = g.geometry.centroid.to_crs(4326)
    g = g.assign(lon=c.x, lat=c.y)
    if region == 'yamal':
        g = g[(g['lat'].between(66.5, 73.5)) & (g['lon'].between(66.0, 73.5))]
    return g.sample(min(n, len(g)), random_state=SEED)['id'].astype(int).tolist()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True, help='имя пакета (папка внутри exports/qc/undef_review)')
    ap.add_argument('--source', default='validation', choices=['validation', 'map'])
    ap.add_argument('--ref', default='aeolian', help='истинный класс по агентам (для --source validation)')
    ap.add_argument('--map-cls', default='undefined', help='класс карты (для --source validation)')
    ap.add_argument('--region', default=None, choices=[None, 'yamal'])
    ap.add_argument('--rule', default=None, help='фильтр по step4_rule (подстрока), только для --source map')
    ap.add_argument('--n', type=int, default=60)
    ap.add_argument('--render', action='store_true', help='рисовать миниатюры (иначе брать готовые из thumbs_final)')
    ap.add_argument('--workers', type=int, default=6)
    a = ap.parse_args()
    t0 = time.time()

    ids = pick_from_validation(a.ref, a.map_cls) if a.source == 'validation' else pick_from_map(a.region, a.n, a.rule)
    log(f'контуров в пакете: {len(ids)}')

    out = OUTROOT / a.tag
    thumbs = out / 'thumbs'
    thumbs.mkdir(parents=True, exist_ok=True)

    log('читаю геометрию и признаки продукта...')
    g = gpd.read_file(PRODUCT, layer='genesis', where=f"id IN ({','.join(map(str, ids))})")
    c = g.geometry.centroid.to_crs(4326)
    g['lon'], g['lat'] = c.x, c.y
    cols = [c for c in SHOW if c in g.columns]
    log(f'найдено {len(g)} контуров, {g["area_ha"].sum():.1f} га')

    # форма вердикта: эксперт заполняет прямо в атрибутах слоя
    g['verdict'] = ''       # aeolian / river_shoal / lake_shoal / shoal / anthropogenic / not_sand / mixed
    g['sign'] = ''          # ГЛАВНОЕ: по какому признаку видно
    g['note'] = ''
    keep = cols + ['verdict', 'sign', 'note', 'geometry']
    g[keep].to_file(out / 'geoms.gpkg', layer='review', driver='GPKG')
    shp = g[keep].copy()
    shp.columns = [c[:10] for c in shp.columns]
    shp.to_file(out / f'{a.tag}.shp', driver='ESRI Shapefile', encoding='utf-8')
    df = pd.DataFrame(g[cols + ['verdict', 'sign', 'note']])
    df.to_csv(out / 'review.csv', index=False, encoding='utf-8')
    log(f'→ {out / "geoms.gpkg"} (слой review), review.csv')

    # миниатюры: либо переносим готовые, либо рисуем
    if a.render:
        sec = {'1': {'name': a.tag, 'ids': [int(i) for i in g['id']]}}
        (out / '_render.json').write_text(json.dumps(sec), encoding='utf-8')
        base = [sys.executable, '-u', str(DRIVER), '--workers', str(a.workers), '--batch', '12', '--samples', str(out / '_render.json'),
                '--overlay', str(QCF / 'overlay_none.gpkg'), '--field', 'genesis', '--sample', str(out / 'geoms.gpkg')]
        subprocess.run(base + ['--out', str(thumbs)], check=False)
        small = [int(i) for i, ar in zip(g['id'], g['area_ha']) if ar < 1]
        if small:
            (out / '_render_zoom.json').write_text(json.dumps({'1': {'name': a.tag, 'ids': small}}), encoding='utf-8')
            zoom = [str(out / '_render_zoom.json') if x == str(out / '_render.json') else x for x in base]
            subprocess.run(zoom + ['--out', str(out / 'thumbs_zoom'), '--km', '0.8'], check=False)
    else:
        n = 0
        for i in ids:
            src = QCF / 'thumbs_final' / f'{i}_esri.png'
            if src.exists():
                shutil.copy2(src, thumbs / f'{i}_esri.png')
                n += 1
        log(f'перенесено готовых миниатюр: {n} из {len(ids)}')

    readme = out / 'README_REVIEW.md'
    readme.write_text(f"""# Пакет на просмотр глазами: `{a.tag}`

Контуров: {len(g)}. Все — класс **неопределённый** на итоговой карте.

## Что нужно

Не столько вердикт, сколько **признак**. По этим контурам правила шага 4 не смогли решить, эоловая это форма или отмель,
и плановые улики (расстояние до русла, доля заливаемости, кластерность) их не разделяют. Нужен твой критерий: что именно
на снимке говорит «раздув», а что — «отмель».

## Как заполнять

Открыть `geoms.gpkg` (слой `review`) в QGIS поверх снимка, снимки продублированы в `thumbs/<id>_esri.png`.
Три пустых поля в таблице атрибутов:

| поле | что писать |
|---|---|
| `verdict` | `aeolian`, `river_shoal`, `lake_shoal`, `shoal`, `anthropogenic`, `not_sand`, `mixed` |
| `sign` | **главное поле**: по какому признаку видно. Коротко, но конкретно: «лопастной край + языки по ветру», «повторяет изгиб русла», «на уровне воды», «выше бровки», «серповидные гривки», «в поле таких же пятен» |
| `note` | всё остальное, свободно |

Сохранить слой под любым именем в этой же папке и сказать мне — перенесу вердикты и проверю, какие из названных
признаков вычислимы автоматически.

## Признаки в таблице

`step4_rule` — какое правило отправило контур в неопределённые; `e_score` — сколько эоловых улик набралось (0–5);
`dist_water_m` / `dist_channel_m` / `dist_sea_m` — до воды, до русла, до моря; `nearest_type` — что за водоём рядом;
`flood_frac0` — доля площади, заливавшаяся за 37 лет; `gsw_seas_max` — сезонность воды; `bare_s2_frac` / `bare2000_frac` —
был ли голым на подложке 2017–19 и в 2000; `ndvi_s2_mean` — зарос или нет; `n_nb_2km` — соседних контуров в 2 км;
`dist_big_m` — до ближайшего массива ≥ 5 га; `elong` — вытянутость.

Сформировано {time.strftime('%Y-%m-%d %H:%M')}, скрипт `python/87_undef_review_package.py`.
""", encoding='utf-8')
    log(f'→ {readme}')
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
