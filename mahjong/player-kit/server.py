# 学号: 250226
# server.py - 网页版立直麻将后端接口
#
# 说明：
# - 老师还没把前端程序员的接口文档发群里，字段名先按群文档里的转述和 game.py 里的结构自己定了，
#   等文档发下来再一起对一下改。
# - 用 Python 自带的 http.server 写的，不用额外装 Flask，直接 python3 server.py 就能跑。
# - 几个同学的函数格式有点对不上，我没有动大家的源码，都在这里做了转换：
#   1. score.py 的 calc_score 返回的是 dict，game.py 里按元组 (得分, 各付) 拆的，这里包了一层。
#   2. 听牌提示 hints 在 game.py 里没算，这里直接调 tenpai.py 的 discard_hints / get_waits 补上。

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

# 确保能 import 同目录下的其他同学模块
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import game
import score
import tenpai


# ---------- 兼容层：把 score.py 的返回值转成 game.py 要的格式 ----------

_orig_calc_score = score.calc_score


def _compat_calc_score(fu, han, is_oya, is_tsumo, honba=0, kyotaku=0):
    res = _orig_calc_score(fu, han, is_oya, is_tsumo, honba, kyotaku)
    if isinstance(res, dict):
        gain = res.get('get', 0)
        if is_tsumo:
            if is_oya:
                return (gain, res.get('ko_pay', 0))
            return (gain, (res.get('oya_pay', 0), res.get('ko_pay', 0)))
        return (gain, res.get('ron_pay', 0))
    return res


# 直接挂到 game 模块上，省得改 250207 的代码
game.calc_score = _compat_calc_score


# ---------- 全局对局状态 ----------
# TODO: 现在只支持单人单局，后面如果社团网站要多人同时玩再按房间号存 dict

current_game = None
DEFAULT_SEAT = 0


def _ensure_game():
    global current_game
    if current_game is None:
        current_game = game.Game(human_seats=[DEFAULT_SEAT])
    return current_game


def _build_hints(g, seat):
    """调 260522 的 tenpai.py 算听牌提示"""
    if g.phase == 'end':
        return {'waits': {}, 'discards': {}}
    try:
        hand = list(g.hands[seat])
        melds = g.melds_plain(seat)
        visible = g.get_visible(seat)
        total = len(hand) + 3 * len(melds)
        if total == 14:
            discards = tenpai.discard_hints(hand, melds, visible)
            return {'waits': {}, 'discards': discards}
        elif total == 13:
            waits = tenpai.get_waits(hand, melds, visible)
            return {'waits': waits, 'discards': {}}
    except Exception as e:
        # 听牌提示出问题先别把整个接口搞崩
        return {'waits': {}, 'discards': {}, 'error': str(e)}
    return {'waits': {}, 'discards': {}}


def _build_state_response(g, seat=DEFAULT_SEAT):
    """拼装给前端的完整状态 JSON"""
    st = g.get_state(seat)
    last_d = st.get('last_discard')
    if isinstance(last_d, (list, tuple)) and len(last_d) == 2:
        last_d = {'seat': last_d[0], 'tile': last_d[1]}

    return {
        'ok': True,
        'seat': seat,
        'round': st['round'],
        'dora': st['dora'],
        'dora_indicators': st['dora_indicators'],
        'remaining': st['remaining'],
        'current': st['current'],
        'drawn': st['drawn'],
        'phase': st['phase'],
        'last_discard': last_d,
        'players': st['players'],
        'legal_actions': st['legal_actions'],
        'hints': _build_hints(g, seat),
        'result': st['result'],
        'game_over': st['game_over'],
    }


def _normalize_action(g, action):
    """前端可能传简写（比如 hu / skip），这里稍微兼容一下"""
    if not action:
        return action
    a = str(action).strip().lower()
    if a in ('skip', 'cancel'):
        return 'pass'
    if a in ('hu', 'win', 'agari'):
        return 'tsumo' if g.phase == 'discard' else 'ron'
    return a


# ---------- HTTP 服务 ----------

class MahjongHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        # 加上跨域头，方便前端本地直接调试
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(body)

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

        if path == '/api/state':
            qs = parse_qs(parsed.query)
            try:
                seat = int(qs.get('seat', [DEFAULT_SEAT])[0])
            except ValueError:
                seat = DEFAULT_SEAT
            g = _ensure_game()
            self._send_json(_build_state_response(g, seat))
            return

        if path == '/':
            self._send_json({'ok': True, 'msg': 'mahjong backend running'})
            return

        self._send_json({'ok': False, 'error': 'not found'}, status=404)

    def do_POST(self):
        global current_game
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            data = self._read_json()
        except Exception:
            self._send_json({'ok': False, 'error': '请求体不是合法 JSON'}, status=400)
            return

        if path == '/api/new_game':
            try:
                seat = int(data.get('seat', DEFAULT_SEAT))
                wall = data.get('wall')
                seed = data.get('seed')
                current_game = game.Game(human_seats=[seat], wall=wall, seed=seed)
                self._send_json(_build_state_response(current_game, seat))
            except Exception as e:
                self._send_json({'ok': False, 'error': str(e)}, status=400)
            return

        if path == '/api/action':
            if current_game is None:
                self._send_json({'ok': False, 'error': '还没开局，请先调用 /api/new_game'}, status=400)
                return
            try:
                seat = int(data.get('seat', DEFAULT_SEAT))
                raw_action = data.get('action') or data.get('type')
                action = _normalize_action(current_game, raw_action)
                tile = data.get('tile')
                tiles = data.get('tiles')
                if not action:
                    self._send_json({'ok': False, 'error': '缺少 action 参数'}, status=400)
                    return
                current_game.do_action(seat, action, tile=tile, tiles=tiles)
                self._send_json(_build_state_response(current_game, seat))
            except ValueError as e:
                self._send_json({'ok': False, 'error': str(e)}, status=400)
            except Exception as e:
                self._send_json({'ok': False, 'error': '执行操作失败: ' + str(e)}, status=500)
            return

        if path == '/api/next':
            if current_game is None:
                self._send_json({'ok': False, 'error': '还没开局'}, status=400)
                return
            try:
                seat = int(data.get('seat', DEFAULT_SEAT))
                wall = data.get('wall')
                current_game.next_round(wall=wall)
                self._send_json(_build_state_response(current_game, seat))
            except ValueError as e:
                self._send_json({'ok': False, 'error': str(e)}, status=400)
            except Exception as e:
                self._send_json({'ok': False, 'error': '进入下一局失败: ' + str(e)}, status=500)
            return

        self._send_json({'ok': False, 'error': 'not found'}, status=404)


def run_server(host='127.0.0.1', port=5000):
    server = HTTPServer((host, port), MahjongHandler)
    print(f'麻将后端已启动: http://{host}:{port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n服务已停止')
    finally:
        server.server_close()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    run_server(port=port)