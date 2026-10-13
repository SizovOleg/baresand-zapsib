"""
BareSand — QC-пакет для ручной верификации класса генезиса (итеративный протокол).

Итерация 1, класс «прибрежные отмели» (shoal, шаг 1 каскада).

Готовит два слоя для ревью экспертом в QGIS:
  1. shoal_review          — контуры, ПОМЕЧЕННЫЕ классом shoal (ловим ложные включения).
                             Подсказка suspect=1: за 37 лет GSW ни разу не была вода —
                             для морской отмели подозрительно (вероятна терраса/техноген).
  2. omission_candidates   — контуры БЕЗ метки в полосе 100–2000 м от границы AOI,
                             севернее 66°N (ловим пропуски). Подсказка likely_shoal=1:
                             GSW occurrence_max ≥ 40% — часто была вода, вероятно отмель.

Протокол ревью (эксперт, ~30 мин):
  - В shoal_review: если контур НЕ морская отмель — поставить err_tag:
      терраса / дюна / река / техноген / не_песок / другое
    Верные контуры не трогать (пустой err_tag = верно).
  - В omission_candidates: если контур ДОЛЖЕН быть отмелью — err_tag = 'отмель'.
    Остальные не трогать.
  - Сохранить правки (это регрессионный набор для всех будущих правок правил).

Вход:
  exports/baresand_genesis_step1.gpkg   (shoal/unassigned + dist_aoi_boundary_m)
  exports/baresand_littoral_v2.gpkg     (GSW-атрибуты тех же контуров, join по id)
Выход:
  exports/qc/qc_step1_shoal_review.gpkg
  exports/qc/qc_step1_omission_candidates.gpkg
  (+ .qml стили и README_QC_step1.md пишутся отдельно)

Запуск:
  python python/41_qc_step1_package.py
"""

import sys
import time
from pathlib import Path

import geopandas as gpd

sys.stdout.reconfigure(encoding='utf-8')

# ════════════════════════════════════════════════════════════════════════════
# ПАРАМЕТРЫ
# ════════════════════════════════════════════════════════════════════════════

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
QC_DIR = EXPORTS / 'qc'
STEP1 = EXPORTS / 'baresand_genesis_step1.gpkg'
LITTORAL_ATTRS = EXPORTS / 'baresand_littoral_v2.gpkg'

# Полоса поиска пропусков: от порога шага 1 до порога DNA W3
OMISSION_DIST_MIN_M = 100.0
OMISSION_DIST_MAX_M = 2000.0
# Южнее — сухопутная админ-граница, кандидаты бессмысленны
OMISSION_LAT_MIN = 66.0

# Подсказки
SUSPECT_OCC_MAX = 0.0    # shoal с occ_max <= 0 → подозрительный
LIKELY_SHOAL_OCC = 40.0  # кандидат с occ_max >= 40 → вероятная отмель

EA_CRS = 'EPSG:3576'


def main() -> None:
    t0 = time.time()
    QC_DIR.mkdir(exist_ok=True)

    print('═══════════════════════════════════════')
    print('QC-ПАКЕТ: ИТЕРАЦИЯ 1, КЛАСС «ПРИБРЕЖНЫЕ»')
    print('═══════════════════════════════════════')

    # ── Базовый слой шага 1 ──
    print(f'Загружаю {STEP1.name}...')
    gdf = gpd.read_file(STEP1)
    print(f'  Контуров: {len(gdf):,} | CRS: {gdf.crs}')

    # ── GSW-атрибуты из littoral_v2 (те же контуры contours_v2, join по id) ──
    print(f'Загружаю GSW-атрибуты из {LITTORAL_ATTRS.name}...')
    lit = gpd.read_file(LITTORAL_ATTRS, ignore_geometry=True)[
        ['id', 'gsw_occ_mean', 'gsw_occ_max', 'gsw_seas_max']]
    if lit['id'].duplicated().any():
        raise ValueError('littoral_v2: id не уникален — join невозможен')
    gdf = gdf.merge(lit, on='id', how='left', validate='1:1')
    n_no_gsw = int(gdf['gsw_occ_max'].isna().sum())
    print(f'  Join по id: OK | контуров без GSW-статы: {n_no_gsw:,}')

    # ── Широта/долгота в градусах (поля centroid_* в исходнике — метры, не использовать) ──
    cent_wgs = gdf.geometry.centroid.set_crs(EA_CRS, allow_override=True).to_crs('EPSG:4326')
    gdf['lat'] = cent_wgs.y.round(4)
    gdf['lon'] = cent_wgs.x.round(4)

    # округление для читаемости в QGIS
    gdf['dist_m'] = gdf['dist_aoi_boundary_m'].round(0)
    gdf['area_ha'] = gdf['area_ha'].round(2)
    gdf['gsw_occ_mean'] = gdf['gsw_occ_mean'].round(1)
    gdf['gsw_occ_max'] = gdf['gsw_occ_max'].round(1)

    cols = ['id', 'area_ha', 'dist_m', 'gsw_occ_mean', 'gsw_occ_max',
            'lat', 'lon', 'err_tag', 'geometry']

    # ── Слой 1: ревью включений ──
    sh = gdf[gdf['genesis'] == 'shoal'].copy()
    sh['suspect'] = ((sh['gsw_occ_max'].isna()) |
                     (sh['gsw_occ_max'] <= SUSPECT_OCC_MAX)).astype('int16')
    sh['err_tag'] = ''
    out1 = QC_DIR / 'qc_step1_shoal_review.gpkg'
    sh[['suspect'] + cols].to_file(out1, layer='shoal_review', driver='GPKG')

    n_susp = int(sh['suspect'].sum())
    print('')
    print(f'Слой 1 shoal_review: {len(sh):,} контуров | {sh["area_km2"].sum():.1f} км²')
    print(f'  из них suspect (37 лет без воды): {n_susp:,} '
          f'({sh.loc[sh["suspect"] == 1, "area_km2"].sum():.1f} км²) ← смотреть в первую очередь')

    # ── Слой 2: кандидаты на пропуск ──
    cand = gdf[(gdf['genesis'] == 'unassigned') &
               (gdf['dist_aoi_boundary_m'] >= OMISSION_DIST_MIN_M) &
               (gdf['dist_aoi_boundary_m'] < OMISSION_DIST_MAX_M) &
               (gdf['lat'] > OMISSION_LAT_MIN)].copy()
    cand['likely_shoal'] = (cand['gsw_occ_max'] >= LIKELY_SHOAL_OCC).astype('int16')
    cand['err_tag'] = ''
    out2 = QC_DIR / 'qc_step1_omission_candidates.gpkg'
    cand[['likely_shoal'] + cols].to_file(out2, layer='omission_candidates', driver='GPKG')

    n_likely = int(cand['likely_shoal'].sum())
    print('')
    print(f'Слой 2 omission_candidates ({OMISSION_DIST_MIN_M:.0f}–{OMISSION_DIST_MAX_M:.0f} м, '
          f'>{OMISSION_LAT_MIN:.0f}°N): {len(cand):,} контуров | {cand["area_km2"].sum():.1f} км²')
    print(f'  из них likely_shoal (occ_max≥{LIKELY_SHOAL_OCC:.0f}%): {n_likely:,} '
          f'({cand.loc[cand["likely_shoal"] == 1, "area_km2"].sum():.1f} км²) ← смотреть в первую очередь')

    print(f'\nСохранено: {out1}')
    print(f'           {out2}')
    print(f'Время: {(time.time()-t0)/60:.1f} мин')


if __name__ == '__main__':
    main()
