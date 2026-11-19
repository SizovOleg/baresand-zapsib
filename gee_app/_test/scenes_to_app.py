# Перенос результата scene_match_precise.csv в таблицу SCENES приложения (baresand_app.js, раздел 2).
# Запуск: PYTHONIOENCODING=utf-8 python repo/gee_app/_test/scenes_to_app.py
# Статусы: id (охват следа маски и точная облачность совпали у одной сцены), amb (у нескольких сцен), fp (точного
# совпадения нет, показана наименее облачная сцена, совпавшая по охвату), cl (след маски не ограничен, сцена по
# облачности), no (ничего не найдено, показана сцена реестра).
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
APP = HERE.parent / 'baresand_app.js'
CSV = HERE / 'scene_match_precise.csv'


def status(r: pd.Series) -> tuple[str, list[str]]:
    match = [x for x in str(r.scenes_match).split(';') if x and x != 'nan']
    if match and not r.bounded:
        return 'cl', match
    if len(match) == 1:
        return 'id', match
    if len(match) > 1:
        return 'amb', sorted(match)
    fp = str(r.scene_fp_least_cloud)
    if fp and fp != 'nan':
        return 'fp', [fp]
    return 'no', []


def main() -> None:
    d = pd.read_csv(CSV)
    lines = []
    for r in d.itertuples(index=False):
        v, c = status(pd.Series(r._asdict()))
        cs = ', '.join("'" + x + "'" for x in c)
        lines.append(f"  {{t: '{r.tile}', s: '{r.scene_126}', v: '{v}', c: [{cs}]}}")
    block = 'var SCENES = [\n' + ',\n'.join(lines) + '\n];'
    src = APP.read_text(encoding='utf-8')
    new, n = re.subn(r'var SCENES = \[\r?\n.*?\r?\n\];', lambda m: block, src, count=1, flags=re.S)
    if n != 1:
        raise SystemExit('блок SCENES не найден')
    APP.write_text(new, encoding='utf-8')
    print(d.assign(v=[status(pd.Series(r._asdict()))[0] for r in d.itertuples(index=False)]).v.value_counts().to_dict())


if __name__ == '__main__':
    main()
