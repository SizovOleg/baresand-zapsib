"""
133_cadastre_anthro.py - техногенные пески внутри и вне кадастровых отводов под объекты (2026-10-04, просьба владельца).

Владелец: «считать строго без тех участков, которые и так отведены под землепользование»; нужны отводы под сами
объекты, эоловые не трогаем; расхождение кадастра и маски исправить привязкой, если сдвиг систематический (оценка
грубая, опциональная). Процессор: все ядра, кроме двух (cpu_limit.apply_heavy), или --cores n (cpu_limit.apply_cores).

Данные: продукт exports/baresand_genesis_step6_v5.gpkg (класс anthropogenic); земельные участки ЕГРН (НСПД 36368,
снимок 08.09.2026) из проекта владельца E:/cadastre-local/data/layers/parcels_89.gpkg и parcels_86.gpkg (только чтение).
Отводы под объекты (группа участка, по приоритету): ind = категория «Земли промышленности, энергетики, транспорта...»;
np = земли населённых пунктов; vri = иная категория, но объектовый ВРИ (недропользование, месторождения, линейные
объекты, трубопроводы, ЛЭП, дороги, склады и т. п.; токены с начала слова и аббревиатуры ВЛ, ДНС, КНС...), кроме общего
перечня видов использования лесов по ст. 25 ЛК (лесные кварталы) и дач, торговли и т. п. Прочие: unk (части ЕЗП,
обособленные и условные участки без категории и ВРИ: назначение неизвестно, верхняя граница «внутри» с ними), forest,
agri, misc. Правила ВРИ уточнены по проверке агентами 2026-10-04.
Привязка: окна 4 x 4 км с наибольшей площадью техногенных песков; в каждом растр 2,5 м контуров и отводов, взаимная
корреляция (FFT) в пределах +-40 м. Оценки отдельных окон шумны (отводы крупнее контуров), поэтому сдвиг региона берётся
по пику суммарной поверхности перекрытия и применяется, если выигрыш не меньше 1 % и модуль не меньше 5 м; иначе 0.
Оверлей: контур ∩ объединение отводов, площади по группам без двойного счёта (ind, затем vri, затем np); вне отводов =
контур минус объединение. Покрытие: Красноярский край (Туруханский район и восточный сектор вне районов OSM восточнее
79° в. д.) кадастра не имеет, cad_cov = 0.
Выход: exports/baresand_genesis_step6_v6.gpkg = v5 + поля cad_* (классы не меняются); exports/baresand_anthro_cadastre.gpkg
(слои anthro_in, anthro_out, parcels, shift_windows); exports/qc/cadastre/ (cadastre_anthro.md, shift_windows.csv,
render_*.png). Запуск: PYTHONIOENCODING=utf-8 python -u python/133_cadastre_anthro.py [--force]

Выход за границы отвода (уточнение владельца 2026-10-06): cad_status in / cross (часть контура дальше 10 м от отвода под
объект, куски не меньше 900 м2: искомое нарушение) / unreg (участка с объектовым назначением ближе 10 м нет) / nocad; площади
выхода cad_exc10_ha, cad_exc20_ha (допуск 20 м), cad_exc10u_ha (части ЕЗП тоже отвод); слои anthro_excess (части за
отводом, in_pct = доля контура в отводе) и anthro_unreg (контуры без отвода целиком, under = что под ними).
Обобщение для v7 (2026-10-06): пути и подпись задаются параметрами (по умолчанию прежние): --src, --out-product,
--out-layers, --qc, --label (подпись в скобках заголовка отчёта), --cores; относительные пути считаются от корня проекта.
Источник, производный от v6, уже несёт поля cad_* и age2000: они удаляются и считаются заново (без дублей _x/_y).
Возраст техногенного контура age2000 (поле продукта рядом с cad_* и слоёв anthro_in / anthro_out; у прочих классов пусто):
new / mid / old / na по доле голого песка в 2000 (bare2000_frac, Hansen GFC 30 м, скрипт 66) с порогами шага 3
(python/62_step3_rule.py, DEFAULTS: new_bare_max = 0.30, old_bare_min = 0.70); в отчёте таблица по возрасту.
Пример (v7): PYTHONIOENCODING=utf-8 python -u python/133_cadastre_anthro.py --src ИСТОЧНИК_v7.gpkg
  --out-product exports/final/baresand_genesis_v7.gpkg --out-layers exports/final/baresand_anthro_cadastre_v7.gpkg
  --qc exports/qc/cadastre_v7 --label "133, v7"
Отводы под локальные объекты (автор 13.10.2026: «дороги и трубопроводы выпали повсеместно»; «правильно выделить все
отводы, именно для локальных объектов»). Формальное правило по полям ЕГРН (порядок проверки):
1) категория «земли промышленности...» -> ind; 2) категория «земли населённых пунктов» -> np (территория НП, вариант А);
3) иная категория и объектовый ВРИ -> vri; 4) --ezp: категории и ВРИ нет, подтип «обособленный» или «условный участок»
(часть единого землепользования; категория и ВРИ у родительского ЕЗП, которого нет в публичной выдаче НСПД) -> ezp;
5) лесной фонд, сельхозназначение, прочее -> forest, agri, misc; категории нет и не часть ЕЗП -> unk.
--local-max-ha X: контур (часть многоконтурного участка) групп ind, vri, ezp крупнее X га -> big (территориальная аренда
или условный участок на весь район, а не отвод под объект); прочие контуры того же участка остаются в своей группе.
Без флагов расчёт совпадает с v7a (группы ezp и big пусты).
"""
import argparse
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from rasterio import features
from rasterio.transform import from_origin
from scipy.signal import correlate

import cpu_limit

ROOT = Path(r'D:\test\baresand_zapsib')
SRC = ROOT / 'exports' / 'baresand_genesis_step6_v5.gpkg'
OUT_PRODUCT = ROOT / 'exports' / 'baresand_genesis_step6_v6.gpkg'
OUT_LAYERS = ROOT / 'exports' / 'baresand_anthro_cadastre.gpkg'
QC = ROOT / 'exports' / 'qc' / 'cadastre'
LABEL = '133, 2026-10-04'           # подпись в скобках заголовка отчёта (по умолчанию прежний заголовок)
ADMIN = ROOT / 'exports' / 'aux' / 'admin6_aoi.gpkg'
PARCELS = [Path(r'E:\cadastre-local\data\layers\parcels_89.gpkg'), Path(r'E:\cadastre-local\data\layers\parcels_86.gpkg')]
# Красноярский край (владелец поставил на докачку 2026-10-06): только с --kras, чтобы недокачанный файл не попал в расчёт
PARCELS_KRAS = Path(r'E:\cadastre-local\data\layers\parcels_24.gpkg')
CRS = 3576
NEAR_M = 60.0                     # участки ближе к техногенному контуру (запас под сдвиг)
WIN_M, RES, MAXSHIFT_M = 4000.0, 2.5, 40.0
N_WIN, MIN_WIN_HA = 400, 10.0
MMU_M2 = 900.0
# выход за границу отвода (уточнение владельца 2026-10-06): «нет отвода» (участок не найден) и «выход за отвод»
# (часть контура в отводе, часть за ним: искомое нарушение) различаются. Полоса вдоль границы отвода шириной в пиксель
# маски (10 м) принимается техническим допуском (не измеренной погрешностью); вариант 20 м; части меньше MMU отбрасываются
EXC_T = (10.0, 20.0)
STATUS_RU = {'in': 'в отводе', 'cross': 'превышение отвода',
             'unreg': 'без отвода (отвода ближе 10 м нет или в отводе меньше 10 % контура)',
             'nocad': 'нет кадастра (Красноярский край)'}
# вариант А (автор 13.10.2026): контур, лишь касающийся чужого отвода (в отводе меньше TOUCH_FRAC площади, часть дальше
# допуска), это отдельный объект без отвода, а не превышение; учитывается площадь всего объекта (слой anthro_noallot)
TOUCH_FRAC = 0.10
EAST_LON = 79.0
# объектовый ВРИ: токены подстрокой (ловят «автодорога», «гидрокарьер»), «хранени» только с начала слова («сохранение»
# не объект), без учёта регистра; аббревиатуры объектов с учётом регистра
OBJ_RE = (r'недр|месторожд|полезн|добыч|карьер|линейн|трубопров|нефт|газ|скважин|куст|промышл|производств|'
          r'энергет|энерго|электр|связ|дорог|автомобил|автозимник|транспорт|склад|(?<![а-яё])хранени|строительств|размещени|'
          r'обустрой|инженерн|коммунал|причал|порт|аэро|вертол|лэп|подстанц|водовод|водоснабж|теплоснабж|канализ|очистн|'
          r'коммуникац|конденсатопров|продуктопров|топливозаправ|вахтов|полигон бытовых|радиобашн|антенн|под объект|'
          r'объекты недвижимости')
OBJ_CS_RE = r'\bВЛ|\d\s*кВ|\bПС\b|\bАЗС|УПСВ|\bДНС|\bКНС|\bКС\b|УКПГ|ЦПС|\bГКМ|ЦРРЛ'
# не отвод под объект: общий перечень видов использования лесов (ст. 25 ЛК) у лесных кварталов (по «недревесным»
# ресурсам; «заготовка древесины» сама по себе не признак: она стоит и в арендах под недропользование и линейные объекты),
# дачи, торговля, охота и т. п.
GENERIC_RE = r'недревесн|не древесн|пищевых лесных|лекарственных растений'
NOT_OBJ_RE = (r'дачн|садов|огород|жилищн|(?<![а-яё])ижс|магазин|(?<![а-яё])спорт|земель запаса|туристич|баз[уаы] отдыха|'
              r'сельскохозяйственного производства|сельскохозяйственной продукции|охотнич|биоресурс')
BIG_VRI_HA = 1000.0                                  # отвод vri крупнее этого порога показывается в отчёте отдельно
MIN_GAIN, MIN_SHIFT_M = 0.01, 5.0                    # сдвиг региона: выигрыш суммарного перекрытия >= 1 % и модуль >= 5 м
# отводы под объекты; terr: территория населённых пунктов (151: замыкание земель НП, дачи, жилая застройка, аэродромы,
# вахтовые посёлки), считается отводом целиком (вариант А, автор 13.10.2026); подаётся --territory, иначе пустая
# ezp и big заполняются только с --ezp и --local-max-ha (см. описание выше); константы общие с рабочими процессами
GROUPS_IN = ('ind', 'vri', 'ezp', 'np', 'terr')
GROUPS_OUT = ('big', 'unk', 'forest', 'agri', 'misc')  # прочие: крупные контуры, категория не указана, лесной фонд, сельхоз, иное
EZP_SUBTYPES = ('Обособленный участок', 'Условный участок')
GROUP_RU = {'ind': 'промышленные земли', 'vri': 'ВРИ под объекты в иных категориях', 'np': 'земли населённых пунктов',
            'ezp': 'части единых землепользований (обособленные и условные участки; категория и ВРИ у родительского ЕЗП)',
            'terr': 'территория населённых пунктов вне участков (улицы, дачи, аэродромы, вахтовые посёлки)',
            'big': 'крупные контуры отводов (территориальные аренды, не локальный объект)',
            'unk': 'назначение неизвестно (участки без категории и ВРИ, не части ЕЗП; без --ezp и части ЕЗП)',
            'forest': 'лесной фонд без объектового ВРИ',
            'agri': 'сельхозназначение без объектового ВРИ', 'misc': 'иные участки (запас, ООПТ, водный фонд)',
            'none': 'вне любых участков'}
# возраст техногена по Hansen-2000 (доля голого песка в 2000, bare2000_frac): пороги шага 3, python/62_step3_rule.py,
# DEFAULTS new_bare_max = 0.30 (new_sand, «не голый в 2000») и old_bare_min = 0.70 (old_sand, «голый уже в 2000»)
NEW_BARE_MAX, OLD_BARE_MIN = 0.30, 0.70
AGE_ORDER = ('new', 'mid', 'old', 'na')
COLS_P = {'/options/cad_num': 'cad_num', '/options/land_record_category_type': 'cat', '/options/category_name': 'cat2',
          '/options/permitted_use_established_by_document': 'vri', '/options/land_record_subtype': 'subtype'}


def log(msg: str) -> None:
    print(f'{time.strftime("%H:%M:%S")} {msg}', flush=True)


def as_poly(geoms) -> np.ndarray:
    """make_valid и только полигональная часть (Polygon / MultiPolygon); пустое, если полигонов нет."""
    g = shapely.make_valid(np.asarray(geoms))
    t = shapely.get_type_id(g)
    bad = ~np.isin(t, (3, 6))                       # 3 Polygon, 6 MultiPolygon
    for i in np.flatnonzero(bad):
        parts = [p for p in shapely.get_parts(g[i]) if shapely.get_type_id(p) in (3, 6)]
        g[i] = shapely.union_all(parts) if parts else shapely.Polygon()
    return g


def age2000(bare2000: pd.Series) -> pd.Series:
    """Возраст техногенного контура по доле голого песка в 2000 (bare2000_frac, Hansen GFC 30 м, скрипт 66):
    new: голого меньше NEW_BARE_MAX (появился после 2000); old: не меньше OLD_BARE_MIN (голый уже в 2000);
    mid: между порогами; na: данных Hansen нет (bare2000_frac пуст, вне покрытия мозаик).
    Наличие данных берётся по самому bare2000_frac: в 62 hansen_covered = bare2000_frac.notna() (строки 215, 263),
    но в v6 у 33 контуров разреза (id 800000-800084) флаг устарел (0 при измеренном bare2000_frac), а у 3 контуров
    v5_mixed_owner пусты оба поля; где флаг согласован (все прочие), правило совпадает с «hansen_covered = 1»."""
    b = pd.to_numeric(bare2000, errors='coerce')
    has = b.notna()
    out = np.select([has & (b < NEW_BARE_MAX), has & (b >= OLD_BARE_MIN), has], ['new', 'old', 'mid'], 'na')
    return pd.Series(out, index=bare2000.index, dtype=object)


def proj_path(s: str) -> Path:
    """Путь из параметра: относительный считается от корня проекта (не от текущей папки)."""
    p = Path(s)
    return p if p.is_absolute() else ROOT / p


# ---------- привязка ----------

def best_shift(args: tuple) -> dict:
    """Сдвиг отводов (м), при котором их растр сильнее всего перекрывает растр техногенных контуров окна."""
    key, x0, y0, t_wkb, p_wkb = args
    pad = MAXSHIFT_M
    n = int(round((WIN_M + 2 * pad) / RES))
    tr = from_origin(x0 - pad, y0 + WIN_M + pad, RES, RES)
    A = features.rasterize(((g, 1) for g in shapely.from_wkb(t_wkb)), out_shape=(n, n), transform=tr, dtype='uint8')
    B = features.rasterize(((g, 1) for g in shapely.from_wkb(p_wkb)), out_shape=(n, n), transform=tr, dtype='uint8')
    if A.sum() == 0 or B.sum() == 0:
        return dict(key=key, ok=False)
    z = correlate(A.astype(np.float32), B.astype(np.float32), mode='full', method='fft')
    c = n - 1                                   # индекс нулевого лага; лаг L: B сдвинут на +L пикселей
    s = int(MAXSHIFT_M / RES)
    sub = z[c - s:c + s + 1, c - s:c + s + 1]
    r, k = np.unravel_index(np.argmax(sub), sub.shape)
    lag_r, lag_c = r - s, k - s
    zero = max(float(z[c, c]), 0.0)             # отрицательный шум FFT около нуля
    return dict(key=key, ok=True, dx=lag_c * RES, dy=-lag_r * RES, overlap0=zero * RES * RES / 1e4,
                overlap_best=float(sub[r, k]) * RES * RES / 1e4, techno_ha=A.sum() * RES * RES / 1e4,
                allot_ha=B.sum() * RES * RES / 1e4, surf=np.clip(sub, 0, None).astype(np.float32) * RES * RES / 1e4)


def self_test() -> None:
    """Проверка знака сдвига на синтетике: отводы смещены на (-10, +7,5) м, найденный сдвиг (+10, -7,5)."""
    sq = shapely.box(1000, 1000, 1600, 1400)
    t = [shapely.to_wkb(sq)]
    p = [shapely.to_wkb(shapely.affinity.translate(sq, -10, 7.5))]
    r = best_shift(('test', 0.0, 0.0, t, p))
    assert abs(r['dx'] - 10) < 1e-6 and abs(r['dy'] + 7.5) < 1e-6, r
    # возраст: границы порогов и пустые значения
    b = pd.Series([0.0, 0.29, NEW_BARE_MAX, 0.69, OLD_BARE_MIN, 1.0, np.nan, None], dtype=object)
    got = age2000(b).tolist()
    assert got == ['new', 'new', 'mid', 'mid', 'old', 'old', 'na', 'na'], got
    # выход за отвод: контур 200 x 100 м, отвод на левой половине -> выход 200 x 100 минус (100 + 10) x 100 = 9 000 м2
    t = shapely.box(0, 0, 200, 100)
    P = np.array([shapely.box(-50, -50, 100, 150), shapely.box(500, 500, 600, 600)])
    g = np.array(['ind', 'forest'])
    e = excess(t, P, np.array([0, 1]), g, GROUPS_IN, 10.0)
    assert e is not None and abs(shapely.area(e) - 9000) < 1, shapely.area(e)
    assert excess(t, P, np.array([1]), g, GROUPS_IN, 10.0) is None          # нет отвода -> None
    far = np.array([shapely.box(215, 0, 300, 100)])                         # отвод в 15 м: при 10 м нет, при 20 м есть
    assert excess(t, far, np.array([0]), np.array(['ind']), GROUPS_IN, 10.0) is None
    assert excess(t, far, np.array([0]), np.array(['ind']), GROUPS_IN, 20.0) is not None


# ---------- оверлей ----------

def big_parts(g: shapely.Geometry, min_m2: float = MMU_M2) -> shapely.Geometry:
    """Полигоны геометрии не меньше min_m2 (MultiPolygon или пустой полигон)."""
    ps = [p for p in shapely.get_parts(as_poly([g])[0]) if shapely.area(p) >= min_m2] if not shapely.is_empty(g) else []
    return shapely.MultiPolygon(ps) if ps else shapely.Polygon()


def excess(t: shapely.Geometry, P: np.ndarray, near: np.ndarray, groups: np.ndarray, use: tuple[str, ...],
           dist: float) -> shapely.Geometry | None:
    """Часть контура t дальше dist от участков групп use (из near: индексы участков в пределах max(EXC_T)), куски не
    меньше MMU; None, если таких участков ближе dist нет (отвода нет)."""
    js = near[np.isin(groups[near], use)]
    if not len(js):
        return None
    box = shapely.box(*(np.asarray(t.bounds) + np.array([-1, -1, 1, 1]) * (max(EXC_T) + 1)))
    U = shapely.union_all(shapely.intersection(P[js], box))
    if shapely.is_empty(U) or not shapely.dwithin(t, U, dist):
        return None
    return big_parts(shapely.difference(t, shapely.buffer(U, dist)))


def overlay_chunk(args: tuple) -> tuple[list, list, list, list]:
    """Площади контуров внутри отводов по группам (без двойного счёта) и вне; выход за границы отвода (EXC_T);
    геометрии частей для слоёв."""
    ids, t_wkb, p_wkb, p_grp, p_cad = args
    T = shapely.from_wkb(t_wkb)
    P = shapely.from_wkb(p_wkb)
    grp = np.asarray(p_grp)
    cad = np.asarray(p_cad)
    tree = shapely.STRtree(P)
    empty = (np.array([], int), np.array([], int))
    ti, pi = tree.query(T, predicate='intersects') if len(P) else empty
    order = np.argsort(ti, kind='stable')
    ti, pi = ti[order], pi[order]
    starts = np.searchsorted(ti, np.arange(len(T)))
    ends = np.searchsorted(ti, np.arange(len(T)), side='right')
    di, dj = tree.query(T, predicate='dwithin', distance=max(EXC_T)) if len(P) else empty
    order = np.argsort(di, kind='stable')
    di, dj = di[order], dj[order]
    dstarts = np.searchsorted(di, np.arange(len(T)))
    dends = np.searchsorted(di, np.arange(len(T)), side='right')
    rows, ins, outs, exs = [], [], [], []
    for i in range(len(T)):
        t = T[i]
        js = pi[starts[i]:ends[i]]
        near = dj[dstarts[i]:dends[i]]
        done = shapely.Polygon()
        part = {}
        for g in GROUPS_IN + GROUPS_OUT:            # отводы, затем прочие участки на остатке; без двойного счёта
            sel = js[grp[js] == g]
            if len(sel):
                u = shapely.union_all(shapely.intersection(t, P[sel]))
                u = shapely.difference(u, done)
                part[g] = u
                done = shapely.union(done, u)
        part['none'] = shapely.difference(t, done)
        a = {g: shapely.area(part.get(g, shapely.Polygon())) / 1e4 for g in GROUPS_IN + GROUPS_OUT + ('none',)}
        r = dict(id=int(ids[i]), cad_n=int((np.isin(grp[js], GROUPS_IN)).sum()))
        r.update({f'cad_{g}_ha': a[g] for g in a})
        r['cad_in_ha'] = sum(a[g] for g in GROUPS_IN)
        r['cad_out_ha'] = sum(a[g] for g in GROUPS_OUT + ('none',))
        # выход за границы отвода: отвод под объект ближе T м и часть контура дальше T м от него
        ex = {dist: excess(t, P, near, grp, GROUPS_IN, dist) for dist in EXC_T}
        exu = excess(t, P, near, grp, GROUPS_IN + ('unk',), EXC_T[0])     # части ЕЗП тоже считаются отводом
        allot = ex[EXC_T[0]] is not None
        r['allot10'] = allot
        r['allot20'] = ex[EXC_T[-1]] is not None      # для отчёта: отвод в 10-20 м у контуров без отвода
        r['unk10'] = exu is not None                  # для отчёта: часть ЕЗП ближе 10 м
        # варианты (20 м, с частями ЕЗП) только у контуров с отводом ближе 10 м: статус задаёт допуск 10 м
        for dist in EXC_T:
            r[f'cad_exc{int(dist)}_ha'] = shapely.area(ex[dist]) / 1e4 if allot else 0.0
        r[f'cad_exc{int(EXC_T[0])}u_ha'] = shapely.area(exu) / 1e4 if allot else 0.0
        rows.append(r)
        for g, u in part.items():
            if shapely.area(u) > 0:
                rec = (int(ids[i]), g, ';'.join(sorted(set(cad[js[grp[js] == g]]))[:3]), shapely.to_wkb(as_poly([u])[0]))
                (ins if g in GROUPS_IN else outs).append(rec)
        e10 = ex[EXC_T[0]]
        if e10 is not None and shapely.area(e10) > 0:
            exs.append((int(ids[i]), shapely.to_wkb(e10)))
    return rows, ins, outs, exs


def run_overlay(techno: gpd.GeoDataFrame, allot: gpd.GeoDataFrame, workers: int) -> tuple[pd.DataFrame, list, list, list]:
    """Оверлей по пространственным блокам 50 км, параллельно."""
    c = techno.geometry.centroid
    bx = (c.x // 50000).astype(int).astype(str) + '_' + (c.y // 50000).astype(int).astype(str)
    ptree = shapely.STRtree(np.asarray(allot.geometry.values))
    tasks = []
    for _, t in techno.groupby(bx):
        # запас на допуск выхода за отвод: отводы за краем охвата блока ближе max(EXC_T) к крайним контурам
        env = shapely.box(*(t.total_bounds + np.array([-1, -1, 1, 1]) * (max(EXC_T) + 1)))
        pj = ptree.query(env, predicate='intersects')
        p = allot.iloc[pj]
        tasks.append((t['id'].to_numpy(), shapely.to_wkb(np.asarray(t.geometry.values)), shapely.to_wkb(np.asarray(p.geometry.values)),
                      p['grp'].to_numpy(), p['cad_num'].fillna('').to_numpy()))
    rows, ins, outs, exs = [], [], [], []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r, i, o, e in ex.map(overlay_chunk, tasks, chunksize=1):
            rows += r
            ins += i
            outs += o
            exs += e
    return pd.DataFrame(rows), ins, outs, exs


# ---------- основной ход ----------

def split_big(p: gpd.GeoDataFrame, max_ha: float) -> gpd.GeoDataFrame:
    """Контуры участков групп ind, vri, ezp крупнее max_ha -> отдельные строки группы big; прочие контуры того же
    участка остаются одной строкой в своей группе."""
    parts = shapely.get_parts(np.asarray(p.geometry.values), return_index=True)
    big = np.isin(p['grp'].to_numpy()[parts[1]], ('ind', 'vri', 'ezp')) & (shapely.area(parts[0]) > max_ha * 1e4)
    if not big.any():
        return p
    hit = np.unique(parts[1][big])
    keep = np.isin(parts[1], hit) & ~big                  # мелкие контуры затронутых участков
    gs = {i: shapely.multipolygons(parts[0][keep & (parts[1] == i)]) for i in np.unique(parts[1][keep])}
    small = p.iloc[list(gs)].copy()
    small['geometry'] = gpd.GeoSeries(list(gs.values()), index=small.index, crs=p.crs)
    large = p.iloc[parts[1][big]].copy()
    large['grp'] = 'big'
    large['geometry'] = gpd.GeoSeries(parts[0][big], index=large.index, crs=p.crs)
    out = gpd.GeoDataFrame(pd.concat([p.drop(index=p.index[hit]), small, large], ignore_index=True), geometry='geometry', crs=p.crs)
    out['area_ha_p'] = (out.geometry.area / 1e4).round(1)
    log(f'контуров крупнее {max_ha:.0f} га (группа big): {int(big.sum())} у {len(hit)} участков, '
        f'{shapely.area(parts[0][big]).sum() / 1e6:.1f} км2')
    return out


def load_parcels(bounds4326: tuple, techno: gpd.GeoDataFrame, files: list[Path] = PARCELS, ezp: bool = False,
                 local_max_ha: float | None = None) -> gpd.GeoDataFrame:
    """Участки регионов (files) в охвате техногенных контуров, ближе NEAR_M к ним, с группой отвода.
    ezp: части единых землепользований без категории и ВРИ считаются отводами (группа ezp), иначе unk;
    local_max_ha: контуры отводов крупнее порога -> big (split_big)."""
    tt = shapely.STRtree(np.asarray(techno.geometry.values))
    parts = []
    for f in files:
        p = pyogrio.read_dataframe(f, columns=list(COLS_P), bbox=bounds4326).rename(columns=COLS_P)
        n0 = len(p)
        p = p.to_crs(CRS)
        p = p.set_geometry(gpd.GeoSeries(as_poly(p.geometry.values), index=p.index, crs=CRS))
        p = p[~p.geometry.is_empty]
        near = np.unique(tt.query(np.asarray(p.geometry.values), predicate='dwithin', distance=NEAR_M)[0])
        p = p.iloc[near].copy()
        p['region'] = f.stem[-2:]
        log(f'{f.name}: в охвате {n0}, у техногенных контуров {len(p)}')
        parts.append(p)
    p = pd.concat(parts, ignore_index=True)
    cat = p['cat'].fillna(p['cat2']).fillna('').str.replace('\xa0', ' ')
    vri = p['vri'].fillna('').str.replace('\xa0', ' ')
    p['cat'] = cat
    p['vri'] = vri
    obj = ((vri.str.contains(OBJ_RE, case=False, regex=True) | vri.str.contains(OBJ_CS_RE, case=True, regex=True))
           & ~vri.str.contains(GENERIC_RE, case=False, regex=True) & ~vri.str.contains(NOT_OBJ_RE, case=False, regex=True))
    p['area_ha_p'] = (p.geometry.area / 1e4).round(1)
    nocat = cat.eq('') | cat.str.contains('не установлена', case=False)
    part_ezp = p['subtype'].fillna('').str.replace('\xa0', ' ').str.strip().isin(EZP_SUBTYPES) & nocat
    p['grp'] = np.select([cat.str.contains('промышленности', case=False), cat.str.contains('населенн|населённ', case=False),
                          obj, cat.str.contains('лесного', case=False),
                          cat.str.contains('сельскохозяйствен', case=False), part_ezp & ezp, nocat],
                         ['ind', 'np', 'vri', 'forest', 'agri', 'ezp', 'unk'], 'misc')
    p['district'] = p['cad_num'].fillna('').str.split(':').str[:2].str.join(':')
    p = gpd.GeoDataFrame(p.drop(columns=['cat2', 'subtype']), geometry='geometry', crs=CRS)
    return split_big(p, local_max_ha) if local_max_ha else p


def estimate_shifts(techno: gpd.GeoDataFrame, allot: gpd.GeoDataFrame, workers: int) -> tuple[pd.DataFrame, dict]:
    """Сдвиги по окнам и решение о сдвиге по кадастровым районам и регионам."""
    c = techno.geometry.centroid
    cell = pd.DataFrame({'cx': (c.x // WIN_M).astype(int), 'cy': (c.y // WIN_M).astype(int), 'a': techno.geometry.area / 1e4})
    top = cell.groupby(['cx', 'cy'])['a'].sum()
    top = top[top >= MIN_WIN_HA].sort_values(ascending=False).head(N_WIN)
    tg, pg = np.asarray(techno.geometry.values), np.asarray(allot.geometry.values)
    ttree = shapely.STRtree(tg)
    ptree = shapely.STRtree(pg)
    tasks, dist_of = [], {}
    for (cx, cy), _ in top.items():
        x0, y0 = cx * WIN_M, cy * WIN_M
        env = shapely.box(x0 - MAXSHIFT_M, y0 - MAXSHIFT_M, x0 + WIN_M + MAXSHIFT_M, y0 + WIN_M + MAXSHIFT_M)
        tj = ttree.query(env, predicate='intersects')
        pj = ptree.query(env, predicate='intersects')
        if len(pj) == 0:
            continue
        key = f'{cx}_{cy}'
        d = allot.iloc[pj]
        dist_of[key] = (d['district'].mode().iat[0], d['region'].mode().iat[0])
        tasks.append((key, x0, y0, shapely.to_wkb(tg[tj]), shapely.to_wkb(pg[pj])))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = [r for r in ex.map(best_shift, tasks, chunksize=4) if r['ok']]
    w = pd.DataFrame(res)
    w['district'] = w['key'].map(lambda k: dist_of[k][0])
    w['region'] = w['key'].map(lambda k: dist_of[k][1])
    w['gain'] = w['overlap_best'] / w['overlap0'].clip(lower=1e-9)
    # лучшие сдвиги отдельных окон шумны (отводы крупнее контуров, поверхность перекрытия почти плоская; проверка
    # агентом: правило по окнам не видит даже внесённый сдвиг 10 м), поэтому решение по суммарной поверхности региона
    reg = {}
    for r, g in w.groupby('region'):
        S = np.sum(np.stack(g['surf'].to_list()), axis=0)
        s = S.shape[0] // 2
        k = np.unravel_index(np.argmax(S), S.shape)
        dx, dy = (k[1] - s) * RES, -(k[0] - s) * RES
        gain = float(S[k] / max(S[s, s], 1e-9) - 1)
        reg[r] = dict(dx=dx, dy=dy, gain=gain, n=len(g), ok=gain >= MIN_GAIN and math.hypot(dx, dy) >= MIN_SHIFT_M)
    shift = {r: ((v['dx'], v['dy'], 'регион') if v['ok'] else (0.0, 0.0, 'нет')) for r, v in reg.items()}
    return w.drop(columns=['surf']), dict(reg=reg, shift=shift)


def coverage(techno: gpd.GeoDataFrame, kras_cad: bool = False) -> pd.DataFrame:
    """cad_cov: 1, если контур в ЯНАО или ХМАО (есть кадастр), 0 для Туруханского района и восточного сектора (1 и там
    при kras_cad: участки Красноярского края подключены);
    district: район OSM по центроиду (как в 121/130; без района: «вне районов» или «восточный сектор»)."""
    adm = gpd.read_file(ADMIN, layer='admin')
    d6 = adm[(adm['admin_level'].astype(str) == '6') & adm['name'].notna()].to_crs(CRS)[['name', 'geometry']]
    pts = gpd.GeoDataFrame(techno[['id']], geometry=techno.geometry.centroid, crs=CRS)
    j = gpd.sjoin(pts, d6, how='left', predicate='within')
    j = j[~j.index.duplicated()]
    lon = gpd.GeoSeries(pts.geometry, crs=CRS).to_crs(4326).x
    east = j['name'].isna() & (lon >= EAST_LON)
    kras = j['name'].fillna('').str.contains('Туруханск') | east
    name = j['name'].fillna('вне районов').where(~east, 'восточный сектор')
    return pd.DataFrame({'cad_cov': np.where(kras & (not kras_cad), 0, 1), 'district': name.str.replace('муниципальный округ ', '')},
                        index=techno.index)


def render_windows(w: pd.DataFrame, techno: gpd.GeoDataFrame, allot0: gpd.GeoDataFrame, allot: gpd.GeoDataFrame,
                   qc: Path) -> list[Path]:
    """Окна для визуальной проверки привязки: снимок Esri, контуры, отводы до (пунктир) и после сдвига; PNG в папку qc."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from qc_thumb_xyz import R_MERC, TILE, fetch_tile, tile_xy
    from PIL import Image
    picks = w[w['overlap0'] >= 5].sort_values('techno_ha', ascending=False).head(4)
    out = []
    for _, r in picks.drop_duplicates('key').iterrows():
        cx, cy = (int(v) for v in r['key'].split('_'))
        box = shapely.box(cx * WIN_M + 1000, cy * WIN_M + 1000, cx * WIN_M + 3000, cy * WIN_M + 3000)
        b3857 = gpd.GeoSeries([box], crs=CRS).to_crs(3857).total_bounds
        z = 16
        tx0, ty0 = tile_xy(b3857[0], b3857[3], z)
        tx1, ty1 = tile_xy(b3857[2], b3857[1], z)
        X0, Y0, X1, Y1 = int(tx0), int(ty0), int(tx1), int(ty1)
        m = Image.new('RGB', ((X1 - X0 + 1) * TILE, (Y1 - Y0 + 1) * TILE))
        for X in range(X0, X1 + 1):
            for Y in range(Y0, Y1 + 1):
                m.paste(fetch_tile(z, X, Y), ((X - X0) * TILE, (Y - Y0) * TILE))
        xs = 2 * R_MERC / (TILE * 2 ** z)
        ext = (-R_MERC + X0 * TILE * xs, -R_MERC + (X1 + 1) * TILE * xs, R_MERC - (Y1 + 1) * TILE * xs, R_MERC - Y0 * TILE * xs)
        fig, ax = plt.subplots(figsize=(8, 8))
        ax.imshow(m, extent=ext)
        for gdf, kw in ((techno, dict(edgecolor='#ff7f00', facecolor='none', linewidth=1.2)),
                        (allot0, dict(edgecolor='#00e5ff', facecolor='none', linewidth=0.7, linestyle='--')),
                        (allot, dict(edgecolor='#2060ff', facecolor='none', linewidth=1.0))):
            sub = gdf[gdf.intersects(box)]
            if len(sub):
                sub.to_crs(3857).plot(ax=ax, **kw)
        ax.set_xlim(b3857[0], b3857[2])
        ax.set_ylim(b3857[1], b3857[3])
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(f'окно {r["key"]} ({r["district"]}): сдвиг окна dx {r["dx"]:+.1f} м, dy {r["dy"]:+.1f} м; '
                     f'оранжевый: техноген, голубой пунктир: отводы до сдвига, синий: после', fontsize=8)
        p = qc / f'render_{r["key"]}.png'
        fig.savefig(p, dpi=110, bbox_inches='tight')
        plt.close(fig)
        out.append(p)
    return out


def attach_fields(g: pd.DataFrame, f: pd.DataFrame, order: list[str]) -> pd.DataFrame:
    """Поля cad_* и age2000 из f (по id) в продукт g. Источник, производный от v6, уже несёт cad_* и age2000 (у прежнего
    набора техногенных контуров): они удаляются до merge, иначе появятся дубли _x/_y и устаревшие значения."""
    stale_cols = [c for c in g.columns if c.startswith('cad_') or c == 'age2000']
    if stale_cols:
        log(f'поля источника удалены перед пересчётом: {len(stale_cols)} ({", ".join(stale_cols)})')
        g = g.drop(columns=stale_cols)
    g = g.merge(f[['id'] + order], on='id', how='left')
    dup = [c for c in g.columns if c.endswith(('_x', '_y'))]
    assert not dup, f'дубли полей после merge: {dup}'
    return g


def status_section(ra: pd.DataFrame) -> list[str]:
    """Раздел отчёта: в отводе / выход за границы отвода / нет отвода (ra: техногенные контуры с кадастром и полями res)."""
    km = lambda s: s.sum() / 100
    t10, t20 = (int(d) for d in EXC_T)
    tot = km(ra['cad_in_ha'] + ra['cad_out_ha'])
    L = ['## В отводе, превышение отвода, без отвода (поле cad_status)', '',
         f'Превышение отвода: у контура есть отвод под объект ближе {t10} м, в отводе лежит не меньше {TOUCH_FRAC:.0%} площади '
         f'контура, а часть контура лежит дальше {t10} м от границы отвода (куски не меньше {MMU_M2:.0f} м2); полоса шириной в '
         f'пиксель маски вдоль границы принимается техническим допуском (не измеренной погрешностью границ). Без отвода: ни '
         f'одного отвода под объект ближе {t10} м или контур лишь касается чужого отвода (в отводе меньше {TOUCH_FRAC:.0%} площади); '
         f'учитывается площадь всего объекта. Территория населённых пунктов (улицы, дачи, аэродромы, вахтовые посёлки) считается '
         f'отводом. «Отвод под объект» здесь операционное определение (категория и ВРИ участка), а не документ об отводе объекта.', '',
         f'| Статус | контуров | км2 | внутри отводов, км2 | выход за {t10} м, км2 | выход за {t20} м, км2 | '
         f'выход за {t10} м с участками unk, км2 |', '|---|---|---|---|---|---|---|']
    for k in ('in', 'cross', 'unreg'):
        s = ra[ra['cad_status'] == k]
        L.append(f'| {STATUS_RU[k]} | {len(s)} | {km(s["cad_in_ha"] + s["cad_out_ha"]):.1f} | {km(s["cad_in_ha"]):.1f} | '
                 f'{km(s[f"cad_exc{t10}_ha"]):.1f} | {km(s[f"cad_exc{t20}_ha"]):.1f} | {km(s[f"cad_exc{t10}u_ha"]):.1f} |')
    L.append(f'| всего | {len(ra)} | {tot:.1f} | {km(ra["cad_in_ha"]):.1f} | {km(ra[f"cad_exc{t10}_ha"]):.1f} | '
             f'{km(ra[f"cad_exc{t20}_ha"]):.1f} | {km(ra[f"cad_exc{t10}u_ha"]):.1f} |')
    cr = ra[ra['cad_status'] == 'cross']
    un = ra[ra['cad_status'] == 'unreg']
    a20 = un[un['allot20'].astype(bool) & ~un['allot10'].astype(bool)]
    u10 = un[un['unk10'].astype(bool) & ~un['allot10'].astype(bool)]
    tch = un[un['touch'].eq(1)] if 'touch' in un.columns else un.iloc[:0]
    L += ['', f'Статус «в отводе» не значит «целиком внутри»: полоса допуска {t10} м и куски меньше {MMU_M2:.0f} м2 остаются '
          f'вне отвода. Среди объектов без отвода касающихся чужого отвода: {len(tch)} контуров '
          f'({km(tch["cad_in_ha"] + tch["cad_out_ha"]):.1f} км2). Чувствительность «без отвода»: у {len(a20)} контуров '
          f'({km(a20["cad_in_ha"] + a20["cad_out_ha"]):.1f} км2) отвод лежит в {t10}-{t20} м (при допуске {t20} м они стали бы '
          f'превышением или касающимися); у {len(u10)} контуров '
          f'({km(u10["cad_in_ha"] + u10["cad_out_ha"]):.1f} км2) ближе {t10} м есть участок без категории и ВРИ (unk).']
    # доля контура в отводе: малая доля = отдельный объект без отвода, касающийся чужого отвода краем
    share = cr['cad_in_ha'] / (cr['cad_in_ha'] + cr['cad_out_ha'])
    bins = pd.cut(share, [0, 0.1, 0.5, 0.9, 1.0001], right=False, labels=['меньше 10 %', '10-50 %', '50-90 %', '90 % и больше'])
    L += ['', f'Превышение отвода по доле площади контура в отводе (поле in_pct слоя anthro_exceed); контуры с долей меньше '
          f'{TOUCH_FRAC:.0%} отнесены к объектам без отвода.', '',
          '| В отводе | контуров | превышение за 10 м, км2 |', '|---|---|---|',
          *[f'| {b} | {int((bins == b).sum())} | {km(cr.loc[bins == b, f"cad_exc{t10}_ha"]):.1f} |' for b in bins.cat.categories]]
    L += ['', f'По возрасту (age2000), км2: превышение отвода (за {t10} м) и площадь объектов без отвода целиком.', '',
          '| Возраст | превышение, км2 | контуров с превышением | без отвода, км2 | контуров без отвода |', '|---|---|---|---|---|']
    for k in AGE_ORDER:
        c, u = cr[cr['age2000'] == k], un[un['age2000'] == k]
        L.append(f'| {k} | {km(c[f"cad_exc{t10}_ha"]):.1f} | {len(c)} | {km(u["cad_in_ha"] + u["cad_out_ha"]):.1f} | {len(u)} |')
    L += ['',
          '- «Превышение отвода» (слой anthro_exceed): нарушенная поверхность выходит за границу участка; это возможные '
          'нарушения, требующие адресной проверки, а не установленные.',
          '- «Без отвода» (слой anthro_noallot, площадь объекта целиком; поле kind: none или touch): участок с объектовым '
          'назначением в использованной выгрузке не найден или контур лишь касается чужого участка. Не у всех объектов '
          'антропогенного происхождения есть отвод (трассы на сервитутах, советские объекты, неполнота выгрузки, различие дат, '
          'ошибка класса); нарушение этим сопоставлением не устанавливается.',
          '- Контур маски может объединять соседние объекты (площадку в отводе и дорогу без участка) и захватывать соседний '
          'природный раздув: такие части тоже попадают в превышение, поэтому слой anthro_exceed требует просмотра.', '']
    return L


def age_section(ra: pd.DataFrame) -> list[str]:
    """Раздел отчёта: площади по возрасту age2000. ra: одна строка на техногенный контур с кадастром (cad_cov = 1),
    поля age2000, cad_in_ha, cad_out_ha, cad_none_ha. Площади по частям контура (как в основной таблице), возраст по контуру."""
    km = lambda s: s.sum() / 100
    th = lambda x: f'{x:.2f}'.replace('.', ',')
    names = {'new': f'new: голого в 2000 меньше {th(NEW_BARE_MAX)} (появился после 2000)',
             'mid': f'mid: голого в 2000 от {th(NEW_BARE_MAX)} до {th(OLD_BARE_MIN)}',
             'old': f'old: голого в 2000 не меньше {th(OLD_BARE_MIN)} (был уже в 2000)',
             'na': 'na: нет данных Hansen', 'all': 'всего'}
    L = ['## По возрасту (Hansen 2000, поле age2000), км2 (часть, покрытая кадастром)', '',
         '| Возраст | контуров | км2 | внутри отводов, км2 | внутри, доля | вне любых участков (cad_none), км2 | вне любых, доля |',
         '|---|---|---|---|---|---|---|']
    for k in AGE_ORDER + ('all',):
        s = ra if k == 'all' else ra[ra['age2000'] == k]
        t = km(s['cad_in_ha'] + s['cad_out_ha'])
        share = lambda x, t=t: f'{x / t:.1%}' if t > 0 else '-'
        L.append(f'| {names[k]} | {len(s)} | {t:.1f} | {km(s["cad_in_ha"]):.1f} | {share(km(s["cad_in_ha"]))} | '
                 f'{km(s["cad_none_ha"]):.1f} | {share(km(s["cad_none_ha"]))} |')
    L += ['',
          '- Сведения ЕГРН здесь ориентир, а не эталон. «Вне отводов» смешивает два случая: участок с объектовым назначением '
          'не найден (нет отвода) и часть контура за полосой допуска от найденного участка (см. раздел о статусе cad_status). '
          'age2000 характеризует оголённость поверхности в 2000 г., а не дату создания объекта.',
          '- Возраст присвоен контуру целиком, а реестр делит контур на части: один контур может лежать частью в отводе, '
          'частью вне. Площади считаются по частям, возраст по контуру.',
          f'- Возраст по Hansen GFC (Landsat, 30 м) при маске 10 м: у мелких и узких объектов доля голого песка в 2000 оценена '
          f'грубо. Пороги {th(NEW_BARE_MAX)} и {th(OLD_BARE_MIN)} из шага 3 (62_step3_rule.py); na: значения нет (вне покрытия '
          f'мозаик Hansen или не посчитано для контура).',
          '- В ArcMap: новые объекты без отвода: слой anthro_noallot, age2000 = \'new\'; превышение отвода новыми '
          'объектами: слой anthro_exceed, age2000 = \'new\'.', '']
    return L


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Параметры запуска; по умолчанию прежние пути (v5 -> v6) и прежний заголовок отчёта."""
    ap = argparse.ArgumentParser(description='Техногенные пески внутри и вне кадастровых отводов (поля cad_*, age2000).')
    ap.add_argument('--force', action='store_true', help='перезаписать существующие выходы')
    ap.add_argument('--src', type=proj_path, default=SRC, help=f'продукт-источник, слой genesis (по умолчанию {SRC})')
    ap.add_argument('--out-product', type=proj_path, default=OUT_PRODUCT,
                    help=f'выходной продукт = источник + поля cad_*, age2000 (по умолчанию {OUT_PRODUCT})')
    ap.add_argument('--out-layers', type=proj_path, default=OUT_LAYERS,
                    help=f'слои anthro_in, anthro_out, parcels, shift_windows (по умолчанию {OUT_LAYERS})')
    ap.add_argument('--qc', type=proj_path, default=QC, help=f'папка отчёта и окон привязки (по умолчанию {QC})')
    ap.add_argument('--label', default=LABEL, help=f'подпись в скобках заголовка отчёта (по умолчанию "{LABEL}")')
    ap.add_argument('--kras', action='store_true',
                    help=f'подключить участки Красноярского края ({PARCELS_KRAS.name}); без флага там cad_cov = 0')
    ap.add_argument('--cores', type=int, default=0,
                    help='0 (по умолчанию): все ядра, кроме двух (cpu_limit.apply_heavy); n > 0: cpu_limit.apply_cores(n)')
    ap.add_argument('--territory', type=proj_path, default=None,
                    help='gpkg со слоем territory (151): территория населённых пунктов, считается отводом (группа terr)')
    ap.add_argument('--touch-frac', type=float, default=TOUCH_FRAC,
                    help=f'контур с долей в отводе меньше этой и частью за допуском: «без отвода» (по умолчанию {TOUCH_FRAC})')
    ap.add_argument('--ezp', action='store_true',
                    help='части единых землепользований (обособленные и условные участки без категории и ВРИ) считать отводами')
    ap.add_argument('--local-max-ha', type=float, default=None,
                    help='контуры отводов ind, vri, ezp крупнее этого, га: территориальная аренда (группа big), не отвод')
    a = ap.parse_args(argv)
    if a.cores < 0:
        ap.error('--cores: нужно 0 или положительное число')
    return a


def main(argv: list[str] | None = None) -> None:
    a = parse_args(argv)
    src, out_product, out_layers, qc = a.src, a.out_product, a.out_layers, a.qc
    if out_product.resolve() == src.resolve():
        raise SystemExit('--out-product совпадает с --src: источник не перезаписывается')
    if out_layers.resolve() in (out_product.resolve(), src.resolve()):
        raise SystemExit('--out-layers совпадает с --out-product или --src')
    # запуск с нестандартными путями (например v7) не пишет в продукты v4-v6, слои 133 и отчёт exports/qc/cadastre
    # даже с --force: проверка --force ниже не видит папку qc, а забытый --qc перезаписал бы отчёт v6
    custom = any(x.resolve() != d.resolve() for x, d in ((src, SRC), (out_product, OUT_PRODUCT), (out_layers, OUT_LAYERS), (qc, QC)))
    protected = {p.resolve() for p in (ROOT / 'exports' / 'baresand_genesis_step6_v4.gpkg', SRC, OUT_PRODUCT, OUT_LAYERS)}
    if custom and (out_product.resolve() in protected or out_layers.resolve() in protected or qc.resolve() == QC.resolve()):
        raise SystemExit('при нестандартных путях нужны свои --out-product, --out-layers и --qc: продукты v4-v6, '
                         f'{OUT_LAYERS.name} и отчёт {QC} не перезаписываются')
    if not a.force and (out_product.exists() or out_layers.exists()):
        raise SystemExit('выходы уже есть; перезапись только с --force')
    workers = cpu_limit.apply_cores(a.cores) if a.cores > 0 else cpu_limit.apply_heavy(reserve=2)
    log(f'рабочих процессов: {workers}')
    qc.mkdir(parents=True, exist_ok=True)
    self_test()
    src_tag = 'v5' if src == SRC else src.name          # подпись источника в отчёте (по умолчанию прежняя)

    ev = ['nspd_parcel_any_frac', 'nspd_parcel_ind_frac', 'nspd_struct_frac']
    techno = pyogrio.read_dataframe(src, layer='genesis', columns=['id', 'genesis'] + ev + ['hansen_covered', 'bare2000_frac'],
                                    where="genesis = 'anthropogenic'")
    techno = techno.to_crs(CRS)
    techno = techno.set_geometry(gpd.GeoSeries(as_poly(techno.geometry.values), index=techno.index, crs=CRS))
    techno = techno.join(coverage(techno, a.kras))
    techno['age2000'] = age2000(techno['bare2000_frac'])
    stale = int((techno['hansen_covered'].fillna(0).eq(1) != techno['bare2000_frac'].notna()).sum())
    log(f'возраст age2000: {techno["age2000"].value_counts().reindex(list(AGE_ORDER), fill_value=0).to_dict()}; '
        f'hansen_covered не согласован с bare2000_frac у {stale} контуров (возраст по bare2000_frac)')
    log(f'техногенных контуров: {len(techno)}, {techno.geometry.area.sum() / 1e6:.1f} км2; без кадастра (Красноярский край): '
        f'{int((techno["cad_cov"] == 0).sum())}, {techno.loc[techno["cad_cov"] == 0].geometry.area.sum() / 1e6:.1f} км2')
    tc = techno[techno['cad_cov'] == 1].reset_index(drop=True)
    files = list(PARCELS)
    if a.kras:
        if not PARCELS_KRAS.exists():
            raise FileNotFoundError(f'--kras: нет {PARCELS_KRAS}')
        files.append(PARCELS_KRAS)
    parcels0 = load_parcels(tuple(tc.to_crs(4326).total_bounds), tc, files, a.ezp, a.local_max_ha)
    log(f'участков у техногенных контуров: {len(parcels0)}; по группам: {parcels0["grp"].value_counts().to_dict()}')

    objs0 = parcels0[parcels0['grp'].isin(GROUPS_IN)].reset_index(drop=True)
    w, dec = estimate_shifts(tc, objs0, workers)
    w.to_csv(qc / 'shift_windows.csv', index=False, encoding='utf-8')
    log(f'окон привязки: {len(w)}; регионы: ' + '; '.join(f'{r}: пик dx {v["dx"]:+.1f}, dy {v["dy"]:+.1f} м, выигрыш {v["gain"]:.2%}, '
                                                       f'n {v["n"]}, {"сдвиг применён" if v["ok"] else "сдвиг не нужен"}' for r, v in dec['reg'].items()))
    # сдвиг региона применяется ко всем его участкам (отводам и прочим)
    parcels = parcels0.copy()
    sh = parcels['region'].map(lambda r: dec['shift'].get(r, (0.0, 0.0, 'нет')))
    parcels['dx'] = [s[0] for s in sh]
    parcels['dy'] = [s[1] for s in sh]
    parcels['shift_src'] = [s[2] for s in sh]
    moved = (parcels['dx'] != 0) | (parcels['dy'] != 0)
    if moved.any():
        geo = np.asarray(parcels.geometry.values).copy()
        for (dx, dy), idx in parcels[moved].groupby(['dx', 'dy']).groups.items():
            k = parcels.index.get_indexer(idx)
            geo[k] = shapely.transform(geo[k], lambda c, dx=dx, dy=dy: c + np.array([dx, dy]))
        parcels = parcels.set_geometry(gpd.GeoSeries(geo, index=parcels.index, crs=CRS))
    log(f'сдвинуто участков: {int(moved.sum())} из {len(parcels)}')
    if a.territory is not None:
        # территория населённых пунктов: группа terr, без сдвига; добавляется после оценки сдвига (не влияет на окна)
        tr = gpd.read_file(a.territory, layer='territory').to_crs(CRS)
        tr = tr.set_geometry(gpd.GeoSeries(as_poly(tr.geometry.values), index=tr.index, crs=CRS))
        tr = tr[~tr.geometry.is_empty]
        tt = shapely.STRtree(np.asarray(tc.geometry.values))
        near = np.unique(tt.query(np.asarray(tr.geometry.values), predicate='dwithin', distance=NEAR_M)[0])
        tr = tr.iloc[near]
        terr = gpd.GeoDataFrame({'cad_num': None, 'region': 'terr', 'district': '', 'grp': 'terr', 'cat': 'территория НП',
                                 'vri': '', 'area_ha_p': (tr.geometry.area / 1e4).round(1).to_numpy(), 'dx': 0.0, 'dy': 0.0,
                                 'shift_src': 'нет'}, geometry=np.asarray(tr.geometry.values), crs=CRS)
        parcels = pd.concat([parcels, terr], ignore_index=True)
        parcels0 = pd.concat([parcels0, terr.drop(columns=['dx', 'dy', 'shift_src'])], ignore_index=True)
        log(f'территория населённых пунктов (terr): {len(terr)} полигонов у техногенных контуров, {terr.geometry.area.sum() / 1e6:.1f} км2')

    res, ins, outs, exs = run_overlay(tc, parcels, workers)
    log('оверлей со сдвигом готов')
    # без сдвига отдельный проход нужен, только если сдвиг применён (иначе это тот же расчёт)
    res0 = run_overlay(tc, parcels0, workers)[0] if moved.any() else res
    log('оверлей без сдвига готов')
    res = res.merge(res0[['id', 'cad_in_ha']].rename(columns={'cad_in_ha': 'cad_in0_ha'}), on='id')
    if len(res) != len(tc):
        raise RuntimeError(f'оверлей вернул {len(res)} строк вместо {len(tc)}')
    # статус контура: нет отвода ближе 10 м -> unreg; есть отвод и часть дальше 10 м от него (куски >= MMU) -> cross;
    # вариант А: при доле в отводе меньше touch_frac такой контур лишь касается чужого отвода -> unreg (объект без отвода)
    e10 = f'cad_exc{int(EXC_T[0])}_ha'
    in_frac = res['cad_in_ha'] / (res['cad_in_ha'] + res['cad_out_ha']).where(lambda s: s > 0)
    res['touch'] = (res['allot10'].astype(bool) & (res[e10] > 0) & (in_frac.fillna(0) < a.touch_frac)).astype(int)
    res['cad_status'] = np.select([~res['allot10'].astype(bool) | res['touch'].eq(1), res[e10] > 0], ['unreg', 'cross'], 'in')
    log(f'касающихся чужого отвода (в отводе меньше {a.touch_frac:.0%}): {int(res["touch"].sum())}, '
        f'{(res.loc[res["touch"].eq(1), "cad_in_ha"] + res.loc[res["touch"].eq(1), "cad_out_ha"]).sum() / 100:.1f} км2 -> без отвода')
    log(f'статус: {res["cad_status"].value_counts().to_dict()}')

    # продукт: источник + поля cad_* и age2000 у техногенных контуров (по умолчанию v6 = v5 + поля)
    g = pyogrio.read_dataframe(src, layer='genesis')
    f = techno[['id', 'cad_cov', 'age2000']].merge(res.drop(columns=['allot10', 'allot20', 'unk10', 'touch']), on='id', how='left')
    f['cad_status'] = f['cad_status'].where(f['cad_cov'] == 1, 'nocad')
    area_cols = [c for c in f.columns if c.startswith('cad_') and c.endswith('_ha')]
    f[area_cols] = f[area_cols].round(4)
    f['cad_out_frac'] = (f['cad_out_ha'] / (f['cad_in_ha'] + f['cad_out_ha'])).round(4)
    exc_cols = [f'cad_exc{int(d)}_ha' for d in EXC_T] + [f'cad_exc{int(EXC_T[0])}u_ha']
    order = ['cad_cov', 'cad_n', 'cad_in_ha', 'cad_ind_ha', 'cad_vri_ha', 'cad_ezp_ha', 'cad_np_ha', 'cad_terr_ha', 'cad_out_ha',
             'cad_big_ha', 'cad_unk_ha', 'cad_forest_ha', 'cad_agri_ha', 'cad_misc_ha', 'cad_none_ha', 'cad_out_frac', 'cad_in0_ha',
             'cad_status', *exc_cols, 'age2000']
    g = attach_fields(g, f, order)
    if len(g) != pyogrio.read_info(src, layer='genesis')['features']:
        raise RuntimeError('число строк продукта изменилось при добавлении полей')
    cols = [c for c in g.columns if c != 'geometry'] + ['geometry']
    g = gpd.GeoDataFrame(g[cols], geometry='geometry', crs=g.crs)
    for p in (out_product, out_layers):
        if p.exists():
            p.unlink()
    out_product.parent.mkdir(parents=True, exist_ok=True)
    out_layers.parent.mkdir(parents=True, exist_ok=True)
    pyogrio.write_dataframe(g, out_product, layer='genesis', driver='GPKG')
    log(f'-> {out_product}')

    age_of = dict(zip(techno['id'], techno['age2000']))   # возраст контура в слои частей (по id)

    def layer(recs: list) -> gpd.GeoDataFrame:
        d = gpd.GeoDataFrame(pd.DataFrame([r[:3] for r in recs], columns=['id', 'grp', 'cad_nums']), crs=CRS,
                             geometry=shapely.from_wkb([r[3] for r in recs]))
        d['grp_ru'] = d['grp'].map(GROUP_RU)
        d['area_ha'] = (d.geometry.area / 1e4).round(4)
        d['ge_mmu'] = (d.geometry.area >= MMU_M2).astype(int)
        d['age2000'] = d['id'].map(age_of)
        return d

    li, lo = layer(ins), layer(outs)
    rs = res.set_index('id')
    # вариант А: части в отводах только у контуров в отводе и с превышением; касающиеся контуры (unreg) целиком в
    # anthro_noallot, их части внутри чужого участка в anthro_in не повторяются (без двойного счёта площади)
    li = li[li['id'].map(rs['cad_status']).ne('unreg')]
    pyogrio.write_dataframe(li, out_layers, layer='anthro_in', driver='GPKG')
    # вариант А: два внешних класса. Превышение отвода (anthro_exceed): части дальше 10 м от отвода (куски >= MMU) у
    # контуров со статусом cross; объекты без отвода (anthro_noallot): контуры со статусом unreg целиком (отвода ближе 10 м
    # нет или контур лишь касается чужого отвода)
    le = gpd.GeoDataFrame({'id': [e[0] for e in exs]}, geometry=shapely.from_wkb([e[1] for e in exs]), crs=CRS)
    le = le[le['id'].map(rs['cad_status']).eq('cross')].copy()
    le['area_ha'] = (le.geometry.area / 1e4).round(4)
    le['in_ha'] = le['id'].map(rs['cad_in_ha']).round(4)
    le['ctr_ha'] = le['id'].map(rs['cad_in_ha'] + rs['cad_out_ha']).round(4)
    le['in_pct'] = (100 * le['in_ha'] / le['ctr_ha']).round(1)     # доля контура в отводе, %
    le['age2000'] = le['id'].map(age_of)
    pyogrio.write_dataframe(le, out_layers, layer='anthro_exceed', driver='GPKG')
    un = tc.loc[tc['id'].map(rs['cad_status']).eq('unreg'), ['id', 'geometry']].copy()
    out_g = list(GROUPS_OUT) + ['none']
    dom = rs[[f'cad_{g}_ha' for g in out_g]].idxmax(axis=1).str.replace('cad_', '').str.replace('_ha', '')
    un['area_ha'] = (un.geometry.area / 1e4).round(4)
    un['kind'] = np.where(un['id'].map(rs['touch']).eq(1), 'touch', 'none')
    un['kind_ru'] = un['kind'].map({'touch': 'касается чужого отвода (в отводе меньше 10 %)', 'none': 'отвода ближе 10 м нет'})
    un['in_pct'] = (100 * un['id'].map(rs['cad_in_ha']) / un['id'].map(rs['cad_in_ha'] + rs['cad_out_ha'])).round(1)
    un['under'] = un['id'].map(dom)          # что под контуром: прочий участок или ничего (по наибольшей площади)
    un['under_ru'] = un['under'].map(GROUP_RU)
    un['age2000'] = un['id'].map(age_of)
    pyogrio.write_dataframe(un, out_layers, layer='anthro_noallot', driver='GPKG')
    log(f'превышение отвода: {len(le)} частей, {le["area_ha"].sum() / 100:.1f} км2; без отвода: {len(un)} контуров, '
        f'{un["area_ha"].sum() / 100:.1f} км2 (касающихся {int(un["kind"].eq("touch").sum())})')
    pyogrio.write_dataframe(parcels[['cad_num', 'region', 'district', 'grp', 'cat', 'vri', 'dx', 'dy', 'shift_src', 'geometry']]
                            .assign(grp_ru=lambda d: d['grp'].map(GROUP_RU)), out_layers, layer='parcels', driver='GPKG')
    wg = gpd.GeoDataFrame(w, geometry=[shapely.box(int(k.split('_')[0]) * WIN_M, int(k.split('_')[1]) * WIN_M,
                                                   (int(k.split('_')[0]) + 1) * WIN_M, (int(k.split('_')[1]) + 1) * WIN_M) for k in w['key']], crs=CRS)
    pyogrio.write_dataframe(wg, out_layers, layer='shift_windows', driver='GPKG')
    log(f'-> {out_layers}')

    # отчёт
    km = lambda s: s.sum() / 100
    tot = km(res['cad_in_ha'] + res['cad_out_ha'])
    L = [f'# Техногенные пески и кадастровые отводы под объекты ({a.label})', '',
         f'Продукт {src_tag}, класс anthropogenic: {len(techno)} контуров, {techno.geometry.area.sum() / 1e6:.1f} км2; без кадастра '
         f'(Красноярский край): {int((techno["cad_cov"] == 0).sum())} контуров, {techno.loc[techno["cad_cov"] == 0].geometry.area.sum() / 1e6:.1f} км2.',
         f'Участков ЕГРН у техногенных контуров (ближе {NEAR_M:.0f} м): {len(parcels0)} ({parcels0["grp"].value_counts().to_dict()}).', '',
         'Правило отвода под локальный объект (поля ЕГРН, по порядку): категория «земли промышленности...» (ind); земли '
         'населённых пунктов (np) и территория НП (terr, вариант А); иная категория и объектовый ВРИ (vri); '
         + ('части единых землепользований: обособленные и условные участки без категории и ВРИ, назначение у родительского ЕЗП (ezp, --ezp); '
            if a.ezp else 'части единых землепользований отводом не считаются (unk); ')
         + (f'контуры ind, vri, ezp крупнее {a.local_max_ha:.0f} га не отвод под объект, а территориальная аренда (big).'
            if a.local_max_ha else 'порога размера контура нет.'), '',
         '## Привязка', '',
         f'Окон {len(w)} (4 x 4 км, растр {RES} м, поиск +-{MAXSHIFT_M:.0f} м). Лучший сдвиг отдельного окна улучшает '
         f'перекрытие меньше чем на 5 % в {(w["gain"] < 1.05).mean():.0%} окон: отводы крупнее контуров, поверхность почти '
         f'плоская, и оценки окон шумны. Решение принимается по суммарной поверхности перекрытия региона (сдвиг применяется при '
         f'выигрыше не меньше {MIN_GAIN:.0%} и модуле не меньше {MIN_SHIFT_M:.0f} м):', '']
    for r, v in dec['reg'].items():
        L.append(f'- регион {r}: пик суммарной поверхности dx {v["dx"]:+.1f} м, dy {v["dy"]:+.1f} м; выигрыш против нулевого '
                 f'сдвига {v["gain"]:.2%}; окон {v["n"]}; {"сдвиг применён" if v["ok"] else "сдвиг не применяется"}')
    applied = {r: s for r, s in dec['shift'].items() if s[2] != 'нет'}
    vri_big = parcels[(parcels['grp'] == 'vri') & (parcels['area_ha_p'] > BIG_VRI_HA)]
    tb = shapely.STRtree(np.asarray(vri_big.geometry.values))
    ti, pj = tb.query(np.asarray(tc.geometry.values), predicate='intersects')
    big_km2 = float(shapely.area(shapely.intersection(np.asarray(tc.geometry.values)[ti], np.asarray(vri_big.geometry.values)[pj])).sum() / 1e6)
    in_ok = res['cad_in_ha'].round(4)
    L += ['', 'Систематического сдвига больше ~5 м не обнаружено; ' + ('сдвиг не применялся.' if not applied else
          'применён: ' + '; '.join(f'{r} dx {s[0]:+.1f} dy {s[1]:+.1f} м' for r, s in applied.items())), '',
          '## Площади, км2 (часть, покрытая кадастром)', '',
          '| Показатель | км2 | доля |', '|---|---|---|',
          f'| техногенные всего | {tot:.1f} | 100 % |',
          f'| внутри отводов под объекты | {km(res["cad_in_ha"]):.1f} | {km(res["cad_in_ha"]) / tot:.1%} |',
          f'| то же с участками unk (без категории и ВРИ; верхняя граница) | {km(res["cad_in_ha"] + res["cad_unk_ha"]):.1f} | '
          f'{km(res["cad_in_ha"] + res["cad_unk_ha"]) / tot:.1%} |',
          f'| справочно: пересечение с отводами vri крупнее {BIG_VRI_HA:.0f} га (с двойным счётом) | {big_km2:.1f} | |']
    for gname in GROUPS_IN:
        L.append(f'| в т. ч. {GROUP_RU[gname]} | {km(res[f"cad_{gname}_ha"]):.1f} | {km(res[f"cad_{gname}_ha"]) / tot:.1%} |')
    L.append(f'| вне отводов под объекты | {km(res["cad_out_ha"]):.1f} | {km(res["cad_out_ha"]) / tot:.1%} |')
    for gname in GROUPS_OUT + ('none',):
        L.append(f'| в т. ч. {GROUP_RU[gname]} | {km(res[f"cad_{gname}_ha"]):.1f} | {km(res[f"cad_{gname}_ha"]) / tot:.1%} |')
    L += [f'| вне отводов, части не меньше 900 м2 | {lo.loc[lo["ge_mmu"] == 1, "area_ha"].sum() / 100:.1f} | |',
          f'| внутри отводов без сдвига (для сравнения) | {km(res["cad_in0_ha"]):.1f} | {km(res["cad_in0_ha"]) / tot:.1%} |',
          f'| контуров целиком вне отводов (внутри меньше 0,01 га, одного пикселя) | {int((in_ok < 0.01).sum())} из {len(res)} | |', '']
    L += status_section(tc[['id', 'age2000']].merge(res, on='id'))
    L += age_section(tc[['id', 'age2000']].merge(res, on='id'))
    # по районам
    r2 = tc[['id', 'district']].merge(res, on='id')
    dt = r2.groupby('district').agg(всего=('cad_in_ha', lambda s: 0), внутри=('cad_in_ha', 'sum'), вне=('cad_out_ha', 'sum'),
                                    вне_участков=('cad_none_ha', 'sum'))
    dt['всего'] = dt['внутри'] + dt['вне']
    dt = (dt / 100).round(1).sort_values('всего', ascending=False)
    dt['вне, %'] = (100 * dt['вне'] / dt['всего']).round(0)
    L += ['## По районам (OSM, по центроиду контура), км2', '', dt.to_markdown(), '']
    # круговость: доля вне отводов у контуров с уликой НСПД шага 3 и без неё
    r3 = tc[['id'] + ev].merge(res, on='id')
    has = r3['nspd_parcel_any_frac'].fillna(0).gt(0) | r3['nspd_struct_frac'].fillna(0).gt(0)
    L += ['## Связь с уликами шага 3', '',
          f'Контуры, у которых шаг 3 видел участок или сооружение НСПД: {int(has.sum())}, {km(r3.loc[has, "cad_in_ha"] + r3.loc[has, "cad_out_ha"]):.1f} км2, '
          f'вне отводов {km(r3.loc[has, "cad_out_ha"]) / km(r3.loc[has, "cad_in_ha"] + r3.loc[has, "cad_out_ha"]):.1%}. '
          f'Без такой улики: {int((~has).sum())}, {km(r3.loc[~has, "cad_in_ha"] + r3.loc[~has, "cad_out_ha"]):.1f} км2, '
          f'вне отводов {km(r3.loc[~has, "cad_out_ha"]) / km(r3.loc[~has, "cad_in_ha"] + r3.loc[~has, "cad_out_ha"]):.1%}.', '']
    L += ['## Ограничения', '',
          '- Шаг 3 уже использовал участки НСПД как улику техногенного класса (поля nspd_parcel_*), поэтому доля «внутри» '
          'частично задана самим правилом.',
          '- Полнота кадастра поставщиком не подтверждена; снимок ЕГРН 08.09.2026, маска по сценам 2020-2025 гг.',
          '- Привязка грубая: маска 10 м, окна по перекрытию с отводами; для точной оценки нужны данные 5 м и точнее.',
          '- «Вне отводов» смешивает брошенные и советские объекты, незарегистрированные трассы и ошибки классификации; '
          'разделение на «нет отвода» и «выход за границы отвода» (cad_status) выше. Выход за отвод зависит от точности '
          'границ: допуск 10 м (пиксель маски), вариант 20 м для устойчивости.']
    (qc / 'cadastre_anthro.md').write_text('\n'.join(L), encoding='utf-8')
    pngs = render_windows(w, tc, objs0, parcels[parcels['grp'].isin(GROUPS_IN)], qc)
    log('\n'.join(L))
    log(f'окна для проверки: {[p.name for p in pngs]}')


if __name__ == '__main__':
    main()
