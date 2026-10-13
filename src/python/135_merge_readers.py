"""
135_merge_readers.py - сведение двух слепых чтений кандидатов «техноген в эоловых» (134) и лист выборочной проверки.

Правило записано до просмотра ответов: exports/qc/aeolian_techno/prereg.md. Оба anthropogenic -> техноген (после
выборочной проверки владельцем); оба natural -> без изменений; остальное -> владельцу.
Выход: exports/qc/aeolian_techno/merged.csv (оба вердикта, согласие, решение), owner_review.csv (список владельцу),
spotcheck.csv и spotcheck_techno.png / spotcheck_natural.png (листы для выборочной проверки: крупные планы с id).
Мелкие кандидаты (137, 2026-10-06): --dir exports/qc/aeolian_techno_small --seed 20261006 --no-sheets (выборочная
проверка в окне 136, листы не нужны).
Запуск: PYTHONIOENCODING=utf-8 python -u python/135_merge_readers.py [--dir ПАПКА --seed N --no-sheets]
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

D = Path(r'D:\test\baresand_zapsib\exports\qc\aeolian_techno')
SEED = 20261005


def read_reader(name: str) -> pd.DataFrame:
    rows = []
    for f in sorted((D / name).glob('chunk_*.jsonl')):
        for line in f.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    r = pd.DataFrame(rows)
    if r['id'].duplicated().any():
        raise ValueError(f'{name}: повторы id {r.loc[r["id"].duplicated(), "id"].tolist()}')
    return r.set_index('id')


def font(size: int):
    try:
        return ImageFont.truetype('arial.ttf', size)
    except OSError:
        return ImageFont.load_default()


def sheet(ids: list[int], out: Path, title: str) -> None:
    """Лист крупных планов (правая половина снимка 134) 5 в ряд с подписью id."""
    tiles = []
    for i in ids:
        im = Image.open(D / 'img' / f'{i}.png').convert('RGB')
        w, h = im.size
        im = im.crop((w // 2, 40, w, h)).resize((480, int(480 * (h - 40) / (w / 2))))
        dr = ImageDraw.Draw(im)
        dr.rectangle((0, 0, 150, 30), fill='black')
        dr.text((6, 3), str(i), fill='yellow', font=font(22))
        tiles.append(im)
    cols = 5
    rows = (len(tiles) + cols - 1) // cols
    th = max(t.size[1] for t in tiles)
    canvas = Image.new('RGB', (cols * 480 + (cols + 1) * 6, rows * th + (rows + 1) * 6 + 40), 'white')
    ImageDraw.Draw(canvas).text((8, 8), title, fill='black', font=font(24))
    for k, t in enumerate(tiles):
        canvas.paste(t, (6 + (k % cols) * 486, 46 + (k // cols) * (th + 6)))
    canvas.save(out)


def main() -> None:
    global D, SEED
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=str(D))
    ap.add_argument('--seed', type=int, default=SEED)
    ap.add_argument('--no-sheets', action='store_true')
    args = ap.parse_args()
    D, SEED = Path(args.dir), args.seed
    b = pd.read_csv(D / 'batch.csv').set_index('id')
    a, bb = read_reader('readerA'), read_reader('readerB')
    for name, r in (('A', a), ('B', bb)):
        miss = sorted(set(b.index) - set(r.index))
        if miss:
            raise ValueError(f'читатель {name}: нет ответов для {len(miss)} id: {miss[:10]}')
    m = b[['area_ha', 'lat', 'lon', 'near_anthro', 'near_road']].join(a.add_suffix('_A')).join(bb.add_suffix('_B'))
    both_t = (m['verdict_A'] == 'anthropogenic') & (m['verdict_B'] == 'anthropogenic')
    both_n = (m['verdict_A'] == 'natural') & (m['verdict_B'] == 'natural')
    m['decision'] = 'owner'
    m.loc[both_t, 'decision'] = 'anthropogenic'
    m.loc[both_n, 'decision'] = 'natural'
    m.to_csv(D / 'merged.csv', encoding='utf-8')
    m[m['decision'] == 'owner'].to_csv(D / 'owner_review.csv', encoding='utf-8')
    ct = pd.crosstab(m['verdict_A'], m['verdict_B'], margins=True)
    agree = (m['verdict_A'] == m['verdict_B']).mean()
    print('Согласие читателей:', f'{agree:.1%}')
    print(ct.to_string())
    s = m.groupby('decision')['area_ha'].agg(['size', 'sum'])
    s['sum'] = (s['sum'] / 100).round(2)
    print('\nРешение (контуров, км2):'); print(s.to_string())
    st = m[both_t].sample(n=min(15, int(both_t.sum())), random_state=SEED)
    sn = m[both_n].sample(n=min(5, int(both_n.sum())), random_state=SEED)
    pd.concat([st.assign(set='techno'), sn.assign(set='natural')]).to_csv(D / 'spotcheck.csv', encoding='utf-8')
    if len(st) and not args.no_sheets:
        sheet(st.index.tolist(), D / 'spotcheck_techno.png', 'Выборочная проверка: оба читателя сказали «техноген» (15 случайных)')
    if len(sn) and not args.no_sheets:
        sheet(sn.index.tolist(), D / 'spotcheck_natural.png', 'Выборочная проверка: оба читателя сказали «природный» (5 случайных)')
    print(f'\n-> {D / "merged.csv"}, owner_review.csv ({int((m["decision"] == "owner").sum())}), spotcheck_*.png')


if __name__ == '__main__':
    main()
