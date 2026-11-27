# 学号: 250226
# server.py - 网页版立直麻将后端接口
#
# 启动：python3 server.py --port 8000
# 默认监听 127.0.0.1:8000；GET / 返回 frontend/index.html。
# 接口严格按 frontend/接口说明.md 输出。

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import game
import tenpai

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, 'frontend', 'index.html')

GAMES = {}
CURRENT_ID = None
COUNTER = 0
LOCK = threading.RLock()

REASON_KEY = {
    '荒牌流局': 'exhaustive',
    '九种九牌': 'kyuushu',
    '四杠散了': 'four_kans',
    '四家立直': 'four_riichi',
    '四风连打': 'four_winds',
    '三家和': 'triple_ron',
}


def _new_id():
    global COUNTER
    COUNTER += 1
    return 'g%d' % COUNTER


def _get_game(game_id):
    if game_id:
        return GAMES.get(game_id)
    if CURRENT_ID:
        return GAMES.get(CURRENT_ID)
    return None


def _waiting_for(g):
    if g.phase == 'discard':
        return [g.current] if g.current in g.human_seats and g.get_legal_actions(g.current) else []
    if g.phase == 'call':
        return sorted(s for s in g.call_options if s in g.human_seats and s not in g.responses)
    return []


def _tile_list(d):
    return [{'tile': t, 'left': n} for t, n in sorted(d.items(), key=lambda kv: game.tile_key(kv[0]))]


def _build_hints(g, seat):
    if g.phase == 'end':
        return None
    hand = list(g.hands[seat])
    melds = g.melds_plain(seat)
    visible = g.get_visible(seat)
    total = len(hand) + 3 * len(melds)
    try:
        if total == 14:
            legal_tiles = set()
            for a in g.get_legal_actions(seat):
                if a.get('type') == 'discard':
                    legal_tiles.update(a.get('tiles') or [])
            hints = tenpai.discard_hints(hand, melds, visible)
            return {
                'waits': [],
                'furiten': False,
                'discards': {t: _tile_list(w) for t, w in hints.items() if t in legal_tiles},
            }
        if total == 13:
            return {
                'waits': _tile_list(tenpai.get_waits(hand, melds, visible)),
                'furiten': bool(g._is_furiten(seat)),
                'discards': {},
            }
    except Exception:
        # 听牌提示算错不该把整局弄崩；页面上不显示提示即可
        pass
    return {'waits': [], 'furiten': False, 'discards': {}}


def _build_legal(g, seat):
    chi_opts, pon_opts, ankan, kakan = [], [], [], []
    out = []
    minkan = False
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
                minkan = True
        elif t in ('discard', 'riichi'):
            out.append({'type': t, 'tiles': list(a['tiles'])})
        elif t in ('tsumo', 'ron', 'kyuushu', 'pass'):
            out.append({'type': t})
    if chi_opts:
        out.append({'type': 'chi', 'options': chi_opts})
    if pon_opts:
        out.append({'type': 'pon', 'options': pon_opts})
    if ankan:
        out.append({'type': 'ankan', 'tiles': ankan})
    if kakan:
        out.append({'type': 'kakan', 'tiles': kakan})
    if minkan:
        out.append({'type': 'minkan'})
    return out


def _build_melds(g, seat):
    return [{
        'type': m['type'],
        'tiles': list(m['tiles']),
        'from': m.get('from'),
        'called_tile': m.get('called_tile'),
    } for m in g.melds[seat]]


def _build_result(g, seat):
    r = g.result
    if not r:
        return None
    if r['type'] in ('tsumo', 'ron'):
        wins = []
        for w in r['wins']:
            hand = list(w['hand'])
            if w['tile'] in hand:
                hand.remove(w['tile'])   # 页面会把和的牌另外画一张
            wins.append({
                'seat': w['seat'],
                'from': w['from'],
                'hand': hand,
                'melds': _build_melds(g, w['seat']),
                'win_tile': w['tile'],
                'yaku': list(w['yaku']),
                'han': w['han'],
                'fu': w['fu'],
                'yakuman': w.get('yakuman', 0),
                'points': w.get('points', 0),
            })
        return {
            'type': 'agari',
            'wins': wins,
            'dora_indicators': list(r.get('dora_indicators') or []),
            'uradora_indicators': list(r.get('ura_indicators') or []),
            'delta': list(r['delta']),
        }
    return {
        'type': 'ryuukyoku',
        'reason': REASON_KEY.get(r.get('reason'), r.get('reason') or ''),
        'tenpai': list(r.get('tenpai') or [False, False, False, False]),
        'delta': list(r['delta']),
    }


def build_state(g, game_id, seat):
    phase = 'playing'
    if g.phase == 'end':
        phase = 'game_end' if g.game_over else 'round_end'

    drawn = g.drawn if (g.phase == 'discard' and seat == g.current) else None
    players = []
    for s in range(4):
        hand_all = list(g.hands[s])
        # 摸到的牌在接口里单独放在 drawn；手牌里只留 13/10/7 张
        if g.drawn is not None and s == g.current and g.phase == 'discard' and g.drawn in hand_all:
            hand_all.remove(g.drawn)
        p = {
            'seat': s,
            'name': ('你' if s == seat else '玩家 %d' % s) if s in g.human_seats else '电脑 %d' % s,
            'score': g.scores[s],
            'seat_wind': g.jikaze(s),
            'riichi': g.riichi[s],
            'discards': [{
                'tile': d['tile'],
                'tsumogiri': bool(d.get('tsumogiri', False)),
                'riichi': bool(d.get('riichi', False)),
                'called': bool(d.get('called', False)),
            } for d in g.rivers[s]],
            'melds': _build_melds(g, s),
            'hand_count': len(hand_all),
        }
        if s == seat:
            p['hand'] = hand_all
        players.append(p)

    events = []
    for e in g.events:
        e = dict(e)
        if e.get('type') == 'draw' and e.get('seat') != seat:
            e['tile'] = None
        if e.get('type') == 'ryuukyoku':
            e['reason'] = REASON_KEY.get(e.get('reason'), e.get('reason'))
        events.append(e)

    return {
        'version': 1,
        'game_id': game_id,
        'phase': phase,
        'round': {
            'wind': g.bakaze,
            'number': g.kyoku % 4 + 1,
            'honba': g.honba,
            'riichi_sticks': g.kyotaku,
            'dealer': g.oya,
        },
        'dora_indicators': list(g.dora_indicators()),
        'wall_left': g.remaining(),
        'viewer': seat,
        'turn': g.current,
        'waiting_for': _waiting_for(g) if phase == 'playing' else [],
        'rules': dict(g.rules),
        'players': players,
        'drawn': drawn,
        'legal_actions': _build_legal(g, seat) if phase == 'playing' else [],
        'hints': _build_hints(g, seat) if phase == 'playing' else None,
        'events': events,
        'result': _build_result(g, seat),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = 'MahjongServer/1.0'

    def log_message(self, fmt, *args):
        # 服务器环境不需要每个请求都刷一行
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(body)

    def _html(self):
        try:
            with open(INDEX, 'rb') as f:
                body = f.read()
        except OSError:
            self._send_json({'error': '找不到 frontend/index.html'}, 500)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
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
        if parsed.path in ('/', '/index.html'):
            self._html()
            return
        if parsed.path == '/api/state':
            qs = parse_qs(parsed.query)
            try:
                seat = int(qs.get('seat', ['0'])[0])
            except (TypeError, ValueError):
                self._send_json({'error': 'seat 必须是 0~3'}, 400)
                return
            if seat not in range(4):
                self._send_json({'error': 'seat 必须是 0~3'}, 400)
                return
            with LOCK:
                g = _get_game(qs.get('game_id', [None])[0])
                if g is None:
                    self._send_json({'error': '还没开局，请先调用 /api/new_game'}, 400)
                    return
                gid = qs.get('game_id', [CURRENT_ID])[0] or CURRENT_ID
                self._send_json(build_state(g, gid, seat))
            return
        self._send_json({'error': 'not found'}, 404)

    def do_POST(self):
        global CURRENT_ID
        parsed = urlparse(self.path)
        try:
            data = self._read_json()
        except Exception:
            self._send_json({'error': '请求体不是合法 JSON'}, 400)
            return
        if not isinstance(data, dict):
            self._send_json({'error': '请求体必须是 JSON 对象'}, 400)
            return

        try:
            with LOCK:
                if parsed.path == '/api/new_game':
                    self._new_game(data)
                    return
                if parsed.path == '/api/action':
                    self._action(data)
                    return
                if parsed.path == '/api/next':
                    self._next(data)
                    return
        except ValueError as e:
            self._send_json({'error': str(e)}, 400)
            return
        except Exception as e:
            self._send_json({'error': '后端出错：%s' % e}, 500)
            return
        self._send_json({'error': 'not found'}, 404)

    def _new_game(self, data):
        global CURRENT_ID
        players = data.get('players') or ['human', 'bot', 'bot', 'bot']
        if not isinstance(players, list) or len(players) != 4:
            raise ValueError('players 要有 4 个')
        if any(p not in ('human', 'bot') for p in players):
            raise ValueError("players 只能是 'human' 或 'bot'")
        seats = [i for i, p in enumerate(players) if p == 'human'] or [0]
        length = data.get('length') or 'tonpuu'
        rules = data.get('rules')
        wall = data.get('wall')
        if wall is not None and (not isinstance(wall, list) or len(wall) != 136):
            raise ValueError('wall 要 136 张')
        g = game.Game(human_seats=seats, wall=wall, seed=data.get('seed'),
                      rules=rules, length=length)
        gid = _new_id()
        GAMES[gid] = g
        CURRENT_ID = gid
        # 只留最近几局，旧局可以不留
        for old in list(GAMES)[:-4]:
            GAMES.pop(old, None)
        self._send_json(build_state(g, gid, 0))

    def _action(self, data):
        gid = data.get('game_id')
        g = _get_game(gid)
        if g is None:
            raise ValueError('还没开局，请先调用 /api/new_game')
        try:
            seat = int(data.get('seat'))
        except (TypeError, ValueError):
            raise ValueError('seat 必须是 0~3')
        if seat not in range(4):
            raise ValueError('seat 必须是 0~3')
        typ = data.get('type') or data.get('action')
        if not isinstance(typ, str) or not typ:
            raise ValueError('缺少 type 参数')
        typ = typ.lower()
        if typ in ('skip', 'cancel'):
            typ = 'pass'
        if typ in ('hu', 'win', 'agari'):
            typ = 'tsumo' if g.phase == 'discard' else 'ron'
        action = typ
        if typ in ('ankan', 'kakan', 'minkan'):
            action = 'kan'
        if action not in ('discard', 'riichi', 'tsumo', 'ron', 'chi', 'pon',
                          'kan', 'kyuushu', 'pass'):
            raise ValueError('不认识的操作：%s' % typ)
        g.do_action(seat, action, tile=data.get('tile'), tiles=data.get('tiles'),
                    tsumogiri=data.get('tsumogiri'))
        self._send_json(build_state(g, gid, seat))

    def _next(self, data):
        gid = data.get('game_id')
        g = _get_game(gid)
        if g is None:
            raise ValueError('还没开局')
        try:
            seat = int(data.get('seat', 0))
        except (TypeError, ValueError):
            raise ValueError('seat 必须是 0~3')
        if seat not in range(4):
            raise ValueError('seat 必须是 0~3')
        g.next_round(wall=data.get('wall'))
        self._send_json(build_state(g, gid, seat))


def run(host='127.0.0.1', port=8000):
    httpd = ThreadingHTTPServer((host, port), Handler)
    print('麻将后端已启动: http://%s:%d/' % (host, port), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    run(host=args.host, port=args.port)
