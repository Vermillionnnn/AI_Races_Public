"""一局：配牌、摸打、鸣牌、杠、立直、振听、和了和流局（规则.md 第 3 节）。

牌山顺序照 接口说明.md“指定牌山”：wall[0:52] 按物理座位配牌，wall[52] 起正常摸牌（庄家先摸），
wall[122:127] 宝牌指示牌，wall[127:132] 里宝，wall[132:136] 岭上牌。

阶段（self.phase）：
- 'turn'：轮到 self.turn 打牌（手里 14 张形），可以打牌、立直、自摸、暗杠、加杠、九种九牌；
- 'response'：等别人对一张牌表态。self.window 是 'discard'（打出的牌：荣和、碰、杠、吃）、
  'kakan'（加杠：抢杠）、'ankan'（暗杠：国士抢暗杠）；
- 'end'：这一局结束，self.result 是结算。
"""

from tiles import DRAGONS, WINDS, YAOCHU, counts, is_yaochu, kind, kind_str, num_of, sort_tiles, valid
from agari import is_kokushi, waits
from score import best_win, win_payments
from yaku_fu import WinContext


class ActionError(Exception):
    """不合法的操作（HTTP 400）。"""


def _uniq_sorted(tiles):
    return sort_tiles(set(tiles))


class Round:
    def __init__(self, game, wall):
        self.g = game
        self.rules = game.rules
        self.dealer = game.dealer
        self.round_wind = game.round_wind
        self.wall = list(wall)
        self.hands = [sort_tiles(self.wall[13 * i:13 * i + 13]) for i in range(4)]
        self.drawn = None
        self.melds = [[] for _ in range(4)]
        self.discards = [[] for _ in range(4)]
        self.next_draw = 52
        self.kans = 0                      # 已经开的杠数（= 摸过的岭上牌数）
        self.kan_by = [0] * 4
        self.dora_shown = 1                # 已翻开的宝牌指示牌张数
        self.pending_dora = 0              # 明杠、加杠后等打牌再翻的张数
        self.riichi = [False] * 4          # 立直成立
        self.double_riichi = [False] * 4
        self.ippatsu = [False] * 4
        self.furiten_temp = [False] * 4    # 同巡振听
        self.furiten_riichi = [False] * 4  # 立直振听
        self.no_calls = True               # 这一局还没有任何人鸣牌（含暗杠）
        self.turn = self.dealer
        self.rinshan_draw = False          # 手里的 drawn 是岭上牌
        self.kuikae = set()                # 食替禁止：这一手不能打的牌种
        self.pending_riichi = None         # 刚宣言立直、宣言牌还在等表态的座位
        self.pending_double = False
        self.four_kan_pending = False      # 第 4 次杠（不是同一人开的）之后，等那人打牌
        self.pao = [{} for _ in range(4)]  # 座位 -> {'大三元'|'大四喜': 负责的座位}
        self.phase = 'turn'
        self.window = None
        self.window_tile = None
        self.window_from = None
        self.responders = {}
        self.responses = {}
        self.events = []
        self.result = None
        self._acts_cache = None
        self._draw(self.dealer)

    # ------------------------------------------------------------ 基本信息

    def wall_left(self):
        return 122 - self.kans - self.next_draw

    def seat_wind(self, s):
        return WINDS[(s - self.dealer) % 4]

    def dora_indicators(self):
        return self.wall[122:122 + self.dora_shown]

    def ura_indicators(self):
        return self.wall[127:127 + self.dora_shown]

    def is_menzen(self, s):
        return all(m['type'] == 'ankan' for m in self.melds[s])

    def player_waits(self, s, hand=None, n_melds=None):
        """13 张形的手听的牌种（元组）。"""
        hand = self.hands[s] if hand is None else hand
        n_melds = len(self.melds[s]) if n_melds is None else n_melds
        if len(hand) % 3 != 1:
            return ()
        return waits(counts(hand), n_melds)

    def is_furiten(self, s):
        w = self.player_waits(s)
        if not w:
            return False
        if self.furiten_temp[s] or self.furiten_riichi[s]:
            return True
        return any(kind(d['tile']) in w for d in self.discards[s])

    def visible_counts(self, viewer):
        """从 viewer 看来每种牌已经看得见的张数：自己的手牌、所有人的河（被鸣走的不重复算）、副露、宝牌指示牌。"""
        c = [0] * 34
        own = list(self.hands[viewer])
        if self.turn == viewer and self.drawn is not None:
            own.append(self.drawn)
        for t in own:
            c[kind(t)] += 1
        for s in range(4):
            for d in self.discards[s]:
                if not d['called']:
                    c[kind(d['tile'])] += 1
            for m in self.melds[s]:
                for t in m['tiles']:
                    c[kind(t)] += 1
        for t in self.dora_indicators():
            c[kind(t)] += 1
        return c

    def waiting_for(self):
        if self.phase == 'turn':
            return [self.turn]
        if self.phase == 'response':
            return [s for s in self._order_from(self.window_from) if s in self.responders and s not in self.responses]
        return []

    def _order_from(self, s):
        """s 的下家开始的三个人。"""
        return [(s + i) % 4 for i in (1, 2, 3)]

    def _event(self, e):
        self.events.append(e)

    def _reveal_dora(self):
        self.dora_shown += 1
        self._event({'type': 'dora', 'tile': self.wall[121 + self.dora_shown]})

    def _reveal_pending(self):
        while self.pending_dora:
            self.pending_dora -= 1
            self._reveal_dora()

    # ------------------------------------------------------------ 摸牌

    def _draw(self, seat, rinshan=False):
        if rinshan:
            t = self.wall[131 + self.kans]
        else:
            t = self.wall[self.next_draw]
            self.next_draw += 1
        self.turn = seat
        self.drawn = t
        self.rinshan_draw = rinshan
        self.kuikae = set()
        self.phase = 'turn'
        self.window = None
        e = {'type': 'draw', 'seat': seat, 'tile': t}
        if rinshan:
            e['rinshan'] = True
        self._event(e)

    # ------------------------------------------------------------ 能做什么

    def legal_actions(self, seat):
        """内部格式：{类型: 附带数据}。不该 seat 操作时为空。"""
        if self.phase == 'turn' and seat == self.turn:
            key = (seat, len(self.events))
            if self._acts_cache is None or self._acts_cache[0] != key:
                self._acts_cache = (key, self._turn_actions())
            return self._acts_cache[1]
        if self.phase == 'response' and seat in self.responders and seat not in self.responses:
            acts = dict(self.responders[seat])
            acts['pass'] = True
            return acts
        return {}

    def _tiles14(self, s):
        return self.hands[s] + ([self.drawn] if (s == self.turn and self.drawn is not None) else [])

    def _turn_actions(self):
        s = self.turn
        d = self.drawn
        t14 = self._tiles14(s)
        acts = {}
        if self.riichi[s]:
            acts['discard'] = [d]
        else:
            acts['discard'] = _uniq_sorted(t for t in t14 if kind(t) not in self.kuikae)
        if d is None:
            return acts
        if self.tsumo_eval(s) is not None:
            acts['tsumo'] = True
        r = self.riichi_tiles(s)
        if r:
            acts['riichi'] = r
        if self.kans < 4 and self.wall_left() > 0:
            c = counts(t14)
            ank = []
            for k in range(34):
                if c[k] == 4 and self._ankan_ok(s, k):
                    ank.append(kind_str(k))
            if ank:
                acts['ankan'] = ank
            kak = []
            for m in self.melds[s]:
                if m['type'] == 'pon':
                    k = kind(m['tiles'][0])
                    if c[k] >= 1:
                        kak.append(kind_str(k))
            if kak:
                acts['kakan'] = sorted(kak, key=lambda x: kind(x))
        if self.rules['kyuushu'] and self.no_calls and not self.discards[s] and not self.rinshan_draw:
            c = counts(t14)
            if sum(1 for k in YAOCHU if c[k]) >= 9:
                acts['kyuushu'] = True
        return acts

    def _ankan_ok(self, s, k):
        if not self.riichi[s]:
            return True
        if not self.rules['riichi_ankan'] or kind(self.drawn) != k:
            return False
        before = self.player_waits(s)
        hand = [t for t in self.hands[s] if kind(t) != k]
        after = self.player_waits(s, hand, len(self.melds[s]) + 1)
        return bool(before) and before == after

    def riichi_tiles(self, s):
        if self.riichi[s] or not self.is_menzen(s) or self.drawn is None:
            return []
        if self.g.scores[s] < 1000 or self.wall_left() < 4:
            return []
        t14 = self._tiles14(s)
        res = []
        for t in _uniq_sorted(t14):
            rest = list(t14)
            rest.remove(t)
            if waits(counts(rest), len(self.melds[s])):
                res.append(t)
        return res

    def _ctx(self, s, tsumo, **kw):
        return WinContext(
            tsumo=tsumo, seat_wind=self.seat_wind(s), round_wind=self.round_wind, dealer=(s == self.dealer),
            rules=self.rules, riichi=self.riichi[s], double_riichi=self.double_riichi[s],
            ippatsu=self.ippatsu[s], dora_indicators=self.dora_indicators(),
            ura_indicators=self.ura_indicators(), **kw)

    def tsumo_eval(self, s):
        if self.drawn is None or s != self.turn:
            return None
        first = self.no_calls and not self.discards[s] and not self.rinshan_draw
        ctx = self._ctx(s, True, haitei=(not self.rinshan_draw and self.wall_left() == 0),
                        rinshan=self.rinshan_draw, tenhou=(first and s == self.dealer),
                        chiihou=(first and s != self.dealer))
        return best_win(self._tiles14(s), self.drawn, self.melds[s], ctx)

    def ron_eval(self, s, tile, mode):
        """s 荣和 tile 的结果（不管振听）；mode: discard / kakan / ankan。"""
        ctx = self._ctx(s, False, houtei=(mode == 'discard' and self.wall_left() == 0),
                        chankan=(mode != 'discard'))
        return best_win(self.hands[s] + [tile], tile, self.melds[s], ctx)

    def can_ron(self, s, tile, mode):
        k = kind(tile)
        if k not in self.player_waits(s) or self.is_furiten(s):
            return False
        if mode == 'ankan':
            if not self.rules['kokushi_ankan_rob'] or self.melds[s]:
                return False
            c = counts(self.hands[s])
            c[k] += 1
            if not is_kokushi(c):
                return False
        return self.ron_eval(s, tile, mode) is not None

    # ------------------------------------------------------------ 操作入口

    def act(self, seat, req):
        typ = req.get('type')
        acts = self.legal_actions(seat)
        if self.phase == 'end':
            raise ActionError('这一局已经结束了，请调用 /api/next')
        if not acts:
            raise ActionError('现在不该座位 %d 操作（在等 %s）' % (seat, self.waiting_for()))
        if typ not in acts:
            raise ActionError('座位 %d 现在不能做 %s，能做的是 %s' % (seat, typ, sorted(acts)))
        if req.get('tsumogiri') is not None and not isinstance(req.get('tsumogiri'), bool):
            raise ActionError('tsumogiri 应该是 true / false')
        if self.phase == 'turn':
            self._turn_act(seat, typ, req, acts)
        else:
            self._respond(seat, typ, req, acts)

    def _turn_act(self, s, typ, req, acts):
        if typ in ('discard', 'riichi'):
            tile = req.get('tile')
            if tile not in acts[typ]:
                raise ActionError('不能%s %r，能打的是 %s' % ('立直打' if typ == 'riichi' else '打', tile, acts[typ]))
            self._discard(s, tile, req.get('tsumogiri'), typ == 'riichi')
        elif typ == 'tsumo':
            self._win([s], None, self.drawn)
        elif typ in ('ankan', 'kakan'):
            tile = req.get('tile')
            if not isinstance(tile, str) or len(tile) != 2:
                raise ActionError('%s 要带 tile（牌种，如 5m）' % typ)
            try:
                k = kind(tile)
            except (ValueError, IndexError):
                raise ActionError('不认识的牌：%r' % tile)
            if kind_str(k) not in acts[typ]:
                raise ActionError('不能%s %s，能杠的是 %s' % ('暗杠' if typ == 'ankan' else '加杠', tile, acts[typ]))
            if typ == 'ankan':
                self._ankan(s, k)
            else:
                self._kakan(s, k)
        elif typ == 'kyuushu':
            self._abort('kyuushu')

    def _respond(self, s, typ, req, acts):
        if typ in ('chi', 'pon'):
            opts = acts[typ]
            tiles = req.get('tiles')
            if tiles is None:
                if len(opts) != 1:
                    raise ActionError('%s 有多种拿法，要带 tiles：%s' % (typ, opts))
                tiles = opts[0]
            if not isinstance(tiles, list) or not all(valid(t) for t in tiles) or sort_tiles(tiles) not in opts:
                raise ActionError('%s 的 tiles 不对：%r，能用的是 %s' % (typ, tiles, opts))
            self.responses[s] = {'type': typ, 'tiles': sort_tiles(tiles)}
        else:
            self.responses[s] = {'type': typ}
        if len(self.responses) == len(self.responders):
            self._resolve()

    # ------------------------------------------------------------ 打牌

    def _discard(self, s, tile, tsumogiri, riichi):
        hand = self.hands[s]
        d = self.drawn
        if self.riichi[s]:
            tsumogiri = True
        if tsumogiri is None:
            tsumogiri = d is not None and tile == d
        if tsumogiri:
            if d != tile:
                raise ActionError('tsumogiri=true，但摸到的牌是 %s，不是 %s' % (d, tile))
        else:
            if tile in hand:
                hand.remove(tile)
                if d is not None:
                    hand.append(d)
            elif d == tile:
                tsumogiri = True
            else:
                raise ActionError('手里没有 %s' % tile)
        self.drawn = None
        self.hands[s] = sort_tiles(hand)
        if riichi:
            self.pending_riichi = s
            self.pending_double = not self.discards[s] and self.no_calls
            self._event({'type': 'riichi', 'seat': s})
        self.discards[s].append({'tile': tile, 'tsumogiri': bool(tsumogiri), 'riichi': riichi, 'called': False})
        self._event({'type': 'discard', 'seat': s, 'tile': tile, 'tsumogiri': bool(tsumogiri)})
        self.furiten_temp[s] = False
        self.ippatsu[s] = False
        self.kuikae = set()
        self.rinshan_draw = False
        self._reveal_pending()
        self._open_discard_window(s, tile)

    def _open_discard_window(self, D, tile):
        self.window, self.window_tile, self.window_from = 'discard', tile, D
        k = kind(tile)
        can_call = self.wall_left() > 0
        responders = {}
        for P in self._order_from(D):
            opts = {}
            if self.can_ron(P, tile, 'discard'):
                opts['ron'] = True
            if can_call and not self.riichi[P]:
                hand = self.hands[P]
                same = [t for t in hand if kind(t) == k]
                pons = []
                for i in range(len(same)):
                    for j in range(i + 1, len(same)):
                        pair = sort_tiles([same[i], same[j]])
                        if pair not in pons and self._call_leaves_discard(P, pair, {k}):
                            pons.append(pair)
                if pons:
                    opts['pon'] = sorted(pons, key=lambda p: [t[0] for t in p], reverse=True)
                if len(same) == 3 and self.kans < 4:
                    opts['minkan'] = True
                if P == (D + 1) % 4 and k < 27:
                    chis = self._chi_options(P, tile)
                    if chis:
                        opts['chi'] = chis
            if opts:
                responders[P] = opts
        self.responders = responders
        self.responses = {}
        self.phase = 'response'
        if not responders:
            self._resolve()

    def _call_leaves_discard(self, P, used, forbidden):
        rest = list(self.hands[P])
        for t in used:
            rest.remove(t)
        if not self.rules['kuikae_ban']:
            return bool(rest)
        return any(kind(t) not in forbidden for t in rest)

    def _chi_forbidden(self, called, used):
        k = kind(called)
        ks = sorted(kind(t) for t in used)
        forb = {k}
        if k < ks[0] and num_of(ks[1]) < 9:
            forb.add(ks[1] + 1)
        elif k > ks[1] and num_of(ks[0]) > 1:
            forb.add(ks[0] - 1)
        return forb

    def _chi_options(self, P, tile):
        k = kind(tile)
        n = num_of(k)
        hand = self.hands[P]
        res = []
        for a, b in ((-2, -1), (-1, 1), (1, 2)):
            if not (1 <= n + a <= 9 and 1 <= n + b <= 9):
                continue
            ka, kb = k + a, k + b
            ta = sorted({t for t in hand if kind(t) == ka}, key=lambda t: t[0] == '0')
            tb = sorted({t for t in hand if kind(t) == kb}, key=lambda t: t[0] == '0')
            for x in ta:
                for y in tb:
                    pair = sort_tiles([x, y])
                    if pair not in res and self._call_leaves_discard(P, pair, self._chi_forbidden(tile, pair)):
                        res.append(pair)
        return res

    # ------------------------------------------------------------ 杠

    def _ankan(self, s, k):
        self._reveal_pending()
        tile = kind_str(k)
        self._event({'type': 'ankan', 'seat': s, 'tile': tile})
        responders = {}
        for P in self._order_from(s):
            if self.can_ron(P, tile, 'ankan'):
                responders[P] = {'ron': True}
        self._open_kan_window('ankan', s, tile, responders)

    def _kakan(self, s, k):
        self._reveal_pending()
        tile = self.drawn if kind(self.drawn) == k else next(t for t in self.hands[s] if kind(t) == k)
        self._event({'type': 'kakan', 'seat': s, 'tile': kind_str(k)})
        responders = {}
        for P in self._order_from(s):
            if self.can_ron(P, tile, 'kakan'):
                responders[P] = {'ron': True}
        self._open_kan_window('kakan', s, tile, responders)

    def _open_kan_window(self, window, s, tile, responders):
        self.window, self.window_tile, self.window_from = window, tile, s
        self.responders = responders
        self.responses = {}
        self.phase = 'response'
        if not responders:
            self._resolve()

    def _complete_kan(self):
        s, tile, window = self.window_from, self.window_tile, self.window
        k = kind(tile)
        t14 = self._tiles14(s)
        if window == 'ankan':
            used = [t for t in t14 if kind(t) == k]
            self.hands[s] = sort_tiles([t for t in t14 if kind(t) != k])
            self.melds[s].append({'type': 'ankan', 'tiles': sort_tiles(used), 'from': None, 'called_tile': None})
        else:
            t14.remove(tile)
            self.hands[s] = sort_tiles(t14)
            for m in self.melds[s]:
                if m['type'] == 'pon' and kind(m['tiles'][0]) == k:
                    m['type'] = 'kakan'
                    m['tiles'] = m['tiles'] + [tile]
                    break
        self.drawn = None
        self._kan_common(s)
        if window == 'ankan' or not self.rules['kan_dora_delay']:
            self._reveal_dora()
        else:
            self.pending_dora += 1
        self._draw(s, rinshan=True)

    def _kan_common(self, s):
        self.kans += 1
        self.kan_by[s] += 1
        self._after_call()
        if self.kans == 4 and max(self.kan_by) < 4:
            self.four_kan_pending = True

    def _after_call(self):
        self.no_calls = False
        self.ippatsu = [False] * 4

    # ------------------------------------------------------------ 表态之后

    def _resolve(self):
        D, tile, window = self.window_from, self.window_tile, self.window
        rons = [P for P in self._order_from(D) if self.responses.get(P, {}).get('type') == 'ron']
        self._apply_misses(D, tile, rons)
        if rons:
            if len(rons) == 3 and self.rules['triple_ron_abort']:
                self._abort('triple_ron')
                return
            if not self.rules['double_ron']:
                rons = rons[:1]
            self._win(rons, D, tile)
            return
        if window != 'discard':
            self._complete_kan()
            return
        # 宣言牌没被荣和：立直成立
        if self.pending_riichi is not None:
            s = self.pending_riichi
            self.pending_riichi = None
            self.g.scores[s] -= 1000
            self.g.riichi_sticks += 1
            self.riichi[s] = True
            self.double_riichi[s] = self.pending_double
            self.ippatsu[s] = True
            if all(self.riichi) and self.rules['four_riichi_abort']:
                self._abort('four_riichi')
                return
        if self.four_kan_pending and self.rules['four_kans_abort']:
            self._abort('four_kans')
            return
        if (self.rules['four_winds_abort'] and self.no_calls and all(len(d) == 1 for d in self.discards)
                and len({kind(d[0]['tile']) for d in self.discards}) == 1 and kind(tile) in WINDS):
            self._abort('four_winds')
            return
        # 鸣牌：碰、大明杠 > 吃
        for typ in ('pon', 'minkan', 'chi'):
            for P, r in self.responses.items():
                if r['type'] == typ:
                    if typ == 'minkan':
                        self._minkan(P)
                    else:
                        self._chi_pon(P, typ, r['tiles'])
                    return
        if self.wall_left() == 0:
            self._exhaustive()
            return
        self._draw((D + 1) % 4)

    def _apply_misses(self, D, tile, rons):
        """漏掉能荣和的牌：同巡振听；立直后漏掉：立直振听。"""
        k = kind(tile)
        for P in self._order_from(D):
            if P in rons:
                continue
            if self.window == 'ankan':
                missed = 'ron' in self.responders.get(P, {})   # 暗杠只有能抢的（国士）才算漏
            elif self.rules['furiten_no_yaku']:
                missed = k in self.player_waits(P)
            else:
                missed = 'ron' in self.responders.get(P, {})
            if missed:
                self.furiten_temp[P] = True
                if self.riichi[P]:
                    self.furiten_riichi[P] = True

    def _take_from_discarder(self):
        D = self.window_from
        self.discards[D][-1]['called'] = True
        return D, self.window_tile

    def _check_pao(self, P, k, D):
        if k in DRAGONS:
            n = sum(1 for m in self.melds[P] if m['type'] != 'chi' and kind(m['tiles'][0]) in DRAGONS)
            if n == 3:
                self.pao[P]['大三元'] = D
        elif k in WINDS:
            n = sum(1 for m in self.melds[P] if m['type'] != 'chi' and kind(m['tiles'][0]) in WINDS)
            if n == 4:
                self.pao[P]['大四喜'] = D

    def _chi_pon(self, P, typ, used):
        D, t = self._take_from_discarder()
        for x in used:
            self.hands[P].remove(x)
        if typ == 'chi':
            tiles = sort_tiles(used + [t])
            forb = self._chi_forbidden(t, used)
        else:
            tiles = sort_tiles(used) + [t]
            forb = {kind(t)}
        self.melds[P].append({'type': typ, 'tiles': tiles, 'from': D, 'called_tile': t})
        self._after_call()
        if typ == 'pon':
            self._check_pao(P, kind(t), D)
        self._event({'type': typ, 'seat': P, 'tiles': tiles, 'from': D})
        self.turn = P
        self.drawn = None
        self.rinshan_draw = False
        self.kuikae = forb if self.rules['kuikae_ban'] else set()
        self.phase = 'turn'
        self.window = None

    def _minkan(self, P):
        D, t = self._take_from_discarder()
        k = kind(t)
        used = [x for x in self.hands[P] if kind(x) == k]
        self.hands[P] = [x for x in self.hands[P] if kind(x) != k]
        tiles = sort_tiles(used) + [t]
        self.melds[P].append({'type': 'minkan', 'tiles': tiles, 'from': D, 'called_tile': t})
        self._kan_common(P)
        self._check_pao(P, k, D)
        self._event({'type': 'minkan', 'seat': P, 'tiles': tiles, 'from': D})
        if self.rules['kan_dora_delay']:
            self.pending_dora += 1
        else:
            self._reveal_dora()
        self._draw(P, rinshan=True)

    # ------------------------------------------------------------ 结束

    def _win(self, winners, frm, tile):
        """和了结算。frm 为 None 是自摸。winners 已按离放铳者从近到远排好。"""
        g = self.g
        tsumo = frm is None
        delta = [0] * 4
        wins = []
        for i, P in enumerate(winners):
            if tsumo:
                ev = self.tsumo_eval(P)
                hand = sort_tiles(self.hands[P])
            else:
                ev = self.ron_eval(P, tile, self.window)
                hand = sort_tiles(self.hands[P])
            pao_seat = None
            for name, _ in ev['yakuman_items']:
                if name in self.pao[P]:
                    pao_seat = self.pao[P][name]
            d = win_payments(ev, P, self.dealer, tsumo, frm, g.honba if i == 0 else 0, pao_seat, self.rules)
            for s in range(4):
                delta[s] += d[s]
            w = {
                'seat': P, 'from': frm, 'hand': hand,
                'melds': [dict(m, tiles=list(m['tiles'])) for m in self.melds[P]],
                'win_tile': tile,
                'yaku': [{'name': n, 'han': h} for n, h in ev['yaku']],
                'han': ev['han'], 'fu': ev['fu'], 'yakuman': ev['yakuman'], 'points': ev['points'],
            }
            if pao_seat is not None and self.rules['pao']:
                w['pao'] = pao_seat
            wins.append(w)
            self._event({'type': 'tsumo', 'seat': P} if tsumo else {'type': 'ron', 'seat': P, 'from': frm})
        delta[winners[0]] += 1000 * g.riichi_sticks
        g.riichi_sticks = 0
        ura = self.ura_indicators() if any(self.riichi[P] for P in winners) else []
        self._finish({'type': 'agari', 'wins': wins, 'dora_indicators': self.dora_indicators(),
                      'uradora_indicators': ura, 'delta': delta},
                     renchan=self.dealer in winners, honba_reset=self.dealer not in winners)

    def _exhaustive(self):
        tenpai = [bool(self.player_waits(s)) for s in range(4)]
        delta = [0] * 4
        nagashi = []
        if self.rules['nagashi_mangan']:
            nagashi = [s for s in range(4) if self.discards[s]
                       and all(is_yaochu(kind(d['tile'])) and not d['called'] for d in self.discards[s])]
        if nagashi:
            for s in nagashi:
                for o in range(4):
                    if o != s:
                        amt = 4000 if (s == self.dealer or o == self.dealer) else 2000
                        delta[o] -= amt
                        delta[s] += amt
        else:
            n = sum(tenpai)
            if 0 < n < 4:
                for s in range(4):
                    delta[s] = 3000 // n if tenpai[s] else -3000 // (4 - n)
        res = {'type': 'ryuukyoku', 'reason': 'exhaustive', 'tenpai': tenpai, 'delta': delta}
        if nagashi:
            res['nagashi'] = nagashi
        self._event({'type': 'ryuukyoku', 'reason': 'exhaustive'})
        self._finish(res, renchan=tenpai[self.dealer], honba_reset=False)

    def _abort(self, reason):
        self._event({'type': 'ryuukyoku', 'reason': reason})
        self._finish({'type': 'ryuukyoku', 'reason': reason, 'delta': [0, 0, 0, 0]}, renchan=True, honba_reset=False)

    def _finish(self, result, renchan, honba_reset):
        for s in range(4):
            self.g.scores[s] += result['delta'][s]
        self.result = result
        self.phase = 'end'
        self.window = None
        self.responders = {}
        self.responses = {}
        self.g.round_over(result, renchan, honba_reset)
