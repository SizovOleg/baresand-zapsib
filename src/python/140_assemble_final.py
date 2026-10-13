"""
140_assemble_final.py - итоговая папка exports/final: шейпы техногена для ArcMap 10.8, граница района, README (2026-10-06).

Итоговый продукт и слои техногена пишет 133 (--out-product exports/final/baresand_genesis_v7.gpkg, --out-layers
exports/final/baresand_anthro_cadastre_v7.gpkg). Этот скрипт добавляет:
  - exports/final/anthro_shp/: anthro_in, anthro_exceed, anthro_noallot (вариант А 13.10.2026; до него anthro_in, anthro_out,
    anthro_excess, anthro_unreg) (ESRI Shapefile, UTF-8 с .cpg; ArcMap
    10.8 открывает шейпы надёжнее, чем GPKG); имена полей не длиннее 10 знаков (проверка);
  - exports/final/aoi/: граница района работ и покрытие маски (копии vector/baresand_aoi_v2.*, mask_coverage_128tiles.*);
  - exports/final/README.md: состав, классы, поля, оговорки, цифры из отчётов 138/133/139.
Существующие шейпы перезаписываются (это выход скрипта). Стили не делаются: владелец настраивает сам в ArcMap 10.8.
Запуск: PYTHONIOENCODING=utf-8 python -u python/140_assemble_final.py
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import shutil
import time
from pathlib import Path

import pyogrio

ROOT = Path(r'D:\test\baresand_zapsib')
FINAL = ROOT / 'exports' / 'final'
PRODUCT = FINAL / 'baresand_genesis_v7.gpkg'
LAYERS = FINAL / 'baresand_anthro_cadastre_v7.gpkg'
VECTOR = ROOT / 'vector'
SHP_LAYERS = ('anthro_in', 'anthro_exceed', 'anthro_noallot')     # вариант А (133 --territory, 13.10.2026)
AOI = ('baresand_aoi_v2', 'mask_coverage_128tiles')


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def export_shp() -> list[str]:
    out = FINAL / 'anthro_shp'
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for lay in SHP_LAYERS:
        d = pyogrio.read_dataframe(LAYERS, layer=lay)
        long = [c for c in d.columns if c != 'geometry' and len(c) > 10]
        if long:
            raise ValueError(f'{lay}: имена полей длиннее 10 знаков: {long}')
        for f in out.glob(f'{lay}.*'):
            f.unlink()
        pyogrio.write_dataframe(d, out / f'{lay}.shp', driver='ESRI Shapefile', encoding='UTF-8')
        lines.append(f'{lay}: {len(d)} объектов, {d["area_ha"].sum() / 100:.1f} км2')
        log(lines[-1])
    return lines


def copy_aoi() -> None:
    out = FINAL / 'aoi'
    out.mkdir(parents=True, exist_ok=True)
    for stem in AOI:
        src = sorted(VECTOR.glob(f'{stem}.*'))
        if not src:
            raise FileNotFoundError(f'нет {VECTOR / stem}.*')
        for f in src:
            shutil.copy2(f, out / f.name)
    log(f'граница района и покрытие -> {out}')


def main() -> None:
    for p in (PRODUCT, LAYERS):
        if not p.exists():
            raise FileNotFoundError(p)
    shp = export_shp()
    copy_aoi()
    log('README пишется отдельно (docs и цифры итоговой версии): exports/final/README.md')
    print('\n'.join(shp))


if __name__ == '__main__':
    main()
