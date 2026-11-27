# 学号 250207
# game.py —— 整局流程：洗牌发牌、摸打、吃碰杠、立直、流局、连庄换庄、本场、电脑玩家
#
# 用法（给 250226 接 server 用）：
#   g = Game(human_seats=[0])        # 开新游戏，自动开始东1局
#   g = Game(human_seats=[0], wall=牌山)   # 指定牌山（136 张）测试用
#   g.get_state(seat)                # 当前状态 dict
#   g.get_legal_actions(seat)        # 这个人现在能做什么
#   g.do_action(seat, 'discard', tile='3m')   # 玩家操作，不合法会 raise ValueError
#   g.next_round()                   # 一局结束后进下一局
#
# 我自己定的几个约定（任务书没写清楚的地方）：
# - 座位 0 是起家（东1局的庄家），之后庄家按 0->1->2->3 轮。当前庄家是 self.oya。
# - 牌在 game 里面原样保留红五 0m/0p/0s（前端就是这么写的）。
#   传给 fu / tenpai 的时候统一换成 5m，传给 yaku 算分的时候给原样的手牌（带 0m），
#   这样 250118 那边能自己数赤宝牌。
# - 传给 fu / yaku 的 hand 是“和了时的门前手牌”，包含和的那张（副露以外的全部，14 - 3*副露数 张），
#   win_tile 另外单独传。
# - 宝牌传的是已经换算好的宝牌（不是指示牌），是个 list，比如 ['5m', '2z']。
#   立直和了的时候里宝牌也直接加进这个 list 里。
# - 双立直的时候 state 里 riichi 和 double_riichi 都是 True（250118 别重复算）。
#   state 里我多加了一个 'chihou'（地和），天凤有这个。

import random
from collections import Counter
from itertools import combinations

try:
    from fu import calc_fu
    from yaku import calc_yaku, calc_yaku_detailed, calc_hand_details
    from score import calc_score
    from tenpai import can_hu
except ImportError:
    # 别人的文件还没交的时候先这样，自测用最下面 __main__ 里的假函数
    calc_fu = calc_yaku = calc_yaku_detailed = calc_hand_details = calc_score = can_hu = None


START_POINTS = 25000
RETURN_POINTS = 30000   # 南入/结束判断用（天凤：有人到 30000 才结束）

ALL_TILES = [str(n) + s for s in 'mps' for n in range(1, 10)] + [str(n) + 'z' for n in range(1, 8)]


def norm(t):
    """红五 0m -> 5m"""
    if t[0] == '0':
        return '5' + t[1]
    return t


def norm_list(tiles):
    return [norm(t) for t in tiles]


def tile_key(t):
    n = 5 if t[0] == '0' else int(t[0])
    return ('mpsz'.index(t[1]), n, t[0] == '0')


def make_wall(aka_dora=True):
    wall = []
    for s in 'mps':
        for n in range(1, 10):
            for k in range(4):
                if aka_dora and n == 5 and k == 0:
                    wall.append('0' + s)   # 每种花色一张红五
                else:
                    wall.append(str(n) + s)
    for n in range(1, 8):
        wall += [str(n) + 'z'] * 4
    return wall


DEFAULT_RULES = {
    'aka_dora': True,
    'kuitan': True,
    'kiriage_mangan': False,
    'renpu_fu': 4,
}


def clean_rules(rules=None):
    """合并并校验整场规则；不允许对局中悄悄改变。"""
    rules = dict(rules or {})
    unknown = set(rules) - set(DEFAULT_RULES)
    if unknown:
        raise ValueError('未知规则开关: ' + ', '.join(sorted(unknown)))
    out = dict(DEFAULT_RULES)
    out.update(rules)
    for key in ('aka_dora', 'kuitan', 'kiriage_mangan'):
        if type(out[key]) is not bool:
            raise ValueError(key + ' 必须是 true/false')
    if type(out['renpu_fu']) is not int or out['renpu_fu'] not in (2, 4):
        raise ValueError('renpu_fu 必须是 2 或 4')
    return out


def dora_from_indicator(ind):
    t = norm(ind)
    n = int(t[0])
    s = t[1]
    if s == 'z':
        if n <= 4:
            n = n % 4 + 1          # 东南西北循环
        else:
            n = (n - 5 + 1) % 3 + 5  # 白发中循环
    else:
        n = n % 9 + 1
    return str(n) + s


def is_yaochu(t):
    t = norm(t)
    return t[1] == 'z' or t[0] in '19'


class Game:
    def __init__(self, human_seats=(0,), wall=None, seed=None, rules=None, length='tonpuu'):
        self.rng = random.Random(seed)
        self.human_seats = set(human_seats)
        if not self.human_seats <= {0, 1, 2, 3}:
            raise ValueError('座位必须在 0~3')
        if length not in ('tonpuu', 'hanchan'):
            raise ValueError('length 必须是 tonpuu 或 hanchan')
        self.length = length
        self.rules = clean_rules(rules)
        self.scores = [START_POINTS] * 4
        self.kyoku = 0      # 0~3 = 东1~东4，4~7 = 南1~南4 / 东风战南入
        self.honba = 0
        self.kyotaku = 0    # 场上的立直棒（根数）
        self.game_over = False
        self.result = None
        self.start_round(wall)

    # ---------- 小工具 ----------
    @property
    def oya(self):
        return self.kyoku % 4

    @property
    def bakaze(self):
        return '1z' if self.kyoku < 4 else '2z'

    def jikaze(self, seat):
        return str((seat - self.oya) % 4 + 1) + 'z'

    def remaining(self):
        """牌山还能摸几张"""
        return self.wall_end - self.wall_pos

    def melds_plain(self, seat, normalize=False):
        res = []
        for m in self.melds[seat]:
            res.append(norm_list(m['tiles']) if normalize else list(m['tiles']))
        return res

    def is_menzen(self, seat):
        return all(m['type'] == 'ankan' for m in self.melds[seat])

    def dora_indicators(self):
        return self.dead_wall[:self.dora_count]

    def ura_indicators(self):
        return self.dead_wall[5:5 + self.dora_count]

    def dora_list(self, with_ura=False):
        res = [dora_from_indicator(t) for t in self.dora_indicators()]
        if with_ura:
            res += [dora_from_indicator(t) for t in self.ura_indicators()]
        return res

    def get_visible(self, seat):
        """供 tenpai 使用：不含自己的手牌/副露（tenpai 会另算），其余可见牌只列一次。"""
        vis = []
        for s in range(4):
            # 被鸣走的牌仍显示在河里，但已经在副露中，不能重复扣两次。
            vis += [r['tile'] for r in self.rivers[s] if not r.get('called')]
            if s != seat:
                for m in self.melds[s]:
                    vis += m['tiles']
        vis += self.dora_indicators()
        return norm_list(vis)

    # ---------- 一局开始 ----------
    def start_round(self, wall=None):
        if wall is None:
            wall = make_wall(self.rules['aka_dora'])
            self.rng.shuffle(wall)
        else:
            wall = list(wall)
            if len(wall) != 136:
                raise ValueError('牌山要 136 张')
            if Counter(wall) != Counter(make_wall(self.rules['aka_dora'])):
                raise ValueError('牌山牌张或赤五配置不正确')
        # 与前端约定一致：配牌按物理座位；正常摸牌到 121；
        # 王牌 122~126 表宝、127~131 里宝、132~135 岭上。
        self.wall = wall
        self.dead_wall = wall[122:136]
        self.wall_pos = 52
        self.wall_end = 122
        self.rinshan_used = 0
        self.dora_count = 1

        self.hands = [sorted(wall[13 * s:13 * s + 13], key=tile_key) for s in range(4)]
        self.rivers = [[] for _ in range(4)]
        self.melds = [[] for _ in range(4)]
        self.riichi = [False] * 4
        self.double_riichi = [False] * 4
        self.ippatsu = [False] * 4
        self.first_turn = [True] * 4
        self.no_call_yet = True
        self.temp_furiten = [False] * 4
        self.riichi_furiten = [False] * 4
        self.riichi_pending = None
        self.kan_seats = []
        self.kakan_pending = None

        self.current = self.oya
        self.drawn = None
        self.is_rinshan_draw = False
        self.after_call = False
        self.kuikae = []
        self.last_discard = None
        self.call_options = {}
        self.responses = {}
        self.result = None
        self.events = []
        self.phase = 'discard'

        self._draw(self.oya)
        self._run()

    # ---------- 摸牌打牌 ----------
    def _draw(self, seat, rinshan=False):
        if rinshan:
            t = self.dead_wall[10 + self.rinshan_used]
            self.rinshan_used += 1
            self.wall_end -= 1   # 每杠一次，正常牌山末尾向前补一张
        else:
            if self.remaining() <= 0:
                raise ValueError('牌山已经没有可摸的牌')
            t = self.wall[self.wall_pos]
            self.wall_pos += 1
        self.hands[seat].append(t)   # 摸的牌放最后，打完再排序
        self.drawn = t
        self.current = seat
        self.is_rinshan_draw = rinshan
        self.after_call = False
        self.kuikae = []
        self.phase = 'discard'
        self.events.append({'type': 'draw', 'seat': seat, 'tile': t})

    def _discard(self, seat, tile, riichi=False, tsumogiri=None):
        hand = self.hands[seat]
        if tsumogiri is None:
            tsumogiri = tile == self.drawn
        hand.remove(tile)
        hand.sort(key=tile_key)
        if self.riichi[seat] and not riichi:
            self.ippatsu[seat] = False    # 立直后自己又打了一张，一发没了
        if riichi:
            self.riichi[seat] = True
            self.ippatsu[seat] = True
            if self.first_turn[seat] and self.no_call_yet:
                self.double_riichi[seat] = True
            self.riichi_pending = seat
            self.events.append({'type': 'riichi', 'seat': seat})
        self.first_turn[seat] = False
        self.temp_furiten[seat] = False   # 同巡振听到自己打牌就解除
        self.rivers[seat].append({'tile': tile, 'riichi': riichi, 'called': False,
                                  'tsumogiri': bool(tsumogiri)})
        self.events.append({'type': 'discard', 'seat': seat, 'tile': tile,
                            'tsumogiri': bool(tsumogiri)})
        self.drawn = None
        self.is_rinshan_draw = False
        self.last_discard = (seat, tile)

        # 别人能不能和/碰/杠/吃
        self.call_options = {}
        self.responses = {}
        last = self.remaining() == 0
        for i in (1, 2, 3):
            s = (seat + i) % 4
            opts = []
            if self._can_ron(s, tile):
                opts.append({'type': 'ron', 'tile': tile})
            if not self.riichi[s] and not last:   # 河底那张不能鸣
                same = [t for t in self.hands[s] if norm(t) == norm(tile)]
                if len(same) >= 2:
                    for combo in self._pon_combos(same):
                        remaining = list(self.hands[s])
                        for own_tile in combo:
                            remaining.remove(own_tile)
                        if any(norm(t) != norm(tile) for t in remaining):
                            opts.append({'type': 'pon', 'tiles': combo})
                if len(same) >= 3 and self.rinshan_used < 4:
                    opts.append({'type': 'kan', 'tiles': same[:3]})
                if i == 1 and tile[1] != 'z':
                    for combo in self._chi_combos(s, tile):
                        opts.append({'type': 'chi', 'tiles': combo})
            if opts:
                self.call_options[s] = opts
        self.phase = 'call'

    def _pon_combos(self, same):
        # 普通五重复时只列一次；红五与普通五的不同拿法要分别提供给前端。
        unique = []
        for combo in combinations(sorted(same, key=lambda t: t[0] != '0'), 2):
            key = tuple(combo)
            if key not in unique:
                unique.append(key)
        return [list(combo) for combo in unique]

    def _kuikae_for_call(self, tile, kind, own):
        forbidden = [norm(tile)]
        if kind == 'chi':
            n = int(norm(tile)[0])
            a, b = sorted(int(norm(t)[0]) for t in own)
            if n < a and b + 1 <= 9:
                forbidden.append(str(b + 1) + tile[1])
            elif n > b and a - 1 >= 1:
                forbidden.append(str(a - 1) + tile[1])
        return forbidden

    def _chi_combos(self, seat, tile):
        n = int(norm(tile)[0])
        s = tile[1]
        hand = self.hands[seat]
        combos = []
        for a, b in ((n - 2, n - 1), (n - 1, n + 1), (n + 1, n + 2)):
            if a < 1 or b > 9:
                continue
            ta = [t for t in hand if norm(t) == str(a) + s]
            tb = [t for t in hand if norm(t) == str(b) + s]
            if ta and tb:
                # 有红五的话就分两种（用不用红五）
                for x in sorted(set(ta), key=tile_key):
                    for y in sorted(set(tb), key=tile_key):
                        remaining = list(hand)
                        remaining.remove(x)
                        remaining.remove(y)
                        forbidden = self._kuikae_for_call(tile, 'chi', [x, y])
                        # 副露较多时尤其要预检：不能让玩家吃完后无牌可打。
                        if any(norm(t) not in forbidden for t in remaining):
                            combos.append([x, y])
        return combos

    # ---------- 和牌判断 ----------
    def _is_tenpai(self, hand13, melds_n):
        h = norm_list(hand13)
        for t in ALL_TILES:
            if can_hu(h + [t], melds_n):
                return True
        return False

    def _waits(self, hand13, melds_n):
        h = norm_list(hand13)
        return set(t for t in ALL_TILES if can_hu(h + [t], melds_n))

    def _is_furiten(self, seat):
        if self.temp_furiten[seat] or self.riichi_furiten[seat]:
            return True
        h = norm_list(self.hands[seat])
        mn = self.melds_plain(seat, True)
        # 舍张振听：自己牌河里（包括被别人鸣走的）有能和的牌
        for t in set(norm(r['tile']) for r in self.rivers[seat]):
            if can_hu(h + [t], mn):
                return True
        return False

    def _ankan_indices(self, seat):
        return [i for i, m in enumerate(self.melds[seat]) if m['type'] == 'ankan']

    def _make_state(self, seat, is_tsumo):
        last = self.remaining() == 0
        return {
            'riichi': self.riichi[seat],
            'ippatsu': self.ippatsu[seat],
            'haitei': is_tsumo and last and not self.is_rinshan_draw,
            'houtei': (not is_tsumo) and last and self.kakan_pending is None,
            'rinshan': is_tsumo and self.is_rinshan_draw,
            'chankan': (not is_tsumo) and self.kakan_pending is not None,
            'double_riichi': self.double_riichi[seat],
            'tenhou': is_tsumo and seat == self.oya and self.first_turn[seat] and self.no_call_yet,
            'chihou': is_tsumo and seat != self.oya and self.first_turn[seat] and self.no_call_yet,
            'ankan_indices': self._ankan_indices(seat),
        }

    def _win_ok(self, seat, hand14, win_tile, is_tsumo):
        """形能和 + 有役。判断有没有役的时候不传宝牌、手牌也换成 5m，这样宝牌赤宝牌不会算进去，0 番就是没役"""
        hn = norm_list(hand14)
        mn = self.melds_plain(seat, True)
        if not can_hu(hn, mn):
            return False
        state = self._make_state(seat, is_tsumo)
        yaku, han = calc_yaku(hn, mn, norm(win_tile), is_tsumo, self.bakaze,
                              self.jikaze(seat), [], state, rules=self.rules)
        return han > 0

    def _can_ron(self, seat, tile):
        if self._is_furiten(seat):
            return False
        return self._win_ok(seat, self.hands[seat] + [tile], tile, False)

    # ---------- 合法操作 ----------
    def get_legal_actions(self, seat):
        if self.phase == 'discard' and seat == self.current:
            return self._turn_actions(seat)
        if self.phase == 'call' and seat in self.call_options and seat not in self.responses:
            return self.call_options[seat] + [{'type': 'pass'}]
        return []

    def _turn_actions(self, seat):
        acts = []
        hand = self.hands[seat]
        if self.riichi[seat]:
            discards = [self.drawn]
        else:
            discards = sorted(set(hand), key=tile_key)
            if self.after_call and self.kuikae:
                # 食替禁止（天凤规则）
                discards = [t for t in discards if norm(t) not in self.kuikae]
        acts.append({'type': 'discard', 'tiles': discards})
        if self.after_call:
            return acts

        if self._win_ok(seat, hand, self.drawn, True):
            acts.append({'type': 'tsumo', 'tile': self.drawn})

        # 立直：门清、1000 点以上、牌山还剩 4 张以上、打掉某张后听牌
        if (not self.riichi[seat] and self.is_menzen(seat) and self.scores[seat] >= 1000
                and self.remaining() >= 4):
            mn = self.melds_plain(seat, True)
            rt = []
            for t in sorted(set(hand), key=tile_key):
                h = list(hand)
                h.remove(t)
                if self._is_tenpai(h, mn):
                    rt.append(t)
            if rt:
                acts.append({'type': 'riichi', 'tiles': rt})

        # 杠（暗杠、加杠）
        if self.rinshan_used < 4 and self.remaining() > 0:
            kans = []
            counts = {}
            for t in hand:
                counts[norm(t)] = counts.get(norm(t), 0) + 1
            for t, c in counts.items():
                if c == 4:
                    if self.riichi[seat]:
                        if norm(self.drawn) != t or not self._riichi_ankan_ok(seat, t):
                            continue
                    kans.append({'type': 'kan', 'tiles': [t], 'kind': 'ankan'})
            if not self.riichi[seat]:
                for m in self.melds[seat]:
                    if m['type'] == 'pon' and norm(m['tiles'][0]) in counts:
                        kans.append({'type': 'kan', 'tiles': [norm(m['tiles'][0])], 'kind': 'kakan'})
            acts += kans

        # 九种九牌
        if self.first_turn[seat] and self.no_call_yet:
            kinds = set(norm(t) for t in hand if is_yaochu(t))
            if len(kinds) >= 9:
                acts.append({'type': 'kyuushu'})
        return acts

    def _riichi_ankan_ok(self, seat, t):
        """立直后暗杠：杠了以后听的牌不变才行（简化判断，只看听牌种类）"""
        hand = list(self.hands[seat])
        hand.remove(self.drawn)
        mn = self.melds_plain(seat, True)
        before = self._waits(hand, mn)
        h2 = [x for x in self.hands[seat] if norm(x) != t]
        after = self._waits(h2, mn + [[t] * 4])
        return before == after and len(before) > 0

    # ---------- 玩家操作 ----------
    def do_action(self, seat, action, tile=None, tiles=None, tsumogiri=None):
        """执行操作；tile 是打牌/杠牌，tiles 是吃碰的两张，tsumogiri 区分摸切。"""
        if self.phase == 'end':
            raise ValueError('这局已经结束了')
        legal = self.get_legal_actions(seat)
        types = [a['type'] for a in legal]
        if action not in types:
            raise ValueError('现在不能 ' + action)

        if self.phase == 'discard':
            if action == 'discard':
                ok = [a for a in legal if a['type'] == 'discard'][0]['tiles']
                if tile not in ok:
                    raise ValueError('不能打这张')
                if self.riichi[seat] and any(a['type'] == 'tsumo' for a in legal):
                    self.riichi_furiten[seat] = True
                self._discard(seat, tile, tsumogiri=tsumogiri)
            elif action == 'riichi':
                ok = [a for a in legal if a['type'] == 'riichi'][0]['tiles']
                if tile not in ok:
                    raise ValueError('打这张不能立直')
                self._discard(seat, tile, riichi=True, tsumogiri=tsumogiri)
            elif action == 'tsumo':
                self._win_tsumo(seat)
            elif action == 'kan':
                kan = None
                for a in legal:
                    if a['type'] == 'kan' and (tile is None or norm(tile) == a['tiles'][0]):
                        kan = a
                        break
                if kan is None:
                    raise ValueError('不能杠这张')
                if kan['kind'] == 'ankan':
                    self._ankan(seat, kan['tiles'][0])
                else:
                    self._kakan(seat, kan['tiles'][0])
            elif action == 'kyuushu':
                self._abort('九种九牌')
        else:
            if action in ('chi', 'pon', 'kan'):
                cand = [a for a in legal if a['type'] == action]
                pick = cand[0]
                if tiles is not None:
                    for a in cand:
                        if sorted(a['tiles']) == sorted(tiles):
                            pick = a
                            break
                    else:
                        raise ValueError('没有这个吃法')
                self.responses[seat] = pick
            else:
                self.responses[seat] = {'type': action}
            self._try_resolve()
        self._run()

    # ---------- 电脑 ----------
    def _cpu_turn(self, seat):
        acts = self._turn_actions(seat)
        if any(a['type'] == 'tsumo' for a in acts):
            self._win_tsumo(seat)
            return
        # 摸什么打什么
        if self.drawn is not None and self.drawn in self.hands[seat]:
            self._discard(seat, self.drawn, tsumogiri=True)
        else:
            self._discard(seat, acts[0]['tiles'][-1], tsumogiri=False)

    def _cpu_response(self, seat):
        for o in self.call_options[seat]:
            if o['type'] == 'ron':
                return o
        return {'type': 'pass'}

    def _run(self):
        """电脑能自己动的都让它动完，轮到人或者一局结束就停"""
        while self.phase != 'end':
            if self.phase == 'discard':
                if self.current in self.human_seats:
                    return
                self._cpu_turn(self.current)
            elif self.phase == 'call':
                for s in self.call_options:
                    if s not in self.human_seats and s not in self.responses:
                        self.responses[s] = self._cpu_response(s)
                if not self._try_resolve():
                    return

    # ---------- 鸣牌结算 ----------
    def _try_resolve(self):
        if self.phase != 'call':
            return True
        for s in self.call_options:
            if s not in self.responses:
                return False
        self._resolve_calls()
        return True

    def _resolve_calls(self):
        discarder, tile = self.last_discard
        order = [(discarder + i) % 4 for i in (1, 2, 3)]
        resp = self.responses
        rons = [s for s in order if resp.get(s, {}).get('type') == 'ron']

        # 能荣和没荣和 -> 同巡振听，立直了就一直振听
        for s, opts in self.call_options.items():
            if any(o['type'] == 'ron' for o in opts) and s not in rons:
                self.temp_furiten[s] = True
                if self.riichi[s]:
                    self.riichi_furiten[s] = True

        if rons and self.riichi_pending == discarder:
            # 宣言牌被和时立直不成立：未收棒，也不能保留立直/双立直标记。
            self.riichi[discarder] = False
            self.double_riichi[discarder] = False
            self.ippatsu[discarder] = False
            self.riichi_pending = None
        if len(rons) == 3:
            self._abort('三家和')
            return
        if rons:
            self._win_ron(rons, discarder, tile)
            return
        if self.kakan_pending is not None:
            # 无人抢杠，加杠才正式成立并摸岭上牌；被抢则不翻杠宝牌。
            self.kakan_pending = None
            self._after_kan(discarder)
            return
        if len(self.kan_seats) == 4 and len(set(self.kan_seats)) > 1:
            # 第四杠后的舍牌无人和即四杠流局，不能再被吃碰继续。
            self._abort('四杠散了')
            return
        # 碰/杠优先于吃
        for s in order:
            r = resp.get(s, {})
            if r.get('type') in ('pon', 'kan'):
                self._pay_riichi_stick()
                self._call_meld(s, discarder, tile, r['type'], r['tiles'])
                return
        for s in order:
            r = resp.get(s, {})
            if r.get('type') == 'chi':
                self._pay_riichi_stick()
                self._call_meld(s, discarder, tile, 'chi', r['tiles'])
                return
        self._after_discard_pass()

    def _pay_riichi_stick(self):
        """立直宣言那张没人荣和，立直成立，放 1000 点"""
        if self.riichi_pending is not None:
            s = self.riichi_pending
            self.scores[s] -= 1000
            self.kyotaku += 1
            self.riichi_pending = None
            return True
        return False

    def _after_discard_pass(self):
        discarder, tile = self.last_discard
        if self._pay_riichi_stick() and all(self.riichi):
            self._abort('四家立直')
            return
        # 四风连打
        if self.no_call_yet and all(len(r) == 1 for r in self.rivers):
            first = [norm(r[0]['tile']) for r in self.rivers]
            if first[0] in ('1z', '2z', '3z', '4z') and len(set(first)) == 1:
                self._abort('四风连打')
                return
        if len(self.kan_seats) == 4 and len(set(self.kan_seats)) > 1:
            self._abort('四杠散了')
            return
        if self.remaining() == 0:
            self._exhaustive_draw()
            return
        self._draw((discarder + 1) % 4)

    def _interrupt(self):
        """有人鸣牌：一发、天和地和、双立直的机会都没了"""
        self.no_call_yet = False
        self.ippatsu = [False] * 4
        self.first_turn = [False] * 4

    def _call_meld(self, seat, discarder, tile, kind, own):
        self._interrupt()
        hand = self.hands[seat]
        for t in own:
            hand.remove(t)
        self.rivers[discarder][-1]['called'] = True
        if kind == 'kan':
            tiles4 = sorted(own + [tile], key=tile_key)
            self.melds[seat].append({'type': 'minkan', 'tiles': tiles4, 'from': discarder,
                                     'called_tile': tile})
            self.events.append({'type': 'minkan', 'seat': seat, 'tiles': tiles4, 'from': discarder})
            self._after_kan(seat)
            return
        meld_tiles = sorted(own + [tile], key=tile_key)
        self.melds[seat].append({'type': kind, 'tiles': meld_tiles, 'from': discarder,
                                 'called_tile': tile})
        self.events.append({'type': kind, 'seat': seat, 'tiles': meld_tiles, 'from': discarder})
        self.current = seat
        self.drawn = None
        self.after_call = True
        self.phase = 'discard'
        # 食替限制与 _chi_combos 的预检共用同一份计算，避免两处规则漂移。
        self.kuikae = self._kuikae_for_call(tile, kind, own)

    def _ankan(self, seat, t):
        self._interrupt()
        own = [x for x in self.hands[seat] if norm(x) == t]
        for x in own:
            self.hands[seat].remove(x)
        self.hands[seat].sort(key=tile_key)
        self.melds[seat].append({'type': 'ankan', 'tiles': own, 'from': None, 'called_tile': None})
        self.events.append({'type': 'ankan', 'seat': seat, 'tile': t})
        self._after_kan(seat)

    def _kakan(self, seat, t):
        self._interrupt()
        x = [y for y in self.hands[seat] if norm(y) == t][0]
        self.hands[seat].remove(x)
        self.hands[seat].sort(key=tile_key)
        for m in self.melds[seat]:
            if m['type'] == 'pon' and norm(m['tiles'][0]) == t:
                m['type'] = 'kakan'
                m['tiles'] = sorted(m['tiles'] + [x], key=tile_key)
                break
        self.events.append({'type': 'kakan', 'seat': seat, 'tile': t})
        self.kakan_pending = (seat, x)
        self.last_discard = (seat, x)
        self.call_options = {}
        self.responses = {}
        for i in (1, 2, 3):
            s = (seat + i) % 4
            if self._can_ron(s, x):
                self.call_options[s] = [{'type': 'ron', 'tile': x}]
        self.phase = 'call'

    def _after_kan(self, seat):
        self.dora_count += 1
        self.kan_seats.append(seat)
        indicator = self.dora_indicators()[-1]
        self.events.append({'type': 'dora', 'tile': indicator})
        self._draw(seat, rinshan=True)

    # ---------- 和牌结算 ----------
    def _parse_score(self, res, is_oya, is_tsumo):
        """统一接受 score.py 的 dict，也保留旧元组自测接口。"""
        if isinstance(res, dict):
            gain = res.get('get', 0)
            if not is_tsumo:
                return gain, res.get('ron_pay', 0), res.get('ron_pay', 0)
            if is_oya:
                pay = res.get('ko_pay', 0)
                return gain, pay, pay
            return gain, res.get('oya_pay', 0), res.get('ko_pay', 0)
        gain, pay = res[0], res[1]
        if isinstance(pay, (list, tuple)):
            if len(pay) >= 2:
                return gain, pay[0], pay[1]
            pay = pay[0]
        return gain, pay, pay

    def _score_one(self, seat, hand14, win_tile, is_tsumo, from_seat, honba, kyotaku):
        melds = self.melds_plain(seat)
        state = self._make_state(seat, is_tsumo)
        dora = self.dora_list()
        state['ura_dora'] = ([dora_from_indicator(t) for t in self.ura_indicators()]
                             if self.riichi[seat] else [])
        # 番与符必须由同一次拆法选择产生，不能分别取不同拆法的最大值。
        yaku, han, fu = calc_hand_details(list(hand14), melds, win_tile, is_tsumo,
                                          self.bakaze, self.jikaze(seat), dora, state,
                                          rules=self.rules)
        # 只有真正的役满役种才设置倍数；普通牌累计到 13 番仍是累计役满。
        yakuman = sum(y['han'] // 13 for y in yaku
                      if y['han'] >= 13
                      and not y['name'].startswith(('宝牌', '赤宝牌', '里宝牌')))
        is_oya = seat == self.oya
        kwargs = {'kiriage_mangan': self.rules['kiriage_mangan'], 'yakuman': yakuman}
        res = calc_score(fu, han, is_oya, is_tsumo, honba, kyotaku, **kwargs)
        base_res = calc_score(fu, han, is_oya, is_tsumo, 0, 0, **kwargs)
        gain, pay_oya, pay_ko = self._parse_score(res, is_oya, is_tsumo)
        base_gain = self._parse_score(base_res, is_oya, is_tsumo)[0]
        delta = [0] * 4
        delta[seat] += gain
        if is_tsumo:
            for s in range(4):
                if s != seat:
                    delta[s] -= pay_oya if s == self.oya else pay_ko
        else:
            delta[from_seat] -= pay_oya
        info = {
            'seat': seat, 'from': from_seat, 'tile': win_tile, 'tsumo': is_tsumo,
            'hand': list(hand14), 'melds': melds,
            'yaku': yaku, 'han': han, 'fu': fu, 'yakuman': yakuman,
            'points': base_gain, 'rank': res.get('rank', '') if isinstance(res, dict) else '',
            'delta': delta,
        }
        return info, delta

    def _win_tsumo(self, seat):
        info, delta = self._score_one(seat, self.hands[seat], self.drawn, True, None,
                                      self.honba, self.kyotaku)
        self.events.append({'type': 'tsumo', 'seat': seat})
        self.kyotaku = 0
        result = {'type': 'tsumo', 'wins': [info],
                  'dora_indicators': self.dora_indicators(),
                  'ura_indicators': self.ura_indicators() if self.riichi[seat] else []}
        self._end_round(result, delta, seat == self.oya, True)

    def _win_ron(self, winners, discarder, tile):
        # 双响可以（天凤），本场和立直棒给离放铳的人最近的那个（上家取り）
        total = [0] * 4
        wins = []
        for i, s in enumerate(winners):
            hb = self.honba if i == 0 else 0
            kt = self.kyotaku if i == 0 else 0
            info, delta = self._score_one(s, self.hands[s] + [tile], tile, False, discarder, hb, kt)
            wins.append(info)
            self.events.append({'type': 'ron', 'seat': s, 'from': discarder})
            for k in range(4):
                total[k] += delta[k]
        self.kyotaku = 0
        any_riichi = any(self.riichi[s] for s in winners)
        result = {'type': 'ron', 'wins': wins,
                  'dora_indicators': self.dora_indicators(),
                  'ura_indicators': self.ura_indicators() if any_riichi else []}
        self._end_round(result, total, self.oya in winners, True)

    # ---------- 流局 ----------
    def _exhaustive_draw(self):
        # TODO 流局满贯没做
        tenpai = [self._is_tenpai(self.hands[s], self.melds_plain(s, True)) for s in range(4)]
        n = sum(tenpai)
        delta = [0] * 4
        if 0 < n < 4:
            for s in range(4):
                if tenpai[s]:
                    delta[s] += 3000 // n
                else:
                    delta[s] -= 3000 // (4 - n)
        result = {'type': 'ryuukyoku', 'reason': '荒牌流局', 'tenpai': tenpai}
        self.events.append({'type': 'ryuukyoku', 'reason': 'exhaustive'})
        self._end_round(result, delta, tenpai[self.oya], False, draw=True)

    def _abort(self, reason):
        # 途中流局：庄家连庄、本场+1，立直棒留着
        result = {'type': 'abort', 'reason': reason}
        keys = {'九种九牌': 'kyuushu', '四杠散了': 'four_kans', '四家立直': 'four_riichi',
                '四风连打': 'four_winds', '三家和': 'triple_ron'}
        self.events.append({'type': 'ryuukyoku', 'reason': keys[reason]})
        self._end_round(result, [0] * 4, True, False, draw=True)

    # ---------- 一局结束、换庄 ----------
    def _end_round(self, result, delta, renchan, is_win, draw=False):
        for s in range(4):
            self.scores[s] += delta[s]
        result['delta'] = delta
        result['scores'] = list(self.scores)
        result['renchan'] = renchan
        self.result = result
        self.phase = 'end'
        self.call_options = {}
        self.responses = {}
        self.next_renchan = renchan
        # 连庄或者流局本场 +1，闲家和了本场清零
        self.next_honba = self.honba + 1 if (renchan or draw) else 0
        self.game_over = self._check_game_over(renchan, is_win)
        if self.game_over:
            # 剩下的立直棒给第一名（天凤）；同分按起家顺序
            top = max(range(4), key=lambda s: (self.scores[s], -s))
            bonus = self.kyotaku * 1000
            self.scores[top] += bonus
            delta[top] += bonus
            result['delta'] = list(delta)
            self.kyotaku = 0
            result['scores'] = list(self.scores)
            result['game_over'] = True
            result['ranking'] = sorted(range(4), key=lambda s: (-self.scores[s], s))

    def _check_game_over(self, renchan, is_win):
        if any(s < 0 for s in self.scores):
            return True   # 被飞
        k = self.kyoku
        top = max(self.scores)
        if self.length == 'hanchan':
            if k < 7:
                return False
            if renchan:
                # 南4庄家和了且为首位、达到30000点则结束，否则继续连庄。
                return is_win and self.scores[self.oya] == top and top >= RETURN_POINTS
            return True
        if k >= 4:
            # 东风战南入后有人到30000就结束，最晚南4非连庄结束。
            if top >= RETURN_POINTS:
                return True
            return k == 7 and not renchan
        if k == 3:
            if renchan:
                if is_win and self.scores[self.oya] == top and top >= RETURN_POINTS:
                    return True
                return False
            return top >= RETURN_POINTS
        return False

    def next_round(self, wall=None):
        if self.phase != 'end':
            raise ValueError('这局还没结束')
        if self.game_over:
            raise ValueError('游戏已经结束了')
        if not self.next_renchan:
            self.kyoku += 1
        self.honba = self.next_honba
        self.start_round(wall)

    # ---------- 给 server 的状态 ----------
    def get_state(self, seat=None):
        """seat 给了的话别人的手牌就藏起来（只给张数）"""
        players = []
        for s in range(4):
            p = {
                'seat': s,
                'score': self.scores[s],
                'wind': self.jikaze(s),
                'river': [dict(r) for r in self.rivers[s]],
                'melds': [{'type': m['type'], 'tiles': list(m['tiles']), 'from': m['from'],
                           'called_tile': m.get('called_tile')} for m in self.melds[s]],
                'riichi': self.riichi[s],
            }
            if seat is None or seat == s or self.phase == 'end':
                p['hand'] = list(self.hands[s])
            else:
                p['hand_count'] = len(self.hands[s])
            players.append(p)
        names = ['东', '南']
        return {
            'round': {
                'name': names[self.kyoku // 4 if self.kyoku < 8 else 1] + str(self.oya + 1) + '局',
                'kyoku': self.kyoku,
                'bakaze': self.bakaze,
                'oya': self.oya,
                'honba': self.honba,
                'kyotaku': self.kyotaku,
            },
            'dora': self.dora_list(),
            'dora_indicators': self.dora_indicators(),
            'remaining': self.remaining(),
            'current': self.current,
            'drawn': self.drawn,
            'phase': self.phase,
            'last_discard': self.last_discard,
            'players': players,
            'legal_actions': self.get_legal_actions(seat) if seat is not None else [],
            'result': self.result,
            'game_over': self.game_over,
            'rules': dict(self.rules),
            'length': self.length,
            'events': [dict(e) for e in self.events],
        }


if __name__ == '__main__':
    # 自测：别人的文件还没交上来，先用很简单的假函数顶一下
    from collections import Counter

    def fake_can_hu(hand, melds):
        c = Counter(hand)
        if len(hand) == 14 and len(c) == 7 and all(v == 2 for v in c.values()):
            return True

        def dfs(c):
            ks = sorted([k for k in c if c[k] > 0], key=tile_key)
            if not ks:
                return True
            t = ks[0]
            if c[t] >= 3:
                c[t] -= 3
                if dfs(c):
                    c[t] += 3
                    return True
                c[t] += 3
            if t[1] != 'z' and int(t[0]) <= 7:
                t2 = str(int(t[0]) + 1) + t[1]
                t3 = str(int(t[0]) + 2) + t[1]
                if c[t2] > 0 and c[t3] > 0:
                    c[t] -= 1; c[t2] -= 1; c[t3] -= 1
                    ok = dfs(c)
                    c[t] += 1; c[t2] += 1; c[t3] += 1
                    if ok:
                        return True
            return False

        if len(hand) % 3 != 2:
            return False
        for p in list(c):
            if c[p] >= 2:
                c[p] -= 2
                ok = dfs(c)
                c[p] += 2
                if ok:
                    return True
        return False

    def fake_calc_yaku(hand, melds, win_tile, is_tsumo, bakaze, jikaze, dora, state):
        yaku = []
        if state['riichi']:
            yaku.append('立直')
        if is_tsumo and not melds:
            yaku.append('门前清自摸和')
        c = Counter(norm_list(hand))
        for t in ('5z', '6z', '7z', bakaze, jikaze):
            if c[t] >= 3:
                yaku.append('役牌')
        han = len(yaku)
        if han == 0:
            return [], 0
        d = sum(norm_list(hand).count(x) for x in dora) + sum(1 for x in hand if x[0] == '0')
        if d:
            yaku.append('宝牌%d' % d)
        return yaku, han + d

    def fake_calc_fu(hand, melds, win_tile, is_tsumo, bakaze, jikaze):
        return 30

    def fake_calc_score(fu, han, is_oya, is_tsumo, honba, kyotaku):
        base = min(fu * 2 ** (han + 2), 2000)
        if is_tsumo:
            if is_oya:
                p = -(-base * 2 // 100) * 100 + honba * 100
                return p * 3 + kyotaku * 1000, p
            po = -(-base * 2 // 100) * 100 + honba * 100
            pk = -(-base // 100) * 100 + honba * 100
            return po + pk * 2 + kyotaku * 1000, (po, pk)
        p = -(-base * (6 if is_oya else 4) // 100) * 100 + honba * 300
        return p + kyotaku * 1000, p

    can_hu = fake_can_hu
    calc_yaku = fake_calc_yaku
    calc_fu = fake_calc_fu
    calc_score = fake_calc_score

    # 1. 全电脑打几个半庄，看能不能打完、点数对不对得上
    for seed in range(20):
        g = Game(human_seats=[], seed=seed)
        rounds = 1
        while not g.game_over:
            assert sum(g.scores) + g.kyotaku * 1000 == 100000, (seed, g.scores, g.kyotaku)
            g.next_round()
            rounds += 1
        assert sum(g.scores) == 100000, (seed, g.scores)
        print('seed', seed, '局数', rounds, g.scores, g.result['type'], g.result.get('reason', ''))

    # 2. 人类座位 0，乱按合法操作（能立直就立直、能和就和）
    for seed in range(20):
        g = Game(human_seats=[0], seed=100 + seed)
        rng = random.Random(seed)
        steps = 0
        while not g.game_over:
            if g.phase == 'end':
                g.next_round()
                continue
            acts = g.get_legal_actions(0)
            assert acts, g.get_state(0)
            types = [a['type'] for a in acts]
            if 'tsumo' in types:
                g.do_action(0, 'tsumo')
            elif 'ron' in types:
                g.do_action(0, 'ron')
            elif 'riichi' in types:
                g.do_action(0, 'riichi', tile=acts[types.index('riichi')]['tiles'][0])
            elif 'kan' in types and rng.random() < 0.5:
                g.do_action(0, 'kan', tile=acts[types.index('kan')]['tiles'][0])
            elif 'pon' in types and rng.random() < 0.5:
                g.do_action(0, 'pon')
            elif 'chi' in types and rng.random() < 0.3:
                g.do_action(0, 'chi', tiles=acts[types.index('chi')]['tiles'])
            elif 'discard' in types:
                g.do_action(0, 'discard', tile=rng.choice(acts[types.index('discard')]['tiles']))
            else:
                g.do_action(0, 'pass')
            steps += 1
        assert sum(g.scores) == 100000
        print('human seed', seed, steps, g.scores)

    # 3. 指定牌山：庄家天和
    w = make_wall()
    tenhou_hand = ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '1z', '1z', '1z', '2z']
    rest = list(w)
    for t in tenhou_hand + ['2z']:
        rest.remove(t)
    random.Random(1).shuffle(rest)
    wall = tenhou_hand + rest[:39] + ['2z'] + rest[39:]
    g = Game(human_seats=[0], wall=wall)
    print(g.get_legal_actions(0))
    g.do_action(0, 'tsumo')
    print(g.result['wins'][0]['yaku'], g.result['delta'])
    print('ok')
