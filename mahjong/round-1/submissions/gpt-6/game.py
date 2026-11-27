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
# 座位 0 是起家。手牌始终保留赤五原值；玩家刚摸到的牌放在手牌末尾。

import random
from collections import Counter
from itertools import combinations

from fu import calc_fu_for_shape
from score import calc_score
from tenpai import can_hu, get_waits
from yaku import hand_shapes, normal_tile as norm, parse_hand, scoring_options


START_POINTS = 25000
RETURN_POINTS = 30000   # 南入/结束判断用（天凤：有人到 30000 才结束）

ALL_TILES = [str(n) + s for s in 'mps' for n in range(1, 10)] + [str(n) + 'z' for n in range(1, 8)]
DEFAULT_RULES = {'aka_dora': True, 'kuitan': True, 'kiriage_mangan': False, 'renpu_fu': 4}


def resolve_rules(rules):
    if rules is None:
        return dict(DEFAULT_RULES)
    if not isinstance(rules, dict):
        raise ValueError('rules 必须是对象')
    result = dict(DEFAULT_RULES)
    for key, value in rules.items():
        if key not in DEFAULT_RULES:
            raise ValueError(f'未知规则：{key}')
        if key == 'renpu_fu':
            if type(value) is not int or value not in (2, 4):
                raise ValueError('renpu_fu 必须是 2 或 4')
        elif type(value) is not bool:
            raise ValueError(f'{key} 必须是 true 或 false')
        result[key] = value
    return result


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
    def __init__(self, human_seats=(0,), wall=None, seed=None, *, length='tonpuu', rules=None):
        if length not in ('tonpuu', 'hanchan'):
            raise ValueError('length 必须是 tonpuu 或 hanchan')
        self.rng = random.Random(seed)
        self.human_seats = set(human_seats)
        self.rules = resolve_rules(rules)
        self.length = length
        self.scores = [START_POINTS] * 4
        self.kyoku = 0      # 0~3 = 东1~东4，4~7 = 南入以后的南1~南4（东风战延长）
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
        """给听牌提示用，排除调用者另外提供的手牌和副露。"""
        vis = []
        for s in range(4):
            vis += [r['tile'] for r in self.rivers[s] if not r['called']]
            if s != seat:
                for m in self.melds[s]:
                    vis += m['tiles']
        if self.pending_kan and self.pending_kan[0] != seat:
            _, tile, kind = self.pending_kan
            vis += [tile] * (4 if kind == 'ankan' else 1)
        vis += self.dora_indicators()
        return norm_list(vis)

    # ---------- 一局开始 ----------
    def _prepare_wall(self, wall):
        expected = make_wall(self.rules['aka_dora'])
        if wall is None:
            self.rng.shuffle(expected)
            return expected
        wall = list(wall)
        if len(wall) != 136 or any(not isinstance(t, str) for t in wall):
            raise ValueError('牌山必须是 136 张牌的数组')
        if Counter(wall) != Counter(expected):
            raise ValueError('牌山的牌种或张数与当前赤宝牌规则不符')
        return wall

    def start_round(self, wall=None):
        self._deal_round(self._prepare_wall(wall))

    def _deal_round(self, wall):
        # 固定座位配牌，庄家先摸。王牌依次放宝牌指示牌、里宝牌指示牌、岭上牌。
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
        self.first_turn = [True] * 4      # 还没打过第一张牌（用于天和地和双立直九种九牌）
        self.no_call_yet = True           # 到现在还没有人鸣牌（暗杠也算）
        self.temp_furiten = [False] * 4   # 同巡振听
        self.riichi_furiten = [False] * 4  # 立直后见逃
        self.riichi_pending = None        # 刚宣言立直，需等待荣和裁定
        self.kan_seats = []               # 谁杠过（四杠散了用）

        self.current = self.oya
        self.drawn = None
        self.is_rinshan_draw = False
        self.after_call = False
        self.kuikae = []
        self.last_discard = None
        self.last_discard_houtei = False
        self.pending_kan = None
        self.call_options = {}
        self.responses = {}
        self.events = []
        self.result = None
        self.phase = 'discard'

        self._draw(self.oya)
        self._run()

    # ---------- 摸牌打牌 ----------
    def _draw(self, seat, rinshan=False):
        if rinshan:
            t = self.dead_wall[10 + self.rinshan_used]
            self.rinshan_used += 1
            self.wall_end -= 1   # 王牌要保持 14 张，海底往前挪一张
        else:
            t = self.wall[self.wall_pos]
            self.wall_pos += 1
        self.hands[seat].append(t)   # 摸的牌放最后，打完再排序
        self.drawn = t
        self.current = seat
        self.is_rinshan_draw = rinshan
        self.after_call = False
        self.kuikae = []
        self.temp_furiten[seat] = False
        self.phase = 'discard'
        self.events.append({'type': 'draw', 'seat': seat, 'tile': t})

    def _discard(self, seat, tile, riichi=False, tsumogiri=None):
        hand = self.hands[seat]
        if tsumogiri is None:
            tsumogiri = tile == self.drawn
        if tsumogiri:
            if self.drawn != tile:
                raise ValueError('摸切必须打出刚摸到的牌')
            hand.pop()
        else:
            concealed = hand[:-1] if self.drawn is not None else hand
            if self.riichi[seat] or tile not in concealed:
                raise ValueError('不能从手牌打这张')
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
            self.scores[seat] -= 1000
            self.kyotaku += 1
            self.events.append({'type': 'riichi', 'seat': seat})
        self.first_turn[seat] = False
        self.rivers[seat].append({'tile': tile, 'riichi': riichi, 'called': False, 'tsumogiri': tsumogiri})
        self.events.append({'type': 'discard', 'seat': seat, 'tile': tile, 'tsumogiri': tsumogiri})
        last = self.remaining() == 0
        self.last_discard_houtei = last and not self.is_rinshan_draw
        self.drawn = None
        self.is_rinshan_draw = False
        self.last_discard = (seat, tile)

        # 别人能不能和/碰/杠/吃
        self.call_options = {}
        self.responses = {}
        for i in (1, 2, 3):
            s = (seat + i) % 4
            opts = []
            if self._can_ron(s, tile):
                opts.append({'type': 'ron', 'tile': tile})
            if not self.riichi[s] and not last and not self._four_kans():
                same = [t for t in self.hands[s] if norm(t) == norm(tile)]
                for combo in sorted(set(combinations(same, 2)), key=lambda c: tuple(map(tile_key, c))):
                    if self._can_discard_after_call(s, tile, 'pon', combo):
                        opts.append({'type': 'pon', 'tiles': list(combo)})
                if len(same) >= 3 and self.rinshan_used < 4:
                    opts.append({'type': 'kan', 'kind': 'minkan', 'tiles': same[:3]})
                if i == 1 and tile[1] != 'z':
                    for combo in self._chi_combos(s, tile):
                        if self._can_discard_after_call(s, tile, 'chi', combo):
                            opts.append({'type': 'chi', 'tiles': combo})
            if opts:
                self.call_options[s] = opts
        self.phase = 'call'

    def _can_discard_after_call(self, seat, tile, kind, own):
        hand = list(self.hands[seat])
        for t in own:
            hand.remove(t)
        forbidden = self._kuikae_tiles(tile, kind, own)
        return any(norm(t) not in forbidden for t in hand)

    def _kuikae_tiles(self, tile, kind, own):
        forbidden = {norm(tile)}
        if kind == 'chi':
            n = int(norm(tile)[0])
            a, b = sorted(int(norm(t)[0]) for t in own)
            if n < a and b < 9:
                forbidden.add(str(b + 1) + tile[1])
            elif n > b and a > 1:
                forbidden.add(str(a - 1) + tile[1])
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
                        combos.append([x, y])
        return combos

    # ---------- 和牌判断 ----------
    def _is_tenpai(self, hand13, melds_n):
        return bool(self._waits(hand13, melds_n))

    def _waits(self, hand13, melds_n):
        return set(get_waits(hand13, melds_n))

    def _is_furiten(self, seat):
        if self.temp_furiten[seat] or self.riichi_furiten[seat]:
            return True
        h = self.hands[seat]
        if seat == self.current and self.drawn is not None:
            h = h[:-1]
        mn = self.melds_plain(seat, True)
        # 舍张振听：自己牌河里（包括被别人鸣走的）有能和的牌
        for t in set(norm(r['tile']) for r in self.rivers[seat]):
            if can_hu(h + [t], mn):
                return True
        return False

    def _make_yaku_state(self, seat, is_tsumo, chankan):
        last = self.remaining() == 0
        return {
            'riichi': self.riichi[seat],
            'ippatsu': self.ippatsu[seat],
            'haitei': is_tsumo and last and not self.is_rinshan_draw,
            'houtei': not is_tsumo and not chankan and self.last_discard_houtei,
            'rinshan': is_tsumo and self.is_rinshan_draw,
            'chankan': chankan,
            'double_riichi': self.double_riichi[seat],
            'tenhou': is_tsumo and seat == self.oya and self.first_turn[seat] and self.no_call_yet,
            'chiihou': is_tsumo and seat != self.oya and self.first_turn[seat] and self.no_call_yet,
            'ankan_indices': [i for i, m in enumerate(self.melds[seat]) if m['type'] == 'ankan'],
            'kuitan': self.rules['kuitan'],
            'aka_dora': self.rules['aka_dora'],
        }

    def _agari_options(self, seat, hand14, win_tile, is_tsumo, chankan=False, include_dora=False):
        state = self._make_yaku_state(seat, is_tsumo, chankan)
        if include_dora and self.riichi[seat]:
            state['ura_dora'] = [dora_from_indicator(t) for t in self.ura_indicators()]
        return scoring_options(hand14, self.melds_plain(seat), win_tile, is_tsumo, self.bakaze,
                               self.jikaze(seat), self.dora_list() if include_dora else (), state)

    def _win_ok(self, seat, hand14, win_tile, is_tsumo, chankan=False, orphans_only=False):
        if not can_hu(hand14, self.melds_plain(seat)):
            return False
        options = self._agari_options(seat, hand14, win_tile, is_tsumo, chankan)
        return any(not orphans_only or option.shape.kind == 'thirteen_orphans' for option in options)

    def _can_ron(self, seat, tile, chankan=False, orphans_only=False):
        return (self._win_ok(seat, self.hands[seat] + [tile], tile, False, chankan, orphans_only)
                and not self._is_furiten(seat))

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
        """立直后的四张只能由原有暗刻加上自摸牌组成，且保持原听牌。"""
        hand = self.hands[seat][:-1]
        mn = self.melds_plain(seat, True)
        before = self._waits(hand, mn)
        h2 = [x for x in self.hands[seat] if norm(x) != t]
        after = self._waits(h2, mn + [[t] * 4])
        if not before or before != after:
            return False
        for tile in before:
            _, counts, groups, win_tile = parse_hand(hand, mn, tile)
            if any(('triplet', t, False) not in shape.groups
                   for shape in hand_shapes(counts, groups, win_tile)):
                return False
        return True

    # ---------- 玩家操作 ----------
    def do_action(self, seat, action, tile=None, tiles=None, tsumogiri=None):
        """执行摸打或应答。tile 指打牌或杠的牌种，tiles 指吃碰用的两张。"""
        if self.phase == 'end':
            raise ValueError('这局已经结束了')
        legal = [a for a in self.get_legal_actions(seat)
                 if a['type'] == action or a.get('kind') == action]
        if not legal:
            raise ValueError(f'现在不能 {action}')
        kind = legal[0]['type']

        if self.phase == 'discard':
            if kind in ('discard', 'riichi'):
                if tile not in legal[0]['tiles']:
                    raise ValueError('不能打这张')
                self._discard(seat, tile, riichi=(kind == 'riichi'), tsumogiri=tsumogiri)
            elif kind == 'tsumo':
                self._win_tsumo(seat)
            elif kind == 'kan':
                kan = next((a for a in legal if tile is None or norm(tile) == a['tiles'][0]), None)
                if kan is None:
                    raise ValueError('不能杠这张')
                self._declare_kan(seat, kan['tiles'][0], kan['kind'])
            elif kind == 'kyuushu':
                self._abort('九种九牌')
        else:
            pick = legal[0]
            if kind in ('chi', 'pon', 'kan') and tiles is not None:
                pick = next((a for a in legal if sorted(a['tiles']) == sorted(tiles)), None)
                if pick is None:
                    raise ValueError('没有这个鸣牌选项')
            self.responses[seat] = pick
        self._run()

    # ---------- 电脑 ----------
    def _cpu_turn(self, seat):
        if self._win_ok(seat, self.hands[seat], self.drawn, True):
            self._win_tsumo(seat)
        else:
            self._discard(seat, self.drawn, tsumogiri=True)

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
        kan = self.pending_kan
        source, tile = kan[:2] if kan else self.last_discard
        order = [(source + i) % 4 for i in (1, 2, 3)]
        resp = self.responses
        rons = [s for s in order if resp.get(s, {}).get('type') == 'ron']

        # 能荣和没荣和 -> 同巡振听，立直了就一直振听
        for s, opts in self.call_options.items():
            if any(o['type'] == 'ron' for o in opts) and s not in rons:
                self.temp_furiten[s] = True
                if self.riichi[s]:
                    self.riichi_furiten[s] = True

        if rons:
            self._cancel_riichi()
            if len(rons) == 3:
                self._abort('三家和')
            else:
                if kan:
                    self.hands[source].remove(tile)
                    self.hands[source].sort(key=tile_key)
                    self.drawn = None
                self._win_ron(rons, source, tile, chankan=kan is not None)
            return
        if kan:
            self._complete_kan(source, norm(tile), kan[2])
            return

        if self.riichi_pending is not None:
            self.riichi_pending = None
            if all(self.riichi):
                self._abort('四家立直')
                return
        if self._four_kans():
            self._abort('四杠散了')
            return

        # 碰/杠优先于吃
        for s in order:
            r = resp.get(s, {})
            if r.get('type') in ('pon', 'kan'):
                self._call_meld(s, source, tile, r.get('kind', r['type']), r['tiles'])
                return
        for s in order:
            r = resp.get(s, {})
            if r.get('type') == 'chi':
                self._call_meld(s, source, tile, 'chi', r['tiles'])
                return
        self._after_discard_pass()

    def _cancel_riichi(self):
        """宣言牌被荣和，返还本次声明挂起的立直棒。"""
        if self.riichi_pending is not None:
            s = self.riichi_pending
            self.scores[s] += 1000
            self.kyotaku -= 1
            self.riichi[s] = self.double_riichi[s] = self.ippatsu[s] = False
            self.riichi_pending = None

    def _four_kans(self):
        return len(self.kan_seats) == 4 and len(set(self.kan_seats)) > 1

    def _after_discard_pass(self):
        discarder, _ = self.last_discard
        # 四风连打
        if self.no_call_yet and all(len(r) == 1 for r in self.rivers):
            first = [norm(r[0]['tile']) for r in self.rivers]
            if first[0] in ('1z', '2z', '3z', '4z') and len(set(first)) == 1:
                self._abort('四风连打')
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
        tiles = sorted(own + [tile], key=tile_key)
        self.melds[seat].append({'type': kind, 'tiles': tiles, 'from': discarder, 'called_tile': tile})
        self.events.append({'type': kind, 'seat': seat, 'tiles': tiles, 'from': discarder})
        if kind == 'minkan':
            self._after_kan(seat)
            return
        self.current = seat
        self.drawn = None
        self.after_call = True
        self.phase = 'discard'
        self.kuikae = self._kuikae_tiles(tile, kind, own)

    def _declare_kan(self, seat, t, kind):
        """加杠可抢和，暗杠仅允许国士无双抢和。杠成立后才翻宝牌。"""
        tile = next(x for x in self.hands[seat] if norm(x) == t)
        self.pending_kan = (seat, tile, kind)
        self.events.append({'type': kind, 'seat': seat, 'tile': t})
        self.phase = 'call'
        self.responses = {}
        self.call_options = {}
        if kind == 'kakan' or is_yaochu(t):
            for other in range(4):
                if other != seat and self._can_ron(other, tile, chankan=True, orphans_only=kind == 'ankan'):
                    self.call_options[other] = [{'type': 'ron', 'tile': tile}]

    def _complete_kan(self, seat, t, kind):
        self._interrupt()
        self.pending_kan = None
        hand = self.hands[seat]
        own = [tile for tile in hand if norm(tile) == t]
        for tile in own:
            hand.remove(tile)
        hand.sort(key=tile_key)
        if kind == 'ankan':
            self.melds[seat].append({'type': kind, 'tiles': sorted(own, key=tile_key),
                                     'from': None, 'called_tile': None})
        else:
            meld = next(m for m in self.melds[seat] if m['type'] == 'pon' and norm(m['tiles'][0]) == t)
            meld['type'] = kind
            meld['tiles'] = meld['tiles'] + own
        self._after_kan(seat)

    def _after_kan(self, seat):
        self.dora_count += 1
        self.events.append({'type': 'dora', 'tile': self.dora_indicators()[-1]})
        self.kan_seats.append(seat)
        self._draw(seat, rinshan=True)

    # ---------- 和牌结算 ----------
    def _score_one(self, seat, hand14, win_tile, is_tsumo, from_seat, honba, kyotaku, chankan=False):
        is_oya = seat == self.oya
        best = None
        best_key = None
        for option in self._agari_options(seat, hand14, win_tile, is_tsumo, chankan, include_dora=True):
            fu = 0 if option.yakuman else calc_fu_for_shape(
                option.shape, win_tile, is_tsumo, self.bakaze, self.jikaze(seat), self.rules['renpu_fu'])
            res = calc_score(fu, option.han, is_oya, is_tsumo, honba, kyotaku,
                             kiriage_mangan=self.rules['kiriage_mangan'], yakuman=option.yakuman)
            key = (res['get'], option.yakuman, option.han, fu)
            if best_key is None or key > best_key:
                best = (option, fu, res)
                best_key = key

        if best is None:
            raise RuntimeError('没有可结算的和牌拆法')
        option, fu, res = best
        delta = [0] * 4
        delta[seat] = res['get']
        if is_tsumo:
            for s in range(4):
                if s != seat:
                    delta[s] -= res['oya_pay'] if s == self.oya else res['ko_pay']
        else:
            delta[from_seat] = -res['ron_pay']
        info = {
            'seat': seat, 'from': from_seat, 'tile': win_tile, 'tsumo': is_tsumo,
            'hand': sorted(hand14, key=tile_key), 'melds': self._meld_state(seat),
            'yaku': [{'name': name, 'han': han} for name, han in option.entries],
            'han': option.han, 'fu': fu, 'yakuman': option.yakuman, 'delta': delta,
            'points': res['get'] - 300 * honba - 1000 * kyotaku,
        }
        return info, delta

    def _win_tsumo(self, seat):
        info, delta = self._score_one(seat, self.hands[seat], self.drawn, True, None,
                                      self.honba, self.kyotaku)
        self.kyotaku = 0
        result = {'type': 'tsumo', 'wins': [info],
                  'dora_indicators': self.dora_indicators(),
                  'ura_indicators': self.ura_indicators() if self.riichi[seat] else []}
        self.events.append({'type': 'tsumo', 'seat': seat})
        self._end_round(result, delta, seat == self.oya, True)

    def _win_ron(self, winners, discarder, tile, chankan=False):
        # 双响的本场和立直棒给顺位上离放铳者最近的和家。
        total = [0] * 4
        wins = []
        for i, s in enumerate(winners):
            hb = self.honba if i == 0 else 0
            kt = self.kyotaku if i == 0 else 0
            info, delta = self._score_one(s, self.hands[s] + [tile], tile, False, discarder, hb, kt,
                                          chankan=chankan)
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
        self.events.append({'type': 'ryuukyoku', 'reason': '荒牌流局'})
        self._end_round(result, delta, tenpai[self.oya], False, draw=True)

    def _abort(self, reason):
        # 途中流局：天凤是庄家连庄、本场+1，立直棒留着
        result = {'type': 'abort', 'reason': reason}
        self.events.append({'type': 'ryuukyoku', 'reason': reason})
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
        if self.drawn is not None:
            self.hands[self.current].sort(key=tile_key)
            self.drawn = None
        self.pending_kan = None
        self.call_options = {}
        self.responses = {}
        self.next_renchan = renchan
        # 连庄或者流局本场 +1，闲家和了本场清零
        self.next_honba = self.honba + 1 if (renchan or draw) else 0
        self.game_over = self._check_game_over(renchan, is_win)
        if self.game_over:
            # 剩下的立直棒给第一名（天凤）；同分按起家顺序
            top = max(range(4), key=lambda s: (self.scores[s], -s))
            award = self.kyotaku * 1000
            self.scores[top] += award
            delta[top] += award
            self.kyotaku = 0
            result['scores'] = list(self.scores)
            result['game_over'] = True
            result['ranking'] = sorted(range(4), key=lambda s: (-self.scores[s], s))

    def _check_game_over(self, renchan, is_win):
        if any(s < 0 for s in self.scores):
            return True   # 被飞
        k = self.kyoku
        first = max(range(4), key=lambda s: (self.scores[s], -s))
        target_reached = self.scores[first] >= RETURN_POINTS
        last_scheduled = 3 if self.length == 'tonpuu' else 7
        if k < last_scheduled:
            return False
        if k > last_scheduled:  # 东风战南入
            return target_reached or (k == 7 and not renchan)
        if renchan:
            return is_win and first == self.oya and target_reached
        return self.length == 'hanchan' or target_reached

    def next_round(self, wall=None):
        if self.phase != 'end':
            raise ValueError('这局还没结束')
        if self.game_over:
            raise ValueError('游戏已经结束了')
        wall = self._prepare_wall(wall)
        if not self.next_renchan:
            self.kyoku += 1
        self.honba = self.next_honba
        self._deal_round(wall)

    # ---------- 给 server 的状态 ----------
    def _meld_state(self, seat):
        return [dict(m, tiles=list(m['tiles'])) for m in self.melds[seat]]

    def get_state(self, seat=None):
        """seat 给了的话别人的手牌就藏起来（只给张数）"""
        players = []
        for s in range(4):
            hand = self.hands[s]
            if s == self.current and self.drawn is not None:
                hand = hand[:-1]
            p = {
                'seat': s,
                'score': self.scores[s],
                'wind': self.jikaze(s),
                'river': [dict(r) for r in self.rivers[s]],
                'melds': self._meld_state(s),
                'riichi': self.riichi[s],
                'hand_count': len(hand),
            }
            if seat is None or seat == s:
                p['hand'] = list(hand)
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
            'drawn': self.drawn if seat is None or seat == self.current else None,
            'phase': self.phase,
            'last_discard': self.last_discard,
            'players': players,
            'legal_actions': self.get_legal_actions(seat) if seat is not None else [],
            'result': self.result,
            'game_over': self.game_over,
        }

