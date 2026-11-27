# 学号: 250226
# server.py - 网页版立直麻将后端接口（按前端《接口说明.md》实现）
#
# 修改说明（qwen4-max 整理）：
# - 原来字段名是自己定的，和前端对不上（页面顶上一串红字）。现在完全按《接口说明》返回：
#   version/game_id/phase/round/rules/players(hand 只给视角本人)/drawn/legal_actions/hints/events/result。
#   这些字段大部分由 game.get_state 直接给出，这里只补 version 和 game_id。
# - 启动命令改成前端要求的 `python3 server.py --port 8000`（默认 8000，只监听 127.0.0.1），
#   GET / 直接返回 frontend/index.html。原来默认 5000、也不回页面。
# - 支持多局：每次 new_game 生成新 game_id，按 game_id 存房间；action/state/next 校验 game_id。
# - 规则开关 rules、场数 length、players/seed/wall 都接住并传给 game。
# - 不再需要 server_patch.py 和猜番数的 YAKU_HAN 表：yaku 现在返回每役番数，game 直接给 result。
# - 只用标准库 http.server，不依赖 Flask。

import argparse
import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import game

INDEX_PATH = os.path.join(BASE_DIR, 'frontend', 'index.html')

# 房间：game_id -> Game
GAMES = {}


def _new_game(data):
    players = data.get('players') or ['human', 'bot', 'bot', 'bot']
    if not isinstance(players, list) or len(players) != 4:
        raise ValueError('players 要是 4 个元素的数组')
    human_seats = [i for i, p in enumerate(players) if p == 'human']
    if not human_seats:
        human_seats = [0]
    length = data.get('length', 'tonpuu')
    rules = data.get('rules') or {}
    if not isinstance(rules, dict):
        raise ValueError('rules 要是对象')
    seed = data.get('seed')
    wall = data.get('wall')
    g = game.Game(human_seats=human_seats, wall=wall, seed=seed, rules=rules, length=length)
    gid = 'g' + uuid.uuid4().hex[:12]
    GAMES[gid] = g
    return gid, g, human_seats[0]


def _get_game(data, qs=None):
    if qs is not None:
        gid = (qs.get('game_id') or [None])[0]
    else:
        gid = data.get('game_id')
    if not gid or gid not in GAMES:
        raise ValueError('game_id 无效，请先开新游戏')
    return gid, GAMES[gid]


def _seat(data, qs=None, default=0):
    try:
        if qs is not None:
            return int((qs.get('seat') or [default])[0])
        return int(data.get('seat', default))
    except (TypeError, ValueError):
        return default


def _state(gid, g, seat):
    if not 0 <= seat <= 3:
        raise ValueError('seat 要在 0~3')
    st = g.get_state(seat)
    st['version'] = 1
    st['game_id'] = gid
    return st


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 安静点

    def _send(self, data, status=200, ctype='application/json; charset=utf-8'):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg, status=400):
        self._send({'error': str(msg)}, status)

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in ('/', '/index.html'):
                with open(INDEX_PATH, 'rb') as f:
                    self._send(f.read(), ctype='text/html; charset=utf-8')
                return
            if path == '/api/state':
                qs = parse_qs(parsed.query)
                gid, g = _get_game(None, qs)
                seat = _seat(None, qs)
                self._send(_state(gid, g, seat))
                return
            self._err('not found', 404)
        except ValueError as e:
            self._err(e)
        except Exception as e:
            self._err('后端出错：%s' % e, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            data = self._read_json()
        except Exception:
            self._err('请求体不是合法 JSON')
            return
        try:
            if path == '/api/new_game':
                gid, g, seat = _new_game(data)
                self._send(_state(gid, g, seat))
                return

            gid, g = _get_game(data)
            seat = _seat(data)

            if path == '/api/action':
                a = str(data.get('type') or data.get('action') or '').strip().lower()
                if not a:
                    raise ValueError('缺少 type 参数')
                # 兼容个别简写
                if a in ('skip', 'cancel'):
                    a = 'pass'
                if a in ('hu', 'win', 'agari'):
                    a = 'tsumo' if g.phase == 'discard' else 'ron'
                tile = data.get('tile')
                tiles = data.get('tiles')
                tsumogiri = data.get('tsumogiri')
                g.do_action(seat, a, tile=tile, tiles=tiles, tsumogiri=tsumogiri)
                self._send(_state(gid, g, seat))
                return

            if path == '/api/next':
                g.next_round(wall=data.get('wall'))
                self._send(_state(gid, g, seat))
                return

            self._err('not found', 404)
        except ValueError as e:
            self._err(e)
        except Exception as e:
            self._err('后端出错：%s' % e, 500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--host', default='127.0.0.1')
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print('麻将后端已启动: http://%s:%d/' % (args.host, args.port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()