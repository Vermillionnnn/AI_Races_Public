# 学号: 250226（已整理修复）
# server.py - 网页版立直麻将后端服务（严格适配 frontend/接口说明.md）
#
# 启动命令：
#   python3 server.py --port 8000
# 默认监听 127.0.0.1:8000，GET / 返回 frontend/index.html。

import argparse
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
import threading
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import game

INDEX_HTML = os.path.join(BASE_DIR, 'frontend', 'index.html')
MAX_GAMES = 32

_lock = threading.Lock()
_games = OrderedDict()
_game_seq = 0


def _create_game(data):
    global _game_seq
    players = data.get('players', ['human', 'bot', 'bot', 'bot'])
    if not isinstance(players, list) or len(players) != 4 or any(p not in ('human', 'bot') for p in players):
        raise ValueError('players 必须是长度为 4、元素为 "human" 或 "bot" 的数组')
    human_seats = [i for i, p in enumerate(players) if p == 'human']
    length = data.get('length', 'tonpuu')
    seed = data.get('seed')
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValueError('seed 必须是整数')
    rules = data.get('rules')
    wall = data.get('wall')

    g = game.Game(
        human_seats=human_seats,
        wall=wall,
        seed=seed,
        length=length,
        rules=rules,
    )
    _game_seq += 1
    gid = f'g{_game_seq}'
    _games[gid] = g
    while len(_games) > MAX_GAMES:
        _games.popitem(last=False)
    return gid, g


def _get_game(gid):
    if not gid or gid not in _games:
        raise ValueError('找不到对应的对局，请先调用 /api/new_game')
    return _games[gid]


def _parse_seat(val, default=None):
    if val is None:
        if default is not None:
            return default
        raise ValueError('缺少 seat 参数')
    if isinstance(val, bool):
        raise ValueError('seat 必须是 0~3 的整数')
    try:
        seat = int(val)
    except (TypeError, ValueError):
        raise ValueError('seat 必须是 0~3 的整数')
    if seat not in (0, 1, 2, 3):
        raise ValueError('seat 必须是 0~3 的整数')
    return seat


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class MahjongHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 保持简洁日志，不刷屏
        pass

    def _add_cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._add_cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self):
        try:
            with open(INDEX_HTML, 'rb') as f:
                body = f.read()
        except OSError as e:
            self._send_json({'error': f'无法读取前端页面: {e}'}, status=500)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._add_cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        obj = json.loads(raw.decode('utf-8'))
        if not isinstance(obj, dict):
            raise ValueError('请求体必须是 JSON 对象')
        return obj

    def do_OPTIONS(self):
        self.send_response(204)
        self._add_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ('/', '/index.html'):
            self._send_html()
            return

        if path == '/api/state':
            qs = parse_qs(parsed.query)
            try:
                gid = qs.get('game_id', [None])[0]
                seat_raw = qs.get('seat', ['0'])[0]
                seat = _parse_seat(seat_raw)
                with _lock:
                    g = _get_game(gid)
                    state = g.to_api_state(viewer=seat, game_id=gid)
                self._send_json(state)
            except ValueError as e:
                self._send_json({'error': str(e)}, status=400)
            except Exception as e:
                self._send_json({'error': f'获取状态失败: {e}'}, status=500)
            return

        self._send_json({'error': 'not found'}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            data = self._read_json()
        except Exception:
            self._send_json({'error': '请求体不是合法的 JSON 对象'}, status=400)
            return

        if path == '/api/new_game':
            try:
                with _lock:
                    gid, g = _create_game(data)
                    state = g.to_api_state(viewer=0, game_id=gid)
                self._send_json(state)
            except ValueError as e:
                self._send_json({'error': str(e)}, status=400)
            except Exception as e:
                self._send_json({'error': f'开局失败: {e}'}, status=500)
            return

        if path == '/api/action':
            try:
                gid = data.get('game_id')
                seat = _parse_seat(data.get('seat'))
                action_type = data.get('type') or data.get('action')
                if not isinstance(action_type, str) or not action_type.strip():
                    raise ValueError('缺少 type 参数')
                action_type = action_type.strip().lower()
                tile = data.get('tile')
                tiles = data.get('tiles')
                tsumogiri = data.get('tsumogiri')
                if tsumogiri is not None and not isinstance(tsumogiri, bool):
                    raise ValueError('tsumogiri 必须是布尔值')
                with _lock:
                    g = _get_game(gid)
                    g.do_action(seat, action_type, tile=tile, tiles=tiles, tsumogiri=tsumogiri)
                    state = g.to_api_state(viewer=seat, game_id=gid)
                self._send_json(state)
            except ValueError as e:
                self._send_json({'error': str(e)}, status=400)
            except Exception as e:
                self._send_json({'error': f'执行操作失败: {e}'}, status=500)
            return

        if path == '/api/next':
            try:
                gid = data.get('game_id')
                seat = _parse_seat(data.get('seat', 0))
                wall = data.get('wall')
                with _lock:
                    g = _get_game(gid)
                    g.next_round(wall=wall)
                    state = g.to_api_state(viewer=seat, game_id=gid)
                self._send_json(state)
            except ValueError as e:
                self._send_json({'error': str(e)}, status=400)
            except Exception as e:
                self._send_json({'error': f'进入下一局失败: {e}'}, status=500)
            return

        self._send_json({'error': 'not found'}, status=404)


def run_server(host='127.0.0.1', port=8000):
    httpd = ReusableThreadingHTTPServer((host, port), MahjongHandler)
    print(f'麻将服务已启动: http://{host}:{port}/', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main():
    default_port = int(os.environ.get('PORT', 8000))
    parser = argparse.ArgumentParser(description='立直麻将后端服务器')
    parser.add_argument('--port', type=int, default=default_port, help='监听端口（默认 8000）')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='监听地址（默认 127.0.0.1）')
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


if __name__ == '__main__':
    main()
