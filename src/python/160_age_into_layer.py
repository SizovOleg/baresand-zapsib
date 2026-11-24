"""
160_age_into_layer.py - запись дополнительно определённого возраста поверхности в итоговые слои v7b (2026-11-20).

Возраст поверхности техногенных контуров (age2000) рассчитан в 133 по доле оголённой поверхности в 2000 г.
(bare2000_frac, шаг 3, скрипт 66, листы Global Forest Change 60-70° с. ш.). У 1 851 контура (севернее 70° с. ш. и части
разделённых смешанных контуров) значения не было (na). 159_age_north70.py определил его по тем же данным в Earth Engine
(exports/qc/article_v3_extra/age_north70_na_contours.csv). Этот скрипт переносит результат 159 в итоговые слои:
  - exports/final/baresand_genesis_v7b.gpkg, слой genesis: поля bare2000_frac и age2000 у 1 851 контура;
  - exports/final/baresand_anthro_cadastre_v7b.gpkg, слои anthro_in, anthro_exceed, anthro_noallot: поле age2000 частей
    и объектов тех же контуров.
Геометрия, классы и остальные поля не меняются: запись идёт SQL-обновлением названных полей в одной транзакции на файл,
контрольная сумма остальных полей и геометрии до и после записи обязана совпасть, иначе транзакция откатывается. Поле
hansen_covered не меняется: каскад шага 3 работал у этих контуров без данных Global Forest Change.
Проверки до записи: набор id со значением na в слое равен набору id таблицы 159, площади совпадают, возраст таблицы
воспроизводится порогами 133. Проверки после записи: число контуров и площади по возрасту равны таблицам 159
(age_north70_S11_5.csv и age_north70_S11_6.csv, строки «после»); возраст частей в слоях групп равен возрасту контура.

Ассеты Earth Engine интерактивной карты (anthro_in, anthro_exceed, anthro_noallot) обновляются на стороне сервера:
  --gee-start  ставит задачи экспорта копий ассетов с заменённым полем age2000 (<слой>_age);
  --gee-swap   после завершения задач сверяет копии с прежними ассетами и таблицей 159 (то же число объектов, na
               заменены возрастом своего контура, остальное без изменений), переименовывает прежние ассеты в
               <слой>_v7b_noage, копии в <слой> и переносит на них права доступа прежних ассетов.
После записи: 140_assemble_final.py --layers exports/final/baresand_anthro_cadastre_v7b.gpkg --shp-dir
exports/final/anthro_shp_v7b (шейпы) и 155_app_stats.py --write-app (статистика интерактивной карты).

Запуск: PYTHONIOENCODING=utf-8 python -u python/160_age_into_layer.py [--apply] | --check | --gee-start | --gee-swap
Без ключей: проверки до записи, файлы не меняются. --check: проверки после записи. Отчёт: exports/qc/age_into_layer/.
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(r'D:\test\baresand_zapsib')
FINAL = ROOT / 'exports' / 'final'
PRODUCT = FINAL / 'baresand_genesis_v7b.gpkg'
LAYERS = FINAL / 'baresand_anthro_cadastre_v7b.gpkg'
SRC = ROOT / 'exports' / 'qc' / 'article_v3_extra'
RECALC = SRC / 'age_north70_na_contours.csv'          # 159: id, age2000_new, bare2000_gee, area_ha
EXPECT_CLASS = SRC / 'age_north70_S11_5.csv'          # 159: класс по возрасту до и после
EXPECT_GROUPS = SRC / 'age_north70_S11_6.csv'         # 159: превышение отвода и без отвода по возрасту до и после
OUT = ROOT / 'exports' / 'qc' / 'age_into_layer'
ANTHRO_LAYERS = ('anthro_in', 'anthro_exceed', 'anthro_noallot')
AGE_ORDER = ('new', 'mid', 'old', 'na')
TOL_KM2 = 1e-6                                        # допуск сверки площадей с таблицами 159
PROJECT = 'nodal-thunder-481307-u1'
FOLDER = f'projects/{PROJECT}/assets/ZapSib_baresands/app'
NEW_SUFFIX, OLD_SUFFIX = '_age', '_v7b_noage'
MIN_PART_M2 = 900.0                                   # как в 150: части anthro_in меньше 900 м² в ассет не загружались
TOL_GEE_HA = 0.01                                     # допуск сверки сумм area_ha ассета и слоя (округление float)


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def age_rule() -> Callable[[pd.Series], pd.Series]:
    """Функция возраста по доле оголённой поверхности из 133 (единственный источник порогов)."""
    spec = importlib.util.spec_from_file_location('cadastre_anthro', Path(__file__).resolve().parent / '133_cadastre_anthro.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.age2000


def load_recalc() -> pd.DataFrame:
    """Таблица 159: id, age (new / mid / old), bare (доля оголённой поверхности в 2000 г.), area_ha."""
    c = pd.read_csv(RECALC).rename(columns={'age2000_new': 'age', 'bare2000_gee': 'bare'})[['id', 'age', 'bare', 'area_ha']]
    if not c['id'].is_unique or c[['age', 'bare']].isna().any().any():
        raise SystemExit(f'{RECALC}: повторы id или пустые значения')
    if not set(c['age']) <= {'new', 'mid', 'old'}:
        raise SystemExit(f'{RECALC}: неожиданные значения возраста {sorted(set(c["age"]))}')
    again = age_rule()(c['bare'])
    if (again.values != c['age'].values).any():
        raise SystemExit(f'{RECALC}: возраст не воспроизводится порогами 133 у {int((again.values != c["age"].values).sum())} контуров')
    return c


def expected() -> dict[str, pd.DataFrame]:
    """Ожидаемые число контуров (объектов) и площадь по возрасту после записи: класс и две группы."""
    a = pd.read_csv(EXPECT_CLASS, index_col=0)
    b = pd.read_csv(EXPECT_GROUPS, index_col=0)
    out = {'genesis': a[a['version'] == 'после'].loc[list(AGE_ORDER), ['N', 'km2']]}
    for lay in ('anthro_exceed', 'anthro_noallot'):
        out[lay] = b[(b['version'] == 'после') & (b['layer'] == lay)].loc[list(AGE_ORDER), ['N', 'km2']]
    return out


def by_age(d: pd.DataFrame) -> pd.DataFrame:
    """Число строк и площадь (км²) по возрасту."""
    g = d.groupby('age2000')['area_ha'].agg(N='size', km2='sum').reindex(list(AGE_ORDER)).fillna(0)
    g['km2'] /= 100
    return g


def stub(name: str) -> Callable[..., None]:
    def f(*args: object) -> None:
        raise RuntimeError(f'триггер вызвал {name}: обновление затронуло геометрию или fid')
    return f


def connect(path: Path, write: bool) -> sqlite3.Connection:
    """Соединение с GeoPackage. Для записи регистрируются заглушки пространственных функций, на которые ссылаются
    триггеры индекса: при обновлении атрибутов они не вызываются, а вызов означал бы изменение геометрии (ошибка)."""
    if not write:
        return sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
    con = sqlite3.connect(path, isolation_level=None)
    names: set[str] = set()
    for (sql,) in con.execute("SELECT sql FROM sqlite_master WHERE type = 'trigger'"):
        names |= set(re.findall(r'\b(ST_\w+)\s*\(', sql or ''))
    for n in sorted(names):
        con.create_function(n, -1, stub(n))
    return con


def table_digest(con: sqlite3.Connection, table: str, skip: tuple[str, ...]) -> tuple[int, str]:
    """Число строк и SHA-256 всех полей таблицы (с геометрией), кроме skip, в порядке fid."""
    cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
    keep = [c for c in cols if c not in skip]
    if len(keep) != len(cols) - len(skip):
        raise SystemExit(f'{table}: нет полей {set(skip) - set(cols)}')
    h = hashlib.sha256()
    n = 0
    for row in con.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in keep)} FROM "{table}" ORDER BY fid'):
        for v in row:
            b = v if isinstance(v, bytes) else repr(v).encode('utf-8')
            h.update(len(b).to_bytes(8, 'little'))
            h.update(b)
        n += 1
    return n, h.hexdigest()


def read_state() -> dict[str, pd.DataFrame]:
    """Атрибуты, нужные для проверок: техногенные контуры продукта и три слоя групп."""
    con = connect(PRODUCT, write=False)
    n_all, n_id = con.execute('SELECT count(*), count(DISTINCT id) FROM genesis').fetchone()
    if n_all != n_id:
        raise SystemExit(f'genesis: id не уникален ({n_all} строк, {n_id} id)')
    st = {'genesis': pd.read_sql("SELECT id, area_ha, bare2000_frac, age2000 FROM genesis WHERE genesis = 'anthropogenic'", con)}
    other = con.execute("SELECT count(*) FROM genesis WHERE genesis != 'anthropogenic' AND age2000 IS NOT NULL").fetchone()[0]
    con.close()
    if other:
        raise SystemExit(f'genesis: age2000 заполнен у {other} не техногенных контуров')
    con = connect(LAYERS, write=False)
    for lay in ANTHRO_LAYERS:
        st[lay] = pd.read_sql(f'SELECT id, area_ha, age2000 FROM "{lay}"', con)
    con.close()
    return st


def check_before(c: pd.DataFrame, st: dict[str, pd.DataFrame]) -> list[str]:
    """Проверки исходного состояния; при несоответствии остановка."""
    g = st['genesis']
    na = g[g['age2000'] == 'na']
    L = [f'контуров без возраста в слое: {len(na)}, {na["area_ha"].sum() / 100:.2f} км²; в таблице 159: {len(c)}']
    if set(na['id']) != set(c['id']):
        raise SystemExit('набор id со значением na в слое не равен набору id таблицы 159 (возраст уже записан?)')
    m = na.merge(c, on='id', suffixes=('', '_t'))
    if not np.allclose(m['area_ha'], m['area_ha_t']) or m['bare2000_frac'].notna().any():
        raise SystemExit('площади контуров не совпадают с таблицей 159 или bare2000_frac уже заполнен')
    if g.loc[g['age2000'] != 'na', 'bare2000_frac'].isna().any():
        raise SystemExit('у контуров с возрастом пуст bare2000_frac')
    for lay in ANTHRO_LAYERS:
        d = st[lay]
        x = d[d['age2000'] == 'na']
        if not set(x['id']) <= set(c['id']) or (d['id'].isin(c['id']) & (d['age2000'] != 'na')).any():
            raise SystemExit(f'{lay}: значения na не соответствуют таблице 159')
        L.append(f'{lay}: строк без возраста {len(x)} ({x["id"].nunique()} контуров), {x["area_ha"].sum() / 100:.2f} км²')
    return L


def check_after(c: pd.DataFrame, st: dict[str, pd.DataFrame]) -> list[str]:
    """Проверки состояния после записи; при несоответствии исключение (внутри транзакции: откат)."""
    exp = expected()
    L = []
    g = st['genesis']
    for name in ('genesis', 'anthro_exceed', 'anthro_noallot'):
        got = by_age(st[name])
        e = exp[name]
        if (got['N'].values != e['N'].values).any() or not np.allclose(got['km2'], e['km2'], atol=TOL_KM2, rtol=0):
            raise RuntimeError(f'{name}: по возрасту не равно таблице 159\n{got}\n{e}')
        L.append(f'{name}: ' + '; '.join(f'{k} {int(got.loc[k, "N"])} / {got.loc[k, "km2"]:.2f} км²' for k in AGE_ORDER))
    m = g.merge(c, on='id')
    if len(m) != len(c) or (m['age2000'] != m['age']).any() or not np.allclose(m['bare2000_frac'], m['bare'], atol=0, rtol=0):
        raise RuntimeError('genesis: значения у контуров таблицы 159 не равны таблице')
    again = age_rule()(g['bare2000_frac'])
    if (again.values != g['age2000'].values).any():
        raise RuntimeError('genesis: age2000 не воспроизводится из bare2000_frac порогами 133')
    age_of = g.set_index('id')['age2000']
    for lay in ANTHRO_LAYERS:
        d = st[lay]
        if (d['id'].map(age_of) != d['age2000']).any():
            raise RuntimeError(f'{lay}: возраст части не равен возрасту контура')
    got = by_age(st['anthro_in'])
    L.append('anthro_in: ' + '; '.join(f'{k} {int(got.loc[k, "N"])} / {got.loc[k, "km2"]:.2f} км²' for k in AGE_ORDER))
    return L


def update_file(path: Path, tables: dict[str, tuple[str, ...]], c: pd.DataFrame, n_expected: dict[str, int]) -> list[str]:
    """Одна транзакция на файл: обновление полей у контуров таблицы 159, сверка контрольных сумм остальных полей."""
    con = connect(path, write=True)
    L = []
    try:
        before = {t: table_digest(con, t, cols) for t, cols in tables.items()}
        con.execute('BEGIN IMMEDIATE')
        con.execute('CREATE TEMP TABLE upd (id INTEGER PRIMARY KEY, age TEXT NOT NULL, bare REAL NOT NULL)')
        con.executemany('INSERT INTO upd VALUES (?, ?, ?)',
                        [(int(i), str(a), float(b)) for i, a, b in zip(c['id'], c['age'], c['bare'])])
        for t, cols in tables.items():
            sets = ['age2000 = (SELECT age FROM upd WHERE upd.id = "%s".id)' % t]
            if 'bare2000_frac' in cols:
                sets.append('bare2000_frac = (SELECT bare FROM upd WHERE upd.id = "%s".id)' % t)
            cur = con.execute(f'UPDATE "{t}" SET {", ".join(sets)} WHERE id IN (SELECT id FROM upd) AND age2000 = \'na\'')
            if cur.rowcount != n_expected[t]:
                raise RuntimeError(f'{t}: обновлено {cur.rowcount} строк, ожидалось {n_expected[t]}')
            left = con.execute(f'SELECT count(*) FROM "{t}" WHERE age2000 = \'na\'').fetchone()[0]
            if left:
                raise RuntimeError(f'{t}: осталось {left} строк со значением na')
            con.execute("UPDATE gpkg_contents SET last_change = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE table_name = ?", (t,))
            after = table_digest(con, t, cols)
            if after != before[t]:
                raise RuntimeError(f'{t}: изменились поля помимо {cols}')
            L.append(f'{path.name}, {t}: обновлено строк {cur.rowcount}; остальные поля и геометрия без изменений '
                     f'({after[0]} строк, sha256 {after[1][:16]})')
        con.execute('COMMIT')
    except Exception:
        if con.in_transaction:
            con.execute('ROLLBACK')
        raise
    finally:
        con.close()
    return L


def apply(c: pd.DataFrame, st: dict[str, pd.DataFrame]) -> list[str]:
    n = {'genesis': len(c)}
    for lay in ANTHRO_LAYERS:
        n[lay] = int((st[lay]['age2000'] == 'na').sum())
    L = update_file(PRODUCT, {'genesis': ('age2000', 'bare2000_frac')}, c, n)
    L += update_file(LAYERS, {lay: ('age2000',) for lay in ANTHRO_LAYERS}, c, n)
    return L


def gee_local(lay: str) -> pd.DataFrame:
    """Число объектов и сумма area_ha по возрасту в локальном слое, с тем же отбором, что при загрузке ассета (150)."""
    import pyogrio
    d = pyogrio.read_dataframe(LAYERS, layer=lay, columns=['id', 'area_ha', 'age2000'])
    if lay == 'anthro_in':
        d = d[d.geometry.area >= MIN_PART_M2]
    return d.groupby('age2000')['area_ha'].agg(N='size', ha='sum')


def gee_stats(asset: str) -> pd.DataFrame:
    """Число объектов и сумма area_ha по возрасту в ассете."""
    import ee
    red = ee.Reducer.sum().combine(ee.Reducer.count(), sharedInputs=True).group(1, 'age')
    rows = ee.List(ee.FeatureCollection(asset).reduceColumns(red, ['area_ha', 'age2000']).get('groups')).getInfo()
    return pd.DataFrame({x['age']: {'N': x['count'], 'ha': x['sum']} for x in rows}).T


def acl_key(acl: dict) -> dict:
    """Права доступа в сравнимом виде (списки отсортированы)."""
    return {k: (sorted(v) if isinstance(v, list) else v) for k, v in acl.items()}


def gee_start(c: pd.DataFrame) -> None:
    import ee
    ee.Initialize(project=PROJECT)
    OUT.mkdir(parents=True, exist_ok=True)
    lookup = ee.Dictionary({str(int(i)): str(a) for i, a in zip(c['id'], c['age'])})
    rec = {}
    for lay in ANTHRO_LAYERS:
        src, dst = f'{FOLDER}/{lay}', f'{FOLDER}/{lay}{NEW_SUFFIX}'
        try:
            ee.data.getAsset(dst)
            raise SystemExit(f'{dst} уже есть')
        except ee.EEException:
            pass

        def patch(f: 'ee.Feature') -> 'ee.Feature':
            key = ee.Number(f.get('id')).toInt().format('%d')
            return f.set('age2000', ee.Algorithms.If(lookup.contains(key), lookup.get(key), f.get('age2000')))

        t = ee.batch.Export.table.toAsset(collection=ee.FeatureCollection(src).map(patch),
                                          description=f'baresand_{lay}{NEW_SUFFIX}', assetId=dst)
        t.start()
        rec[lay] = {'task': t.id, 'src': src, 'dst': dst}
        log(f'{dst}: задача {t.id}')
    (OUT / 'gee_tasks.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')


def gee_pairs(asset: str, ids: list[int]) -> pd.DataFrame:
    """Объекты ассета с id из списка: id, age2000, area_ha."""
    import ee
    fc = ee.FeatureCollection(asset).filter(ee.Filter.inList('id', ids))
    rows = fc.reduceColumns(ee.Reducer.toList(3), ['id', 'age2000', 'area_ha']).get('list').getInfo()
    return pd.DataFrame(rows, columns=['id', 'age2000', 'area_ha'])


def gee_verify(lay: str, cur: str, new: str, c: pd.DataFrame) -> str:
    """Сверка копии ассета с прежним ассетом и таблицей 159: то же число объектов, значения na заменены возрастом
    своего контура, у остальных объектов число и площадь по возрасту прежние. Сравнение с локальным слоем справочное:
    при загрузке 150 часть объектов могла выпасть (пустая геометрия после упрощения)."""
    age_of = dict(zip(c['id'].astype(int), c['age']))
    ids = sorted(age_of)
    was, now = gee_stats(cur), gee_stats(new)
    if 'na' in now.index or int(now['N'].sum()) != int(was['N'].sum()):
        raise SystemExit(f'{lay}: в копии остались na или изменилось число объектов\n{was}\n{now}')
    p_was, p_now = gee_pairs(cur, ids), gee_pairs(new, ids)
    n_na = int(was.loc['na', 'N']) if 'na' in was.index else 0
    if len(p_was) != n_na or (p_was['age2000'] != 'na').any():
        raise SystemExit(f'{lay}: объекты контуров таблицы 159 в прежнем ассете: {len(p_was)}, со значением na: {n_na}')
    if len(p_now) != len(p_was) or (p_now['age2000'] != p_now['id'].astype(int).map(age_of)).any():
        raise SystemExit(f'{lay}: возраст в копии не равен таблице 159')
    add = p_now.groupby('age2000')['area_ha'].agg(N='size', ha='sum')
    exp = was.drop(index='na', errors='ignore').astype(float).add(add.astype(float), fill_value=0).reindex(now.index)
    if (exp['N'].values != now['N'].astype(float).values).any() \
            or not np.allclose(exp['ha'], now['ha'].astype(float), atol=TOL_GEE_HA, rtol=0):
        raise SystemExit(f'{lay}: число или площадь по возрасту в копии не равны ожидаемым\n{exp}\n{now}')
    loc = gee_local(lay)
    d_n = int(loc['N'].sum()) - int(now['N'].sum())
    return (f'заменено значений na: {n_na}; объектов {int(now["N"].sum())}'
            + (f' (в локальном слое с тем же отбором на {d_n} больше: выпали при загрузке 150)' if d_n else ' (как в локальном слое)'))


def gee_swap(c: pd.DataFrame) -> None:
    import ee
    ee.Initialize(project=PROJECT)
    rec = json.loads((OUT / 'gee_tasks.json').read_text(encoding='utf-8'))
    L = ['', '## Ассеты Earth Engine', '']
    for lay in ANTHRO_LAYERS:
        state = ee.data.getTaskStatus(rec[lay]['task'])[0]['state']
        if state != 'COMPLETED':
            raise SystemExit(f'{lay}: задача {rec[lay]["task"]} в состоянии {state}')
    checked = {lay: gee_verify(lay, f'{FOLDER}/{lay}', f'{FOLDER}/{lay}{NEW_SUFFIX}', c) for lay in ANTHRO_LAYERS}
    for lay in ANTHRO_LAYERS:
        cur, new, old = f'{FOLDER}/{lay}', f'{FOLDER}/{lay}{NEW_SUFFIX}', f'{FOLDER}/{lay}{OLD_SUFFIX}'
        loc = gee_local(lay)
        acl = acl_key(ee.data.getAssetAcl(cur))
        ee.data.renameAsset(cur, old)
        ee.data.renameAsset(new, cur)
        if acl_key(ee.data.getAssetAcl(cur)) != acl:
            ee.data.setAssetAcl(cur, acl)
        same = acl_key(ee.data.getAssetAcl(cur)) == acl
        fin = gee_stats(cur).reindex(loc.index)
        line = (f'{lay}: ' + '; '.join(f'{k} {int(fin.loc[k, "N"])} / {float(fin.loc[k, "ha"]) / 100:.2f} км²' for k in fin.index)
                + f'; {checked[lay]}; права доступа перенесены: {"да" if same else "НЕТ"}; прежний ассет: {old}')
        log(line)
        L.append('- ' + line)
        if not same:
            raise SystemExit(f'{lay}: права доступа не совпали с прежними')
    with (OUT / 'report.md').open('a', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


def main() -> None:
    ap = argparse.ArgumentParser(description='Запись дополнительно определённого возраста поверхности в итоговые слои v7b.')
    ap.add_argument('--apply', action='store_true', help='записать (без ключа только проверки до записи)')
    ap.add_argument('--check', action='store_true', help='проверки после записи')
    ap.add_argument('--gee-start', action='store_true', help='задачи экспорта копий ассетов с новым возрастом')
    ap.add_argument('--gee-swap', action='store_true', help='сверка копий и замена ассетов')
    a = ap.parse_args()
    c = load_recalc()
    if a.gee_start:
        return gee_start(c)
    if a.gee_swap:
        return gee_swap(c)
    OUT.mkdir(parents=True, exist_ok=True)
    st = read_state()
    if a.check:
        print('\n'.join(check_after(c, st)))
        return
    L = ['# Запись возраста поверхности в итоговые слои v7b (python/160_age_into_layer.py)', '',
         f'Источник: {RECALC.relative_to(ROOT).as_posix()} ({len(c)} контуров: '
         + ', '.join(f'{k} {v}' for k, v in c['age'].value_counts().items()) + ').', '', '## До записи', '']
    L += ['- ' + x for x in check_before(c, st)]
    print('\n'.join(L))
    if not a.apply:
        log('проверки до записи пройдены; файлы не менялись (для записи: --apply)')
        return
    done = apply(c, st)
    after = check_after(c, read_state())
    tail = ['', '## Запись', ''] + ['- ' + x for x in done] + ['', '## После записи (контуров или частей / км² по возрасту)', ''] \
        + ['- ' + x for x in after]
    print('\n'.join(tail))
    (OUT / 'report.md').write_text('\n'.join(L + tail) + '\n', encoding='utf-8')
    log(f'записано; отчёт: {OUT / "report.md"}')


if __name__ == '__main__':
    main()
