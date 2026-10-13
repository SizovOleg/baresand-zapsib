"""
112_tail_labels.py - сводная таблица меток для переноса на хвост (2026-09-27).

Уровни (при нескольких метках одного контура берётся верхний по порядку):
  owner: окно проверки owner_gold (последняя партия) > expert_big > owner30 (укрупнённо) > undef_review aeolian18/river18;
  agent: озёрный проход fit/audit (итог дешифровщика и скептика, спор снят супервайзером) и пилот big (итог двух-трёх прочтений).
Классы: fine (lake_shoal, river_shoal, shoal, aeolian, anthropogenic, not_sand) и coarse (shoal = отмель любого типа).
Неклассовые итоги (смешанный, спорный, не понять, нечитаемо) в обучение не идут.
Флаг o3_random: 40 случайных контуров непросмотренного хвоста из O3 (undef_S, undef_L), единственная несмещённая проверка на хвосте.
Выход: exports/qc/alphaearth/labels.csv. Запуск: PYTHONIOENCODING=utf-8 python -u python/112_tail_labels.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
QC = ROOT / 'exports' / 'qc'
OUT = QC / 'alphaearth' / 'labels.csv'
FINE = {'lake_shoal', 'river_shoal', 'shoal', 'aeolian', 'anthropogenic', 'not_sand'}
RU = {'отмель': 'shoal_any', 'отмель речная': 'river_shoal', 'отмель озёрная': 'lake_shoal', 'раздув': 'aeolian',
      'эоловый': 'aeolian', 'техноген': 'anthropogenic', 'не песок': 'not_sand'}
COARSE = {'lake_shoal': 'shoal', 'river_shoal': 'shoal', 'shoal': 'shoal', 'shoal_any': 'shoal', 'aeolian': 'aeolian',
          'anthropogenic': 'anthropogenic', 'not_sand': 'not_sand'}


def main() -> None:
    parts = []
    gold = pd.read_csv(QC / 'owner_click' / 'owner_gold.csv')
    num = gold['batch'].astype(str).str.extract(r'(\d+)')[0].astype(float)
    gold = gold.assign(n=num).sort_values('n').groupby('id').last().reset_index()
    parts.append(pd.DataFrame({'id': gold['id'], 'label': gold['label'], 'src': 'owner_click:' + gold['batch'], 'tier': 'owner', 'rank': 0,
                               'o3_random': (gold['batch'] == 'O3') & gold['group'].isin(['undef_S', 'undef_L'])}))
    e = pd.read_csv(QC / 'lake' / 'big' / 'expert_big.csv')
    parts.append(pd.DataFrame({'id': e['id'], 'label': e['verdict'], 'src': 'expert_big', 'tier': 'owner', 'rank': 1}))
    o = pd.read_csv(QC / 'lake' / 'owner30' / 'owner30_compare.csv')
    parts.append(pd.DataFrame({'id': o['id'], 'label': o['owner'].map(RU), 'src': 'owner30', 'tier': 'owner', 'rank': 2}))
    for p, s in (('undef_review/aeolian18/dem.shp', 'aeolian18'), ('undef_review/river18/river18.shp', 'river18')):
        u = gpd.read_file(QC / p, ignore_geometry=True)
        parts.append(pd.DataFrame({'id': u['id'], 'label': u['verdict'].map(RU), 'src': s, 'tier': 'owner', 'rank': 3}))
    m = pd.read_csv(QC / 'disputed' / 'multireader.csv')
    m = m[m['source'].isin(['fit', 'audit', 'big'])]
    parts.append(pd.DataFrame({'id': m['id'], 'label': m['final'], 'src': 'agent:' + m['source'], 'tier': 'agent', 'rank': 4}))
    a = pd.concat(parts, ignore_index=True)
    a['o3_random'] = a['o3_random'].fillna(False).astype(bool)
    a['coarse'] = a['label'].map(COARSE)
    a = a[a['coarse'].notna()]   # неклассовые итоги не идут в обучение
    a['fine'] = np.where(a['label'].isin(FINE), a['label'], None)
    lab = a.sort_values('rank').groupby('id').first().reset_index().drop(columns='rank')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lab.to_csv(OUT, index=False, encoding='utf-8')
    print(f'меток: {len(lab)}; по уровню {lab["tier"].value_counts().to_dict()}')
    print(pd.crosstab(lab['coarse'], lab['tier']).to_string())
    print(f'o3_random: {int(lab["o3_random"].sum())}')
    print(f'-> {OUT}')


if __name__ == '__main__':
    main()
