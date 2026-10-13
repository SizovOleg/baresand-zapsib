"""
owner_click_server.py - локальный сервер окна проверки владельцем (2026-09-26).

Раздаёт exports/qc/owner_click/ и принимает метки: POST /api/save/<партия> с JSON {id: {label, note, t}}.
Метки СЛИВАЮТСЯ с уже сохранёнными (пришедшие записи заменяют те же id, остальные сохраняются), поэтому браузер
с пустым хранилищем не может стереть чужие метки. Файл пишется атомарно (временный файл + os.replace), каждое
сохранение дописывается в журнал labels_log.jsonl. Только 127.0.0.1.
Запуск (из .claude/launch.json, конфигурация owner-click): python python/owner_click_server.py --port 8777
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
import argparse
import json
import os
import re
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(r'D:\test\baresand_zapsib\exports\qc\owner_click')
BATCH_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')
LABELS = {'lake_shoal', 'river_shoal', 'shoal', 'aeolian', 'anthropogenic', 'not_sand', 'mixed', 'unresolved', 'disputed'}


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        # метки и страницы не кэшировать, иначе браузер покажет старое состояние
        if self.path.endswith('.json') or self.path.endswith('.html'):
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def _reply(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        m = re.match(r'^/api/save/([^/?#]+)$', self.path)
        if not m or not BATCH_RE.match(m.group(1)):
            return self._reply(404, {'ok': False, 'error': 'bad path'})
        batch_dir = ROOT / m.group(1)
        if not batch_dir.is_dir():
            return self._reply(404, {'ok': False, 'error': 'no batch'})
        try:
            n = int(self.headers.get('Content-Length', '0'))
            data = json.loads(self.rfile.read(n).decode('utf-8'))
            assert isinstance(data, dict)
            clean = {}
            for k, v in data.items():
                if str(k).isdigit() and isinstance(v, dict) and v.get('label') in LABELS:
                    clean[str(int(k))] = {'label': v['label'], 'note': str(v.get('note', ''))[:500], 't': str(v.get('t', ''))[:40]}
        except Exception as e:
            return self._reply(400, {'ok': False, 'error': str(e)[:200]})
        path = batch_dir / 'labels.json'
        old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        old.update(clean)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(old, ensure_ascii=False, indent=0), encoding='utf-8')
        os.replace(tmp, path)
        with (batch_dir / 'labels_log.jsonl').open('a', encoding='utf-8') as fh:
            fh.write(json.dumps({'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'received': len(clean), 'total': len(old)}) + '\n')
        return self._reply(200, {'ok': True, 'received': len(clean), 'total': len(old)})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8777)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), partial(Handler, directory=str(ROOT)))
    print(f'owner-click: http://localhost:{a.port}/ -> {ROOT}', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
