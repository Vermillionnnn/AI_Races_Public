# 学号: 250226（原作者）；整合修改：claude-opus-5-5
# server.py - 网页版立直麻将后端接口，按 frontend/接口说明.md 的格式收发 JSON
#
# 启动：python3 server.py --port 8000     （不带参数默认 8000，只监听 127.0.0.1）
# 浏览器打开 http://127.0.0.1:8000/ 就是 frontend/index.html
#
# 和原来的 server.py / 老师的 server_patch.py 相比：
# - 合成一个文件，GET / 直接给页面，支持 --port，多局按 game_id 分开存。
# - 字段全部按 接口说明.md：phase / round / waiting_for / rules / events / result ……
# - 结算里每个役的番数、役满倍数直接用 yaku.py 算出来的，不再查表估。
# - points 不含本场和供托（说明里要求的），delta 含。

import argparse
import json
import os
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import game  # noqa: E402

INDEX = os.path.join(BASE_DIR, 'frontend', 'index.html')
MAX_GAMES = 200          # 内存里最多留这么多局，旧的丢掉

GAMES = {}               # game_id -> Game
LOCK = threading.Lock()  # 一次只处理一个请求，Game 不是线程安全的


class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


# ---------- 状态转换：Game -> 前端格式 ----------

def _tile_left(d):
    return [{'tile': t, 'left': n} for t, n in d.items()]


def _hints(g, seat):
    if g.phase == 'end':
        return None
    hand = list(g.hands[seat])
    melds = g.melds_plain(seat)
    visible = g.get_visible(seat)
    total = len(hand) + 3 * len(melds)
    out = {'waits': [], 'furiten': False, 'discards': {}}
    if total == 14 and seat == g.current and g.phase == 'discard':
        allowed = set()
        for a in g.get_legal_actions(seat):
            if a['type'] == 'discard':
                allowed = set(a['tiles'])
        for t, w in game.tenpai_discard_hints(hand, melds, visible).items():
            if t in allowed:
                out['discards'][t] = _tile_left(w)
        # 摸牌前的 13 张听什么（打掉刚摸的牌时）
        if g.drawn is not None:
            h13 = list(hand)
            h13.remove(g.drawn)
            out['waits'] = _tile_left(game.tenpai_get_waits(h13, melds, visible))
            out['furiten'] = bool(out['waits']) and g._is_furiten_hand(seat, h13)
    elif total == 13:
        out['waits'] = _tile_left(game.tenpai_get_waits(hand, melds, visible))
        out['furiten'] = bool(out['waits']) and g._is_furiten(seat)
    return out


def _legal(g, seat):
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
    # pass 放最后
    res.sort(key=lambda x: x['type'] == 'pass')
    return res


def _waiting_for(g):
    if g.phase == 'discard':
        return [g.current]
    if g.phase == 'call':
        return sorted(s for s in g.call_options if s not in g.responses)
    return []


def _meld_out(m):
    return {'type': m['type'], 'tiles': list(m['tiles']), 'from': m.get('from'),
            'called_tile': m.get('called_tile')}


def _result(g):
    r = g.result
    if not r:
        return None
    if r['type'] in ('tsumo', 'ron'):
        wins = []
        for w in r['wins']:
            hand = list(w['hand'])
            hand.remove(w['tile'])   # 前端要不含和了的那张
            wins.append({
                'seat': w['seat'],
                'from': w['from'],
                'hand': sorted(hand, key=game.tile_key),
                'melds': [_meld_out(m) for m in w['melds']],
                'win_tile': w['tile'],
                'yaku': [{'name': n, 'han': h} for n, h in w['yaku']],
                'han': w['han'],
                'fu': w['fu'] if not w['yakuman'] else 0,
                'yakuman': w['yakuman'],
                'points': w['points'],
            })
        return {
            'type': 'agari',
            'wins': wins,
            'dora_indicators': list(r['dora_indicators']),
            'uradora_indicators': list(r.get('ura_indicators') or []),
            'delta': list(r['delta']),
        }
    out = {
        'type': 'ryuukyoku',
        'reason': 'exhaustive' if r['type'] == 'ryuukyoku' else game.ABORT_KEY.get(r['reason'], r['reason']),
        'delta': list(r['delta']),
    }
    if r.get('tenpai') is not None:
        out['tenpai'] = list(r['tenpai'])
    return out


def _events(g, seat):
    out = []
    for e in g.events:
        e = dict(e)
        if e['type'] == 'draw' and e['seat'] != seat:
            e['tile'] = None
        out.append(e)
    return out


def build_state(gid, g, seat):
    if g.phase == 'end':
        phase = 'game_end' if g.game_over else 'round_end'
    else:
        phase = 'playing'
    drawn = g.drawn if (g.phase == 'discard' and seat == g.current) else None
    players = []
    for s in range(4):
        hand = list(g.hands[s])
        if s == g.current and g.phase == 'discard' and g.drawn is not None:
            hand.remove(g.drawn)
        q = {
            'seat': s,
            'name': ('你' if s == seat else '座位 %d' % s) if s in g.human_seats else '电脑 %d' % s,
            'score': g.scores[s],
            'seat_wind': g.jikaze(s),
            'riichi': g.riichi[s],
            'discards': [{'tile': d['tile'], 'tsumogiri': d['tsumogiri'], 'riichi': d['riichi'],
                          'called': d['called']} for d in g.rivers[s]],
            'melds': [_meld_out(m) for m in g.melds[s]],
            'hand_count': len(hand),
        }
        if s == seat:
            q['hand'] = sorted(hand, key=game.tile_key)
        players.append(q)
    return {
        'version': 1,
        'game_id': gid,
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
        'viewer': seat,
        'turn': g.current,
        'waiting_for': _waiting_for(g),
        'rules': dict(g.rules),
        'players': players,
        'drawn': drawn,
        'legal_actions': _legal(g, seat) if phase == 'playing' else [],
        'hints': _hints(g, seat),
        'events': _events(g, seat),
        'result': _result(g),
    }


# ---------- 请求处理 ----------

def _seat(v):
    try:
        s = int(v)
    except (TypeError, ValueError):
        raise ApiError('seat 必须是 0~3')
    if s not in range(4):
        raise ApiError('seat 必须是 0~3')
    return s


def _get_game(gid):
    g = GAMES.get(gid)
    if g is None:
        raise ApiError('找不到这局游戏（game_id=%s），请重新开局' % gid, 404)
    return g


def api_new_game(data):
    players = data.get('players') or ['human', 'bot', 'bot', 'bot']
    if not isinstance(players, list) or len(players) != 4 or any(p not in ('human', 'bot') for p in players):
        raise ApiError('players 要 4 个，每个是 human 或 bot')
    humans = [i for i, p in enumerate(players) if p == 'human']
    rules = data.get('rules') or {}
    if not isinstance(rules, dict):
        raise ApiError('rules 应该是对象')
    seed = data.get('seed')
    g = game.Game(human_seats=humans, wall=data.get('wall'), seed=seed,
                  rules=rules, length=data.get('length') or 'tonpuu')
    gid = uuid.uuid4().hex[:12]
    GAMES[gid] = g
    while len(GAMES) > MAX_GAMES:
        GAMES.pop(next(iter(GAMES)))
    return build_state(gid, g, humans[0] if humans else 0)


def api_action(data):
    gid = data.get('game_id')
    g = _get_game(gid)
    seat = _seat(data.get('seat'))
    if seat not in g.human_seats:
        raise ApiError('座位 %d 是电脑，不能替它操作' % seat)
    a = str(data.get('type') or '').lower()
    if a not in ('discard', 'riichi', 'tsumo', 'ron', 'chi', 'pon', 'minkan', 'ankan', 'kakan',
                 'kyuushu', 'pass'):
        raise ApiError('不认识的操作 type=%r' % a)
    if g.phase == 'end':
        raise ApiError('这局已经结束了')
    if seat not in _waiting_for(g):
        raise ApiError('现在不该座位 %d 操作' % seat)
    tile = data.get('tile')
    tiles = data.get('tiles')
    if a in ('ankan', 'kakan') and isinstance(tile, str):
        tile = game.norm(tile)
    g.do_action(seat, a, tile=tile, tiles=tiles, tsumogiri=data.get('tsumogiri'))
    return build_state(gid, g, seat)


def api_next(data):
    gid = data.get('game_id')
    g = _get_game(gid)
    seat = _seat(data.get('seat', 0))
    g.next_round(wall=data.get('wall'))
    return build_state(gid, g, seat)


def api_state(qs):
    gid = qs.get('game_id', [None])[0]
    g = _get_game(gid)
    seat = _seat(qs.get('seat', [0])[0])
    return build_state(gid, g, seat)


class MahjongHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass   # 别刷屏

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length <= 0:
            return {}
        data = json.loads(self.rfile.read(length).decode('utf-8'))
        if not isinstance(data, dict):
            raise ApiError('请求体应该是 JSON 对象')
        return data

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _handle(self, fn, *args):
        try:
            with LOCK:
                self._send_json(fn(*args))
        except ApiError as e:
            self._send_json({'error': str(e)}, e.status)
        except ValueError as e:     # game.py 里不合法的操作都 raise ValueError
            self._send_json({'error': str(e)}, 400)
        except Exception as e:
            self._send_json({'error': '后端出错：%s: %s' % (type(e).__name__, e)}, 500)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            with open(INDEX, 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == '/api/state':
            self._handle(api_state, parse_qs(parsed.query))
            return
        self._send_json({'error': 'not found'}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        routes = {'/api/new_game': api_new_game, '/api/action': api_action, '/api/next': api_next}
        if path not in routes:
            self._send_json({'error': 'not found'}, 404)
            return
        try:
            data = self._read_json()
        except ApiError as e:
            self._send_json({'error': str(e)}, 400)
            return
        except Exception:
            self._send_json({'error': '请求体不是合法 JSON'}, 400)
            return
        self._handle(routes[path], data)


def main():
    ap = argparse.ArgumentParser(description='麻将后端')
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--host', default='127.0.0.1')
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), MahjongHandler)
    print('麻将后端已启动: http://%s:%d/' % (args.host, args.port), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
