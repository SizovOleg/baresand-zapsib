// Прогон baresand_app.js в Node с заглушками ee/ui: ловит ошибки выполнения в логике панели, переключателях,
// смене масштаба, щелчке по карте и карточках атрибутов. Серверные вызовы ee не выполняются (цепочки-заглушки).
// Запуск: node repo/gee_app/_test/mock_run.js
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const log = [];
const evals = [];
const assetCalls = [];

function chain(name) {
  const f = function () {};
  return new Proxy(f, {
    get(t, p) {
      if (p === 'evaluate') return (cb) => evals.push({name, cb});
      if (p === Symbol.toPrimitive || p === 'toString') return () => name;
      if (p === 'then') return undefined;
      return chain(name + '.' + String(p));
    },
    apply(t, self, args) { return chain(name + '(' + args.length + ')'); },
    construct() { return chain('new ' + name); }
  });
}

const ee = chain('ee');
const eeData = {getAsset: (p, cb) => assetCalls.push({p, cb})};
const eeProxy = new Proxy(ee, {get(t, p) { return p === 'data' ? eeData : t[p]; }});

// --- виджеты ---
const all = [];
class Style { constructor(o) { this.o = Object.assign({}, o || {}); } set(k, v) { if (typeof k === 'object') Object.assign(this.o, k); else this.o[k] = v; return this; } get(k) { return this.o[k]; } }
class List { constructor(a) { this.a = (a || []).slice(); } add(w) { this.a.push(w); } reset(a) { this.a = (a || []).slice(); } set(i, w) { this.a[i] = w; } get(i) { return this.a[i]; } length() { return this.a.length; } }
class Widget {
  constructor(kind, o) { this.kind = kind; this.o = o || {}; this._style = new Style(this.o.style); all.push(this); }
  style() { return this._style; }
  setValue(v, trigger) { this.o.value = v; if (trigger && this.o.onChange) this.o.onChange(v); return this; }
  getValue() { return this.o.value; }
  onChange(cb) { this.o.onChange = cb; }
}
class Panel extends Widget {
  constructor(a, layout, style) {
    let o = {};
    if (Array.isArray(a) || a === undefined || a === null) o = {widgets: a || [], style};
    else o = a;
    super('Panel', o);
    this._w = new List(o.widgets || []);
  }
  widgets() { return this._w; }
  add(w) { if (!w) throw new Error('Panel.add(undefined)'); this._w.add(w); }
  clear() { this._w.reset([]); }
}
Panel.Layout = {flow: (d) => 'flow-' + d};
class Select extends Widget { constructor(o) { super('Select', o); this._items = new List(o.items || []); } items() { return this._items; } }
class MapLayer {
  constructor(kind, obj, vis, name, shown, opacity) { Object.assign(this, {kind, obj, vis, name, shown: shown !== false, opacity}); this.sets = 0; }
  setEeObject(o) { if (!o) throw new Error('setEeObject(null) ' + this.name); this.obj = o; this.sets++; }
  setShown(v) { this.shown = !!v; } getShown() { return this.shown; }
  setOpacity(v) { this.opacity = v; } setVisParams(v) { this.vis = v; }
}
class UiMap extends Widget {
  constructor() { super('Map', {}); this._layers = new List(); this.widgetsOn = []; }
  layers() { return this._layers; }
  setOptions() {} setControlVisibility() {} setCenter() {} centerObject() {}
  add(w) { this.widgetsOn.push(w); }
  onClick(cb) { this.click = cb; } onChangeZoom(cb) { this.zoomCb = cb; }
}
let theMap = null;
function PanelF(a, l, s) { return new Panel(a, l, s); }
PanelF.Layout = Panel.Layout;
const ui = {
  Panel: PanelF, Select: function (o) { return new Select(o); },
  Label: function (v, style) { const o = typeof v === 'object' && v !== null ? v : {value: v, style}; const w = new Widget('Label', o); return w; },
  Checkbox: function (o) { return new Widget('Checkbox', o); },
  Slider: function (o) { return new Widget('Slider', o); },
  Button: function (o) { return new Widget('Button', o); },
  SplitPanel: function (a, b) { return new Widget('SplitPanel', {a, b}); },
  Map: function () { theMap = new UiMap(); return theMap; },
  root: {clear() {}, add(w) { log.push('root.add ' + w.kind); }}
};
ui.Label.prototype = Widget.prototype;
ui.Map.Layer = function (obj, vis, name, shown, opacity) { return new MapLayer('Layer', obj, vis, name, shown, opacity); };
ui.Map.FeatureViewLayer = function (id, vis, name, shown, opacity) { return new MapLayer('FV', id, vis, name, shown, opacity); };
// у Label должен быть setValue
ui.Label = new Proxy(ui.Label, {apply(t, s, args) { return t.apply(s, args); }});

// --- прогон ---
let src = fs.readFileSync(path.join(__dirname, '..', 'baresand_app.js'), 'utf8');
const withFV = process.argv.includes('--fv');
src = src.replace("'projects/<PROJECT>/assets/baresand'", "'projects/test/assets/baresand'");
if (withFV) {
  src = src.replace(/(var FEATURE_VIEWS = \{\r?\n\s*contours: )''(,\r?\n\s*genesis: )''(,\r?\n\s*anthroIn: )''/,
    "$1'projects/test/assets/baresand/contours_fv'$2'projects/test/assets/baresand/genesis_fv'" +
    "$3'projects/test/assets/baresand/anthro_in_fv'");
  if (src.indexOf('genesis_fv') < 0) throw new Error('FEATURE_VIEWS не подставлены');
}
const ctx = vm.createContext({ee: eeProxy, ui, print: () => {}, Map: {}, Export: {}, console});
vm.runInContext(src, ctx, {filename: 'baresand_app.js'});
const L = vm.runInContext('LAYERS', ctx);
const st = vm.runInContext('state', ctx);
console.log('слоёв:', L.length, '| мест на карте:', theMap.layers().length(), '| запросов getAsset при старте:', assetCalls.length);

// ассеты: первая половина ok, затем пропавший растр классов
const missing = process.argv.includes('--missing-raster');
function flushAssets() {
  while (assetCalls.length) {
    const c = assetCalls.shift();
    const bad = missing && /genesis_r50/.test(c.p);
    c.cb(bad ? null : {type: 'TABLE'}, bad ? 'not found' : undefined);
  }
}
flushAssets();

// включить все чекбоксы, затем выключить и снова включить
const boxes = all.filter((w) => w.kind === 'Checkbox');
for (const b of boxes) { b.o.onChange(true); flushAssets(); }
for (const b of boxes) b.o.onChange(false);
for (const b of boxes) { b.o.onChange(true); flushAssets(); }
console.log('чекбоксов:', boxes.length, '| слоёв в панели:', all.filter((w) => w.kind === 'Checkbox' && w.o.style && w.o.style.width === '238px').map((w) => w.o.label).join('; '));
// все варианты всех списков
for (const s of all.filter((w) => w.kind === 'Select')) {
  for (const it of s.items().a) { s.o.onChange(typeof it === 'object' ? it.value : it); flushAssets(); }
}
// конкретный тайл и сцена-кандидат
const tileSel = all.find((w) => w.kind === 'Select' && w.items().a.some((i) => i.value === 'ALL'));
tileSel.o.onChange('45WVQ');
const sceneSel = all.find((w) => w.kind === 'Select' && w.items().a.some((i) => /кандидат/.test(i.label)));
console.log('сцен у 45WVQ в списке:', sceneSel ? sceneSel.items().a.length : 0);
if (sceneSel) sceneSel.o.onChange(sceneSel.items().a[1].value);
// слайдеры
for (const s of all.filter((w) => w.kind === 'Slider')) s.o.onChange(0.3);
// масштабы
for (const z of [3, 5, 8, 9, 10, 11, 14, 6]) theMap.zoomCb(z);
// щелчок
theMap.zoomCb(12);
theMap.click({lon: 72.5, lat: 65.5});
console.log('запросов evaluate по щелчку:', evals.length);
for (const e of evals) e.cb(null, undefined);           // пустые ответы
theMap.click({lon: 72.5, lat: 65.5});
for (const e of evals.slice(-50)) e.cb(undefined, 'Error: asset not found');  // ошибки
// карточки на типичных ответах
const samples = {
  // схема ассетов 150 (поля, прочитанные из ассетов 18.11.2026) и расширенная схема prepare_assets.py
  genesis: [{id: 185329, genesis: 'aeolian', gcode: 1, area_ha: 0.09},
            {id: 11, genesis: 'anthropogenic', gcode: 5, area_ha: 12.3, step6_rule: 'v7_agent_techno'},
            {id: 12, genesis: 'shoal', gcode: 4, area_ha: 250.5, step6_rule: 'v4_transfer'},
            {id: 97550, genesis: 'anthropogenic', gen_main: 'anthropogenic', area_ha: 0.37, rule: 'v4_a_nspd_on', rule_step: 3,
             step6_rule: '', gen_v6: 'anthropogenic', note: '', cad_status: 'in', cad_in_ha: 0.3264, cad_out_ha: 0.0436,
             exc10_ha: 0, age2000: 'new', gcode: 5},
            {id: 5, genesis: 'river_shoal', gen_main: 'alluvial_littoral', shoal_type: 'river', shoal_src: 'rule', area_ha: 1234.5,
             rule: 'v3_B1_channel_cross', rule_step: 5, step6_rule: 'v4_expert', gen_v6: 'aeolian', note: 'речная отмель'},
            {id: 7, genesis: 'aeolian', area_ha: 2, rule: 'step4', rule_step: 4}, null],
  contours: [{id: 297258}, {id: 1, area_ha: 0.09}, null],
  density: [0, null, 12.5],
  anthroIn: [{age2000: 'mid', area_ha: 0.0911, grp: 'ezp', id: 392764, _dist: 0},
             {id: 1, grp: 'ind', grp_ru: 'земли промышленности', area_ha: 2.5, ge_mmu: 1, age2000: 'old', _dist: 0}, null],
  anthroExceed: [{age2000: 'mid', area_ha: 0.264, id: 462242, in_pct: 10},
                 {id: 1, area_ha: 2.5, in_ha: 1.2, ctr_ha: 4, in_pct: 48.1, age2000: 'mid'}],
  anthroNoallot: [{age2000: 'old', area_ha: 0.09, id: 28284, in_pct: 0, kind: 'none', under: 'forest'},
                  {age2000: 'new', area_ha: 3.5, id: 28285, in_pct: 4, kind: 'touch', under: 'none'},
                  {id: 1, area_ha: 2.5, under_ru: 'вне участков', age2000: 'na', newfield: 'x'}],
  oilfields: [{name_ru: 'Ямбургское', type: 'gas', stage_ru: 'разрабатываемое'}, null],
  dem: [15.3, null], gsw: [80, null], hansen: [{treecover2000: 12, lossyear: 5}, {treecover2000: null, lossyear: 0}, null],
  s2: [['20240705T071621_20240705T071621_T41VPK'], []], tiles: [['41VPK'], []]
};
const printCards = {genesis: [185329, 11], anthroIn: [392764], anthroExceed: [462242], anthroNoallot: [28284, 28285], contours: [297258]};
let cards = 0;
for (const l of L) {
  if (!l.render) continue;
  for (const smp of samples[l.id] || []) {
    const rows = l.render(smp);
    for (const r of rows) if (r.length !== 2 || typeof r[0] !== 'string' || typeof r[1] !== 'string') throw new Error('строка карточки ' + l.id + ': ' + JSON.stringify(r));
    cards++;
    if (smp && (printCards[l.id] || []).indexOf(smp.id) >= 0) console.log('карточка ' + l.id + ':', JSON.stringify(rows));
  }
}
console.log('карточек проверено:', cards);
const shown = L.filter((l) => l.mapLayer && l.mapLayer.getShown()).map((l) => l.id);
console.log('видимые слои на масштабе 12:', shown.join(', '));
const st2 = L.filter((l) => l.status && l.status.o.value).map((l) => l.id + ': ' + l.status.o.value);
console.log('статусы:', st2.length ? st2.join(' | ') : 'нет');
const fv = theMap.layers().a.filter((x) => x.kind === 'FV').map((x) => x.name + (x.shown ? ' (показан)' : ''));
console.log('FeatureView:', fv.length ? fv.join(', ') : 'нет');
console.log('OK');
