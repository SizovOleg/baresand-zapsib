"""
69_step3_nspd_download.py — выгрузка объектов ЕГРН с публичной кадастровой карты (НСПД, nspd.gov.ru) по всей AOI.

Источник: WMS-сервис геопортала НСПД https://nspd.gov.ru/api/aeggis/v3/<layer>/wms (GetCapabilities: Fees none, AccessConstraints none).
Приём: GetFeatureInfo возвращает объекты в GeoJSON с геометрией (EPSG:3857) и атрибутами ЕГРН (кад. номер, категория земель, ВРИ,
площадь, статус…) — до FEATURE_COUNT ≤ 5000 (10000 → ошибка 500). Сервер ищет объекты в радиусе ≈ 8 px вокруг запрошенного пикселя
(калибровка 2026-09-07), поэтому:
  * картинка 1×1 px (пиксель = вся ячейка) отдаёт объекты из окна ~17×17 ячеек — 99 % ответа вне ячейки, потолок 5000 упирается
    в плотных районах и часть объектов самой ячейки теряется (так была сделана первая выгрузка участков — кэш «старого формата»);
  * картинка IMG_PX×IMG_PX с пикселем в центре: полудиагональ ячейки 6.4 px < 8 px — вся ячейка покрыта, запас за границей ≤ 0.4 ячейки,
    ответ в 10–100 раз меньше и быстрее (0.5 с вместо 10 с) — «точный» запрос, используется для всех новых запросов.
Поисковый API (api/geoportal/v2/search) закрыт WAF для не-браузеров (403), WFS нет (500) — WMS открыт при браузерных заголовках.
Сертификат — российский корневой (Минцифры): verify=False или свой CA-bundle.
Слои (exports/qc/step3/nspd_layers.csv): 36048 Земельные участки ЕГРН; 36049 Здания; 36328 Сооружения; 36329 ОНС;
  36302 ЗОУИТ (все); 37578 ЗОУИТ объектов энергетики, связи, транспорта; 36315 Территориальные зоны; 36314 Лесничества; 36070/36071 кад. районы/кварталы.

Алгоритм: адаптивная квадродеревная сетка по bbox AOI (EPSG:3857): ячейка START_KM; если объектов ≥ потолка — делим на 4 (до MIN_KM);
--only-where — запрашиваются только ячейки в NEAR_M от контуров; WORKERS параллельных запросов; ответы кэшируются в
exports/nspd/cache/<layer>/<cell>.json.gz (возобновляемо; только границы и ключевые атрибуты — slim). Старый кэш 1×1 — надмножество
объектов ячейки: используется как есть, но упёршиеся в потолок листья перезапрашиваются точно. Сбои сервера: 6 попыток с растущей
паузой, затем до MAX_ROUNDS повторных раундов; окончательно потерянные ячейки → exports/nspd/nspd_<layer>_lost.gpkg (покрытие для 70).
Дедупликация по externalKey (кад. номер); выход — exports/nspd/nspd_<layer>.gpkg (EPSG:3576).
Запуск: python -u python/69_step3_nspd_download.py --layer 36048 --workers 3 --only-where exports/baresand_genesis_step3_v3e.gpkg
        --where "genesis IN ('unassigned','anthropogenic')" [--start-km 50 --min-km 1 --pause 0.2]
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import argparse
import gzip
import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import urllib3
from shapely.geometry import box, shape

urllib3.disable_warnings()
EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
OUT_DIR = EXPORTS / 'nspd'
BASE = 'https://nspd.gov.ru/api/aeggis/v3'
AOI_LL = (62.0, 61.0, 90.1, 73.0)        # lon/lat bbox AOI с запасом
FEATURE_COUNT = 5000
IMG_PX = 9                               # картинка W×W, пиксель I=J=W//2 в центре (радиус поиска сервера ≈ 8 px)
NEAR_M = 2500                            # запас вокруг контуров при отборе ячеек, м EPSG:3857 (≈ 1 км на 67° с.ш.) — для улик расстояния
MAX_ROUNDS = 3                           # повторные раунды для ячеек, не полученных из-за сбоев сервера
ROUND_PAUSE_S = 300
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
           'Accept': 'application/json, text/plain, */*', 'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
           'Referer': 'https://nspd.gov.ru/map', 'Origin': 'https://nspd.gov.ru',
           'sec-fetch-dest': 'empty', 'sec-fetch-mode': 'cors', 'sec-fetch-site': 'same-origin'}
KEY_OPTS = ('cad_num', 'cad_number', 'land_record_category_type', 'permitted_use_established_by_document', 'ownership_type', 'status',
            'specified_area', 'declared_area', 'land_record_type', 'land_record_subtype', 'quarter_cad_number',
            'type_zone', 'name_by_doc', 'purpose', 'name', 'building_name', 'object_type_value', 'params_extension', 'params_built_up_area')


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def slim(f: dict) -> dict:
    """Оставить только границы и ключевые атрибуты (объём кэша ~5–8× меньше): даты, стоимость, адреса и прочее отбрасываются."""
    pr = f.get('properties') or {}
    o = pr.get('options') or {}
    return {'properties': {'externalKey': pr.get('externalKey'), 'interactionId': pr.get('interactionId'), 'label': pr.get('label'),
                           'categoryName': pr.get('categoryName'), 'cadastralDistrictsCode': pr.get('cadastralDistrictsCode'),
                           'options': {k: o[k] for k in KEY_OPTS if k in o}},
            'geometry': f.get('geometry')}


class TruncatedResponse(Exception):
    """Ответ сервера обрезан (JSON не разобран) — слишком много/тяжёлых объектов для одного запроса."""


class Client:
    def __init__(self, pause: float) -> None:
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.s.verify = False
        self.pause = pause
        self.n_req = 0
        self.lock = threading.Lock()

    def features(self, layer: int, bbox, count: int = FEATURE_COUNT, exact: bool = True):
        x0, y0, x1, y1 = bbox
        w = IMG_PX if exact else 1
        url = (f'{BASE}/{layer}/wms?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetFeatureInfo&LAYERS={layer}&QUERY_LAYERS={layer}'
               f'&CRS=EPSG:3857&BBOX={x0},{y0},{x1},{y1}&WIDTH={w}&HEIGHT={w}&I={w // 2}&J={w // 2}&INFO_FORMAT=application/json'
               f'&FEATURE_COUNT={count}&STYLES=&FORMAT=image/png')
        for attempt in range(6):
            try:
                r = self.s.get(url, timeout=(20, 300))     # (соединение, чтение): зависший SYN не должен стоить 5 минут
                with self.lock:
                    self.n_req += 1
                time.sleep(self.pause)
                if r.status_code == 200:
                    try:
                        return r.json().get('features', [])
                    except ValueError:                      # сервер обрезает ответ ~17.6 МБ → JSON не закрыт: просить меньше объектов
                        raise TruncatedResponse(len(r.content))
                if r.status_code in (403, 429):
                    wait_s = 60 * (attempt + 1)
                    log(f'  HTTP {r.status_code} — пауза {wait_s} с')
                    time.sleep(wait_s)
                    continue
                log(f'  HTTP {r.status_code}: {r.text[:100]!r} — повтор через {10 * 2 ** attempt} с')
                time.sleep(10 * 2 ** attempt)
            except requests.RequestException as e:
                log(f'  ошибка сети {e} — повтор через {10 * 2 ** attempt} с')
                time.sleep(10 * 2 ** attempt)
        raise RuntimeError(f'не удалось получить {bbox}')


def fetch_cell(cl: Client, cache: Path, layer: int, cell, force: bool = False):
    """Одна ячейка: из кэша или с сервера (slim + gzip). → (cell, features | None, потолок, точный_ли_запрос)."""
    x, y, s = cell
    key = f'{int(x)}_{int(y)}_{int(s)}'
    p, pz = cache / f'{key}.json', cache / f'{key}.json.gz'
    if not force:
        if pz.exists():
            with gzip.open(pz, 'rt', encoding='utf-8') as fh:
                data = json.load(fh)
            if isinstance(data, dict):                   # {'count': потолок, 'exact': точный ли запрос, 'features': [...]}
                return cell, data['features'], data['count'], bool(data.get('exact', False))
            return cell, data, FEATURE_COUNT, False        # старый список — 1×1, надмножество
        if p.exists():                                   # старый несжатый полный кэш (тест) — ужимаем на лету
            return cell, [slim(f) for f in json.loads(p.read_text(encoding='utf-8'))], FEATURE_COUNT, False
    fl, used = None, 0
    for count in (FEATURE_COUNT, 2500, 1000, 400):
        try:
            fl = [slim(f) for f in cl.features(layer, (x, y, x + s, y + s), count)]
            used = count
            break
        except TruncatedResponse as e:
            log(f'  ответ обрезан ({e.args[0] / 1e6:.1f} МБ) при FEATURE_COUNT={count}, ячейка {key} — уменьшаю')
    if fl is None:
        return cell, None, 0, True
    tmp = pz.with_suffix('.gz.tmp')
    with gzip.open(tmp, 'wt', encoding='utf-8', compresslevel=6) as fh:
        json.dump({'count': used, 'exact': True, 'features': fl}, fh, ensure_ascii=False)
    tmp.replace(pz)
    return cell, fl, used, True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--layer', type=int, default=36048)
    ap.add_argument('--start-km', type=float, default=50.0)
    ap.add_argument('--min-km', type=float, default=1.0)
    ap.add_argument('--pause', type=float, default=0.2)
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--bbox', type=float, nargs=4, default=None, help='lon0 lat0 lon1 lat1 (по умолчанию AOI)')
    ap.add_argument('--only-where', default=None, help='gpkg контуров: запрашивать только ячейки в NEAR_M от контуров')
    ap.add_argument('--where', default=None, help='SQL-фильтр к --only-where (например "genesis IN (\'unassigned\',\'anthropogenic\')")')
    a = ap.parse_args()
    t0 = time.time()
    from pyproj import Transformer
    tr = Transformer.from_crs('EPSG:4326', 'EPSG:3857', always_xy=True)
    lon0, lat0, lon1, lat1 = a.bbox or AOI_LL
    X0, Y0 = tr.transform(lon0, lat0)
    X1, Y1 = tr.transform(lon1, lat1)
    cache = OUT_DIR / 'cache' / str(a.layer)
    cache.mkdir(parents=True, exist_ok=True)
    cl = Client(a.pause)
    min_m = a.min_km * 1000
    tree = None
    if a.only_where:
        from shapely.strtree import STRtree
        cont = gpd.read_file(a.only_where, columns=['id'], where=a.where).to_crs('EPSG:3857')
        tree = STRtree(cont.geometry.values)
        log(f'фильтр ячеек по {len(cont):,} контурам (запас {NEAR_M} м)')

    def wanted(cell) -> bool:
        x, y, s = cell
        return tree is None or len(tree.query(box(x - NEAR_M, y - NEAR_M, x + s + NEAR_M, y + s + NEAR_M))) > 0

    step = a.start_km * 1000
    initial = [(x, y, step) for x in _frange(X0, X1, step) for y in _frange(Y0, Y1, step)]
    log(f'слой {a.layer}: стартовых ячеек {len(initial)} по {a.start_km:.0f} км; потоков {a.workers}; точный запрос {IMG_PX}×{IMG_PX} px; кэш {cache}')
    feats = {}
    n = dict(cells=0, split=0, empty=0, skip=0, trunc=0, refetch=0, fail=0)
    lost = []                                            # окончательно потерянные ячейки: (x, y, s, причина)
    ex = ThreadPoolExecutor(max_workers=a.workers)
    pending = {}                                         # future → (cell, force)
    queue = []                                           # (cell, force) — стек (обход в глубину)
    failed = []
    for c in initial:
        if wanted(c):
            queue.append((c, False))
        else:
            n['skip'] += 1

    def top_up() -> None:
        while queue and len(pending) < a.workers * 2:
            cell, force = queue.pop()
            pending[ex.submit(fetch_cell, cl, cache, a.layer, cell, force)] = (cell, force)

    def children(x: float, y: float, s: float) -> None:
        h = s / 2
        for c in ((x, y, h), (x + h, y, h), (x, y + h, h), (x + h, y + h, h)):
            if wanted(c):
                queue.append((c, False))
            else:
                n['skip'] += 1
        n['split'] += 1

    for rnd in range(MAX_ROUNDS + 1):
        if rnd:
            log(f'раунд повтора {rnd}: {len(failed)} ячеек после паузы {ROUND_PAUSE_S} с')
            time.sleep(ROUND_PAUSE_S)
            queue.extend(failed)
            failed = []
        top_up()
        while pending:
            done, _ = wait(list(pending), return_when=FIRST_COMPLETED)
            for fut in done:
                item = pending.pop(fut)
                try:
                    (x, y, s), fl, used, exact = fut.result()
                except Exception as e:                   # одна ячейка не должна валить весь прогон — в повторный раунд
                    n['fail'] += 1
                    failed.append(item)
                    log(f'  ОШИБКА ячейки {int(item[0][0])}_{int(item[0][1])}_{int(item[0][2])}: {e}')
                    continue
                n['cells'] += 1
                if fl is None:                           # обрезано даже при 400 объектах — делим, если можно
                    if s / 2 >= min_m:
                        children(x, y, s)
                    else:
                        lost.append((x, y, s, 'truncated'))
                        log(f'  ПОТЕРЯ: ячейка {int(x)}_{int(y)}_{int(s)} обрезана на минимальном размере')
                    continue
                for f in fl:                             # все полученные объекты настоящие — в объединение (в т.ч. из надмножеств 1×1)
                    pr = f['properties']
                    k = pr.get('externalKey') or pr.get('interactionId') or f'{pr.get("label")}|{json.dumps(f.get("geometry"), sort_keys=True)[:300]}'
                    if k not in feats:
                        feats[k] = f
                capped = len(fl) >= used
                if not fl:
                    n['empty'] += 1
                if capped and s / 2 >= min_m:
                    children(x, y, s)
                elif capped and not exact:               # старый 1×1-ответ упёрся в потолок на листе: сама ячейка могла не попасть в 5000
                    queue.append(((x, y, s), True))
                    n['refetch'] += 1
                elif capped:
                    n['trunc'] += 1                      # минимальная ячейка всё ещё упирается в потолок — часть объектов потеряна
                    lost.append((x, y, s, 'capped'))
                if n['cells'] % 50 == 0:
                    log(f'  ячеек {n["cells"]} (делений {n["split"]}, пустых {n["empty"]}, пропущено без контуров {n["skip"]}, '
                        f'перезапрошено листьев {n["refetch"]}, усечённых {n["trunc"]}, сбоев {n["fail"]}), объектов {len(feats):,}, '
                        f'запросов {cl.n_req}, в очереди {len(queue) + len(pending)} | {(time.time() - t0) / 60:.1f} мин')
            top_up()
        if not failed:
            break
    ex.shutdown()
    for (x, y, s), _ in failed:
        lost.append((x, y, s, 'failed'))
    log(f'ячеек {n["cells"]} (усечённых на минимальном размере: {n["trunc"]}, потеряно после повторов: {len(failed)}, '
        f'перезапрошено листьев: {n["refetch"]}, пропущено без контуров: {n["skip"]}), объектов {len(feats):,}; сборка GPKG...')

    out_lost = OUT_DIR / f'nspd_{a.layer}_lost.gpkg'
    out_lost.unlink(missing_ok=True)                     # иначе GPKG получит второй слой, а читатели возьмут старый
    if lost:
        gl = gpd.GeoDataFrame({'size_km': [s / 1000 for _, _, s, _ in lost], 'reason': [r for *_, r in lost]},
                              geometry=[box(x, y, x + s, y + s) for x, y, s, _ in lost], crs='EPSG:3857').to_crs('EPSG:3576')
        gl.to_file(out_lost, driver='GPKG')
        log(f'потерянные ячейки → {out_lost.name}: {len(gl)} ({gl["reason"].value_counts().to_dict()})')
    else:
        out_lost.unlink(missing_ok=True)

    rows = []
    for k, f in feats.items():
        pr = f['properties']
        o = pr.get('options') or {}
        row = {'ext_key': k, 'label': pr.get('label'), 'category_name': pr.get('categoryName'), 'district_code': pr.get('cadastralDistrictsCode')}
        for c in KEY_OPTS:
            if c in o:
                row[c] = o[c]
        row['geometry'] = shape(f['geometry']) if f.get('geometry') else None
        rows.append(row)
    g = gpd.GeoDataFrame(rows, geometry='geometry', crs='EPSG:3857')
    g = g[g.geometry.notna() & ~g.geometry.is_empty].to_crs('EPSG:3576')
    g['area_ha_geom'] = (g.geometry.area / 1e4).round(3)
    out = OUT_DIR / f'nspd_{a.layer}.gpkg'
    g.to_file(out, layer='features', driver='GPKG')
    log(f'сохранено {out}: {len(g):,} объектов | запросов {cl.n_req} | {(time.time() - t0) / 60:.1f} мин')
    if 'land_record_category_type' in g.columns:
        print(g['land_record_category_type'].value_counts().head(12).to_string())
    if 'permitted_use_established_by_document' in g.columns:
        print(g['permitted_use_established_by_document'].astype(str).str.lower().str.strip().value_counts().head(20).to_string())


def _frange(a: float, b: float, step: float):
    v = a
    while v < b:
        yield v
        v += step


if __name__ == '__main__':
    main()
