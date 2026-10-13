"""
143_control_review.py - страница просмотра меток T3 на промахи клавиш (2026-10-06).

Все 150 контуров партии T3 сеткой миниатюр, сгруппированы по метке автора (группа выборки и решения модели не
показываются, просмотр одинаковый для всех контуров). Щелчок по миниатюре: снимки крупно и кнопки 1-8. Исправления
пишутся отдельно: exports/qc/owner_click/T3r/labels.json (сервер owner_click_server.py, POST /api/save/T3r); исходный
T3/labels.json не меняется. 142_control_estimates.py применяет исправления и перечисляет их в отчёте.
Выход: exports/qc/owner_click/T3r/index.html, thumb/.
Запуск: PYTHONIOENCODING=utf-8 python -u python/143_control_review.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import json
from pathlib import Path

import pandas as pd
from PIL import Image

ROOT = Path(r'D:\test\baresand_zapsib')
OC = ROOT / 'exports' / 'qc' / 'owner_click'
SRC = OC / 'T3'
OUT = OC / 'T3r'
THUMB_H = 240
LABELS = [('lake_shoal', 'озёрная отмель'), ('river_shoal', 'речная отмель'), ('shoal', 'морская отмель'),
          ('aeolian', 'эоловый'), ('anthropogenic', 'техноген'), ('not_sand', 'не песок'), ('mixed', 'смешанный'),
          ('disputed', 'спорный')]

PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Просмотр T3</title>
<style>
:root { --bg:#f6f5f2; --ink:#1d1d1b; --mute:#6b6a66; --line:#d9d6cf; --acc:#b3372e; --chip:#ffffff; --ok:#2e7d4f; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { position:sticky; top:0; z-index:2; background:var(--bg); display:flex; gap:16px; align-items:baseline;
  padding:10px 16px; border-bottom:1px solid var(--line); flex-wrap:wrap; }
header b { font-size:17px; } .mute { color:var(--mute); }
main { padding:6px 16px 40px; } h2 { font-size:16px; margin:18px 0 8px; } h2 .mute { font-weight:normal; }
.grid { display:flex; flex-wrap:wrap; gap:8px; }
.card { background:var(--chip); border:2px solid var(--line); border-radius:6px; padding:3px; cursor:pointer; }
.card:hover { border-color:var(--ink); } .card img { height:__H__px; display:block; }
.card .cap { font-size:12px; color:var(--mute); padding:2px 2px 0; display:flex; justify-content:space-between; gap:6px; }
.card.fix { border-color:var(--acc); } .card.fix .cap b { color:var(--acc); }
#modal { position:fixed; inset:0; background:rgba(0,0,0,.6); display:none; z-index:5; }
#box { position:absolute; inset:2vh 2vw; background:var(--bg); border-radius:8px; padding:10px 14px; display:flex; flex-direction:column; }
.imgs { display:flex; gap:8px; flex:1; min-height:0; } figure { margin:0; flex:1 1 0; min-width:0; display:flex; flex-direction:column; }
figure:first-child { flex:2 1 0; } figure img { width:100%; flex:1; min-height:0; object-fit:contain; background:#e9e6df; border:1px solid var(--line); }
figcaption { font-size:12px; color:var(--mute); margin-top:3px; }
.btns { display:flex; gap:6px; flex-wrap:wrap; margin:8px 0 6px; }
button { font:inherit; padding:7px 11px; border:1px solid var(--line); border-radius:8px; background:var(--chip); cursor:pointer; }
button:hover { border-color:var(--ink); } button.sel { background:var(--ink); color:#fff; border-color:var(--ink); }
button.orig { outline:2px dashed var(--mute); outline-offset:1px; }
button kbd { font:12px ui-monospace, monospace; color:var(--mute); margin-right:6px; } button.sel kbd { color:#ddd; }
.row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
input[type=text] { font:inherit; padding:7px 10px; min-width:300px; border:1px solid var(--line); border-radius:8px; }
</style></head><body>
<header><b>Просмотр T3 на промахи</b>
<span class="mute">Контуры сгруппированы по вашей метке. Если снимок стоит не в своей группе, щёлкните его и нажмите
верную клавишу 1-8. Исправления сохраняются отдельно, исходные метки не меняются.</span>
<span id="cnt"></span><span id="sync" class="mute"></span></header>
<main id="main"></main>
<div id="modal"><div id="box">
  <div class="row"><b id="mt"></b><span id="mo" class="mute"></span><span style="flex:1"></span><button id="close"><kbd>Esc</kbd>закрыть без изменений</button></div>
  <div class="imgs" id="imgs"></div>
  <div class="btns" id="btns"></div>
  <div class="row"><input type="text" id="note" placeholder="заметка (необязательно)">
  <span class="mute">Клавиши 1-8: метка и закрыть. Пунктир: ваша исходная метка; выбрать её снова значит отменить исправление.</span></div>
</div></div>
<script>
const NAME = "T3r", KEY = "baresand_owner_click_" + NAME;
const ITEMS = __ITEMS__;
const ORIG = __ORIG__;
const LABELS = __LABELS__;
const RU = Object.fromEntries(LABELS);
let fix = {}; try { fix = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { fix = {}; }
let cur = null;
const $ = s => document.getElementById(s);
function save() { try { localStorage.setItem(KEY, JSON.stringify(fix)); } catch (e) {} }
function sync() {
  if (!Object.keys(fix).length) return;
  fetch("/api/save/" + NAME, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fix) })
    .then(r => r.json()).then(j => { $("sync").textContent = j.ok ? "сохранено на диске" : "ошибка записи"; $("sync").style.color = j.ok ? "var(--ok)" : "var(--acc)"; })
    .catch(() => { $("sync").textContent = "нет связи с сервером: исправления пока только в этом браузере"; $("sync").style.color = "var(--acc)"; });
}
const eff = id => (fix[id] ? fix[id].label : ORIG[id]);
function render() {
  const n = ITEMS.filter(it => eff(it.id) !== ORIG[it.id]).length;
  $("cnt").innerHTML = "исправлено: <b>" + n + "</b>";
  $("main").innerHTML = LABELS.map(([l, ru]) => {
    const its = ITEMS.filter(it => ORIG[it.id] === l);
    if (!its.length) return "";
    return `<h2>${ru} <span class="mute">(${its.length})</span></h2><div class="grid">` + its.map(it => {
      const e = eff(it.id), changed = e !== ORIG[it.id];
      return `<div class="card${changed ? " fix" : ""}" data-id="${it.id}"><img src="${it.thumb}" alt="">` +
        `<div class="cap"><span>${it.id}, ${it.area_ha} га</span>${changed ? "<b>теперь: " + RU[e] + "</b>" : ""}</div></div>`;
    }).join("") + "</div>";
  }).join("");
  document.querySelectorAll(".card").forEach(c => c.onclick = () => open(+c.dataset.id));
}
function open(id) {
  cur = ITEMS.find(it => it.id === id);
  $("mt").textContent = "id " + id + ", " + cur.area_ha + " га";
  $("mo").textContent = "ваша метка: " + RU[ORIG[id]] + (eff(id) !== ORIG[id] ? "; исправлено на: " + RU[eff(id)] : "");
  $("imgs").innerHTML = cur.imgs.map(m => `<figure><img src="${m.src}" alt=""><figcaption>${m.cap}</figcaption></figure>`).join("");
  $("btns").innerHTML = LABELS.map((l, k) => `<button data-l="${l[0]}" class="${eff(id) === l[0] ? "sel" : ""} ${ORIG[id] === l[0] ? "orig" : ""}"><kbd>${k + 1}</kbd>${l[1]}</button>`).join("");
  document.querySelectorAll("#btns button").forEach(b => b.onclick = () => pick(b.dataset.l));
  $("note").value = fix[id] && fix[id].note ? fix[id].note : "";
  $("modal").style.display = "block";
}
function close() { $("modal").style.display = "none"; cur = null; }
function pick(l) {
  if (!cur) return;
  fix[cur.id] = { label: l, note: $("note").value.trim(), t: new Date().toISOString() };
  save(); sync(); close(); render();
}
$("close").onclick = close;
$("modal").onclick = e => { if (e.target === $("modal")) close(); };
$("note").addEventListener("keydown", e => { if (e.key === "Enter") e.target.blur(); e.stopPropagation(); });
document.addEventListener("keydown", e => {
  if (!cur) return;
  if (e.key === "Escape") { close(); return; }
  const k = parseInt(e.key, 10);
  if (k >= 1 && k <= LABELS.length) pick(LABELS[k - 1][0]);
});
render();
fetch("labels.json", { cache: "no-store" }).then(r => r.ok ? r.json() : {}).catch(() => ({})).then(srv => {
  for (const [k, v] of Object.entries(srv || {})) if (!fix[k] || fix[k].t < v.t) fix[k] = v;
  save(); render();
});
</script></body></html>
"""


def main() -> None:
    orig = json.loads((SRC / 'labels.json').read_text(encoding='utf-8'))
    b = pd.read_csv(SRC / 'batch.csv')
    if set(map(int, orig)) != set(b['id']):
        raise ValueError('метки T3 не совпадают с партией')
    (OUT / 'thumb').mkdir(parents=True, exist_ok=True)
    items = []
    for r in b.sort_values('area_ha', ascending=False).itertuples():
        i = int(r.id)
        im = Image.open(SRC / 'img' / f'{i}_esri.jpg').convert('RGB')
        im.thumbnail((10_000, THUMB_H * 2), Image.LANCZOS)
        im.save(OUT / 'thumb' / f'{i}.jpg', quality=85)
        cap = ('Esri: слева обзор, справа крупный план' if r.area_ha >= 5 else 'Esri: окно не меньше 500 м')
        imgs = [{'src': f'../T3/img/{i}_esri.jpg', 'cap': cap}]
        if (SRC / 's2' / f'{i}_s2.png').exists():
            imgs.append({'src': f'../T3/s2/{i}_s2.png', 'cap': 'Sentinel-2, лето 2024-2025 (период маски)'})
        items.append({'id': i, 'area_ha': round(float(r.area_ha), 2), 'thumb': f'thumb/{i}.jpg', 'imgs': imgs})
    html = (PAGE.replace('__H__', str(THUMB_H)).replace('__ITEMS__', json.dumps(items, ensure_ascii=False))
            .replace('__ORIG__', json.dumps({k: v['label'] for k, v in orig.items()}, ensure_ascii=False))
            .replace('__LABELS__', json.dumps(LABELS, ensure_ascii=False)))
    (OUT / 'index.html').write_text(html, encoding='utf-8')
    print(f'страница: {OUT / "index.html"}; контуров {len(items)}')


if __name__ == '__main__':
    main()
