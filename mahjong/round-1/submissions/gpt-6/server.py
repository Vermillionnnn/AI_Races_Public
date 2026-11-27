# 学号：250226
# 网页版立直麻将的 HTTP/JSON 接口。协议见 frontend/接口说明.md。

import argparse
import json
import math
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import tenpai
from game import ALL_TILES, Game
from yaku import RED_FIVES

INDEX = Path(__file__).resolve().parent / 'frontend' / 'index.html'
TILES = set(ALL_TILES) | RED_FIVES
ACTIONS = {'discard', 'riichi', 'tsumo', 'ron', 'chi', 'pon', 'minkan', 'ankan',
           'kakan', 'kyuushu', 'pass'}
DRAW_REASONS = {
    '荒牌流局': 'exhaustive',
    '九种九牌': 'kyuushu',
    '四杠散了': 'four_kans',
    '四家立直': 'four_riichi',
    '四风连打': 'four_winds',
    '三家和': 'triple_ron',
}


def _tile_left(waits):
    return [{'tile': tile, 'left': left} for tile, left in waits.items()]


def _build_hints(g, seat, actions):
    hand = g.hands[seat]
    melds = g.melds_plain(seat)
    visible = g.get_visible(seat)
    waits = []
    discards = {}
    if len(hand) + 3 * len(melds) == 13:
        waits = _tile_left(tenpai.get_waits(hand, melds, visible))
    discard = next((a for a in actions if a['type'] == 'discard'), None)
    if discard:
        hints = tenpai.discard_hints(hand, melds, visible)
        discards = {tile: _tile_left(hints[tile]) for tile in discard['tiles'] if tile in hints}
    return {'waits': waits, 'furiten': g._is_furiten(seat), 'discards': discards}


def _legal_actions(actions):
    grouped = {}
    for action in actions:
        kind = action.get('kind', action['type'])
        entry = grouped.setdefault(kind, {'type': kind})
        if kind in ('chi', 'pon'):
            entry.setdefault('options', []).append(list(action['tiles']))
        elif kind in ('ankan', 'kakan'):
            entry.setdefault('tiles', []).extend(action['tiles'])
        elif kind in ('discard', 'riichi'):
            entry['tiles'] = list(action['tiles'])
    return list(grouped.values())


def _waiting_for(g):
    if g.phase == 'discard':
        return [g.current] if g.current in g.human_seats else []
    if g.phase == 'call':
        return sorted(s for s in g.call_options if s in g.human_seats and s not in g.responses)
    return []


def _events(g, viewer):
    events = []
    for event in g.events:
        event = dict(event)
        if event['type'] == 'draw' and event['seat'] != viewer:
            event['tile'] = None
        elif event['type'] == 'ryuukyoku':
            event['reason'] = DRAW_REASONS[event['reason']]
        events.append(event)
    return events


def _result(result):
    if result is None:
        return None
    if result['type'] in ('tsumo', 'ron'):
        wins = []
        for win in result['wins']:
            hand = list(win['hand'])
            hand.remove(win['tile'])
            wins.append({
                'seat': win['seat'],
                'from': win['from'],
                'hand': hand,
                'melds': win['melds'],
                'win_tile': win['tile'],
                'yaku': win['yaku'],
                'han': win['han'],
                'fu': win['fu'],
                'yakuman': win['yakuman'],
                'points': win['points'],
            })
        return {
            'type': 'agari',
            'wins': wins,
            'dora_indicators': result['dora_indicators'],
            'uradora_indicators': result['ura_indicators'],
            'delta': result['delta'],
        }
    out = {'type': 'ryuukyoku', 'reason': DRAW_REASONS[result['reason']], 'delta': result['delta']}
    if 'tenpai' in result:
        out['tenpai'] = result['tenpai']
    return out


def build_state(g, game_id, viewer):
    state = g.get_state(viewer)
    r = state['round']
    phase = 'playing'
    if g.phase == 'end':
        phase = 'game_end' if g.game_over else 'round_end'
    players = []
    for p in state['players']:
        seat = p['seat']
        players.append({
            'seat': seat,
            'name': f'玩家 {seat}' if seat in g.human_seats else f'电脑 {seat}',
            'score': p['score'],
            'seat_wind': p['wind'],
            'riichi': p['riichi'],
            'discards': p['river'],
            'melds': p['melds'],
            'hand_count': p['hand_count'],
        })
        if seat == viewer:
            players[-1]['hand'] = p['hand']
    actions = _legal_actions(state['legal_actions'])
    return {
        'version': 1,
        'game_id': game_id,
        'phase': phase,
        'round': {
            'wind': r['bakaze'], 'number': r['oya'] + 1, 'honba': r['honba'],
            'riichi_sticks': r['kyotaku'], 'dealer': r['oya'],
        },
        'dora_indicators': state['dora_indicators'],
        'wall_left': state['remaining'],
        'viewer': viewer,
        'turn': state['current'],
        'waiting_for': _waiting_for(g),
        'rules': dict(g.rules),
        'players': players,
        'drawn': state['drawn'],
        'legal_actions': actions,
        'hints': _build_hints(g, viewer, actions) if phase == 'playing' else None,
        'events': _events(g, viewer),
        'result': _result(g.result),
    }


class RequestError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _seat(value):
    if type(value) is not int or not 0 <= value < 4:
        raise RequestError('seat 必须是 0 到 3 的整数')
    return value


def _wall(data):
    if 'wall' in data and not isinstance(data['wall'], list):
        raise RequestError('wall 必须是牌数组')
    return data.get('wall')


def _new_game(data):
    players = data.get('players', ['human', 'bot', 'bot', 'bot'])
    if not isinstance(players, list) or len(players) != 4 or any(
            player not in ('human', 'bot') for player in players):
        raise RequestError('players 必须包含四个 human 或 bot')
    seed = data.get('seed')
    if seed is not None and (type(seed) not in (int, float) or
                             (type(seed) is float and not math.isfinite(seed))):
        raise RequestError('seed 必须是有限的数字')
    if 'rules' in data and not isinstance(data['rules'], dict):
        raise RequestError('rules 必须是对象')
    seats = [seat for seat, player in enumerate(players) if player == 'human']
    return Game(seats, wall=_wall(data), seed=seed,
                length=data.get('length', 'tonpuu'), rules=data.get('rules'))


def _action(g, seat, data):
    kind = data.get('type')
    if not isinstance(kind, str) or kind not in ACTIONS:
        raise RequestError('type 不是有效的操作')
    tile = data.get('tile')
    tiles = data.get('tiles')
    tsumogiri = data.get('tsumogiri')
    if kind in ('discard', 'riichi', 'ankan', 'kakan'):
        if not isinstance(tile, str) or tile not in TILES:
            raise RequestError('tile 不是有效的牌')
        if kind in ('ankan', 'kakan') and tile in RED_FIVES:
            raise RequestError('杠五时请用普通五表示牌种')
    if kind in ('discard', 'riichi') and 'tsumogiri' in data and type(tsumogiri) is not bool:
        raise RequestError('tsumogiri 必须是 true 或 false')
    if kind in ('chi', 'pon') and (not isinstance(tiles, list) or len(tiles) != 2 or any(
            not isinstance(t, str) or t not in TILES for t in tiles)):
        raise RequestError('tiles 必须是手里拿出的两张牌')
    g.do_action(seat, kind, tile=tile, tiles=tiles if kind in ('chi', 'pon') else None,
                tsumogiri=tsumogiri)


class MahjongHandler(BaseHTTPRequestHandler):
    timeout = 5

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send(self, data, mime, status=200):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self._send(body, 'application/json; charset=utf-8', status)

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        if not 0 <= length <= 16_384:
            raise RequestError('请求体长度无效')
        body = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}
        if not isinstance(body, dict):
            raise RequestError('请求体必须是 JSON 对象')
        return body

    def _game(self, game_id):
        if not isinstance(game_id, str) or not game_id:
            raise RequestError('必须提供 game_id')
        active = self.server.active_game
        if active is None or active[0] != game_id:
            raise RequestError('找不到这个对局，请开新游戏', 404)
        return active[1]

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def _dispatch(self):
        try:
            url = urlparse(self.path)
            if self.command == 'GET':
                if url.path in ('/', '/index.html'):
                    self._send(INDEX.read_bytes(), 'text/html; charset=utf-8')
                    return
                response = self._get(url)
            else:
                response = self._post(url.path)
            self._send_json(response)
        except RequestError as e:
            self._send_json({'error': str(e)}, e.status)
        except (json.JSONDecodeError, UnicodeError):
            self._send_json({'error': '请求体必须是合法 JSON'}, 400)
        except ValueError as e:
            self._send_json({'error': str(e)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            traceback.print_exc()
            self._send_json({'error': '服务器处理请求失败'}, 500)

    def _get(self, url):
        if url.path != '/api/state':
            raise RequestError('找不到这个路径', 404)
        query = parse_qs(url.query, keep_blank_values=True)
        ids = query.get('game_id', [])
        seats = query.get('seat', [])
        if len(ids) != 1:
            raise RequestError('必须提供一个 game_id')
        if len(seats) != 1 or seats[0] not in ('0', '1', '2', '3'):
            raise RequestError('seat 必须是 0 到 3 的整数')
        return build_state(self._game(ids[0]), ids[0], int(seats[0]))

    def _post(self, path):
        if path not in ('/api/new_game', '/api/action', '/api/next'):
            raise RequestError('找不到这个路径', 404)
        data = self._read_json()
        if path == '/api/new_game':
            g = _new_game(data)
            game_id = uuid4().hex
            response = build_state(g, game_id, 0)
            self.server.active_game = (game_id, g)
            return response

        game_id = data.get('game_id')
        g = self._game(game_id)
        seat = _seat(data.get('seat'))
        if path == '/api/action':
            _action(g, seat, data)
        else:
            g.next_round(wall=_wall(data))
        return build_state(g, game_id, seat)


class MahjongServer(HTTPServer):
    active_game = None


def run_server(host='127.0.0.1', port=8000):
    with MahjongServer((host, port), MahjongHandler) as httpd:
        print(f'麻将后端已启动 http://{host}:{httpd.server_port}/', flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def main(default_port=8000):
    parser = argparse.ArgumentParser(description='启动网页版立直麻将')
    parser.add_argument('--port', type=int, default=default_port)
    args = parser.parse_args()
    run_server(port=args.port)


if __name__ == '__main__':
    main()
