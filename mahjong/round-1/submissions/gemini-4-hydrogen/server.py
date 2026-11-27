# 学号: 250226
# server.py - 网页版立直麻将后端接口

import argparse
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import game
import tenpai

INDEX_PATH = os.path.join(BASE_DIR, 'frontend', 'index.html')
TILE_RE = re.compile(r'^([0-9][mps]|[1-7]z)$')

GAMES = {}
GAME_ORDER = []
GAME_SEQ = 0
MAX_GAMES = 64


def _next_game_id():
    global GAME_SEQ
    GAME_SEQ += 1
    return f'g{GAME_SEQ}'


def _store_game(gid, g):
    GAMES[gid] = g
    GAME_ORDER.append(gid)
    while len(GAME_ORDER) > MAX_GAMES:
        old = GAME_ORDER.pop(0)
        GAMES.pop(old, None)


def _get_game(gid):
    if gid:
        g = GAMES.get(gid)
        if g is None:
            raise ValueError('找不到对局：' + str(gid))
        return gid, g
    if not GAME_ORDER:
        raise ValueError('还没开局，请先调用 /api/new_game')
    last_id = GAME_ORDER[-1]
    return last_id, GAMES[last_id]


def _parse_seat(val, default=0):
    if val is None or val == '':
        return default
    if isinstance(val, bool):
        raise ValueError('seat 必须是 0~3 的整数')
    try:
        seat = int(val)
    except (TypeError, ValueError):
        raise ValueError('seat 必须是 0~3 的整数')
    if seat not in (0, 1, 2, 3):
        raise ValueError('seat 必须在 0~3 之间')
    return seat


def _validate_wall(wall):
    if wall is None:
        return None
    if not isinstance(wall, list) or len(wall) != 136:
        raise ValueError('wall 必须是 136 张牌的数组')
    for i, t in enumerate(wall):
        if not isinstance(t, str) or not TILE_RE.match(t):
            raise ValueError(f'wall[{i}] 不是合法的牌：{t!r}')
    return list(wall)


def _player_name(g, s):
    if g.human_seats == {0}:
        return '你' if s == 0 else f'电脑 {s}'
    return f'玩家 {s}' if s in g.human_seats else f'电脑 {s}'


def _legal_actions(g, seat):
    if g.phase == 'end':
        return []
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


def _waiting_for(g):
    if g.phase == 'discard':
        return [g.current] if g.current in g.human_seats else []
    if g.phase == 'call':
        return sorted(
            s for s in g.call_options
            if s in g.human_seats and s not in g.responses
        )
    return []


def _format_waits(waits_dict):
    items = sorted(waits_dict.items(), key=lambda kv: game.tile_key(kv[0]))
    return [{'tile': t, 'left': n} for t, n in items]


def _build_hints(g, seat, legal):
    if g.phase == 'end':
        return None
    hand = list(g.hands[seat])
    melds = g.melds_plain(seat)
    visible = g.get_visible(seat)
    total = len(hand) + 3 * len(melds)

    if g.phase == 'discard' and seat == g.current and total == 14:
        if g.riichi[seat]:
            return {'waits': [], 'furiten': False, 'discards': {}}
        discard_set = set()
        for a in legal:
            if a['type'] == 'discard':
                discard_set.update(a['tiles'])
        raw_discards = tenpai.discard_hints(hand, melds, visible)
        discards_out = {}
        for t, w in raw_discards.items():
            if t in discard_set:
                discards_out[t] = _format_waits(w)
        return {'waits': [], 'furiten': False, 'discards': discards_out}

    if total == 13:
        waits = tenpai.get_waits(hand, melds, visible)
        furiten = bool(waits and g._is_furiten(seat))
        return {'waits': _format_waits(waits), 'furiten': furiten, 'discards': {}}

    return {'waits': [], 'furiten': False, 'discards': {}}


def _build_events(g, seat):
    out = []
    for e in g.events:
        if e['type'] == 'draw':
            out.append({
                'type': 'draw',
                'seat': e['seat'],
                'tile': e['tile'] if e['seat'] == seat else None,
            })
        else:
            out.append(dict(e))
    return out


def _build_result(g):
    r = g.result
    if not r:
        return None
    if r['type'] in ('tsumo', 'ron'):
        wins = []
        for w in r['wins']:
            wins.append({
                'seat': w['seat'],
                'from': w['from'],
                'hand': sorted(w['hand'], key=game.tile_key),
                'melds': [
                    {
                        'type': m['type'],
                        'tiles': list(m['tiles']),
                        'from': m['from'],
                        'called_tile': m.get('called_tile'),
                    }
                    for m in w['melds']
                ],
                'win_tile': w['tile'],
                'yaku': [dict(y) for y in w['yaku']],
                'han': w['han'],
                'fu': w['fu'],
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

    reason_key = game.RYUUKYOKU_KEY.get(r.get('reason'), r.get('reason') or '')
    out = {
        'type': 'ryuukyoku',
        'reason': reason_key,
        'delta': list(r['delta']),
    }
    if reason_key == 'exhaustive':
        out['tenpai'] = list(r.get('tenpai') or [False] * 4)
    return out


def build_state(g, game_id, seat):
    if g.phase == 'end':
        phase = 'game_end' if g.game_over else 'round_end'
    else:
        phase = 'playing'

    players = []
    for s in range(4):
        hand_all = list(g.hands[s])
        if g.phase == 'discard' and s == g.current and g.drawn is not None and hand_all:
            hand = hand_all[:-1]
        else:
            hand = hand_all

        discards = [
            {
                'tile': d['tile'],
                'tsumogiri': bool(d.get('tsumogiri', False)),
                'riichi': bool(d.get('riichi', False)),
                'called': bool(d.get('called', False)),
            }
            for d in g.rivers[s]
        ]
        melds = [
            {
                'type': m['type'],
                'tiles': list(m['tiles']),
                'from': m['from'],
                'called_tile': m.get('called_tile'),
            }
            for m in g.melds[s]
        ]
        p = {
            'seat': s,
            'name': _player_name(g, s),
            'score': g.scores[s],
            'seat_wind': g.jikaze(s),
            'riichi': g.riichi[s],
            'discards': discards,
            'melds': melds,
            'hand_count': len(hand),
        }
        if s == seat:
            p['hand'] = hand
        players.append(p)

    legal = _legal_actions(g, seat)
    drawn = g.drawn if (phase == 'playing' and g.phase == 'discard' and seat == g.current) else None

    return {
        'version': 1,
        'game_id': game_id,
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
        'waiting_for': _waiting_for(g) if phase == 'playing' else [],
        'rules': dict(g.rules),
        'players': players,
        'drawn': drawn,
        'legal_actions': legal,
        'hints': _build_hints(g, seat, legal),
        'events': _build_events(g, seat),
        'result': _build_result(g),
    }


def _normalize_action(g, raw_action):
    if not raw_action:
        return None, None
    a = str(raw_action).strip().lower()
    if a in ('skip', 'cancel'):
        return 'pass', None
    if a in ('hu', 'win', 'agari'):
        return ('tsumo' if g.phase == 'discard' else 'ron'), None
    if a in ('ankan', 'kakan', 'minkan'):
        return 'kan', a
    return a, None


class MahjongHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 避免控制台刷屏影响启动速度，保留错误或按需打印
        pass

    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self):
        with open(INDEX_PATH, 'rb') as f:
            body = f.read()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        data = json.loads(raw.decode('utf-8'))
        if not isinstance(data, dict):
            raise ValueError('请求体必须是 JSON 对象')
        return data

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
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
                gid, g = _get_game(gid)
                seat = _parse_seat(qs.get('seat', [0])[0], default=0)
                self._send_json(build_state(g, gid, seat))
            except ValueError as e:
                self._send_json({'error': str(e)}, status=400)
            except Exception as e:
                self._send_json({'error': '获取状态失败：' + str(e)}, status=500)
            return
        self._send_json({'error': 'not found'}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            data = self._read_json()
        except Exception:
            self._send_json({'error': '请求体不是合法 JSON'}, status=400)
            return

        try:
            if path == '/api/new_game':
                players = data.get('players')
                if players is None:
                    players = ['human', 'bot', 'bot', 'bot']
                if (not isinstance(players, list) or len(players) != 4
                        or any(p not in ('human', 'bot') for p in players)):
                    raise ValueError('players 必须是长度为 4、元素为 human 或 bot 的数组')
                seats = [i for i, p in enumerate(players) if p == 'human']
                length = data.get('length') or 'tonpuu'
                seed = data.get('seed')
                if seed is not None and (isinstance(seed, bool) or not isinstance(seed, (int, float))):
                    raise ValueError('seed 必须是数字')
                if isinstance(seed, float):
                    seed = int(seed)
                rules = data.get('rules')
                if rules is not None and not isinstance(rules, dict):
                    raise ValueError('rules 必须是对象')
                wall = _validate_wall(data.get('wall'))

                g = game.Game(
                    human_seats=seats,
                    wall=wall,
                    seed=seed,
                    length=length,
                    rules=rules,
                )
                gid = _next_game_id()
                _store_game(gid, g)
                self._send_json(build_state(g, gid, 0))
                return

            if path == '/api/action':
                gid, g = _get_game(data.get('game_id'))
                seat = _parse_seat(data.get('seat'), default=0)
                raw_action = data.get('type') or data.get('action')
                action, expected_kan_kind = _normalize_action(g, raw_action)
                if not action:
                    raise ValueError('缺少 type 参数')
                tile = data.get('tile')
                tiles = data.get('tiles')
                tsumogiri = data.get('tsumogiri')
                g.do_action(
                    seat, action, tile=tile, tiles=tiles,
                    tsumogiri=tsumogiri, expected_kan_kind=expected_kan_kind
                )
                self._send_json(build_state(g, gid, seat))
                return

            if path == '/api/next':
                gid, g = _get_game(data.get('game_id'))
                seat = _parse_seat(data.get('seat'), default=0)
                wall = _validate_wall(data.get('wall'))
                g.next_round(wall=wall)
                self._send_json(build_state(g, gid, seat))
                return
        except ValueError as e:
            self._send_json({'error': str(e)}, status=400)
            return
        except Exception as e:
            self._send_json({'error': '后端出错：' + str(e)}, status=500)
            return

        self._send_json({'error': 'not found'}, status=404)


def run_server(host='127.0.0.1', port=8000):
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    server = HTTPServer((host, port), MahjongHandler)
    print(f'Mahjong server listening on http://{host}:{port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServer stopped')
    finally:
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='网页版立直麻将后端服务')
    parser.add_argument(
        '--port',
        type=int,
        default=int(os.environ.get('PORT', 8000)),
        help='监听端口（默认 8000）',
    )
    args = parser.parse_args()
    run_server(host='127.0.0.1', port=args.port)
