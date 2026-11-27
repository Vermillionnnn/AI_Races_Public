# 学号: 250226
# server.py - 网页版立直麻将后端接口
#
# 【拼装修复 glm-5-3】这个文件我重写了一遍（详见 说明.md），原来的问题：
# - 不支持 `python3 server.py --port 8000`（前端朋友的服务器必须这样启动），
#   也不会把 frontend/index.html 给浏览器（打开就是一行 JSON）。
# - 字段名按当初群里的转述写的，和《接口说明.md》对不上（页面顶上一串红字）。
# - 只能开一局，页面连开第二局就乱了；现在按 game_id 存 dict，可以连续开很多局。
# - 没有 rules / events / waiting_for / round.wind 这些字段。
# - score.py 的返回值是 dict，250207 的 game.py 按 tuple 拆的，这里包一层转过去。
# - server_patch.py（老师的补丁）已经合并进来了，不再需要那个文件。
#
# 接口格式见 frontend/接口说明.md。

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import game
import score
import tenpai

INDEX_PATH = os.path.join(BASE_DIR, 'frontend', 'index.html')

# game.py 要 (得分, 各付) 这样的 tuple，260409 的 score.py 返回 dict，这里转一层
_orig_calc_score = score.calc_score


def _compat_calc_score(fu, han, is_oya, is_tsumo, honba=0, kyotaku=0, rules=None):
    res = _orig_calc_score(fu, han, is_oya, is_tsumo, honba, kyotaku, rules=rules)
    if isinstance(res, dict):
        gain = res.get('get', 0)
        if is_tsumo:
            if is_oya:
                return (gain, res.get('ko_pay', 0))
            return (gain, (res.get('oya_pay', 0), res.get('ko_pay', 0)))
        return (gain, res.get('ron_pay', 0))
    return res


game.calc_score = _compat_calc_score

# ---------- 开着的对局：game_id -> Game ----------

games = {}
game_seq = 0

RYUUKYOKU_KEY = {
    '荒牌流局': 'exhaustive',
    '九种九牌': 'kyuushu',
    '四杠散了': 'four_kans',
    '四家立直': 'four_riichi',
    '四风连打': 'four_winds',
    '三家和': 'triple_ron',
}

# 役名 -> 每个役几番（页面要在役列表里显示每个役的番数）
# 数番役按常见值；250118 的 calc_yaku 只给役名，番数在这里还原。
YAKU_HAN = {
    '立直': 1, '一发': 1, '门前清自摸和': 1, '断幺九': 1, '一杯口': 1,
    '自风': 1, '场风': 1, '役牌': 1, '平和': 1, '岭上开花': 1, '海底摸月': 1,
    '河底捞鱼': 1, '抢杠': 1,
    '两立直': 2, '七对子': 2, '三色同顺': 2, '一气通贯': 2, '对对和': 2,
    '三暗刻': 2, '三色同刻': 2, '三杠子': 2, '小三元': 2, '混老头': 2,
    '混全带幺九': 2,
    '纯全带幺九': 3, '二杯口': 3, '混一色': 3,
    '清一色': 6,
    # 役满（单倍 13 番；下面的双倍役满 26 番）
    '天和': 13, '地和': 13, '大三元': 13, '小四喜': 13, '四暗刻': 13,
    '四杠子': 13, '国士无双': 13, '九莲宝灯': 13, '字一色': 13,
    '清老头': 13, '绿一色': 13,
    '大四喜': 26, '四暗刻单骑': 26, '国士无双十三面': 26, '纯正九莲宝灯': 26,
}


def _yaku_han(name):
    """宝牌3 / 赤宝牌1 / 里宝牌2 这种名字里带张数的直接取，其余查表，查不到算 1。"""
    if name[:2] in ('宝牌', '里宝') or name[:3] == '赤宝牌':
        n = ''.join(ch for ch in name if ch.isdigit())
        if n:
            return int(n)
    return YAKU_HAN.get(name, 1)


def _g(game_id):
    g = games.get(game_id)
    if g is None:
        raise ValueError('找不到对局 %s，请先开新游戏' % game_id)
    return g


# ---------- 听牌提示 ----------

def _build_hints(g, seat):
    if g.phase == 'end':
        return None
    try:
        hand = list(g.hands[seat])
        melds = g.melds_plain(seat)
        # 拼装修复 round2：get_visible 里已经包含了自己的副露，get_waits 又会把
        # 传进去的 melds 数一遍，等于自己的碰/杠被扣两次，“还剩几张”就少了。
        # 把自己的副露从 visible 里扣掉再传。
        vis = g.get_visible(seat)
        for m in g.melds[seat]:
            for t in m['tiles']:
                vis.remove(game.norm(t))
        # 拼装修复 round2：立直以后只能摸切，别再提示“打哪张能听”，只提示现在听什么
        if g.riichi[seat]:
            h = list(hand)
            if g.drawn is not None and g.drawn in h:
                h.remove(g.drawn)
            if len(h) + 3 * len(melds) == 13:
                waits = tenpai.get_waits(h, melds, vis)
                return {'waits': _tile_left(waits), 'discards': {},
                        'furiten': bool(waits) and g._is_furiten(seat)}
            return None
        total = len(hand) + 3 * len(melds)
        if total == 14:
            discards = tenpai.discard_hints(hand, melds, vis)
            out = {'waits': [], 'discards': {}}
            for t, waits in discards.items():
                out['discards'][t] = _tile_left(waits)
        elif total == 13:
            waits = tenpai.get_waits(hand, melds, vis)
            out = {'waits': _tile_left(waits), 'discards': {}}
        else:
            return None
        try:
            out['furiten'] = bool(out['waits']) and g._is_furiten(seat)
        except Exception:
            out['furiten'] = False
        return out
    except Exception:
        return None


def _tile_left(d):
    """tenpai 返回 {牌: 剩几张}，页面要 [{tile, left}]"""
    return [{'tile': t, 'left': n} for t, n in d.items()]


# ---------- legal_actions：game 的写法 -> 页面的写法 ----------

def _legal(g, seat):
    res = []
    chi_opts, pon_opts, ankan, kakan = [], [], [], []
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
            res.append({'type': t, 'tiles': list(a['tiles'])})
        elif t in ('tsumo', 'ron', 'kyuushu', 'pass'):
            res.append({'type': t})
    if chi_opts:
        res.append({'type': 'chi', 'options': chi_opts})
    if pon_opts:
        res.append({'type': 'pon', 'options': pon_opts})
    if ankan:
        res.append({'type': 'ankan', 'tiles': ankan})
    if kakan:
        res.append({'type': 'kakan', 'tiles': kakan})
    if minkan:
        res.append({'type': 'minkan'})
    return res


def _waiting_for(g):
    """现在在等哪些人类座位做决定"""
    if g.phase == 'discard':
        return [g.current] if g.current in g.human_seats else []
    if g.phase == 'call':
        return sorted(s for s in g.call_options
                      if s in g.human_seats and s not in g.responses)
    return []


# ---------- result：game 的写法 -> 页面的写法 ----------

def _result(g):
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
            # 拼装修复 round2：是不是役满要看役里有没有役满牌型（名字按表是 13/26 番）。
            # 番数凑到 13 以上的“累计役满”按接口说明 yakuman 写 0、照常显示符番，
            # 点数在算点那边本来就按役满给。别再把累计的也标成役满了。
            is_yakuman = any(_yaku_han(n) >= 13 for n in w['yaku'])
            yakuman = (han // 13) if (han >= 13 and is_yakuman) else 0
            wins.append({
                'seat': w['seat'],
                'from': w['from'],
                'han': han,
                'fu': w['fu'],
                'yakuman': yakuman,
                'points': w.get('points', w['delta'][w['seat']]),
                'yaku': [{'name': n, 'han': _yaku_han(n)} for n in w['yaku']],
                'hand': sorted(hand, key=game.tile_key),
                'melds': [dict(m) for m in g.melds[w['seat']]],
                'win_tile': w['tile'],
            })
        return {
            'type': 'agari',
            'wins': wins,
            'delta': list(r['delta']),
            'dora_indicators': list(r['dora_indicators']),
            'uradora_indicators': list(r.get('ura_indicators') or []),
        }
    # 荒牌流局和途中流局都归到 ryuukyoku
    return {
        'type': 'ryuukyoku',
        'reason': RYUUKYOKU_KEY.get(r.get('reason'), r.get('reason') or ''),
        'tenpai': list(r.get('tenpai') or [False] * 4),
        'delta': list(r['delta']),
    }


# ---------- 状态：game 的内部写法 -> 《接口说明.md》的格式 ----------

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
        hand = list(g.hands[s])
        # 手牌里含刚摸的那张，页面是手牌和 drawn 分开画，这里拆开
        if s == g.current and drawn is not None and drawn in hand:
            hand.remove(drawn)
        discards = [{'tile': d['tile'], 'riichi': d.get('riichi', False),
                     'called': d.get('called', False),
                     'tsumogiri': d.get('tsumogiri', False)} for d in p['river']]
        melds = [{'type': m['type'], 'tiles': list(m['tiles']),
                  'from': None if m['type'] == 'ankan' else m.get('from'),
                  'called_tile': None if m['type'] == 'ankan' else m.get('called_tile')}
                 for m in p['melds']]
        q = {
            'seat': s,
            'name': '你' if s == seat else ('电脑 %d' % s if s not in g.human_seats else '玩家 %d' % s),
            'score': p['score'],
            'seat_wind': p['wind'],
            'riichi': p['riichi'],
            'discards': discards,
            'melds': melds,
            'hand_count': len(hand),
        }
        if s == seat:
            # 拼装修复 round2：手牌按接口说明排好序再给（摸的那张是拆开另给的，
            # 不会再混在手牌里跑到最右边）
            q['hand'] = sorted(hand, key=game.tile_key)
        players.append(q)

    return {
        'version': 1,
        'game_id': g.game_id,
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
        'rules': st['rules'],
        'players': players,
        'drawn': drawn if (g.phase == 'discard' and seat == g.current) else None,
        'legal_actions': _legal(g, seat),
        'hints': _build_hints(g, seat),
        # 拼装修复 round2：接口说明要求 draw 事件的 tile 只给摸牌的人自己看，
        # 原来把别人的摸牌也发下去了（记录栏能看到别人摸什么）
        'events': [_hide_event_tile(e, seat) for e in st['events']],
        'result': _result(g),
    }


def _hide_event_tile(e, seat):
    if e.get('type') == 'draw' and e.get('seat') != seat:
        e = dict(e)
        e['tile'] = None
    return e


def _normalize_action(g, action):
    """前端可能传简写（hu / skip），这里兼容一下"""
    if not action:
        return action
    a = str(action).strip().lower()
    if a in ('skip', 'cancel'):
        return 'pass'
    if a in ('hu', 'win', 'agari'):
        return 'tsumo' if g.phase == 'discard' else 'ron'
    return a


# ---------- HTTP ----------

class MahjongHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):   # 安静一点，正式跑的时候少刷屏
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode('utf-8'))

    def _html(self):
        try:
            with open(INDEX_PATH, 'rb') as f:
                body = f.read()
        except OSError:
            self._send_json({'error': '找不到 frontend/index.html'}, status=500)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Content-Length', '0')
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ('/', '/index.html'):
            self._html()
            return
        if path == '/api/state':
            try:
                qs = parse_qs(parsed.query)
                game_id = (qs.get('game_id') or [None])[0]
                if not game_id:
                    raise ValueError('缺少 game_id')
                g = _g(game_id)
                seat = self._seat(qs=qs)
                self._send_json(build_state(g, seat))
            except ValueError as e:
                self._send_json({'error': str(e)}, status=400)
            except Exception as e:
                self._send_json({'error': '后端出错：%s' % e}, status=500)
            return
        self._send_json({'error': 'not found'}, status=404)

    def _seat(self, data=None, qs=None):
        try:
            if qs is not None:
                return int((qs.get('seat') or ['0'])[0])
            return int(data.get('seat', 0))
        except (TypeError, ValueError):
            raise ValueError('seat 应该是 0~3 的数字')

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
                global game_seq
                game_seq += 1
                game_id = 'g%d' % game_seq
                players = data.get('players') or ['human', 'bot', 'bot', 'bot']
                if not isinstance(players, list) or len(players) != 4:
                    raise ValueError('players 要是 4 个元素的数组')
                # 拼装修复 round2：全是电脑就传空列表（原来兜底成座位 0 是人类，
                # 结果游戏干等一个不存在的人操作，开局就卡死）
                humans = [i for i, p in enumerate(players) if p == 'human']
                g = game.Game(human_seats=humans, wall=data.get('wall'),
                              seed=data.get('seed'), rules=data.get('rules'),
                              length=data.get('length') or 'tonpuu')
                g.game_id = game_id
                games[game_id] = g
                # 旧的对局不用留着（前端说明：旧的局可以不留），只留最近 20 个
                if len(games) > 20:
                    for old in list(games)[:-20]:
                        games.pop(old, None)
                # 拼装修复 round2：接口说明规定 new_game 一律回“座位 0 的视角”，
                # 原来回的是第一个人类座位，真人不在座位 0 时页面的视角就对不上
                self._send_json(build_state(g, 0))
                return

            g = _g(data.get('game_id'))
            if path == '/api/action':
                seat = self._seat(data)
                a = str(data.get('type') or data.get('action') or '').lower()
                if not a:
                    raise ValueError('缺少操作类型 type')
                tile = data.get('tile')
                tiles = data.get('tiles')
                # 页面的 ankan/kakan/minkan 在 game.py 里统一叫 kan
                if a in ('ankan', 'kakan', 'minkan'):
                    a = 'kan'
                a = _normalize_action(g, a)
                g.do_action(seat, a, tile=tile, tiles=tiles,
                            tsumogiri=bool(data.get('tsumogiri')))
                self._send_json(build_state(g, seat))
                return

            if path == '/api/next':
                seat = self._seat(data)
                g.next_round(wall=data.get('wall'))
                self._send_json(build_state(g, seat))
                return

            self._send_json({'error': 'not found'}, status=404)
        except ValueError as e:
            self._send_json({'error': str(e)}, status=400)
        except Exception as e:
            self._send_json({'error': '后端出错：%s' % e}, status=500)


def run_server(host='127.0.0.1', port=8000):
    server = ThreadingHTTPServer((host, port), MahjongHandler)
    print('麻将后端已启动: http://%s:%d/  （页面在 /，接口在 /api/...）' % (host, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='网页麻将后端')
    parser.add_argument('--port', type=int, default=8000, help='监听端口（默认 8000）')
    parser.add_argument('--host', default='127.0.0.1', help='监听地址（默认 127.0.0.1）')
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
