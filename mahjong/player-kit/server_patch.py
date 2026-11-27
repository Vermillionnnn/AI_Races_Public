# 指导老师的补丁：python3 server_patch.py 启动（学生的 .py 一个字没动）
#
# 背景：250226 的 server.py 返回的字段和朋友写的牌桌页面对不上（页面顶上一串红字），
# 而且 server.py 不会把 index.html 给浏览器。我不懂麻将也看不懂前端，
# 就照着页面顶上红字提示的那些字段，在这里把 game.get_state() 的结果改个样子再返回。
# 算得对不对我不管，先能开局、能点。
#
# 用法：python3 server_patch.py   （端口默认 5000，PORT=xxxx 可改）
#       浏览器打开 http://127.0.0.1:5000/

import json
import os
from http.server import HTTPServer
from urllib.parse import urlparse, parse_qs

import server          # 250226 的，先不动
import game            # 250207 的，先不动
import tenpai

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, 'frontend', 'index.html')

GAME_ID = 'g1'   # 页面要一个 game_id 字符串；现在只有一局，随便写一个

# 页面里流局原因用英文 key，game.py 里是中文
RYUUKYOKU_KEY = {
    '荒牌流局': 'exhaustive',
    '九种九牌': 'kyuushu',
    '四杠散了': 'four_kans',
    '四家立直': 'four_riichi',
    '四风连打': 'four_winds',
    '三家和': 'triple_ron',
}

# 每个役几番：yaku.py 只给了役名和总番数，没给每个役的番数，
# 页面要每个役的番，这里先按常见的估一下，不在表里的算 1 番。（不确定对不对，先这样）
YAKU_HAN = {
    '七对子': 2, '三色同顺': 2, '一气通贯': 2, '混全带幺九': 2, '对对和': 2,
    '三暗刻': 2, '三色同刻': 2, '三杠子': 2, '小三元': 2, '混老头': 2,
    '双立直': 2, '纯全带幺九': 3, '混一色': 3, '二杯口': 3, '清一色': 6,
}

# ---------- 当前对局（server.py 里的 current_game 我另存一份指过来） ----------
human_seats = [0]


def _g():
    return server.current_game


def _tile_left(d):
    """tenpai 返回 {牌: 剩几张}，页面要 [{tile, left}]"""
    return [{'tile': t, 'left': n} for t, n in d.items()]


def _hints(g, seat):
    """听牌提示：沿用 250226 的 _build_hints，改成页面要的样子"""
    raw = server._build_hints(g, seat)
    waits = raw.get('waits') or {}
    discards = raw.get('discards') or {}
    out = {
        'waits': _tile_left(waits),
        'discards': {t: _tile_left(w) for t, w in discards.items()},
        'furiten': False,
    }
    try:
        if waits and g._is_furiten(seat):
            out['furiten'] = True
    except Exception:
        pass
    return out


def _legal(g, seat):
    """game 里的 legal_actions 改成页面的写法：
    - 吃/碰：game 是一个选项一条，页面要 {type, options: [[牌, 牌], ...]}
    - 杠：game 只有 kan（kind 区分暗/加/明），页面分 ankan / kakan / minkan
    - 暗杠/加杠页面要 tiles 列表"""
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
        elif t in ('tsumo', 'ron'):
            res.append({'type': t})
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
        return sorted(s for s in g.call_options
                      if s in g.human_seats and s not in g.responses)
    return []


def _yaku_list(names):
    return [{'name': n, 'han': YAKU_HAN.get(n, 1)} for n in names]


def _result(g, seat):
    r = g.result
    if not r:
        return None
    if r['type'] in ('tsumo', 'ron'):
        wins = []
        for w in r['wins']:
            hand = list(w['hand'])
            if w['tile'] in hand:
                hand.remove(w['tile'])   # 页面会把和的牌另外画一张
            han = w['han']
            yakuman = han // 13 if han >= 13 else 0   # yaku.py：役满一倍 13 番
            wins.append({
                'seat': w['seat'],
                'from': w['from'],
                'han': han,
                'fu': w['fu'],
                'yakuman': yakuman,
                'points': w['delta'][w['seat']],
                'yaku': _yaku_list(w['yaku']),
                'hand': hand,
                'melds': [{'tiles': list(m)} for m in w['melds']],
                'win_tile': w['tile'],
            })
        return {
            'type': 'agari',
            'wins': wins,
            'delta': list(r['delta']),
            'dora_indicators': list(r['dora_indicators']),
            'uradora_indicators': list(r.get('ura_indicators') or []),
        }
    # 荒牌、途中流局（abort）都归到 ryuukyoku
    return {
        'type': 'ryuukyoku',
        'reason': RYUUKYOKU_KEY.get(r.get('reason'), r.get('reason') or ''),
        'tenpai': list(r.get('tenpai') or [False] * 4),
        'delta': list(r['delta']),
    }


def build_state(g, seat):
    st = g.get_state(seat)
    r = st['round']
    if g.phase == 'end':
        phase = 'game_end' if g.game_over else 'round_end'
    else:
        phase = 'playing'

    drawn = st['drawn']
    players = []
    for p in st['players']:
        s = p['seat']
        hand_all = list(g.hands[s])
        hand = list(hand_all)
        # game.py 的手牌里已经含摸到的那张，页面是手牌和 drawn 分开画，这里拆开
        if s == g.current and drawn is not None and drawn in hand:
            hand.remove(drawn)
        discards = []
        for d in p['river']:
            discards.append({'tile': d['tile'], 'riichi': d.get('riichi', False),
                             'called': d.get('called', False), 'tsumogiri': False})
        melds = [{'type': m['type'], 'tiles': m['tiles'], 'from': m.get('from')}
                 for m in p['melds']]
        q = {
            'seat': s,
            'name': '座位 %d' % s,
            'score': p['score'],
            'seat_wind': p['wind'],
            'riichi': p['riichi'],
            'discards': discards,
            'melds': melds,
            'hand_count': len(hand),
        }
        if s == seat:
            q['hand'] = hand
        players.append(q)

    out = {
        'version': 1,
        'game_id': GAME_ID,
        'phase': phase,
        'round': {
            'wind': r['bakaze'],
            'number': r['oya'] + 1,
            'honba': r['honba'],
            'riichi_sticks': r['kyotaku'],
            'dealer': r['oya'],
        },
        'dora_indicators': st['dora_indicators'],
        'wall_left': st['remaining'],
        'viewer': seat,
        'turn': st['current'],
        'waiting_for': _waiting_for(g) if phase == 'playing' else [],
        'players': players,
        'drawn': drawn if (g.phase == 'discard' and seat == g.current) else None,
        'legal_actions': _legal(g, seat),
        'hints': _hints(g, seat) if g.phase != 'end' else None,
        'result': _result(g, seat),
        'events': [],   # 记录栏：game.py 没留记录，先空着
    }
    if g.phase != 'discard' or seat != g.current:
        out['drawn'] = None
        # 不是自己的回合，手牌里不含摸牌，hand 已经是全部
    return out


def _seat_of(data, qs=None):
    try:
        if qs is not None:
            return int(qs.get('seat', [0])[0])
        return int(data.get('seat', 0))
    except (TypeError, ValueError):
        return 0


class PatchedHandler(server.MahjongHandler):
    def _html(self):
        with open(INDEX, 'rb') as f:
            body = f.read()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            self._html()
            return
        if parsed.path == '/api/state':
            g = _g()
            if g is None:
                self._send_json({'ok': False, 'error': '还没开局，请先点新游戏'}, status=400)
                return
            seat = _seat_of(None, parse_qs(parsed.query))
            self._send_json(build_state(g, seat))
            return
        self._send_json({'ok': False, 'error': 'not found'}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            data = self._read_json()
        except Exception:
            self._send_json({'ok': False, 'error': '请求体不是合法 JSON'}, status=400)
            return
        try:
            if path == '/api/new_game':
                players = data.get('players') or ['human', 'bot', 'bot', 'bot']
                seats = [i for i, p in enumerate(players) if p == 'human'] or [0]
                # 页面还会传 length（东风/半庄），game.py 只做了东风，先不管
                server.current_game = game.Game(human_seats=seats, wall=data.get('wall'),
                                                seed=data.get('seed'))
                self._send_json(build_state(server.current_game, seats[0]))
                return

            g = _g()
            if g is None:
                self._send_json({'ok': False, 'error': '还没开局，请先点新游戏'}, status=400)
                return
            seat = _seat_of(data)

            if path == '/api/action':
                a = str(data.get('type') or data.get('action') or '').lower()
                tile = data.get('tile')
                tiles = data.get('tiles')
                # 页面的 ankan/kakan/minkan 在 game.py 里都叫 kan
                if a in ('ankan', 'kakan', 'minkan'):
                    a = 'kan'
                a = server._normalize_action(g, a)
                g.do_action(seat, a, tile=tile, tiles=tiles)
                self._send_json(build_state(g, seat))
                return

            if path == '/api/next':
                g.next_round(wall=data.get('wall'))
                self._send_json(build_state(g, seat))
                return
        except ValueError as e:
            self._send_json({'ok': False, 'error': str(e)}, status=400)
            return
        except Exception as e:
            self._send_json({'ok': False, 'error': '后端出错：%s' % e}, status=500)
            return
        self._send_json({'ok': False, 'error': 'not found'}, status=404)


def run(host='127.0.0.1', port=5000):
    httpd = HTTPServer((host, port), PatchedHandler)
    print('补丁版后端已启动: http://%s:%d/' % (host, port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    run(port=int(os.environ.get('PORT', 5000)))
