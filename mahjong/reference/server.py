"""HTTP 后端（只用标准库）。接口照 club-project/frontend/接口说明.md。

    python3 server.py --port 8000 [--page PATH]

只监听 127.0.0.1。GET / 返回牌桌页面：--page 指定的文件，否则 ../frontend/index.html（round-2 选手包里后端在
backend/，页面在旁边的 frontend/），再没有就用 ../club-project/frontend/index.html。
页面路径在载入模块时就定好，tools/http_bridge.py 把本文件当模块载入（不走 __main__）时 GET / 也能返回页面。
"""

import argparse
import json
import os
import sys
import threading
import traceback
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from game import Game                    # noqa: E402
from kyoku import ActionError            # noqa: E402
from rules import RuleError, parse_rules  # noqa: E402
from view import build_state             # noqa: E402

MAX_GAMES = 2000
LOCK = threading.Lock()
GAMES = OrderedDict()


class ApiError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


def find_page(arg=None):
    if arg:
        return os.path.abspath(arg)
    for p in (os.path.join(HERE, '..', 'frontend', 'index.html'),
              os.path.join(HERE, '..', 'club-project', 'frontend', 'index.html')):
        if os.path.exists(p):
            return os.path.abspath(p)
    return None


PAGE = find_page()


def _seat(v):
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 3:
        raise ApiError(400, 'seat 应该是 0-3 的整数')
    return v


def _game(gid):
    if not isinstance(gid, str) or gid not in GAMES:
        raise ApiError(404, '没有这局游戏：%r' % (gid,))
    GAMES.move_to_end(gid)
    return GAMES[gid]


def api_new_game(body):
    players = body.get('players', ['human', 'bot', 'bot', 'bot'])
    if not isinstance(players, list) or len(players) != 4 or any(p not in ('human', 'bot') for p in players):
        raise ApiError(400, 'players 应该是 4 个 "human" / "bot"')
    length = body.get('length', 'tonpuu')
    if length not in ('tonpuu', 'hanchan'):
        raise ApiError(400, 'length 只能是 tonpuu / hanchan')
    seed = body.get('seed')
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, (int, float, str))):
        raise ApiError(400, 'seed 应该是数字')
    try:
        rules = parse_rules(body.get('rules'))
    except RuleError as e:
        raise ApiError(400, str(e))
    gid = uuid.uuid4().hex[:12]
    g = Game(gid, players, length, seed, rules, body.get('wall'))
    GAMES[gid] = g
    while len(GAMES) > MAX_GAMES:
        GAMES.popitem(last=False)
    return build_state(g, 0)


def api_action(body):
    g = _game(body.get('game_id'))
    seat = _seat(body.get('seat'))
    if not isinstance(body.get('type'), str):
        raise ApiError(400, '缺少 type')
    g.act(seat, body)
    return build_state(g, seat)


def api_next(body):
    g = _game(body.get('game_id'))
    seat = _seat(body.get('seat', 0))
    g.next_round(body.get('wall'))
    return build_state(g, seat)


def api_state(query):
    g = _game((query.get('game_id') or [None])[0])
    try:
        seat = int((query.get('seat') or ['0'])[0])
    except ValueError:
        raise ApiError(400, 'seat 应该是 0-3 的整数')
    return build_state(g, _seat(seat))


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send(self, status, data, ctype='application/json; charset=utf-8'):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self._cors()
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, fn):
        try:
            with LOCK:
                res = fn()
            self._send(200, res)
        except ApiError as e:
            self._send(e.status, {'error': str(e)})
        except (ActionError, RuleError) as e:
            self._send(400, {'error': str(e)})
        except Exception as e:   # 后端自己的错：500，并把堆栈打到标准错误
            traceback.print_exc()
            self._send(500, {'error': '服务器内部错误：%s: %s' % (type(e).__name__, e)})

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ('/', '/index.html'):
            if not PAGE or not os.path.exists(PAGE):
                self._send(404, {'error': '找不到页面文件'})
                return
            with open(PAGE, 'rb') as f:
                self._send(200, f.read(), 'text/html; charset=utf-8')
        elif u.path == '/api/state':
            self._handle(lambda: api_state(parse_qs(u.query)))
        else:
            self._send(404, {'error': '没有这个地址：%s' % u.path})

    def do_POST(self):
        u = urlparse(self.path)
        routes = {'/api/new_game': api_new_game, '/api/action': api_action, '/api/next': api_next}
        if u.path not in routes:
            self._send(404, {'error': '没有这个地址：%s' % u.path})
            return
        try:
            n = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(n) if n else b''
            body = json.loads(raw.decode('utf-8')) if raw.strip() else {}
            if not isinstance(body, dict):
                raise ValueError('请求体应该是 JSON 对象')
        except (ValueError, UnicodeDecodeError) as e:
            self._send(400, {'error': '请求体不是合法的 JSON：%s' % e})
            return
        self._handle(lambda: routes[u.path](body))


def main():
    global PAGE
    ap = argparse.ArgumentParser(description='立直麻将参考后端')
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--page', default=None, help='GET / 返回的页面文件')
    args = ap.parse_args()
    PAGE = find_page(args.page)
    srv = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    srv.daemon_threads = True
    print('参考后端 http://127.0.0.1:%d/  页面：%s' % (args.port, PAGE), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
