# 学号: 250226
# server.py - 网页版立直麻将后端接口
#
# [修改] 拼代码时按 frontend/接口说明.md 重写了（原来的字段是按转述猜的，说明当时还没发下来）。
# 老师的 server_patch.py 里的格式转换也并进来了，那个文件不再需要。
#
# 启动（上线就用这条）：python3 server.py --port 8000
#   - 只监听 127.0.0.1；GET / 返回 frontend/index.html
#   - 只用 Python 标准库（http.server），不用装 Flask
#   - 一个进程可以同时开很多局，按 game_id 分开存（只留最近 MAX_GAMES 局）

import argparse
import itertools
import json
import os
import random
import sys
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import game     # noqa: E402
import tenpai   # noqa: E402

INDEX = os.path.join(BASE_DIR, 'frontend', 'index.html')
MAX_GAMES = 500

GAMES = OrderedDict()          # game_id -> Room
LOCK = threading.Lock()        # 同一时间只处理一个请求里的对局逻辑
_ids = itertools.count(1)
_id_salt = '%04x' % random.SystemRandom().randrange(0x10000)


class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


class Room:
    def __init__(self, game_id, players, g):
        self.game_id = game_id
        self.players = players     # ['human', 'bot', ...]
        self.g = g


# ---------- 状态：game 里的数据 -> 前端要的格式 ----------

def _names(room):
    res = []
    bot = 0
    for i, p in enumerate(room.players):
        if p == 'human':
            res.append('你' if room.players.count('human') == 1 else '玩家 %d' % i)
        else:
            bot += 1
            res.append('电脑 %d' % bot)
    return res


def _meld_out(m):
    return {'type': m['type'], 'tiles': list(m['tiles']), 'from': m.get('from'),
            'called_tile': m.get('called_tile')}


def _legal(g, seat):
    """game 的 legal_actions 改成页面的写法（吃/碰合并成 options，杠分成 ankan/kakan/minkan）"""
    res = []
    chi_opts, pon_opts, ankan, kakan = [], [], [], []
    for a in g.get_legal_actions(seat):
        t = a['type']
        if t == 'chi':
            chi_opts.append(list(a['tiles']))
        elif t == 'pon':
            pon_opts.append(list(a['tiles']))
        elif t == 'kan':
            kind = a.get('kind')
            if kind == 'ankan':
                ankan.append(a['tiles'][0])
            elif kind == 'kakan':
                kakan.append(a['tiles'][0])
            else:
                res.append({'type': 'minkan'})
        elif t in ('discard', 'riichi'):
            res.append({'type': t, 'tiles': list(a['tiles'])})
        else:
            res.append({'type': t})
    if chi_opts:
        res.append({'type': 'chi', 'options': chi_opts})
    if pon_opts:
        res.append({'type': 'pon', 'options': pon_opts})
    if ankan:
        res.append({'type': 'ankan', 'tiles': ankan})
    if kakan:
        res.append({'type': 'kakan', 'tiles': kakan})
    return res


def _tile_left(d):
    return [{'tile': t, 'left': n} for t, n in d.items()]


def _hints(g, seat, legal):
    """调 260522 的 tenpai.py 算听牌提示"""
    if g.phase == 'end':
        return None
    hand = list(g.hands[seat])
    melds = g.melds_plain(seat)
    visible = g.get_visible(seat)
    total = len(hand) + 3 * len(melds)
    out = {'waits': [], 'furiten': False, 'discards': {}}
    if total == 14:
        can = None
        for a in legal:
            if a['type'] == 'discard':
                can = set(a['tiles'])
        for t, w in tenpai.discard_hints(hand, melds, visible).items():
            if can is None or t in can:
                out['discards'][t] = _tile_left(w)
    elif total == 13:
        waits = tenpai.get_waits(hand, melds, visible)
        out['waits'] = _tile_left(waits)
        out['furiten'] = bool(waits) and g._is_furiten(seat)
    return out


def _waiting_for(g):
    if g.phase == 'discard':
        return [g.current] if g.current in g.human_seats else []
    if g.phase == 'call':
        return sorted(s for s in g.call_options if s in g.human_seats and s not in g.responses)
    return []


def _events(g, viewer):
    res = []
    for e in g.events:
        e = dict(e)
        if e['type'] == 'draw' and e['seat'] != viewer:
            e['tile'] = None     # 别人摸了什么不能给
        res.append(e)
    return res


def build_state(room, viewer):
    g = room.g
    if g.phase == 'end':
        phase = 'game_end' if g.game_over else 'round_end'
    else:
        phase = 'playing'
    names = _names(room)
    players = []
    for s in range(4):
        hand = list(g.hands[s])
        # game 的手牌里含刚摸的那张，页面是手牌和 drawn 分开画
        if g.phase == 'discard' and s == g.current and g.drawn is not None:
            hand.remove(g.drawn)
        p = {
            'seat': s,
            'name': names[s],
            'score': g.scores[s],
            'seat_wind': g.jikaze(s),
            'riichi': g.riichi[s],
            'discards': [{'tile': d['tile'], 'tsumogiri': d['tsumogiri'], 'riichi': d['riichi'],
                          'called': d['called']} for d in g.rivers[s]],
            'melds': [_meld_out(m) for m in g.melds[s]],
            'hand_count': len(hand),
        }
        if s == viewer:
            p['hand'] = hand
        players.append(p)
    legal = _legal(g, viewer) if phase == 'playing' else []
    drawn = g.drawn if (g.phase == 'discard' and viewer == g.current) else None
    return {
        'version': 1,
        'game_id': room.game_id,
        'phase': phase,
        'round': {
            'wind': g.bakaze,
            'number': g.oya + 1,
            'honba': g.honba,
            'riichi_sticks': g.kyotaku,
            'dealer': g.oya,
        },
        'dora_indicators': g.dora_indicators(),
        'wall_left': g.remaining(),
        'viewer': viewer,
        'turn': g.current,
        'waiting_for': _waiting_for(g) if phase == 'playing' else [],
        'rules': dict(g.rules),
        'players': players,
        'drawn': drawn,
        'legal_actions': legal,
        'hints': _hints(g, viewer, legal),
        'events': _events(g, viewer),
        'result': g.result if g.phase == 'end' else None,
    }


# ---------- 请求处理 ----------

def _seat(v, default=0):
    if v is None:
        return default
    try:
        s = int(v)
    except (TypeError, ValueError):
        raise ApiError('seat 应该是 0~3')
    if s not in (0, 1, 2, 3):
        raise ApiError('seat 应该是 0~3')
    return s


def _room(game_id):
    room = GAMES.get(game_id)
    if room is None:
        raise ApiError('找不到这局游戏（game_id=%s），请重新开始新游戏' % game_id, 404)
    return room


def api_new_game(data):
    players = data.get('players') or ['human', 'bot', 'bot', 'bot']
    if (not isinstance(players, list) or len(players) != 4
            or any(p not in ('human', 'bot') for p in players)):
        raise ApiError('players 应该是 4 个 "human" / "bot"')
    length = data.get('length') or 'tonpuu'
    seed = data.get('seed')
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, (int, float, str))):
        raise ApiError('seed 不对')
    rules = data.get('rules') or {}
    if not isinstance(rules, dict):
        raise ApiError('rules 应该是对象')
    humans = [i for i, p in enumerate(players) if p == 'human']
    g = game.Game(human_seats=humans, wall=data.get('wall'), seed=seed, rules=rules, length=length)
    game_id = 'g%s%d' % (_id_salt, next(_ids))
    room = Room(game_id, players, g)
    GAMES[game_id] = room
    while len(GAMES) > MAX_GAMES:
        GAMES.popitem(last=False)
    return build_state(room, humans[0] if humans else 0)


# 前端的操作名 -> game.py 的操作名
ACTION_MAP = {'discard': 'discard', 'riichi': 'riichi', 'tsumo': 'tsumo', 'ron': 'ron',
              'chi': 'chi', 'pon': 'pon', 'minkan': 'kan', 'ankan': 'kan', 'kakan': 'kan',
              'kyuushu': 'kyuushu', 'pass': 'pass'}


def api_action(data):
    room = _room(data.get('game_id'))
    g = room.g
    seat = _seat(data.get('seat'))
    typ = data.get('type')
    if typ not in ACTION_MAP:
        raise ApiError('不认识的操作 type：%r' % (typ,))
    if room.players[seat] != 'human':
        raise ApiError('座位 %d 是电脑，不能替它操作' % seat)
    tile = data.get('tile')
    tiles = data.get('tiles')
    # ankan / kakan 要确认种类对得上（game.py 里都叫 kan）
    if typ in ('ankan', 'kakan'):
        kinds = [a for a in g.get_legal_actions(seat) if a['type'] == 'kan' and a.get('kind') == typ]
        if not any(tile is None or game.norm(str(tile)) == a['tiles'][0] for a in kinds):
            raise ApiError('现在不能%s这张' % ('暗杠' if typ == 'ankan' else '加杠'))
    if typ == 'minkan' and g.phase != 'call':
        raise ApiError('现在不能明杠')
    g.do_action(seat, ACTION_MAP[typ], tile=tile, tiles=tiles, tsumogiri=data.get('tsumogiri'))
    return build_state(room, seat)


def api_next(data):
    room = _room(data.get('game_id'))
    seat = _seat(data.get('seat'))
    room.g.next_round(wall=data.get('wall'))
    return build_state(room, seat)


def api_state(qs):
    room = _room((qs.get('game_id') or [None])[0])
    seat = _seat((qs.get('seat') or [None])[0])
    return build_state(room, seat)


class MahjongHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass   # 不刷屏

    def _cors(self):
        # 加上跨域头，方便前端本地直接调试（?api=http://localhost:8000）
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send(self, body, ctype, status=200):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data, status=200):
        self._send(json.dumps(data, ensure_ascii=False).encode('utf-8'),
                   'application/json; charset=utf-8', status)

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError('请求体不是合法 JSON')
        if not isinstance(data, dict):
            raise ApiError('请求体应该是 JSON 对象')
        return data

    def _handle(self, fn):
        try:
            with LOCK:
                out = fn()
            self._send_json(out)
        except ApiError as e:
            self._send_json({'error': str(e)}, e.status)
        except ValueError as e:      # game.py 里不合法的操作都是 ValueError
            self._send_json({'error': str(e)}, 400)
        except Exception as e:       # 别让一个请求把服务搞崩
            self._send_json({'error': '后端出错：%s: %s' % (type(e).__name__, e)}, 500)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            try:
                with open(INDEX, 'rb') as f:
                    body = f.read()
            except OSError:
                self._send_json({'error': '找不到 frontend/index.html'}, 500)
                return
            self._send(body, 'text/html; charset=utf-8')
            return
        if parsed.path == '/api/state':
            self._handle(lambda: api_state(parse_qs(parsed.query)))
            return
        self._send_json({'error': 'not found'}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        routes = {'/api/new_game': api_new_game, '/api/action': api_action, '/api/next': api_next}
        if path not in routes:
            self._send_json({'error': 'not found'}, 404)
            return
        self._handle(lambda: routes[path](self._read_json()))


def run_server(host='127.0.0.1', port=8000):
    server = ThreadingHTTPServer((host, port), MahjongHandler)
    print('麻将后端已启动: http://%s:%d/' % (host, port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='网页麻将后端')
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--host', default='127.0.0.1')
    args = ap.parse_args()
    run_server(args.host, args.port)
