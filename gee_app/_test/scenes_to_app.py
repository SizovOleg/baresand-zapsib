# Перенос сцен тайлов в таблицу SCENES приложения (baresand_app.js, раздел 2).
# Источник (19.11.2026): scenes_from_scripts_final.csv, сцены восстановлены по копиям 21_<тайл>_.js из репозитория GEE
# автора (scenes_from_scripts.py: те же даты, месяцы, порог облачности, сортировка, NUM_SCENES и номера USE_SCENES; при
# нескольких номерах классифицировалась мозаика сцен). У 43VEJ копии с _ нет: по копии 21_43VEJ.js и по покрытию
# контуров итогового слоя это мозаика двух сцен (статус cover).
# Проверка по векторам: вне следов данных восстановленных сцен 36 из 575 054 контуров (0,24 км²), 21 из них ближе 30 м.
# Запуск: PYTHONIOENCODING=utf-8 python repo/gee_app/_test/scenes_to_app.py
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
APP = HERE.parent / 'baresand_app.js'
CSV = HERE / 'scenes_from_scripts_final.csv'


def main() -> None:
    d = pd.read_csv(CSV).sort_values('tile')
    lines = []
    for r in d.itertuples(index=False):
        sc = [x for x in str(r.scenes).split(';') if x and x != 'nan']
        v = 'cover' if r.tile == '43VEJ' else 'script'
        use = str(r.use).replace("'", '')
        cs = ', '.join("'" + x + "'" for x in sc)
        lines.append(f"  {{t: '{r.tile}', v: '{v}', u: '{use}', c: [{cs}]}}")
    block = 'var SCENES = [\n' + ',\n'.join(lines) + '\n];'
    src = APP.read_text(encoding='utf-8')
    new, n = re.subn(r'var SCENES = \[\r?\n.*?\r?\n\];', lambda m: block, src, count=1, flags=re.S)
    if n != 1:
        raise SystemExit('блок SCENES не найден')
    APP.write_text(new, encoding='utf-8')
    print('тайлов:', len(d), '| сцен на тайл:', d.n_scenes.value_counts().to_dict())


if __name__ == '__main__':
    main()
