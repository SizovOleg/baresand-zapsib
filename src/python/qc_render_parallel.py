"""
BareSand — Параллельный предрендер снимков Esri для визуальной QC.

Берёт id из visual_sample_step1.json (+ visual_sample_step1_flat.json, если есть),
пропускает уже отрендеренные PNG, делит на N воркеров и гонит qc_thumb_xyz.py параллельно
(узкое место — сеть; кэш тайлов пишется атомарно, воркеры не мешают друг другу).

Запуск: python -u python/qc_render_parallel.py [--workers 6] [--batch 12]
"""
import sys
import json
import argparse
import subprocess
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

QC = Path(r'D:\test\baresand_zapsib\exports\qc')
THUMB = Path(r'D:\test\baresand_zapsib\python\qc_thumb_xyz.py')
SAMPLES = [QC / 'visual_sample_step1.json', QC / 'visual_sample_step1_flat.json']


def collect_ids() -> list[int]:
    ids: list[int] = []
    for p in SAMPLES:
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding='utf-8'))
        for _, v in d.items():
            ids.extend(int(i) for i in (v['ids'] if isinstance(v, dict) else v))
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--batch', type=int, default=12)
    ap.add_argument('--samples', nargs='*', default=None, help='json-файлы выборок (по умолчанию шаг 1)')
    ap.add_argument('--out', default=str(QC / 'thumbs'))
    ap.add_argument('--overlay', default=None)
    ap.add_argument('--field', default='genesis')
    ap.add_argument('--sample', default=None)
    ap.add_argument('--evidence', default=None)
    ap.add_argument('--km', default=None, help='фиксированное окно, км (для приближенных снимков мелких контуров)')
    a = ap.parse_args()
    t0 = time.time()
    global SAMPLES
    if a.samples:
        SAMPLES = [Path(p) for p in a.samples]
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    extra = ['--out', str(out_dir)]
    for k in ('overlay', 'field', 'sample', 'evidence', 'km'):
        v = getattr(a, k)
        if v:
            extra += [f'--{k}', str(v)]

    ids = collect_ids()
    todo = [i for i in ids if not (out_dir / f'{i}_esri.png').exists()]
    print(f'всего id: {len(ids)} | к рендеру: {len(todo)} | воркеров: {a.workers}', flush=True)

    batches = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
    log_dir = out_dir / '_logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    # stdout/stderr воркеров — в файлы: PIPE в Windows имеет буфер 4 КБ и даёт дедлок,
    # если родитель читает только после выхода дочернего процесса
    running: list[tuple[subprocess.Popen, list[int], Path, Path]] = []
    done, errors = 0, []
    bi = 0
    while bi < len(batches) or running:
        while len(running) < a.workers and bi < len(batches):
            b = batches[bi]
            bi += 1
            out_p, err_p = log_dir / f'batch_{bi:03d}.json', log_dir / f'batch_{bi:03d}.err'
            p = subprocess.Popen([sys.executable, str(THUMB), '--ids', *map(str, b), *extra],
                                 stdout=open(out_p, 'w', encoding='utf-8'),
                                 stderr=open(err_p, 'w', encoding='utf-8'))
            running.append((p, b, out_p, err_p))
        time.sleep(2.0)
        still = []
        for p, b, out_p, err_p in running:
            if p.poll() is None:
                still.append((p, b, out_p, err_p))
                continue
            p.wait()
            try:
                res = json.loads(out_p.read_text(encoding='utf-8'))
                errors += [x for x in res if 'error' in x]
                done += len([x for x in res if 'error' not in x])
            except Exception:  # noqa: BLE001
                errors.append({'batch': b[:3], 'error': err_p.read_text(encoding='utf-8', errors='replace')[-300:]})
            print(f'  готово {done}/{len(todo)} | ошибок {len(errors)} | {(time.time()-t0)/60:.1f} мин', flush=True)
        running = still

    n_png = len(list(out_dir.glob('*_esri.png')))
    print(f'\nPNG на диске: {n_png} | ошибок: {len(errors)} | время {(time.time()-t0)/60:.1f} мин')
    for e in errors[:10]:
        print('  ', e)


if __name__ == '__main__':
    main()
