"""
BareSand — Генезис, ШАГ 1: морские отмели (первое приближение).

Подход (по решению владельца): отмель = контуры, ПРИЛЕГАЮЩИЕ к границе AOI.
Северная граница AOI = береговая линия (Карское море, Обская/Тазовская/Гыданская
губы, Енисейский залив). Контур, касающийся этой границы, в первом приближении —
морская/прибрежная отмель. Никаких GSW/HND-правил на этом шаге.

Сброс: генезис-классификация (littoral_v2 с W0–W3) отбрасывается. Стартуем
от чистых контуров baresand_contours_v2.gpkg.

Вход:
  - exports/baresand_contours_v2.gpkg  (574k контуров, EPSG:3576)
  - exports/aoi_v2.geojson             (полигон AOI)
Выход:
  - exports/baresand_genesis_step1.gpkg
    genesis = 'shoal' (прилегает к границе) | 'unassigned' (на шаг 2)
    + dist_aoi_boundary_m

Запуск:
  python python/32b_step1_shoal.py            # порог по умолчанию
  python python/32b_step1_shoal.py 300        # порог 300 м
"""

import sys
import time
from pathlib import Path

import geopandas as gpd

sys.stdout.reconfigure(encoding='utf-8')

EXPORTS = Path(r'D:\test\baresand_zapsib\exports')
CONTOURS = EXPORTS / 'baresand_contours_v2.gpkg'
AOI_GEOJSON = EXPORTS / 'aoi_v2.geojson'
OUTPUT = EXPORTS / 'baresand_genesis_step1.gpkg'

# Порог «прилегания» к границе (м). 0 = касание; 100 = в пределах ~10 пикселей.
SHOAL_DIST_M = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0

EA_CRS = 'EPSG:3576'  # equal-area, в нём считаем расстояния


def main() -> None:
    t0 = time.time()
    print('═══════════════════════════════════════')
    print('ГЕНЕЗИС ШАГ 1: МОРСКИЕ ОТМЕЛИ (первое приближение)')
    print('═══════════════════════════════════════')
    print(f'Порог прилегания к границе AOI: {SHOAL_DIST_M:.0f} м')

    # ── Сброс: чистые контуры ──
    print(f'\nЗагружаю чистые контуры: {CONTOURS.name}')
    gdf = gpd.read_file(CONTOURS).to_crs(EA_CRS)
    print(f'  Контуров: {len(gdf):,} | площадь {gdf["area_km2"].sum():.0f} км²')

    # оставляем только базовые атрибуты (сброс любых прежних genesis-полей)
    keep = [c for c in ['id', 'area_ha', 'area_km2', 'perimeter_m', 'compactness',
                        'centroid_lon', 'centroid_lat', 'geometry'] if c in gdf.columns]
    gdf = gdf[keep].copy()

    # ── Граница AOI ──
    print('Считаю расстояние до границы AOI...')
    aoi = gpd.read_file(AOI_GEOJSON).to_crs(EA_CRS)
    aoi_boundary = aoi.geometry.union_all().boundary
    gdf['dist_aoi_boundary_m'] = gdf.geometry.distance(aoi_boundary)

    # ── Выделение прилегающих ──
    gdf['genesis'] = 'unassigned'
    is_shoal = gdf['dist_aoi_boundary_m'] < SHOAL_DIST_M
    gdf.loc[is_shoal, 'genesis'] = 'shoal'

    n_shoal = int(is_shoal.sum())
    a_shoal = gdf.loc[is_shoal, 'area_km2'].sum()
    tot = gdf['area_km2'].sum()

    print('')
    print('═══════════════════════════════════════')
    print('РЕЗУЛЬТАТ')
    print('═══════════════════════════════════════')
    print(f'  ОТМЕЛЬ (прилегает к границе): {n_shoal:,} контуров | '
          f'{a_shoal:.1f} км² ({100*a_shoal/tot:.1f}%)')
    print(f'  Остаток (на шаг 2):          {len(gdf)-n_shoal:,} контуров | '
          f'{tot-a_shoal:.1f} км² ({100*(tot-a_shoal)/tot:.1f}%)')

    # ── Контроль: где лежат отмели по широте ──
    # Север = реальное море (Карское, губы). Юг ~61–63°N = сухопутная админ-граница.
    print('\n── Разбивка отмелей по широте (контроль ложного прилегания к суше) ──')
    sh = gdf[is_shoal]
    bands = [(-90, 63, '<63°N южная сух. граница (ПОДОЗРИТ.)'),
             (63, 66, '63–66°N'),
             (66, 69, '66–69°N губы'),
             (69, 90, '>69°N Карское море/Гыдан')]
    for lo, hi, label in bands:
        b = sh[(sh['centroid_lat'] >= lo) & (sh['centroid_lat'] < hi)]
        if len(b) == 0:
            continue
        print(f'  {label:38s}: {len(b):6,} конт. | {b["area_km2"].sum():7.1f} км²')

    gdf.to_file(OUTPUT, driver='GPKG', layer='genesis')
    print(f'\nСохранено: {OUTPUT}')
    print(f'  слой genesis: shoal / unassigned')
    print(f'Время: {time.time()-t0:.0f} с')


if __name__ == '__main__':
    main()
