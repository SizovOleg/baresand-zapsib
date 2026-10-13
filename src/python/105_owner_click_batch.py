"""
105_owner_click_batch.py - партия для быстрой проверки владельцем «окно + кнопки» (2026-09-26).

Владелец смотрит контур и нажимает класс (клавиши 1-8); метки хранятся в localStorage страницы, супервайзер забирает их
из встроенного браузера и считает (107_owner_click_ingest.py). Метки владельца: эталон проекта.
Партия O<n> (по умолчанию):
  burn - случайные undefined в v4 с подписью «песок на месте редколесья после потери леса» (tc2000 >= 10, loss >= 0.3),
         страты по размеру (S < 1 га, L >= 1 га); проверка правила «гари в эоловый» (решение владельца 2026-09-26);
  v4   - случайные правки пилота в v4 (step6_rule = v4_big_nb); проверка v4 глазом владельца.
Исключаются все ранее размеченные id. Порядок перемешан, группа и предложение модели на странице не показываются.
Снимки: обзор Esri (окно по контуру), приближение Esri 0.8 км для < 1 га, Sentinel-2 медиана июль-август 2024-2025
(период маски), контур красным.

Выход: exports/qc/owner_click/<name>/batch.csv, batch.json, geoms.gpkg, img/, index.html.
Запуск: PYTHONIOENCODING=utf-8 python -u python/105_owner_click_batch.py --name O1 --n-burn 40 --n-v4 20
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import shutil
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
EXPORTS = ROOT / 'exports'
PRODUCT = EXPORTS / 'baresand_genesis_step6_v4.gpkg'
OUT_ROOT = EXPORTS / 'qc' / 'owner_click'
QCF = EXPORTS / 'qc' / 'final'
QCL = EXPORTS / 'qc' / 'lake'
DRIVER = ROOT / 'python' / 'qc_render_parallel.py'
SEED = 20260926
S2_DATE = ('2024-06-15', '2025-09-15')
S2_MONTHS = (7, 8)
S2_PX = 640
LABELS = [('lake_shoal', 'озёрная отмель'), ('river_shoal', 'речная отмель'), ('shoal', 'морская отмель'),
          ('aeolian', 'эоловый'), ('anthropogenic', 'техноген'), ('not_sand', 'не песок'), ('mixed', 'смешанный'),
          ('disputed', 'спорный')]


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def labelled() -> set:
    ids: set = set()
    for p in (QCF / 'validation_sample.csv', EXPORTS / 'qc' / 'target' / 'target_sample.csv', QCL / 'lake_fit.csv',
              QCL / 'lake_audit.csv', QCL / 'big' / 'big_sample.csv'):
        if p.exists():
            ids |= set(pd.read_csv(p, usecols=['id'])['id'])
    gold = OUT_ROOT / 'owner_gold.csv'
    if gold.exists():
        ids |= set(pd.read_csv(gold, usecols=['id'])['id'])
    return ids


def select_arms(a: argparse.Namespace) -> gpd.GeoDataFrame:
    """Отбор по плечам из готовой совокупности (csv: id, area_ha, arm): простая случайная выборка внутри плеча."""
    pop = pd.read_csv(a.pop_csv)
    excl = labelled()
    rng = np.random.default_rng(SEED + a.seed_offset)
    parts = []
    spec = ([(x.split(':')[0], int(x.split(':')[1])) for x in a.arms.split(',')] if a.arms
            else [('arm_clear', a.n_arm_clear), ('arm_burn', a.n_arm_burn)])
    owner_seen = set(pd.read_csv(QCL / 'big' / 'expert_big.csv', usecols=['id'])['id'])
    if (OUT_ROOT / 'owner_gold.csv').exists():
        owner_seen |= set(pd.read_csv(OUT_ROOT / 'owner_gold.csv', usecols=['id'])['id'])
    census = set(a.census_arms.split(',')) if a.census_arms else set()
    for arm, n in spec:
        p = pop[pop['arm'] == arm]
        # спорные уже смотрели агенты: для них исключаем только то, что видел владелец; сплошные страты берутся целиком
        cand = p if arm in census else p[~p['id'].isin(owner_seen if arm.startswith('disputed') else excl)]
        pick = cand.sample(min(n, len(cand)), random_state=int(rng.integers(0, 2**31)))
        parts.append(pick.assign(group=arm, stratum=arm, N_stratum=len(p), A_stratum_km2=p['area_ha'].sum() / 100))
    s = pd.concat(parts).sample(frac=1, random_state=int(rng.integers(0, 2**31))).reset_index(drop=True)
    geo = gpd.read_file(PRODUCT, layer='genesis', columns=['id', 'genesis'], where=f"id IN ({','.join(map(str, s['id']))})")
    s = geo.merge(s.drop(columns=['genesis'], errors='ignore'), on='id')
    c = s.geometry.centroid
    w = gpd.GeoSeries(c, crs=s.crs).to_crs(4326)
    s['lon'], s['lat'] = w.x.round(5), w.y.round(5)
    log(f'плечи: {s["group"].value_counts().to_dict()}; совокупность {pop.groupby("arm").size().to_dict()}')
    return gpd.GeoDataFrame(s, geometry='geometry', crs=geo.crs)


def select(a: argparse.Namespace) -> gpd.GeoDataFrame:
    cols = ['id', 'genesis', 'area_ha', 'tc2000_mean', 'loss_frac', 'step6_rule']
    g = gpd.read_file(PRODUCT, layer='genesis', columns=cols,
                      where="genesis = 'undefined' OR step6_rule = 'v4_big_nb'")
    rng = np.random.default_rng(SEED + a.seed_offset)
    burn_pop = g[(g['genesis'] == 'undefined') & (g['tc2000_mean'].fillna(0) >= 10) & (g['loss_frac'].fillna(0) >= 0.3)].copy()
    burn_pop['stratum'] = np.where(burn_pop['area_ha'] >= 1, 'burn_L', 'burn_S')
    v4_pop = g[g['step6_rule'].eq('v4_big_nb') & ~g['genesis'].eq('undefined')].copy()
    v4_pop['stratum'] = 'v4_' + v4_pop['genesis']
    excl = labelled()
    parts = []
    n_l = a.n_burn // 2
    for st, n in (('burn_L', n_l), ('burn_S', a.n_burn - n_l)):
        pop = burn_pop[(burn_pop['stratum'] == st)]
        cand = pop[~pop['id'].isin(excl)]
        pick = cand.sample(min(n, len(cand)), random_state=int(rng.integers(0, 2**31)))
        pick = pick.assign(group='burn', N_stratum=len(pop), A_stratum_km2=pop['area_ha'].sum() / 100)
        parts.append(pick)
    # правки v4 размечали только агенты; исключаем лишь то, что уже видел владелец
    owner_seen = set(pd.read_csv(QCL / 'big' / 'expert_big.csv', usecols=['id'])['id'])
    gold = OUT_ROOT / 'owner_gold.csv'
    if gold.exists():
        owner_seen |= set(pd.read_csv(gold, usecols=['id'])['id'])
    cand = v4_pop[~v4_pop['id'].isin(owner_seen)]
    pick = cand.sample(min(a.n_v4, len(cand)), random_state=int(rng.integers(0, 2**31)))
    parts.append(pick.assign(group='v4', N_stratum=len(v4_pop), A_stratum_km2=v4_pop['area_ha'].sum() / 100))
    s = pd.concat(parts).sample(frac=1, random_state=int(rng.integers(0, 2**31))).reset_index(drop=True)
    c = s.geometry.centroid
    w = gpd.GeoSeries(c, crs=s.crs).to_crs(4326)
    s['lon'], s['lat'] = w.x.round(5), w.y.round(5)
    log(f'burn: совокупность {len(burn_pop)} конт. / {burn_pop["area_ha"].sum() / 100:.1f} км2; v4: {len(v4_pop)} конт.; '
        f'в партии {len(s)} ({s["group"].value_counts().to_dict()})')
    return gpd.GeoDataFrame(s, geometry='geometry', crs=g.crs)


def render_esri(out: Path, s: gpd.GeoDataFrame) -> None:
    j = {'1': {'name': out.name, 'ids': [int(i) for i in s['id']]}}
    (out / 'batch.json').write_text(json.dumps(j), encoding='utf-8')
    base = [sys.executable, '-u', str(DRIVER), '--workers', str(cpu_limit.RENDER_WORKERS), '--batch', '8', '--samples', str(out / 'batch.json'),
            '--overlay', str(QCF / 'overlay_none.gpkg'), '--field', 'genesis', '--sample', str(out / 'geoms.gpkg')]
    subprocess.run(base + ['--out', str(out / 'esri')], check=False, stdout=subprocess.DEVNULL)
    small = [int(i) for i, ar in zip(s['id'], s['area_ha']) if ar < 1]
    if small:
        (out / 'zoom.json').write_text(json.dumps({'1': {'name': 'zoom', 'ids': small}}), encoding='utf-8')
        zoom = [str(out / 'zoom.json') if x == str(out / 'batch.json') else x for x in base]
        subprocess.run(zoom + ['--out', str(out / 'esri_zoom'), '--km', '0.8'], check=False, stdout=subprocess.DEVNULL)


def render_s2(out: Path, s: gpd.GeoDataFrame) -> None:
    import ee
    try:
        ee.Initialize()
    except Exception:
        ee.Initialize(project='ee-ntcomz18')
    (out / 's2').mkdir(parents=True, exist_ok=True)

    def one(row) -> str:
        p = out / 's2' / f'{int(row.id)}_s2.png'
        if p.exists():
            return 'skip'
        minx, miny, maxx, maxy = row.geometry.bounds
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        half = min(max(max(maxx - minx, maxy - miny) * 3.0, 1200.0), 10000.0) / 2
        win = gpd.GeoSeries([box(cx - half, cy - half, cx + half, cy + half)], crs=s.crs).to_crs(4326).iloc[0]
        region = ee.Geometry.Rectangle(list(win.bounds))
        col = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(region).filterDate(*S2_DATE)
               .filter(ee.Filter.calendarRange(*S2_MONTHS, 'month')).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
               .map(lambda im: im.updateMask(im.select('SCL').remap([3, 8, 9, 10], [0, 0, 0, 0], 1))))
        tc = col.select(['B4', 'B3', 'B2']).median().visualize(min=0, max=3000, gamma=1.1)
        geo = json.loads(gpd.GeoSeries([row.geometry], crs=s.crs).to_crs(4326).to_json())['features'][0]['geometry']
        line = ee.Image().byte().paint(ee.FeatureCollection([ee.Feature(ee.Geometry(geo))]), 1, 2).visualize(palette=['ff0000'])
        # без crs снимок строится в градусах (EPSG:4326) и на 63-68° с. ш. растянут по долготе в 2-2.5 раза (до 2026-10-05)
        url = tc.blend(line).getThumbURL({'region': region, 'dimensions': S2_PX, 'format': 'png', 'crs': 'EPSG:3857'})
        urllib.request.urlretrieve(url, p)
        return 'ok'

    with ThreadPoolExecutor(max_workers=cpu_limit.RENDER_WORKERS) as ex:
        res = list(ex.map(lambda r: _safe(one, r), s.itertuples()))
    log(f'Sentinel-2: {sum(r == "ok" for r in res)} новых, ошибок {sum(r.startswith("ERR") for r in res)}')
    for r in res:
        if r.startswith('ERR'):
            log(r)


def _safe(fn, row) -> str:
    try:
        return fn(row)
    except Exception as e:
        return f'ERR {int(row.id)}: {str(e)[:150]}'


PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Проверка __NAME__</title>
<style>
:root { --bg:#f6f5f2; --ink:#1d1d1b; --mute:#6b6a66; --line:#d9d6cf; --acc:#b3372e; --chip:#ffffff; --ok:#2e7d4f; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { display:flex; gap:16px; align-items:baseline; padding:10px 16px; border-bottom:1px solid var(--line); flex-wrap:wrap; }
header b { font-size:17px; } .mute { color:var(--mute); } #bar { flex:1; min-width:120px; height:6px; background:var(--line); border-radius:3px; }
#fill { height:6px; background:var(--acc); border-radius:3px; width:0; }
main { padding:10px 16px 150px; } .imgs { display:flex; gap:8px; }
figure { margin:0; flex:1 1 0; min-width:0; max-width:640px; } figure img { width:100%; max-height:62vh; object-fit:contain; border:1px solid var(--line); cursor:zoom-in; display:block; background:#e9e6df; }
figcaption { font-size:12px; color:var(--mute); margin-top:3px; }
.btns { display:flex; gap:6px; flex-wrap:wrap; margin:0 0 6px; }
#controls { position:fixed; left:0; right:0; bottom:0; background:var(--bg); border-top:1px solid var(--line); padding:8px 16px; }
button { font:inherit; padding:7px 11px; border:1px solid var(--line); border-radius:8px; background:var(--chip); cursor:pointer; }
button:hover { border-color:var(--ink); } button.sel { background:var(--ink); color:#fff; border-color:var(--ink); }
button kbd { font:12px ui-monospace, monospace; color:var(--mute); margin-right:6px; } button.sel kbd { color:#ddd; }
.row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; } input[type=text] { font:inherit; padding:7px 10px; min-width:260px; border:1px solid var(--line); border-radius:8px; }
#over { position:fixed; inset:0; background:rgba(0,0,0,.85); display:none; align-items:center; justify-content:center; cursor:zoom-out; }
#over img { max-width:96vw; max-height:96vh; } #done { display:none; padding:24px 16px; }
textarea { width:100%; height:160px; font:12px ui-monospace, monospace; }
</style></head><body>
<header><b>Проверка __NAME__</b><span id="pos" class="mute"></span><div id="bar"><div id="fill"></div></div>
<span id="meta" class="mute"></span><span id="sync" class="mute"></span></header>
<main id="card">
  <div class="imgs" id="imgs"></div>
  <div id="controls"><div class="btns" id="btns"></div>
  <div class="row"><input type="text" id="note" placeholder="заметка (необязательно), Enter: сохранить">
    <button id="back"><kbd>←</kbd>назад</button><button id="skip"><kbd>→</kbd>дальше без метки</button></div>
  <span class="mute">Клавиши 1-8: класс и следующий контур. Щелчок по снимку: увеличить.</span></div></div>
</main>
<div id="done"><h2>Партия размечена</h2><p>Напиши в чате «готово», я заберу метки. Запасной вариант: скопируй текст ниже.</p>
<textarea id="dump" readonly></textarea><p><button id="again">вернуться к первому контуру</button></p></div>
<div id="over"><img id="bigimg" alt=""></div>
<script>
const NAME = "__NAME__", KEY = "baresand_owner_click_" + NAME;
const ITEMS = __ITEMS__;
const LABELS = __LABELS__;
let state = {}; try { state = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { state = {}; }
let i = ITEMS.findIndex(it => !state[it.id]); if (i < 0) i = ITEMS.length;
const $ = s => document.getElementById(s);
function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
function sync() {
  if (!Object.keys(state).length) return;
  fetch("/api/save/" + NAME, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state) })
    .then(r => r.json()).then(j => { $("sync").textContent = j.ok ? ("на диске: " + j.total) : "ошибка записи"; $("sync").style.color = j.ok ? "var(--ok)" : "var(--acc)"; })
    .catch(() => { $("sync").textContent = "нет связи с сервером: метки пока только в этом браузере"; $("sync").style.color = "var(--acc)"; });
}
function show() {
  const n = Object.keys(state).length;
  $("fill").style.width = (100 * n / ITEMS.length) + "%";
  if (i >= ITEMS.length) { $("card").style.display = "none"; $("done").style.display = "block";
    $("pos").textContent = n + " из " + ITEMS.length; $("dump").value = JSON.stringify(state); return; }
  $("card").style.display = "block"; $("done").style.display = "none";
  const it = ITEMS[i];
  $("pos").textContent = (i + 1) + " / " + ITEMS.length + " (размечено " + n + ")";
  $("meta").textContent = "id " + it.id + ", " + it.area_ha + " га, " + it.lat + " N " + it.lon + " E";
  $("imgs").innerHTML = it.imgs.map(m => `<figure><img src="${m.src}" alt="${m.cap}"><figcaption>${m.cap}</figcaption></figure>`).join("");
  document.querySelectorAll("#imgs img").forEach(im => im.onclick = () => { $("bigimg").src = im.src; $("over").style.display = "flex"; });
  const cur = state[it.id] ? state[it.id].label : null;
  $("btns").innerHTML = LABELS.map((l, k) => `<button data-l="${l[0]}" class="${cur === l[0] ? "sel" : ""}"><kbd>${k + 1}</kbd>${l[1]}</button>`).join("");
  document.querySelectorAll("#btns button").forEach(b => b.onclick = () => pick(b.dataset.l));
  $("note").value = state[it.id] && state[it.id].note ? state[it.id].note : "";
}
function pick(l) {
  const it = ITEMS[i];
  state[it.id] = { label: l, note: $("note").value.trim(), t: new Date().toISOString() };
  save(); sync(); i += 1; show();
}
$("back").onclick = () => { if (i > 0) { i -= 1; show(); } };
$("skip").onclick = () => { if (i < ITEMS.length) { i += 1; show(); } };
$("again").onclick = () => { i = 0; show(); };
$("over").onclick = () => { $("over").style.display = "none"; };
$("note").addEventListener("keydown", e => { if (e.key === "Enter") { const it = ITEMS[i]; if (state[it.id]) { state[it.id].note = $("note").value.trim(); save(); sync(); } e.target.blur(); } e.stopPropagation(); });
document.addEventListener("keydown", e => {
  if ($("over").style.display === "flex") { $("over").style.display = "none"; return; }
  const k = parseInt(e.key, 10);
  if (k >= 1 && k <= LABELS.length && i < ITEMS.length) { pick(LABELS[k - 1][0]); }
  else if (e.key === "ArrowLeft" || e.key === "Backspace") { if (i > 0) { i -= 1; show(); } e.preventDefault(); }
  else if (e.key === "ArrowRight") { if (i < ITEMS.length) { i += 1; show(); } }
});
show();
fetch("labels.json", { cache: "no-store" }).then(r => r.ok ? r.json() : {}).catch(() => ({})).then(srv => {
  for (const [k, v] of Object.entries(srv || {})) if (!state[k]) state[k] = v;
  save(); i = ITEMS.findIndex(it => !state[it.id]); if (i < 0) i = ITEMS.length; show(); sync();
});
</script></body></html>
"""


def build_page(out: Path, s: gpd.GeoDataFrame) -> None:
    img = out / 'img'
    img.mkdir(exist_ok=True)
    items = []
    for r in s.itertuples():
        i = int(r.id)
        pics = []
        for sub, suf, cap in (('esri', '_esri.png', 'Esri, обзор'), ('esri_zoom', '_esri.png', 'Esri, окно 0.8 км'),
                              ('s2', '_s2.png', 'Sentinel-2, лето 2024-2025 (период маски)')):
            src = out / sub / f'{i}{suf}'
            if src.exists():
                dst = img / f'{i}_{sub}.png'
                shutil.copyfile(src, dst)
                pics.append({'src': f'img/{dst.name}', 'cap': cap})
        items.append({'id': i, 'area_ha': round(float(r.area_ha), 2), 'lat': float(r.lat), 'lon': float(r.lon), 'imgs': pics})
    html = (PAGE.replace('__NAME__', out.name).replace('__ITEMS__', json.dumps(items, ensure_ascii=False))
            .replace('__LABELS__', json.dumps(LABELS, ensure_ascii=False)))
    (out / 'index.html').write_text(html, encoding='utf-8')
    miss = [it['id'] for it in items if len(it['imgs']) < 2]
    log(f'страница: {out / "index.html"}; контуров {len(items)}; без полного набора снимков: {miss}')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', default='O1')
    ap.add_argument('--n-burn', type=int, default=40)
    ap.add_argument('--n-v4', type=int, default=20)
    ap.add_argument('--seed-offset', type=int, default=0)
    ap.add_argument('--page-only', action='store_true')
    ap.add_argument('--pop-csv', default=None, help='совокупность с плечами (108): id, area_ha, arm')
    ap.add_argument('--n-arm-clear', type=int, default=40)
    ap.add_argument('--n-arm-burn', type=int, default=20)
    ap.add_argument('--arms', default=None, help='плечи и объёмы из --pop-csv: имя:n,имя:n')
    ap.add_argument('--resume', action='store_true', help='дорисовать снимки уже отобранной партии (выборка не меняется)')
    ap.add_argument('--census-arms', default=None, help='плечи, которые берутся целиком без исключения размеченных: имя,имя')
    a = ap.parse_args()
    cpu_limit.apply()
    t0 = time.time()
    out = OUT_ROOT / a.name
    out.mkdir(parents=True, exist_ok=True)
    if a.page_only:
        s = gpd.read_file(out / 'geoms.gpkg', layer='batch')
    elif a.resume:
        s = gpd.read_file(out / 'geoms.gpkg', layer='batch')
        log(f'продолжение партии {a.name}: {len(s)} контуров, отбор не меняется')
        render_esri(out, s)
        log(f'Esri: {len(list((out / "esri").glob("*.png")))} обзорных, '
            f'{len(list((out / "esri_zoom").glob("*.png"))) if (out / "esri_zoom").exists() else 0} приближенных')
        render_s2(out, s)
    else:
        s = select_arms(a) if a.pop_csv else select(a)
        s.to_file(out / 'geoms.gpkg', layer='batch', driver='GPKG')
        pd.DataFrame(s.drop(columns='geometry')).to_csv(out / 'batch.csv', index=False, encoding='utf-8')
        # драйверу рендера нужен слой sample с id
        s[['id', 'area_ha', 'geometry']].to_file(out / 'geoms.gpkg', layer='sample', driver='GPKG')
        render_esri(out, s)
        log(f'Esri: {len(list((out / "esri").glob("*.png")))} обзорных, '
            f'{len(list((out / "esri_zoom").glob("*.png"))) if (out / "esri_zoom").exists() else 0} приближенных')
        render_s2(out, s)
    build_page(out, s)
    log(f'готово | {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
