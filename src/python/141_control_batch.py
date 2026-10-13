"""
141_control_batch.py - контрольная партия T3: слепая разметка автором 150 контуров итогового слоя v7 (2026-10-06).

План записан до разметки: exports/qc/control_v7/prereg.md (группы g1-g5, страты по размеру, объёмы, зерно 20261007).
g1 v7_agent_techno, g2 v7_agent_small (переводы по двум запускам модели); g3 мелкие «природные», g4 мелкие неоднозначные,
g5 крупные «природные» (оставлены эоловыми). Контуры с меткой автора исключены. Снимки: те, что видели запуски модели
(134: два окна для крупных, 137: одно окно для мелких) и Sentinel-2 лето 2024-2025 (105). Окно и клавиши как в T1/T2
(105/136); группа и прежние решения не показываются, порядок перемешан. Метки пишет owner_click_server.py.
Выход: exports/qc/owner_click/T3/batch.csv, geoms.gpkg, img/, s2/, index.html; exports/qc/control_v7/sample.csv.
Запуск: PYTHONIOENCODING=utf-8 python -u python/141_control_batch.py [--page-only]
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
import numpy as np
import pandas as pd
import pyogrio
from PIL import Image

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
PRODUCT = ROOT / 'exports' / 'final' / 'baresand_genesis_v7.gpkg'
OC = ROOT / 'exports' / 'qc' / 'owner_click'
OUT = OC / 'T3'
CTRL = ROOT / 'exports' / 'qc' / 'control_v7'
LARGE = ROOT / 'exports' / 'qc' / 'aeolian_techno'
SMALL = ROOT / 'exports' / 'qc' / 'aeolian_techno_small'
SEED = 20261007
# группа -> [(нижняя граница га, верхняя граница га, объём; None = сплошь)]
PLAN = {
    'g1_agent_large': [(5, 20, 20), (20, 1e9, None)],
    'g2_agent_small': [(0, 1, 20), (1, 5, 20)],
    'g3_natural_small': [(0, 1, 15), (1, 5, 15)],
    'g4_ambiguous_small': [(0, 1, 12), (1, 5, 12)],
    'g5_natural_large': [(5, 20, 10), (20, 100, 10), (100, 1e9, None)],
}
HINT = ('Контрольная партия: техноген или природный раздув? Раздув у дороги или площадки считаем эоловым. Если в контуре '
        'явно больше одного из двух, жмите его; «смешанный», если обоих заметно. Клавиши 1-8: класс и следующий контур. '
        'Щелчок по снимку: увеличить.')
OLD_HINT = 'Клавиши 1-8: класс и следующий контур. Щелчок по снимку: увеличить.'
CSS = '#imgs figure { max-width:none; } #imgs figure:first-child { flex:2 1 0; }'


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def load_105() -> ModuleType:
    spec = importlib.util.spec_from_file_location('owner_click_batch', ROOT / 'python' / '105_owner_click_batch.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def populations() -> dict[str, pd.DataFrame]:
    v = pyogrio.read_dataframe(PRODUCT, layer='genesis', read_geometry=False,
                               columns=['id', 'genesis', 'area_ha', 'step6_rule', 'step4_rule'])
    own = set(v.loc[v['step6_rule'].isin(['v4_expert', 'v5_mixed_owner', 'v7_owner_techno'])
                    | v['step4_rule'].eq('expert_override'), 'id'])
    for b in ('T1', 'T2'):
        own |= {int(k) for k in json.loads((OC / b / 'labels.json').read_text(encoding='utf-8'))}
    big, sm = pd.read_csv(LARGE / 'merged.csv'), pd.read_csv(SMALL / 'merged.csv')
    vi = v.set_index('id')

    def left_aeolian(ids: pd.Series) -> pd.DataFrame:
        d = vi.loc[[i for i in ids if i in vi.index and i not in own]]
        return d[d['genesis'] == 'aeolian']

    pops = {'g1_agent_large': vi[vi['step6_rule'].eq('v7_agent_techno')],
            'g2_agent_small': vi[vi['step6_rule'].eq('v7_agent_small')],
            'g3_natural_small': left_aeolian(sm.loc[sm['decision'].eq('natural'), 'id']),
            'g4_ambiguous_small': left_aeolian(sm.loc[sm['decision'].eq('owner'), 'id']),
            'g5_natural_large': left_aeolian(big.loc[big['decision'].eq('natural'), 'id'])}
    return {k: d.reset_index()[['id', 'area_ha']] for k, d in pops.items()}


def select() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    rows, strata = [], []
    for g, plan in PLAN.items():
        pop = populations_cache[g]
        for lo, hi, n in plan:
            st = pop[(pop['area_ha'] >= lo) & (pop['area_ha'] < hi)]
            name = f'{g}:{lo:g}-{hi:g}' if hi < 1e9 else f'{g}:>={lo:g}'
            pick = st if n is None or n >= len(st) else st.sample(n, random_state=int(rng.integers(0, 2**31)))
            strata.append({'group': g, 'stratum': name, 'N_h': len(st), 'A_h_ha': round(st['area_ha'].sum(), 4),
                           'n_h': len(pick), 'census': n is None or n >= len(st)})
            rows.append(pick.assign(group=g, stratum=name))
    s = pd.concat(rows, ignore_index=True)
    s = s.sample(frac=1, random_state=SEED).reset_index(drop=True)
    st = pd.DataFrame(strata)
    s = s.merge(st[['stratum', 'N_h', 'A_h_ha']], on='stratum')
    CTRL.mkdir(parents=True, exist_ok=True)
    st.to_csv(CTRL / 'strata.csv', index=False, encoding='utf-8')
    log(f'выборка: {len(s)} контуров; ' + '; '.join(f'{r.stratum} {r.n_h}/{r.N_h}' for r in st.itertuples()))
    return s


def main() -> None:
    global populations_cache
    ap = argparse.ArgumentParser()
    ap.add_argument('--page-only', action='store_true')
    a = ap.parse_args()
    cpu_limit.apply()
    m105 = load_105()
    if a.page_only:
        g = gpd.read_file(OUT / 'geoms.gpkg', layer='batch')
    else:
        if (OUT / 'labels.json').exists():
            raise SystemExit(f'{OUT / "labels.json"} уже есть: партию не пересобираю')
        OUT.mkdir(parents=True, exist_ok=True)
        populations_cache = populations()
        s = select()
        geo = pyogrio.read_dataframe(PRODUCT, layer='genesis', columns=['id', 'genesis'],
                                     where=f"id IN ({','.join(map(str, s['id']))})")
        g = gpd.GeoDataFrame(s.merge(geo, on='id', how='left'), geometry='geometry', crs=geo.crs)
        if g['geometry'].isna().any():
            raise ValueError('нет геометрии у части выборки')
        w = g.geometry.centroid.to_crs(4326)
        g['lon'], g['lat'] = w.x.round(5), w.y.round(5)
        g.to_file(OUT / 'geoms.gpkg', layer='batch', driver='GPKG')
        pd.DataFrame(g.drop(columns='geometry')).to_csv(OUT / 'batch.csv', index=False, encoding='utf-8')
        pd.DataFrame(g.drop(columns='geometry')).to_csv(CTRL / 'sample.csv', index=False, encoding='utf-8')
        (OUT / 'img').mkdir(exist_ok=True)
        for r in g.itertuples():
            src = (LARGE / 'img' / f'{int(r.id)}.png') if r.area_ha >= 5 else (SMALL / 'img' / f'{int(r.id)}.jpg')
            Image.open(src).convert('RGB').save(OUT / 'img' / f'{int(r.id)}_esri.jpg', quality=90)
        m105.render_s2(OUT, g)
    items = []
    for r in g.itertuples():
        i = int(r.id)
        cap = ('Esri: слева обзор, справа крупный план (сенсор и дата в заголовке)' if r.area_ha >= 5
               else 'Esri: окно не меньше 500 м (сенсор и дата в заголовке)')
        pics = [{'src': f'img/{i}_esri.jpg', 'cap': cap}]
        if (OUT / 's2' / f'{i}_s2.png').exists():
            pics.append({'src': f's2/{i}_s2.png', 'cap': 'Sentinel-2, лето 2024-2025 (период маски)'})
        items.append({'id': i, 'area_ha': round(float(r.area_ha), 2), 'lat': float(r.lat), 'lon': float(r.lon), 'imgs': pics})
    html = (m105.PAGE.replace('__NAME__', OUT.name).replace('__ITEMS__', json.dumps(items, ensure_ascii=False))
            .replace('__LABELS__', json.dumps(m105.LABELS, ensure_ascii=False)))
    if OLD_HINT not in html:
        raise ValueError('шаблон 105 изменился')
    html = html.replace(OLD_HINT, HINT).replace('</style>', CSS + '\n</style>', 1)
    (OUT / 'index.html').write_text(html, encoding='utf-8')
    log(f'страница: {OUT / "index.html"}; контуров {len(items)}; без Sentinel-2: {[it["id"] for it in items if len(it["imgs"]) < 2]}')


populations_cache: dict[str, pd.DataFrame] = {}

if __name__ == '__main__':
    main()
