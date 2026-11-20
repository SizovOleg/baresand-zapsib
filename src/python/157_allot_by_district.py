"""
Доля техногенных песков в отводах ЕГРН по строкам табл. 3 статьи (районы и субъекты РФ), слой v7b.

Привязка к районам та же, что в article_facts.py (центроид контура внутри района OSM, города
присоединены к районам; вне районов восточнее 79° в. д. считается Красноярским краем). Доля в отводах:
сумма поля cad_in_ha, делённая на площадь техногенных контуров строки. Для контроля выводятся группы
«превышение отвода» (cad_exc10_ha у контуров со статусом cross) и «без отвода» (контуры со статусом unreg).

Запуск: PYTHONIOENCODING=utf-8 python python/157_allot_by_district.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import cpu_limit  # noqa: E402

cpu_limit.apply()

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
import pyogrio  # noqa: E402
import shapely  # noqa: E402

import article_facts as facts  # noqa: E402

# Строки табл. 3: (подпись, субъект, ключевые слова в названии района OSM)
ROWS: list[tuple[str, str, tuple[str, ...]]] = [
    ('Ямальский', 'ЯНАО', ('Ямальский',)),
    ('Тазовский', 'ЯНАО', ('Тазовский',)),
    ('Надымский', 'ЯНАО', ('Надымский',)),
    ('Пуровский', 'ЯНАО', ('Пуровский',)),
    ('Приуральский', 'ЯНАО', ('Приуральский',)),
    ('Красноселькупский и Шурышкарский', 'ЯНАО', ('Красноселькупский', 'Шурышкарский')),
    ('Сургутский', 'ХМАО', ('Сургутский',)),
    ('Нижневартовский', 'ХМАО', ('Нижневартовский',)),
    ('Прочие районы ХМАО', 'ХМАО', ('Белоярский', 'Ханты-Мансийский', 'Октябрьский', 'Берёзовский', 'Нефтеюганский')),
    ('Красноярский край', 'Красноярский край', ('Туруханский',)),
]
EAST_LABEL = 'Красноярский край'
OUTSIDE_LABEL = 'Вне районов'
STATUS_EXCEED = 'cross'
STATUS_NOALLOT = 'unreg'
OUT_CSV = facts.ROOT / 'exports' / 'qc' / 'article_v3_extra' / 'allot_by_district.csv'


def row_of(district: object, lon: float) -> str:
    """Строка табл. 3 для контура по названию района и долготе центроида."""
    if not isinstance(district, str):
        return EAST_LABEL if lon >= facts.EAST_SECTOR_LON else OUTSIDE_LABEL
    for label, _subject, keys in ROWS:
        if any(k in district for k in keys):
            return label
    return OUTSIDE_LABEL


def summarize(df: pd.DataFrame) -> dict[str, float]:
    """Площадь класса, площадь в отводах и вне групп, км², и доля в отводах, %."""
    area = df['area_ha'].sum() / 100.0
    in_allot = df['cad_in_ha'].sum() / 100.0
    exceed = df.loc[df['cad_status'] == STATUS_EXCEED, 'cad_exc10_ha'].sum() / 100.0
    noallot = df.loc[df['cad_status'] == STATUS_NOALLOT, 'area_ha'].sum() / 100.0
    return {'км²': area, 'в отводах, км²': in_allot, 'в отводах, %': 100.0 * in_allot / max(area, 1e-9),
            'превышение, км²': exceed, 'без отвода, км²': noallot, 'без отвода, %': 100.0 * noallot / max(area, 1e-9)}


def main() -> None:
    cols = ['id', 'area_ha', 'genesis_main', 'cad_status', 'cad_in_ha', 'cad_exc10_ha']
    g = pyogrio.read_dataframe(facts.PRODUCT_GPKG, layer='genesis', columns=cols,
                               where="genesis_main = 'anthropogenic'")
    assert g.crs.to_epsg() == facts.TARGET_CRS
    print(f'техногенных контуров: {len(g)}, площадь {g["area_ha"].sum() / 100.0:.1f} км²')

    cov = gpd.read_file(facts.COVERAGE_GPKG, layer='coverage').to_crs(facts.TARGET_CRS)
    cov_geom = shapely.make_valid(cov.geometry.union_all())
    d6, _host = facts.load_admin_districts(cov_geom)

    centroids = g.geometry.centroid
    g['lon'] = gpd.GeoSeries(centroids, crs=facts.TARGET_CRS).to_crs(4326).x.to_numpy()
    pts = gpd.GeoDataFrame(g[['id']], geometry=centroids, crs=facts.TARGET_CRS)
    joined = gpd.sjoin(pts, d6[['name', 'district', 'geometry']], how='left', predicate='within')
    joined = joined[~joined.index.duplicated()]
    g['district'] = joined['district'].to_numpy()
    g['row'] = [row_of(d, lon) for d, lon in zip(g['district'], g['lon'])]
    subject_of = {label: subject for label, subject, _ in ROWS}
    g['subject'] = g['row'].map(subject_of).fillna(OUTSIDE_LABEL)

    out: list[dict[str, object]] = []
    for subject in ('ЯНАО', 'ХМАО', 'Красноярский край'):
        out.append({'строка': f'{subject}, всего', **summarize(g[g['subject'] == subject])})
        for label, subj, _ in ROWS:
            if subj == subject and label != subject:
                out.append({'строка': label, **summarize(g[g['row'] == label])})
    out.append({'строка': OUTSIDE_LABEL, **summarize(g[g['row'] == OUTSIDE_LABEL])})
    out.append({'строка': 'Всего', **summarize(g)})

    table = pd.DataFrame(out)
    pd.set_option('display.width', 200)
    print(table.round(1).to_string(index=False))
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    table.round(3).to_csv(OUT_CSV, index=False, encoding='utf-8-sig')
    print('записано:', OUT_CSV)


if __name__ == '__main__':
    main()
