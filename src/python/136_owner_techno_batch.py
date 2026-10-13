"""
136_owner_techno_batch.py - партия T1 для окна проверки владельцем: кандидаты «техноген в эоловых» (2026-10-05).

Состав (exports/qc/aeolian_techno/prereg.md, п. 3 и 4):
  tech_owner  - контуры, где два слепых читателя-агента разошлись или сказали «смешанный» / «не песок» / «не понять»
                (135, decision = owner): решение за владельцем;
  tech_spot_t - 15 случайных из «оба читателя: техноген» (spotcheck.csv): выборочная проверка п. 4;
  tech_spot_n - 5 случайных из «оба читателя: природный».
Группа, мнения агентов и класс карты на странице не показываются, порядок перемешан: метки владельца остаются слепыми.
Снимки: рендер 134 (Esri, обзор и крупный план, сенсор и дата в заголовке; то же видели агенты) и Sentinel-2, медиана
июль-август 2024-2025 (период маски, render_s2 из 105). Страница и клавиши 1-8 из 105, метки на диск пишет
owner_click_server.py (POST /api/save/T1 -> T1/labels.json).
Выход: exports/qc/owner_click/T1/batch.csv, geoms.gpkg, img/, s2/, index.html.
Мелкие кандидаты (137, 2026-10-06): --source small --name T2. Только выборочная проверка prereg п. 4 мелких
(exports/qc/aeolian_techno_small/prereg.md): small_spot_t 15 и small_spot_n 5 из spotcheck.csv; списка спорных
владельцу нет (п. 3). Снимок Esri одно окно 137.
Запуск: PYTHONIOENCODING=utf-8 python -u python/136_owner_techno_batch.py [--name T1] [--source large|small] [--page-only]
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import importlib.util
import json
import time
from pathlib import Path
from types import ModuleType

import geopandas as gpd
import pandas as pd
import pyogrio
from PIL import Image

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
SRC = ROOT / 'exports' / 'qc' / 'aeolian_techno'
PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v6.gpkg'
OUT_ROOT = ROOT / 'exports' / 'qc' / 'owner_click'
SEED = 20261005
OLD_HINT = 'Клавиши 1-8: класс и следующий контур. Щелчок по снимку: увеличить.'
HINT = ('Вопрос партии: техноген или природный раздув? Раздув у дороги или площадки считаем эоловым (если не согласны, '
        'напишите в заметке). Если в контуре явно больше одного из двух, жмите его; «смешанный» оставит контур эоловым. '
        'Клавиши 1-8: класс и следующий контур. Щелчок по снимку: увеличить.')
# рендер 134 широкий (два окна, 1600 x 830), Sentinel-2 квадратный: ширины пропорциональны, высоты равны
CSS = '#imgs figure { max-width:none; } #imgs figure:first-child { flex:1.93 1 0; }'
# источники партий: папка разметки агентов, префикс групп, есть ли список спорных владельцу, снимок Esri, подпись, стиль
SOURCES = {
    'large': {'dir': SRC, 'prefix': 'tech', 'owner_list': True, 'img': '{i}.png', 'seed': 20261005,
              'cap': 'Esri: слева обзор, справа крупный план (сенсор и дата снимка в заголовке)', 'css': CSS},
    'small': {'dir': ROOT / 'exports' / 'qc' / 'aeolian_techno_small', 'prefix': 'small', 'owner_list': False,
              'img': '{i}.jpg', 'seed': 20261006, 'cap': 'Esri: окно не меньше 500 м (сенсор и дата снимка в заголовке)',
              'css': '#imgs figure { max-width:none; }'},
}


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def load_105() -> ModuleType:
    """Модуль 105 (шаблон страницы, классы кнопок, render_s2); имя файла начинается с цифры, поэтому через importlib."""
    spec = importlib.util.spec_from_file_location('owner_click_batch', ROOT / 'python' / '105_owner_click_batch.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def select(src: dict) -> gpd.GeoDataFrame:
    m = pd.read_csv(src['dir'] / 'merged.csv')
    sp = pd.read_csv(src['dir'] / 'spotcheck.csv', usecols=['id', 'set'])
    p = src['prefix']
    own = (m.loc[m['decision'] == 'owner', ['id']] if src['owner_list'] else m.iloc[:0][['id']]).assign(group=f'{p}_owner')
    spot = sp.assign(group=sp['set'].map({'techno': f'{p}_spot_t', 'natural': f'{p}_spot_n'}))[['id', 'group']]
    b = pd.concat([own, spot], ignore_index=True)
    if b['id'].duplicated().any() or b['group'].isna().any():
        raise ValueError(f'повторы или неизвестная группа: {b[b["id"].duplicated() | b["group"].isna()].to_dict("records")}')
    # совокупности групп (для отчёта 107: N_stratum, A_stratum_km2)
    pop = {f'{p}_owner': m['decision'].eq('owner'), f'{p}_spot_t': m['decision'].eq('anthropogenic'),
           f'{p}_spot_n': m['decision'].eq('natural')}
    b['stratum'] = b['group']
    b['N_stratum'] = b['group'].map({g: int(x.sum()) for g, x in pop.items()})
    b['A_stratum_km2'] = b['group'].map({g: round(m.loc[x, 'area_ha'].sum() / 100, 3) for g, x in pop.items()})
    b = b.sample(frac=1, random_state=src['seed']).reset_index(drop=True)
    geo = pyogrio.read_dataframe(PRODUCT, layer='genesis', columns=['id', 'genesis', 'area_ha'],
                                 where=f"id IN ({','.join(map(str, b['id']))})")
    miss = sorted(set(b['id']) - set(geo['id']))
    if miss:
        raise ValueError(f'нет в продукте v6: {miss}')
    if not geo['genesis'].eq('aeolian').all():
        raise ValueError(f'не эоловые в v6: {geo.loc[~geo["genesis"].eq("aeolian"), ["id", "genesis"]].to_dict("records")}')
    s = gpd.GeoDataFrame(b.merge(geo, on='id', how='left'), geometry='geometry', crs=geo.crs)
    w = s.geometry.centroid.to_crs(4326)
    s['lon'], s['lat'] = w.x.round(5), w.y.round(5)
    log(f'партия: {len(s)} контуров, {s["area_ha"].sum() / 100:.2f} км2; группы {s["group"].value_counts().to_dict()}')
    return s


def esri_images(out: Path, s: gpd.GeoDataFrame, src: dict) -> None:
    """Снимки разметки агентов (134 или 137) в JPEG (PNG по 2 МБ не нужны: страница только для просмотра)."""
    (out / 'img').mkdir(parents=True, exist_ok=True)
    for i in s['id']:
        dst = out / 'img' / f'{int(i)}_esri.jpg'
        if not dst.exists():
            Image.open(src['dir'] / 'img' / src['img'].format(i=int(i))).convert('RGB').save(dst, quality=90)


def build_page(out: Path, s: gpd.GeoDataFrame, m105: ModuleType, src: dict) -> None:
    items = []
    for r in s.itertuples():
        i = int(r.id)
        pics = [{'src': f'img/{i}_esri.jpg', 'cap': src['cap']}]
        if (out / 's2' / f'{i}_s2.png').exists():
            pics.append({'src': f's2/{i}_s2.png', 'cap': 'Sentinel-2, лето 2024-2025 (период маски)'})
        items.append({'id': i, 'area_ha': round(float(r.area_ha), 2), 'lat': float(r.lat), 'lon': float(r.lon), 'imgs': pics})
    html = (m105.PAGE.replace('__NAME__', out.name).replace('__ITEMS__', json.dumps(items, ensure_ascii=False))
            .replace('__LABELS__', json.dumps(m105.LABELS, ensure_ascii=False)))
    if OLD_HINT not in html or '</style>' not in html:
        raise ValueError('шаблон страницы 105 изменился: подсказка или стиль не найдены')
    html = html.replace(OLD_HINT, HINT).replace('</style>', src['css'] + '\n</style>', 1)
    (out / 'index.html').write_text(html, encoding='utf-8')
    no_s2 = [it['id'] for it in items if len(it['imgs']) < 2]
    log(f'страница: {out / "index.html"}; контуров {len(items)}; без Sentinel-2: {no_s2}')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', default='T1')
    ap.add_argument('--page-only', action='store_true', help='только пересобрать страницу из готовой партии')
    ap.add_argument('--source', choices=sorted(SOURCES), default='large')
    a = ap.parse_args()
    cpu_limit.apply()
    t0 = time.time()
    out = OUT_ROOT / a.name
    src = SOURCES[a.source]
    m105 = load_105()
    if a.page_only:
        s = gpd.read_file(out / 'geoms.gpkg', layer='batch')
    else:
        if (out / 'labels.json').exists():
            raise SystemExit(f'{out / "labels.json"} уже есть: партию не пересобираю (метки владельца); для страницы --page-only')
        out.mkdir(parents=True, exist_ok=True)
        s = select(src)
        s.to_file(out / 'geoms.gpkg', layer='batch', driver='GPKG')
        pd.DataFrame(s.drop(columns='geometry')).to_csv(out / 'batch.csv', index=False, encoding='utf-8')
        esri_images(out, s, src)
        m105.render_s2(out, s)
    build_page(out, s, m105, src)
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
