# 学号 250207
# game.py —— 整局流程：洗牌发牌、摸打、吃碰杠、立直、流局、连庄换庄、本场、电脑玩家
#
# 本文件由指导老师整合后修复。对外接口保持原样，另外增加：
#   Game(..., rules=None, length='tonpuu')
#   do_action(..., tsumogiri=None)
# 牌山顺序严格按 frontend/接口说明.md：
#   wall[0:13] 座位0配牌，[13:26] 座位1，[26:39] 座位2，[39:52] 座位3
#   wall[52] 起庄家第一摸，之后按顺序摸到 wall[121]
#   wall[122:127] 宝牌指示牌，[127:132] 里宝牌指示牌，[132:136] 岭上牌

import random

from fu import calc_fu
from yaku import calc_yaku, is_yakuman_names
from score import calc_score
from tenpai import can_hu


START_POINTS = 25000
ALL_TILES = [str(n) + s for s in 'mps' for n in range(1, 10)] + [str(n) + 'z' for n in range(1, 8)]

DEFAULT_RULES = {
    'aka_dora': True,
    'kuitan': True,
    'kiriage_mangan': False,
    'renpu_fu': 4,
}


def norm(t):
    """红五 0m -> 5m"""
    if t and t[0] == '0':
        return '5' + t[1]
    return t


def norm_list(tiles):
    return [norm(t) for t in tiles]


def tile_key(t):
    n = 5 if t[0] == '0' else int(t[0])
    return ('mpsz'.index(t[1]), n, t[0] == '0')


def normalize_rules(rules):
    r = dict(DEFAULT_RULES)
    if rules:
        if not isinstance(rules, dict):
            raise ValueError('rules 必须是对象')
        for k in ('aka_dora', 'kuitan', 'kiriage_mangan'):
            if k in rules:
                if not isinstance(rules[k], bool):
                    raise ValueError('rules.%s 必须是 true/false' % k)
                r[k] = rules[k]
        if 'renpu_fu' in rules:
            if rules['renpu_fu'] not in (2, 4):
                raise ValueError('rules.renpu_fu 必须是 2 或 4')
            r['renpu_fu'] = rules['renpu_fu']
    return r


def make_wall(aka_dora=True):
    wall = []
    for s in 'mps':
        for n in range(1, 10):
            for k in range(4):
                if n == 5 and k == 0 and aka_dora:
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
    def __init__(self, human_seats=(0,), wall=None, seed=None, rules=None, length='tonpuu'):
        if length not in ('tonpuu', 'hanchan'):
            raise ValueError("length 只能是 'tonpuu' 或 'hanchan'")
        self.length = length
        self.rules = normalize_rules(rules)
        self.rng = random.Random(seed)
        self.human_seats = set(human_seats)
        self.scores = [START_POINTS] * 4
        self.kyoku = 0      # 0~3 东1~东4，4~7 南1~南4
        self.honba = 0
        self.kyotaku = 0    # 场上的立直棒（根数）
        self.game_over = False
        self.result = None
        self.next_renchan = False
        self.next_honba = 0
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
        """牌山还能正常摸几张（不算王牌）"""
        return max(0, self.wall_end - self.wall_pos)

    def melds_plain(self, seat, normalize=False):
        res = []
        for m in self.melds[seat]:
            res.append(norm_list(m['tiles']) if normalize else list(m['tiles']))
        return res

    def ankan_indices(self, seat):
        return [i for i, m in enumerate(self.melds[seat]) if m['type'] == 'ankan']

    def ankan_lists(self, seat, normalize=True):
        out = []
        for m in self.melds[seat]:
            if m['type'] == 'ankan':
                out.append(norm_list(m['tiles']) if normalize else list(m['tiles']))
        return out

    def is_menzen(self, seat):
        return all(m['type'] == 'ankan' for m in self.melds[seat])

    def dora_indicators(self):
        return [self.dead_wall[i] for i in range(min(self.dora_count, 5))]

    def ura_indicators(self):
        return [self.dead_wall[5 + i] for i in range(min(self.dora_count, 5))]

    def dora_list(self):
        return [dora_from_indicator(t) for t in self.dora_indicators()]

    def ura_dora_list(self):
        return [dora_from_indicator(t) for t in self.ura_indicators()]

    def get_visible(self, seat):
        """听牌提示用：未被人鸣走的牌河、别人的明副露、宝牌指示牌。
        自己的副露由 tenpai 自己扣；被鸣走的牌已经在副露里，不能再从牌河扣一次；
        别人的暗杠是盖着的，不算“看得到”。
        """
        vis = []
        for s in range(4):
            vis += [r['tile'] for r in self.rivers[s] if not r.get('called')]
            if s != seat:
                for m in self.melds[s]:
                    if m['type'] != 'ankan':
                        vis += m['tiles']
        vis += self.dora_indicators()
        return norm_list(vis)

    def _event(self, typ, **kw):
        e = {'type': typ}
        e.update(kw)
        self.events.append(e)

    # ---------- 一局开始 ----------
    def start_round(self, wall=None):
        if wall is None:
            wall = make_wall(self.rules['aka_dora'])
            self.rng.shuffle(wall)
        else:
            wall = list(wall)
            if len(wall) != 136:
                raise ValueError('牌山要 136 张')
            bad = [t for t in wall if t not in ALL_TILES and t not in ('0m', '0p', '0s')]
            if bad:
                raise ValueError('牌山里有不认识的牌：%s' % bad[0])

        self.wall = wall
        self.dead_wall = wall[122:136]
        self.wall_pos = 52
        self.wall_end = 122
        self.rinshan_used = 0
        self.dora_count = 1

        self.hands = [[] for _ in range(4)]
        # 配牌按物理座位，不是从庄家开始
        for s in range(4):
            self.hands[s] = sorted(wall[13 * s:13 * s + 13], key=tile_key)
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
        self.chankan_pending = None
        self.kan_seats = []

        self.current = self.oya
        self.drawn = None
        self.is_rinshan_draw = False
        self.after_call = False
        self.kuikae = []
        self.last_discard = None
        self.call_options = {}
        self.responses = {}
        self.result = None
        self.phase = 'discard'
        self.events = []

        self._draw(self.oya)
        self._run()

    # ---------- 摸牌打牌 ----------
    def _draw(self, seat, rinshan=False):
        if rinshan:
            if self.rinshan_used >= 4:
                raise ValueError('岭上牌已经摸完')
            t = self.dead_wall[10 + self.rinshan_used]
            self.rinshan_used += 1
            self.wall_end -= 1   # 每开一次杠，正常摸牌的最后一张少一张
        else:
            if self.wall_pos >= self.wall_end:
                raise ValueError('牌山已经摸完')
            t = self.wall[self.wall_pos]
            self.wall_pos += 1
        self.hands[seat].append(t)   # 摸的牌放最后，打完再排序
        self.drawn = t
        self.current = seat
        self.is_rinshan_draw = rinshan
        self.after_call = False
        self.kuikae = []
        self.phase = 'discard'
        self.temp_furiten[seat] = False
        self._event('draw', seat=seat, tile=t)

    def _discard(self, seat, tile, riichi=False, tsumogiri=None):
        hand = self.hands[seat]
        drawn = self.drawn
        if tsumogiri is None:
            tsumogiri = drawn is not None and tile == drawn
        hand.remove(tile)
        hand.sort(key=tile_key)
        if riichi:
            self.riichi[seat] = True
            self.ippatsu[seat] = True
            if self.first_turn[seat] and self.no_call_yet:
                self.double_riichi[seat] = True
            self.riichi_pending = seat
            self._event('riichi', seat=seat)
        elif self.riichi[seat]:
            self.ippatsu[seat] = False    # 立直后自己又打了一张，一发没了
        self.first_turn[seat] = False
        self.rivers[seat].append({
            'tile': tile, 'riichi': riichi, 'called': False,
            'tsumogiri': bool(tsumogiri),
        })
        self._event('discard', seat=seat, tile=tile, tsumogiri=bool(tsumogiri))
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
                    for pair in self._pon_options(same):
                        if self._can_discard_after_call(s, 'pon', pair, tile):
                            opts.append({'type': 'pon', 'tiles': pair})
                if len(same) >= 3 and self.rinshan_used < 4:
                    opts.append({'type': 'kan', 'tiles': same[:3]})
                if i == 1 and tile[1] != 'z':
                    for combo in self._chi_combos(s, tile):
                        if self._can_discard_after_call(s, 'chi', combo, tile):
                            opts.append({'type': 'chi', 'tiles': combo})
            if opts:
                self.call_options[s] = opts
        self.phase = 'call'

    def _pon_options(self, same):
        out = []
        seen = set()
        for i in range(len(same)):
            for j in range(i + 1, len(same)):
                pair = sorted([same[i], same[j]], key=tile_key)
                key = tuple(pair)
                if key not in seen:
                    seen.add(key)
                    out.append(pair)
        return out

    def _chi_combos(self, seat, tile):
        n = int(norm(tile)[0])
        s = tile[1]
        hand = self.hands[seat]
        combos = []
        seen = set()
        for a, b in ((n - 2, n - 1), (n - 1, n + 1), (n + 1, n + 2)):
            if a < 1 or b > 9:
                continue
            ta = sorted(set(t for t in hand if norm(t) == str(a) + s), key=tile_key)
            tb = sorted(set(t for t in hand if norm(t) == str(b) + s), key=tile_key)
            for x in ta:
                for y in tb:
                    key = tuple(sorted([x, y], key=tile_key))
                    if key not in seen:
                        seen.add(key)
                        combos.append([x, y])
        return combos

    def _kuikae_set(self, kind, own, tile):
        """吃/碰后不能马上打的牌种（食替）。"""
        forbidden = {norm(tile)}
        if kind == 'chi':
            n = int(norm(tile)[0])
            a, b = sorted(int(norm(t)[0]) for t in own)
            if n < a and b + 1 <= 9:
                forbidden.add(str(b + 1) + tile[1])
            elif n > b and a - 1 >= 1:
                forbidden.add(str(a - 1) + tile[1])
        return forbidden

    def _can_discard_after_call(self, seat, kind, own, tile):
        """吃了/碰了以后手里至少要留一张能打的牌，否则这个鸣牌不应该给。"""
        hand = list(self.hands[seat])
        try:
            for t in own:
                hand.remove(t)
        except ValueError:
            return False
        if not hand:
            return False
        forbidden = self._kuikae_set(kind, own, tile)
        return any(norm(t) not in forbidden for t in hand)

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
        hand = list(self.hands[seat])
        # 14 张时（刚摸牌）要拿掉摸的那张再判断
        if len(hand) + 3 * len(self.melds[seat]) == 14 and self.drawn in hand:
            hand.remove(self.drawn)
        h = norm_list(hand)
        mn = self.melds_plain(seat, True)
        for t in set(norm(r['tile']) for r in self.rivers[seat]):
            if can_hu(h + [t], mn):
                return True
        return False

    def _make_state(self, seat, is_tsumo, chankan=False):
        last = self.remaining() == 0
        return {
            'riichi': self.riichi[seat],
            'ippatsu': self.ippatsu[seat],
            'haitei': is_tsumo and last and not self.is_rinshan_draw,
            'houtei': (not is_tsumo) and last,
            'rinshan': is_tsumo and self.is_rinshan_draw,
            'chankan': (not is_tsumo) and chankan,
            'double_riichi': self.double_riichi[seat],
            'tenhou': is_tsumo and seat == self.oya and self.first_turn[seat] and self.no_call_yet,
            'chihou': is_tsumo and seat != self.oya and self.first_turn[seat] and self.no_call_yet,
            'ankan_indices': self.ankan_indices(seat),
            'ura_dora': self.ura_dora_list() if self.riichi[seat] else [],
        }

    def _win_ok(self, seat, hand14, win_tile, is_tsumo, chankan=False):
        """形能和 + 有役。算役时不传宝牌，避免只有宝牌没役也能和。"""
        hn = norm_list(hand14)
        mn = self.melds_plain(seat, True)
        if not can_hu(hn, mn):
            return False
        state = self._make_state(seat, is_tsumo, chankan=chankan)
        yaku, han = calc_yaku(hn, mn, norm(win_tile), is_tsumo, self.bakaze,
                              self.jikaze(seat), [], state, rules=self.rules)
        return han > 0

    def _can_ron(self, seat, tile, chankan=False):
        if self._is_furiten(seat):
            return False
        return self._win_ok(seat, self.hands[seat] + [tile], tile, False,
                            chankan=chankan)

    # ---------- 合法操作 ----------
    def get_legal_actions(self, seat):
        if self.phase == 'end':
            return []
        if self.phase == 'discard' and seat == self.current:
            return self._turn_actions(seat)
        if self.phase == 'call' and seat in self.call_options and seat not in self.responses:
            return self.call_options[seat] + [{'type': 'pass'}]
        return []

    def _turn_actions(self, seat):
        acts = []
        hand = self.hands[seat]
        if self.riichi[seat]:
            discards = [self.drawn] if self.drawn is not None else []
        else:
            discards = sorted(set(hand), key=tile_key)
            if self.after_call and self.kuikae:
                filtered = [t for t in discards if norm(t) not in self.kuikae]
                if filtered:
                    discards = filtered
        acts.append({'type': 'discard', 'tiles': discards})
        if self.after_call:
            return acts

        if self.drawn is not None and self._win_ok(seat, hand, self.drawn, True):
            acts.append({'type': 'tsumo'})

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
                        if not self._riichi_ankan_ok(seat, t):
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
        """立直后暗杠：杠了以后听的牌不变才行（只看听牌种类）"""
        hand = list(self.hands[seat])
        if self.drawn in hand:
            hand.remove(self.drawn)
        mn = self.melds_plain(seat, True)
        before = self._waits(hand, mn)
        h2 = [x for x in self.hands[seat] if norm(x) != t]
        after = self._waits(h2, mn + [[t] * 4])
        return before == after and len(before) > 0

    # ---------- 玩家操作 ----------
    def do_action(self, seat, action, tile=None, tiles=None, tsumogiri=None):
        """action: discard / riichi / tsumo / ron / chi / pon / kan / pass / kyuushu"""
        if self.phase == 'end':
            raise ValueError('这局已经结束了')
        legal = self.get_legal_actions(seat)
        types = [a['type'] for a in legal]
        if action not in types:
            raise ValueError('现在不能 %s' % action)

        if self.phase == 'discard':
            if action in ('discard', 'riichi'):
                ok = [a for a in legal if a['type'] == action][0]['tiles']
                if tile not in ok:
                    raise ValueError('不能打这张')
                self._discard(seat, tile, riichi=(action == 'riichi'), tsumogiri=tsumogiri)
            elif action == 'tsumo':
                self._win_tsumo(seat)
            elif action == 'kan':
                kan = None
                for a in legal:
                    if a['type'] == 'kan' and (tile is None or norm(tile) == a['tiles'][0]):
                        kan = a
                        break
                if kan is None:
                    if tile is None:
                        kan = [a for a in legal if a['type'] == 'kan'][0]
                    else:
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
                elif tile is not None:
                    for a in cand:
                        if a['tiles'] and norm(a['tiles'][0]) == norm(tile):
                            pick = a
                            break
                    else:
                        raise ValueError('不能杠这张')
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
            self._discard(seat, acts[0]['tiles'][-1])

    def _cpu_response(self, seat):
        for o in self.call_options.get(seat, []):
            if o['type'] == 'ron':
                return o
        return {'type': 'pass'}

    def _run(self):
        """电脑能自己动的都让它动完，轮到人或者一局结束就停"""
        guard = 0
        while self.phase != 'end':
            guard += 1
            if guard > 10000:
                raise RuntimeError('对局流程死循环')
            if self.phase == 'discard':
                if self.current in self.human_seats and self.get_legal_actions(self.current):
                    return
                self._cpu_turn(self.current)
            elif self.phase == 'call':
                for s in list(self.call_options):
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

        # 加杠抢杠：只有荣和，没有碰/吃；没人抢就继续加杠
        if self.chankan_pending is not None:
            kseat, ktile = self.chankan_pending
            if len(rons) >= 3:
                self.chankan_pending = None
                self._abort('三家和')
                return
            if rons:
                self.chankan_pending = None
                if ktile in self.hands[kseat]:
                    self.hands[kseat].remove(ktile)
                    self.hands[kseat].sort(key=tile_key)
                self._win_ron(rons, kseat, ktile, chankan=True)
            else:
                self._complete_kakan(kseat, ktile)
            return

        if len(rons) >= 3:
            self._cancel_riichi_on_ron(discarder)
            self._abort('三家和')
            return
        if rons:
            self._win_ron(rons, discarder, tile)
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
            self.melds[seat].append({
                'type': 'minkan', 'tiles': own + [tile], 'from': discarder,
                'called_tile': tile,
            })
            self._event('minkan', seat=seat, tiles=own + [tile], **{'from': discarder})
            self._after_kan(seat)
            return
        self.melds[seat].append({
            'type': kind, 'tiles': sorted(own + [tile], key=tile_key),
            'from': discarder, 'called_tile': tile,
        })
        self._event(kind, seat=seat, tiles=own + [tile], **{'from': discarder})
        self.current = seat
        self.drawn = None
        self.after_call = True
        self.phase = 'discard'
        # 食替：碰的那张、吃的那张和它筋上另一头都不能马上打
        self.kuikae = list(self._kuikae_set(kind, own, tile))

    def _ankan(self, seat, t):
        self._interrupt()
        own = [x for x in self.hands[seat] if norm(x) == t]
        for x in own:
            self.hands[seat].remove(x)
        self.hands[seat].sort(key=tile_key)
        self.melds[seat].append({
            'type': 'ankan', 'tiles': own, 'from': None, 'called_tile': None,
        })
        self._event('ankan', seat=seat, tile=t)
        self._after_kan(seat)

    def _kakan(self, seat, t):
        # 加杠先问抢杠：别人能和这张牌就先让他和，杠不成立、不翻杠宝牌。
        self._interrupt()
        x = [y for y in self.hands[seat] if norm(y) == t][0]
        self.chankan_pending = (seat, x)
        self.last_discard = (seat, x)
        self.call_options = {}
        self.responses = {}
        for i in (1, 2, 3):
            s = (seat + i) % 4
            if self._can_ron(s, x, chankan=True):
                self.call_options[s] = [{'type': 'ron', 'tile': x}]
        if self.call_options:
            self.phase = 'call'
            return
        self._complete_kakan(seat, x)

    def _complete_kakan(self, seat, x):
        self.chankan_pending = None
        self.call_options = {}
        self.responses = {}
        self.last_discard = None
        self.hands[seat].remove(x)
        self.hands[seat].sort(key=tile_key)
        for m in self.melds[seat]:
            if m['type'] == 'pon' and norm(m['tiles'][0]) == norm(x):
                m['type'] = 'kakan'
                m['tiles'] = m['tiles'] + [x]
                break
        self._event('kakan', seat=seat, tile=x)
        self._after_kan(seat)

    def _after_kan(self, seat):
        self.dora_count = min(self.dora_count + 1, 5)
        self.kan_seats.append(seat)
        self._event('dora', tile=self.dora_indicators()[-1])
        # 四杠散了：总共四个杠，且不是同一个人开的四个杠（一个人四杠是四杠子）
        if len(self.kan_seats) >= 4 and len(set(self.kan_seats)) > 1:
            self._abort('四杠散了')
            return
        self._draw(seat, rinshan=True)

    # ---------- 和牌结算 ----------
    def _parse_score(self, res, is_oya, is_tsumo):
        if isinstance(res, dict):
            gain = res.get('get', 0)
            if is_tsumo:
                if is_oya:
                    p = res.get('ko_pay', 0)
                    return gain, p, p
                return gain, res.get('oya_pay', 0), res.get('ko_pay', 0)
            return gain, res.get('ron_pay', 0), 0
        gain, pay = res[0], res[1]
        if isinstance(pay, (list, tuple)):
            if len(pay) >= 2:
                return gain, pay[0], pay[1]
            pay = pay[0]
        return gain, pay, pay

    def _score_one(self, seat, hand14, win_tile, is_tsumo, from_seat, honba, kyotaku,
                   chankan=False):
        melds = self.melds_plain(seat)
        melds_n = self.melds_plain(seat, True)
        state = self._make_state(seat, is_tsumo, chankan=chankan)
        dora = self.dora_list()
        yaku, han = calc_yaku(list(hand14), melds, win_tile, is_tsumo,
                              self.bakaze, self.jikaze(seat), dora, state,
                              rules=self.rules, detail=True)
        yaku_names = [y[0] for y in yaku]
        fu = calc_fu(norm_list(hand14), melds_n, norm(win_tile), is_tsumo,
                     self.bakaze, self.jikaze(seat), an_gang=self.ankan_lists(seat),
                     rules=self.rules, yaku_names=yaku_names,
                     decomp=state.get('_decomp'))
        is_oya = seat == self.oya
        yakuman = 0
        if is_yakuman_names(yaku_names):
            yakuman = max(1, han // 13)
        sc = calc_score(fu, han, is_oya, is_tsumo, honba, kyotaku,
                        rules=self.rules, yakuman=yakuman)
        gain, pay_oya, pay_ko = self._parse_score(sc, is_oya, is_tsumo)
        delta = [0] * 4
        delta[seat] += gain
        if is_tsumo:
            for s in range(4):
                if s == seat:
                    continue
                delta[s] -= pay_oya if s == self.oya else pay_ko
        else:
            delta[from_seat] -= pay_oya
        info = {
            'seat': seat, 'from': from_seat, 'tile': win_tile, 'tsumo': is_tsumo,
            'hand': list(hand14), 'melds': melds,
            'yaku': [{'name': n, 'han': h} for n, h in yaku],
            'han': han, 'fu': fu, 'yakuman': yakuman,
            'points': sc.get('points', 0) if isinstance(sc, dict) else gain,
            'delta': delta,
        }
        return info, delta

    def _win_tsumo(self, seat):
        info, delta = self._score_one(seat, self.hands[seat], self.drawn, True, None,
                                      self.honba, self.kyotaku)
        self.kyotaku = 0
        self._event('tsumo', seat=seat)
        result = {
            'type': 'tsumo', 'wins': [info],
            'dora_indicators': self.dora_indicators(),
            'ura_indicators': self.ura_indicators() if self.riichi[seat] else [],
        }
        self._end_round(result, delta, seat == self.oya, True)

    def _cancel_riichi_on_ron(self, discarder):
        """立直宣言牌被荣和：立直不成立，不收立直棒，也不算立直役。"""
        if self.riichi_pending == discarder:
            self.riichi[discarder] = False
            self.double_riichi[discarder] = False
            self.ippatsu[discarder] = False
            if self.rivers[discarder]:
                self.rivers[discarder][-1]['riichi'] = False
            self.riichi_pending = None

    def _win_ron(self, winners, discarder, tile, chankan=False):
        self._cancel_riichi_on_ron(discarder)
        # 双响可以；本场和立直棒给离放铳的人最近的那个（上家取り）
        total = [0] * 4
        wins = []
        for i, s in enumerate(winners):
            hb = self.honba if i == 0 else 0
            kt = self.kyotaku if i == 0 else 0
            info, delta = self._score_one(s, self.hands[s] + [tile], tile, False,
                                          discarder, hb, kt, chankan=chankan)
            wins.append(info)
            for k in range(4):
                total[k] += delta[k]
        self.kyotaku = 0
        any_riichi = any(self.riichi[s] for s in winners)
        for s in winners:
            self._event('ron', seat=s, **{'from': discarder})
        result = {
            'type': 'ron', 'wins': wins,
            'dora_indicators': self.dora_indicators(),
            'ura_indicators': self.ura_indicators() if any_riichi else [],
        }
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
        self._event('ryuukyoku', reason='exhaustive')
        result = {'type': 'ryuukyoku', 'reason': '荒牌流局', 'tenpai': tenpai}
        self._end_round(result, delta, tenpai[self.oya], False, draw=True)

    def _abort(self, reason):
        self._event('ryuukyoku', reason=reason)
        result = {'type': 'abort', 'reason': reason}
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
        self.next_honba = self.honba + 1 if (renchan or draw) else 0
        self.game_over = self._check_game_over(renchan, is_win)
        if self.game_over:
            top = max(range(4), key=lambda s: (self.scores[s], -s))
            bonus = self.kyotaku * 1000
            if bonus:
                # 终局时桌上剩下的立直棒给第一名；这笔钱也要进这一局的 delta，
                # 否则 result.delta 和“分数变化”对不上。
                self.scores[top] += bonus
                delta[top] += bonus
                result['delta'] = delta
            self.kyotaku = 0
            result['scores'] = list(self.scores)
            result['game_over'] = True
            result['ranking'] = sorted(range(4), key=lambda s: (-self.scores[s], s))

    def _check_game_over(self, renchan, is_win):
        if any(s < 0 for s in self.scores):
            return True   # 被飞
        last = 3 if self.length == 'tonpuu' else 7
        if self.kyoku > last:
            return True
        if self.kyoku == last and not renchan:
            return True
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
        players = []
        for s in range(4):
            p = {
                'seat': s,
                'score': self.scores[s],
                'wind': self.jikaze(s),
                'river': [dict(r) for r in self.rivers[s]],
                'melds': [{
                    'type': m['type'], 'tiles': list(m['tiles']),
                    'from': m['from'], 'called_tile': m.get('called_tile'),
                } for m in self.melds[s]],
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
                'name': names[0 if self.kyoku < 4 else 1] + str(self.kyoku % 4 + 1) + '局',
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
