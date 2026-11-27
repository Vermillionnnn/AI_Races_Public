# 学号 250207
# game.py —— 整局流程：洗牌发牌、摸打、吃碰杠、立直、流局、连庄换庄、本场、电脑玩家

from collections import Counter
from itertools import combinations
import random

try:
    from fu import calc_fu, calc_fu_decomp
    from yaku import calc_yaku, calc_yaku_candidates, split_hand, normal_tile as _ynorm
    from score import calc_score
    from tenpai import can_hu, YAOCHU
except ImportError:
    calc_fu = calc_fu_decomp = calc_yaku = calc_yaku_candidates = None
    split_hand = _ynorm = calc_score = can_hu = None
    YAOCHU = {
        '1m', '9m', '1p', '9p', '1s', '9s',
        '1z', '2z', '3z', '4z', '5z', '6z', '7z',
    }


START_POINTS = 25000
RETURN_POINTS = 30000

DEFAULT_RULES = {
    'aka_dora': True,
    'kuitan': True,
    'kiriage_mangan': False,
    'renpu_fu': 4,
}

ALL_TILES = [str(n) + s for s in 'mps' for n in range(1, 10)] + [str(n) + 'z' for n in range(1, 8)]

RYUUKYOKU_KEY = {
    '荒牌流局': 'exhaustive',
    '九种九牌': 'kyuushu',
    '四杠散了': 'four_kans',
    '四家立直': 'four_riichi',
    '四风连打': 'four_winds',
    '三家和': 'triple_ron',
}


def normalize_rules(rules=None):
    out = dict(DEFAULT_RULES)
    if rules:
        for k in ('aka_dora', 'kuitan', 'kiriage_mangan'):
            if k in rules:
                if not isinstance(rules[k], bool):
                    raise ValueError(f'rules.{k} 必须是布尔值')
                out[k] = rules[k]
        if 'renpu_fu' in rules:
            if rules['renpu_fu'] not in (2, 4) or isinstance(rules['renpu_fu'], bool):
                raise ValueError('rules.renpu_fu 必须是 2 或 4')
            out['renpu_fu'] = rules['renpu_fu']
    return out


def norm(t):
    """红五 0m -> 5m"""
    if t[0] == '0':
        return '5' + t[1]
    return t


def norm_list(tiles):
    return [norm(t) for t in tiles]


def tile_key(t):
    n = 5 if t[0] == '0' else int(t[0])
    return ('mpsz'.index(t[1]), n, 0 if t[0] == '0' else 1)


def make_wall(aka_dora=True):
    wall = []
    for s in 'mps':
        for n in range(1, 10):
            for k in range(4):
                if aka_dora and n == 5 and k == 0:
                    wall.append('0' + s)
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
            n = n % 4 + 1
        else:
            n = (n - 5 + 1) % 3 + 5
    else:
        n = n % 9 + 1
    return str(n) + s


def is_yaochu(t):
    t = norm(t)
    return t[1] == 'z' or t[0] in '19'


class Game:
    def __init__(self, human_seats=(0,), wall=None, seed=None, length='tonpuu', rules=None):
        if length not in ('tonpuu', 'hanchan'):
            raise ValueError('length 只能是 tonpuu 或 hanchan')
        self.rng = random.Random(seed)
        self.human_seats = set(human_seats)
        self.length = length
        self.rules = normalize_rules(rules)
        self.scores = [START_POINTS] * 4
        self.kyoku = 0      # 0~3 = 东1~东4, 4~7 = 南1~南4, 8~11 = 西1~西4
        self.honba = 0
        self.kyotaku = 0
        self.game_over = False
        self.result = None
        self.start_round(wall)

    # ---------- 小工具 ----------
    @property
    def oya(self):
        return self.kyoku % 4

    @property
    def bakaze(self):
        winds = ('1z', '2z', '3z', '4z')
        return winds[min(self.kyoku // 4, 3)]

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

    def ankan_indices(self, seat):
        return [i for i, m in enumerate(self.melds[seat]) if m['type'] == 'ankan']

    def ankan_tiles(self, seat):
        return [list(m['tiles']) for m in self.melds[seat] if m['type'] == 'ankan']

    def is_menzen(self, seat):
        return all(m['type'] == 'ankan' for m in self.melds[seat])

    def dora_indicators(self):
        return list(self.dead_wall[0:self.dora_count])

    def ura_indicators(self):
        return list(self.dead_wall[5:5 + self.dora_count])

    def dora_list(self, with_ura=False):
        res = [dora_from_indicator(t) for t in self.dora_indicators()]
        if with_ura:
            res += [dora_from_indicator(t) for t in self.ura_indicators()]
        return res

    def ura_dora_list(self):
        return [dora_from_indicator(t) for t in self.ura_indicators()]

    def get_visible(self, seat):
        """给听牌提示用：场上可见且未计入自身 hand/melds 的牌
        （所有未被人鸣走的牌河 + 他人副露 + 已翻开宝牌指示牌），避免与 tenpai.py 重复扣减。
        """
        vis = []
        for s in range(4):
            vis += [r['tile'] for r in self.rivers[s] if not r.get('called')]
            if s != seat:
                for m in self.melds[s]:
                    vis += m['tiles']
        vis += self.dora_indicators()
        return norm_list(vis)

    # ---------- 一局开始 ----------
    def start_round(self, wall=None):
        if wall is None:
            wall = make_wall(aka_dora=self.rules['aka_dora'])
            self.rng.shuffle(wall)
        else:
            wall = list(wall)
            if len(wall) != 136:
                raise ValueError('牌山要 136 张')
        # 按《接口说明》牌山布局：
        #   wall[0:13]..wall[39:52] 按物理座位 0..3 配牌
        #   wall[52:122] 正常摸牌
        #   wall[122:127] 宝牌指示牌 1~5
        #   wall[127:132] 里宝牌指示牌 1~5
        #   wall[132:136] 岭上牌 1~4
        self.wall = wall
        self.dead_wall = wall[122:136]
        self.wall_pos = 52
        self.wall_end = 122
        self.rinshan_used = 0
        self.dora_count = 1
        self.pending_kan_dora = 0

        self.hands = [[] for _ in range(4)]
        for seat in range(4):
            self.hands[seat] = sorted(wall[13 * seat:13 * seat + 13], key=tile_key)
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
        self.four_kans_pending = False
        self.chankan_ctx = None
        self.events = []

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

        self._draw(self.oya)
        self._run()

    # ---------- 摸牌打牌 ----------
    def _reveal_pending_dora(self):
        while self.pending_kan_dora > 0:
            self.pending_kan_dora -= 1
            if self.dora_count < 5:
                self.dora_count += 1
                self.events.append({'type': 'dora', 'tile': self.dora_indicators()[-1]})

    def _draw(self, seat, rinshan=False):
        if rinshan:
            t = self.dead_wall[10 + self.rinshan_used]
            self.rinshan_used += 1
            self.wall_end -= 1
        else:
            t = self.wall[self.wall_pos]
            self.wall_pos += 1
        self.hands[seat].append(t)
        self.drawn = t
        self.current = seat
        self.is_rinshan_draw = rinshan
        self.after_call = False
        self.kuikae = []
        self.phase = 'discard'
        self.events.append({'type': 'draw', 'seat': seat, 'tile': t})

    def _discard(self, seat, tile, riichi=False, tsumogiri=None):
        if tsumogiri is None:
            tsumogiri = (self.drawn is not None and tile == self.drawn)
        hand = self.hands[seat]
        if tsumogiri and hand and hand[-1] == tile:
            hand.pop()
        else:
            hand.remove(tile)
        hand.sort(key=tile_key)

        if self.riichi[seat] and not riichi:
            self.ippatsu[seat] = False
        if riichi:
            self.riichi[seat] = True
            self.ippatsu[seat] = True
            if self.first_turn[seat] and self.no_call_yet:
                self.double_riichi[seat] = True
            self.riichi_pending = seat
            self.events.append({'type': 'riichi', 'seat': seat})

        self.first_turn[seat] = False
        self.temp_furiten[seat] = False
        self.rivers[seat].append({
            'tile': tile,
            'tsumogiri': bool(tsumogiri),
            'riichi': bool(riichi),
            'called': False,
        })
        self.events.append({
            'type': 'discard',
            'seat': seat,
            'tile': tile,
            'tsumogiri': bool(tsumogiri),
        })
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
            # 第4次杠打出后不能吃碰杠，只能荣和或触发四杠散了
            if not self.riichi[s] and not last and not self.four_kans_pending:
                same = [t for t in self.hands[s] if norm(t) == norm(tile)]
                if len(same) >= 2:
                    for pt in self._pon_combos(s, tile, same):
                        opts.append({'type': 'pon', 'tiles': pt})
                if len(same) >= 3 and self.rinshan_used < 4:
                    opts.append({'type': 'kan', 'tiles': sorted(same[:3], key=tile_key)})
                if i == 1 and tile[1] != 'z':
                    for combo in self._chi_combos(s, tile):
                        opts.append({'type': 'chi', 'tiles': combo})
            if opts:
                self.call_options[s] = opts
        self.phase = 'call'

    def _has_non_kuikae_discard(self, seat, own, forbidden_norms):
        rem = list(self.hands[seat])
        for t in own:
            rem.remove(t)
        return any(norm(t) not in forbidden_norms for t in rem)

    def _pon_combos(self, seat, tile, same):
        seen = set()
        combos = []
        forbidden = {norm(tile)}
        for a, b in combinations(sorted(same, key=tile_key), 2):
            key = (a, b)
            if key in seen:
                continue
            seen.add(key)
            if self._has_non_kuikae_discard(seat, [a, b], forbidden):
                combos.append([a, b])
        return combos

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
                forbidden = {norm(tile)}
                if n < a and b + 1 <= 9:
                    forbidden.add(str(b + 1) + s)
                elif n > b and a - 1 >= 1:
                    forbidden.add(str(a - 1) + s)
                for x in sorted(set(ta), key=tile_key):
                    for y in sorted(set(tb), key=tile_key):
                        if self._has_non_kuikae_discard(seat, [x, y], forbidden):
                            combos.append([x, y])
        return combos

    # ---------- 和牌判断 ----------
    def _is_tenpai(self, hand13, melds_n):
        h = norm_list(hand13)
        hs = set(h)
        cands = set(hs)
        for t in hs:
            if t[1] != 'z':
                n = int(t[0])
                s = t[1]
                if n > 1:
                    cands.add(f'{n - 1}{s}')
                if n < 9:
                    cands.add(f'{n + 1}{s}')
        if len(melds_n) == 0 and hs.issubset(YAOCHU):
            cands.update(YAOCHU)
        for t in ALL_TILES:
            if t in cands and can_hu(h + [t], melds_n):
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
        if len(h) + 3 * len(mn) != 13:
            return False
        for t in set(norm(r['tile']) for r in self.rivers[seat]):
            if can_hu(h + [t], mn):
                return True
        return False

    def _make_state(self, seat, is_tsumo, is_chankan=False):
        last = self.remaining() == 0
        chihou = is_tsumo and seat != self.oya and self.first_turn[seat] and self.no_call_yet
        return {
            'riichi': self.riichi[seat],
            'ippatsu': self.ippatsu[seat],
            'haitei': is_tsumo and last and not self.is_rinshan_draw,
            'houtei': (not is_tsumo) and last and not is_chankan,
            'rinshan': is_tsumo and self.is_rinshan_draw,
            'chankan': is_chankan,
            'double_riichi': self.double_riichi[seat],
            'tenhou': is_tsumo and seat == self.oya and self.first_turn[seat] and self.no_call_yet,
            'chihou': chihou,
            'chiihou': chihou,
            'ankan_indices': self.ankan_indices(seat),
            'ura_dora': self.ura_dora_list() if self.riichi[seat] else [],
            'kuitan': self.rules['kuitan'],
            'aka_dora': self.rules['aka_dora'],
        }

    def _win_ok(self, seat, hand14, win_tile, is_tsumo, is_chankan=False):
        """形能和 + 有役（不传宝牌，避免无役靠宝牌和牌）"""
        hn = norm_list(hand14)
        mn = self.melds_plain(seat, True)
        if not can_hu(hn, mn):
            return False
        state = self._make_state(seat, is_tsumo, is_chankan=is_chankan)
        _, han = calc_yaku(
            hn, mn, norm(win_tile), is_tsumo,
            self.bakaze, self.jikaze(seat), [], state, rules=self.rules
        )
        return han > 0

    def _can_ron(self, seat, tile, chankan=False):
        if self._is_furiten(seat):
            return False
        return self._win_ok(seat, self.hands[seat] + [tile], tile, False, is_chankan=chankan)

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
                filtered = [t for t in discards if norm(t) not in self.kuikae]
                if filtered:
                    discards = filtered
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
        """立直后暗杠：听牌种类不变，且不会改变原手牌的面子构成（禁止送りカン）"""
        hand = list(self.hands[seat])
        hand.remove(self.drawn)
        mn = self.melds_plain(seat, True)
        before = self._waits(hand, mn)
        h2 = [x for x in self.hands[seat] if norm(x) != t]
        after = self._waits(h2, mn + [[t] * 4])
        if before != after or len(before) == 0:
            return False

        if split_hand is not None:
            hn = norm_list(hand)
            groups_needed = 4 - len(mn)
            for w in before:
                c = Counter(hn + [w])
                decomps = list(split_hand(c, groups_needed))
                if not decomps:
                    # 国士/七对子不可能暗杠 4 张
                    return False
                for _, groups in decomps:
                    if ('triplet', t, False) not in groups:
                        return False
        return True

    # ---------- 玩家操作 ----------
    def do_action(self, seat, action, tile=None, tiles=None, tsumogiri=None, expected_kan_kind=None):
        """action: discard / riichi / tsumo / ron / chi / pon / kan / pass / kyuushu"""
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
                    if a['type'] == 'kan':
                        if expected_kan_kind and a.get('kind') != expected_kan_kind:
                            continue
                        if tile is None or norm(tile) == a['tiles'][0]:
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
                if expected_kan_kind and expected_kan_kind != 'minkan':
                    raise ValueError('现在不能 ' + expected_kan_kind)
                cand = [a for a in legal if a['type'] == action]
                pick = cand[0]
                if tiles is not None:
                    for a in cand:
                        if sorted(a['tiles']) == sorted(tiles):
                            pick = a
                            break
                    else:
                        msg = '没有这个吃法' if action == 'chi' else '没有这个碰法'
                        raise ValueError(msg)
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
        if self.drawn is not None and self.drawn in self.hands[seat] and self.drawn in acts[0]['tiles']:
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

        is_chankan = self.chankan_ctx is not None
        if len(rons) == 3:
            self.chankan_ctx = None
            self._abort('三家和')
            return
        if rons:
            self.chankan_ctx = None
            self._win_ron(rons, discarder, tile, chankan=is_chankan)
            return

        if is_chankan:
            ctx = self.chankan_ctx
            self.chankan_ctx = None
            if ctx['kind'] == 'kakan':
                self._finish_kakan(ctx['seat'], ctx['tile'], ctx['norm_tile'])
            else:
                self._finish_ankan(ctx['seat'], ctx['norm_tile'])
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
        discarder, _ = self.last_discard
        if self._pay_riichi_stick() and all(self.riichi):
            self._abort('四家立直')
            return
        self._reveal_pending_dora()
        # 四风连打
        if self.no_call_yet and all(len(r) == 1 for r in self.rivers):
            first = [norm(r[0]['tile']) for r in self.rivers]
            if first[0] in ('1z', '2z', '3z', '4z') and len(set(first)) == 1:
                self._abort('四风连打')
                return
        # 四杠散了：至少两人合计杠满 4 次，第 4 杠打出无人荣和时流局
        if self.four_kans_pending:
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
            all_tiles = sorted(own + [tile], key=tile_key)
            self.melds[seat].append({
                'type': 'minkan',
                'tiles': all_tiles,
                'from': discarder,
                'called_tile': tile,
            })
            self.events.append({
                'type': 'minkan',
                'seat': seat,
                'tiles': list(all_tiles),
                'from': discarder,
            })
            self._after_kan(seat, is_open=True)
            return

        all_tiles = sorted(own + [tile], key=tile_key)
        self.melds[seat].append({
            'type': kind,
            'tiles': all_tiles,
            'from': discarder,
            'called_tile': tile,
        })
        self.events.append({
            'type': kind,
            'seat': seat,
            'tiles': list(all_tiles),
            'from': discarder,
        })
        self.current = seat
        self.drawn = None
        self.after_call = True
        self.phase = 'discard'
        n = int(norm(tile)[0])
        self.kuikae = [norm(tile)]
        if kind == 'chi':
            a, b = sorted(int(norm(t)[0]) for t in own)
            if n < a and b + 1 <= 9:
                self.kuikae.append(str(b + 1) + tile[1])
            elif n > b and a - 1 >= 1:
                self.kuikae.append(str(a - 1) + tile[1])

    def _can_kokushi_chankan(self, seat, t):
        if len(self.melds[seat]) != 0 or self._is_furiten(seat):
            return False
        hn = norm_list(self.hands[seat])
        if not set(hn).issubset(YAOCHU) or t not in YAOCHU:
            return False
        return can_hu(hn + [t], [])

    def _ankan(self, seat, t):
        self._interrupt()
        self.drawn = None
        # 国士无双抢暗杠检查
        opts = {}
        for i in (1, 2, 3):
            s = (seat + i) % 4
            if self._can_kokushi_chankan(s, t):
                opts[s] = [{'type': 'ron', 'tile': t}]
        if opts:
            self.chankan_ctx = {'seat': seat, 'tile': t, 'norm_tile': t, 'kind': 'ankan'}
            self.last_discard = (seat, t)
            self.call_options = opts
            self.responses = {}
            self.phase = 'call'
            return
        self._finish_ankan(seat, t)

    def _finish_ankan(self, seat, t):
        own = sorted([x for x in self.hands[seat] if norm(x) == t], key=tile_key)
        for x in own:
            self.hands[seat].remove(x)
        self.hands[seat].sort(key=tile_key)
        self.melds[seat].append({
            'type': 'ankan',
            'tiles': own,
            'from': None,
            'called_tile': None,
        })
        self.events.append({'type': 'ankan', 'seat': seat, 'tile': t})
        self._after_kan(seat, is_open=False)

    def _kakan(self, seat, t):
        self._interrupt()
        self.drawn = None
        x = [y for y in self.hands[seat] if norm(y) == t][0]
        opts = {}
        for i in (1, 2, 3):
            s = (seat + i) % 4
            if self._can_ron(s, x, chankan=True):
                opts[s] = [{'type': 'ron', 'tile': x}]
        if opts:
            self.chankan_ctx = {'seat': seat, 'tile': x, 'norm_tile': t, 'kind': 'kakan'}
            self.last_discard = (seat, x)
            self.call_options = opts
            self.responses = {}
            self.phase = 'call'
            return
        self._finish_kakan(seat, x, t)

    def _finish_kakan(self, seat, x, t):
        self.hands[seat].remove(x)
        self.hands[seat].sort(key=tile_key)
        for m in self.melds[seat]:
            if m['type'] == 'pon' and norm(m['tiles'][0]) == t:
                m['type'] = 'kakan'
                m['tiles'] = m['tiles'] + [x]
                break
        self.events.append({'type': 'kakan', 'seat': seat, 'tile': t})
        self._after_kan(seat, is_open=True)

    def _after_kan(self, seat, is_open):
        self._reveal_pending_dora()
        if is_open:
            self.pending_kan_dora += 1
        else:
            if self.dora_count < 5:
                self.dora_count += 1
                self.events.append({'type': 'dora', 'tile': self.dora_indicators()[-1]})
        self.kan_seats.append(seat)
        if len(self.kan_seats) == 4 and len(set(self.kan_seats)) >= 2:
            self.four_kans_pending = True
        self._draw(seat, rinshan=True)

    # ---------- 和牌结算 ----------
    def _parse_score(self, res):
        if isinstance(res, dict):
            gain = res.get('get', 0)
            if res.get('ron_pay', 0) > 0:
                return gain, res['ron_pay'], res['ron_pay']
            oya_pay = res.get('oya_pay', 0)
            ko_pay = res.get('ko_pay', 0)
            return gain, (oya_pay if oya_pay > 0 else ko_pay), ko_pay
        gain, pay = res[0], res[1]
        if isinstance(pay, (list, tuple)):
            if len(pay) >= 2:
                return gain, pay[0], pay[1]
            pay = pay[0]
        return gain, pay, pay

    def _evaluate_score(self, seat, hand14, win_tile, is_tsumo, honba, kyotaku, chankan=False):
        melds_raw = self.melds_plain(seat)
        melds_norm = self.melds_plain(seat, True)
        an_gang = self.ankan_tiles(seat)
        state = self._make_state(seat, is_tsumo, is_chankan=chankan)
        dora = self.dora_list(with_ura=False)
        is_oya = (seat == self.oya)
        renpu_fu = self.rules['renpu_fu']
        kiriage = self.rules['kiriage_mangan']

        if calc_yaku_candidates is not None and calc_fu_decomp is not None:
            cands = calc_yaku_candidates(
                list(hand14), melds_raw, win_tile, is_tsumo,
                self.bakaze, self.jikaze(seat), dora, state, rules=self.rules
            )
            best = None
            for c in cands:
                if 'fixed_fu' in c:
                    fu = c['fixed_fu']
                else:
                    fu = calc_fu_decomp(
                        c['pair'], c['hand_groups'], melds_norm, norm(win_tile),
                        is_tsumo, self.bakaze, self.jikaze(seat), c['wait'],
                        an_gang=an_gang, renpu_fu=renpu_fu
                    )
                base_res = calc_score(
                    fu, c['han'], is_oya, is_tsumo, 0, 0,
                    kiriage_mangan=kiriage, yakuman=c['yakuman']
                )
                points = base_res['get'] if isinstance(base_res, dict) else self._parse_score(base_res)[0]
                full_res = calc_score(
                    fu, c['han'], is_oya, is_tsumo, honba, kyotaku,
                    kiriage_mangan=kiriage, yakuman=c['yakuman']
                )
                rank_key = (points, c['yakuman'], c['han'], fu)
                if best is None or rank_key > best[0]:
                    best = (rank_key, c, fu, points, full_res)
            if best is not None:
                _, c, fu, points, full_res = best
                yaku_items = [{'name': n, 'han': h} for n, h in c['yaku']]
                return yaku_items, c['han'], fu, c['yakuman'], points, full_res

        # 兜底（如单元测试替换了假函数）
        yaku_names, han = calc_yaku(
            list(hand14), melds_raw, win_tile, is_tsumo,
            self.bakaze, self.jikaze(seat), dora, state
        )
        fu = calc_fu(
            norm_list(hand14), melds_norm, norm(win_tile),
            is_tsumo, self.bakaze, self.jikaze(seat)
        )
        base_res = calc_score(fu, han, is_oya, is_tsumo, 0, 0)
        points = base_res['get'] if isinstance(base_res, dict) else self._parse_score(base_res)[0]
        full_res = calc_score(fu, han, is_oya, is_tsumo, honba, kyotaku)
        yaku_items = [{'name': n, 'han': 1} for n in yaku_names]
        return yaku_items, han, fu, 0, points, full_res

    def _score_one(self, seat, hand14, win_tile, is_tsumo, from_seat, honba, kyotaku, chankan=False):
        yaku_items, han, fu, yakuman, points, res = self._evaluate_score(
            seat, hand14, win_tile, is_tsumo, honba, kyotaku, chankan=chankan
        )
        gain, pay_oya, pay_ko = self._parse_score(res)
        delta = [0] * 4
        delta[seat] += gain
        if is_tsumo:
            for s in range(4):
                if s == seat:
                    continue
                delta[s] -= pay_oya if s == self.oya else pay_ko
        else:
            delta[from_seat] -= pay_oya
        hand_without_win = list(hand14)
        if win_tile in hand_without_win:
            hand_without_win.remove(win_tile)
        info = {
            'seat': seat,
            'from': from_seat,
            'tile': win_tile,
            'tsumo': is_tsumo,
            'hand': hand_without_win,
            'melds': [
                {
                    'type': m['type'],
                    'tiles': list(m['tiles']),
                    'from': m['from'],
                    'called_tile': m.get('called_tile'),
                }
                for m in self.melds[seat]
            ],
            'yaku': yaku_items,
            'han': han,
            'fu': fu,
            'yakuman': yakuman,
            'points': points,
            'delta': delta,
        }
        return info, delta

    def _win_tsumo(self, seat):
        self.events.append({'type': 'tsumo', 'seat': seat})
        info, delta = self._score_one(
            seat, self.hands[seat], self.drawn, True, None, self.honba, self.kyotaku
        )
        self.kyotaku = 0
        result = {
            'type': 'tsumo',
            'wins': [info],
            'dora_indicators': self.dora_indicators(),
            'ura_indicators': self.ura_indicators() if self.riichi[seat] else [],
        }
        self._end_round(result, delta, seat == self.oya, True)

    def _win_ron(self, winners, discarder, tile, chankan=False):
        # 宣言牌被荣和时立直未成立
        if self.riichi_pending == discarder:
            self.riichi[discarder] = False
            self.double_riichi[discarder] = False
            self.riichi_pending = None
        for s in winners:
            self.events.append({'type': 'ron', 'seat': s, 'from': discarder})
        total = [0] * 4
        wins = []
        for i, s in enumerate(winners):
            hb = self.honba if i == 0 else 0
            kt = self.kyotaku if i == 0 else 0
            info, delta = self._score_one(
                s, self.hands[s] + [tile], tile, False, discarder, hb, kt, chankan=chankan
            )
            wins.append(info)
            for k in range(4):
                total[k] += delta[k]
        self.kyotaku = 0
        any_riichi = any(self.riichi[s] for s in winners)
        result = {
            'type': 'ron',
            'wins': wins,
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
        self.events.append({'type': 'ryuukyoku', 'reason': 'exhaustive'})
        result = {'type': 'ryuukyoku', 'reason': '荒牌流局', 'tenpai': tenpai}
        self._end_round(result, delta, tenpai[self.oya], False, draw=True)

    def _abort(self, reason):
        self.events.append({'type': 'ryuukyoku', 'reason': RYUUKYOKU_KEY.get(reason, reason)})
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
            self.scores[top] += self.kyotaku * 1000
            self.kyotaku = 0
            result['scores'] = list(self.scores)
            result['game_over'] = True
            result['ranking'] = sorted(range(4), key=lambda s: (-self.scores[s], s))

    def _check_game_over(self, renchan, is_win):
        if any(s < 0 for s in self.scores):
            return True
        k = self.kyoku
        top = max(self.scores)
        base_last = 3 if self.length == 'tonpuu' else 7
        ext_last = 7 if self.length == 'tonpuu' else 11
        if k < base_last:
            return False
        if k == base_last:
            if renchan:
                if is_win and self.scores[self.oya] == top and top >= RETURN_POINTS:
                    return True
                return False
            return top >= RETURN_POINTS
        if top >= RETURN_POINTS:
            return True
        return k >= ext_last and not renchan

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
                'melds': [
                    {
                        'type': m['type'],
                        'tiles': list(m['tiles']),
                        'from': m['from'],
                        'called_tile': m.get('called_tile'),
                    }
                    for m in self.melds[s]
                ],
                'riichi': self.riichi[s],
            }
            if seat is None or seat == s or self.phase == 'end':
                p['hand'] = list(self.hands[s])
            else:
                p['hand_count'] = len(self.hands[s])
            players.append(p)
        names = ['东', '南', '西', '北']
        return {
            'round': {
                'name': names[min(self.kyoku // 4, 3)] + str(self.oya + 1) + '局',
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
        }
