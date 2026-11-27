# 学号 250207（已整理修复）
# game.py —— 整局流程：洗牌发牌、摸打、吃碰杠、抢杠、立直、流局、连庄换庄、本场、规则开关、电脑玩家

import random
import re

from fu import calc_fu
from score import calc_score
from tenpai import can_hu, discard_hints, get_waits
from yaku import calc_yaku, evaluate_hand, split_hand, yaku_chiitoitsu, yaku_kokushi

START_POINTS = 25000
RETURN_POINTS = 30000   # 南入/西入与终局 30000 点线

ALL_TILES = (
    [str(n) + s for s in 'mps' for n in range(1, 10)]
    + [str(n) + 'z' for n in range(1, 8)]
)
TILE_RE = re.compile(r'^([0-9][mps]|[1-7]z)$')

DEFAULT_RULES = {
    'aka_dora': True,
    'kuitan': True,
    'kiriage_mangan': False,
    'renpu_fu': 4,
}


def norm(t):
    """红五 0m/0p/0s -> 5m/5p/5s。"""
    if t and len(t) == 2 and t[0] == '0' and t[1] in 'mps':
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


def normalize_rules(rules):
    merged = dict(DEFAULT_RULES)
    if rules is None:
        return merged
    if not isinstance(rules, dict):
        raise ValueError('rules 必须是对象')
    for k, v in rules.items():
        if k not in DEFAULT_RULES:
            continue
        if k in ('aka_dora', 'kuitan', 'kiriage_mangan'):
            if not isinstance(v, bool):
                raise ValueError(f'rules.{k} 必须是 true 或 false')
            merged[k] = v
        elif k == 'renpu_fu':
            if isinstance(v, bool) or v not in (2, 4):
                raise ValueError('rules.renpu_fu 必须是 2 或 4')
            merged[k] = int(v)
    return merged


def _validate_wall(wall, aka_dora):
    if not isinstance(wall, list) or len(wall) != 136:
        raise ValueError('牌山必须是长度为 136 的数组')
    out = []
    for i, t in enumerate(wall):
        if not isinstance(t, str) or not TILE_RE.match(t):
            raise ValueError(f'牌山第 {i} 张牌不合法: {t!r}')
        out.append(norm(t) if not aka_dora else t)
    return out


class Game:
    def __init__(self, human_seats=(0,), wall=None, seed=None,
                 length='tonpuu', rules=None, player_names=None):
        if length not in ('tonpuu', 'hanchan'):
            raise ValueError('length 只能是 tonpuu 或 hanchan')
        self.length = length
        self.rules = normalize_rules(rules)
        self.rng = random.Random(seed)
        self.human_seats = set(human_seats)
        if player_names is not None:
            self.player_names = list(player_names)
        else:
            self.player_names = self._default_names()
        self.scores = [START_POINTS] * 4
        self.kyoku = 0
        self.honba = 0
        self.kyotaku = 0
        self.game_over = False
        self.result = None
        self.start_round(wall)

    def _default_names(self):
        if self.human_seats == {0}:
            return ['你', '电脑 1', '电脑 2', '电脑 3']
        names = []
        bot_idx = 1
        for s in range(4):
            if s in self.human_seats:
                names.append(f'座位 {s}')
            else:
                names.append(f'电脑 {bot_idx}')
                bot_idx += 1
        return names

    # ---------- 基础属性 ----------
    @property
    def oya(self):
        return self.kyoku % 4

    @property
    def bakaze(self):
        winds = ['1z', '2z', '3z', '4z']
        return winds[min(self.kyoku // 4, 3)]

    def jikaze(self, seat):
        return str((seat - self.oya) % 4 + 1) + 'z'

    def remaining(self):
        """牌山还能正常摸几张（不含王牌）。"""
        return self.wall_end - self.wall_pos

    def melds_plain(self, seat, normalize=False):
        res = []
        for m in self.melds[seat]:
            res.append(norm_list(m['tiles']) if normalize else list(m['tiles']))
        return res

    def ankan_indices(self, seat):
        return [i for i, m in enumerate(self.melds[seat]) if m['type'] == 'ankan']

    def is_menzen(self, seat):
        return all(m['type'] == 'ankan' for m in self.melds[seat])

    def _full_hand(self, seat):
        """手牌 + 刚摸到的牌（若轮到该座位且有 drawn）。"""
        if seat == self.current and self.drawn is not None and self.phase == 'discard':
            return list(self.hands[seat]) + [self.drawn]
        return list(self.hands[seat])

    def dora_indicators(self):
        """wall[122..126] 为宝牌指示牌。"""
        return [self.dead_wall[i] for i in range(self.dora_count)]

    def ura_indicators(self):
        """wall[127..131] 为里宝牌指示牌。"""
        return [self.dead_wall[5 + i] for i in range(self.dora_count)]

    def dora_list(self, with_ura=False):
        res = [dora_from_indicator(t) for t in self.dora_indicators()]
        if with_ura:
            res += [dora_from_indicator(t) for t in self.ura_indicators()]
        return res

    def ura_dora_list(self):
        return [dora_from_indicator(t) for t in self.ura_indicators()]

    def get_visible(self, seat):
        """场上除自己手牌与自己副露外能看到的牌（不重复统计被鸣走的牌和自己副露）。"""
        vis = []
        for s in range(4):
            # 被鸣走的牌已经在鸣牌者的 melds 里，河里不再重复统计
            for r in self.rivers[s]:
                if not r.get('called'):
                    vis.append(r['tile'])
            if s != seat:
                for m in self.melds[s]:
                    vis.extend(m['tiles'])
        vis.extend(self.dora_indicators())
        return norm_list(vis)

    def _emit(self, event):
        self.events.append(event)

    # ---------- 一局开始 ----------
    def start_round(self, wall=None):
        if wall is None:
            wall = make_wall(aka_dora=self.rules['aka_dora'])
            self.rng.shuffle(wall)
        else:
            wall = _validate_wall(wall, self.rules['aka_dora'])

        # 按 接口说明.md 约定：
        #   wall[0:13]..wall[39:52] 对应物理座位 0..3 的配牌（不管谁是庄家）
        #   wall[52:122] 正常摸牌，当前庄家先摸 wall[52]
        #   wall[122:136] 王牌 14 张：
        #     dead_wall[0:5]   = wall[122:127] 宝牌指示牌
        #     dead_wall[5:10]  = wall[127:132] 里宝牌指示牌
        #     dead_wall[10:14] = wall[132:136] 岭上牌
        self.wall = wall
        self.dead_wall = wall[122:136]
        self.wall_pos = 52
        self.wall_end = 122
        self.rinshan_used = 0
        self.dora_count = 1
        self.pending_dora = 0

        self.hands = [
            sorted(wall[13 * s:13 * s + 13], key=tile_key)
            for s in range(4)
        ]
        self.rivers = [[] for _ in range(4)]
        self.melds = [[] for _ in range(4)]
        self.riichi = [False] * 4
        self.double_riichi = [False] * 4
        self.ippatsu = [False] * 4
        self.riichi_tile_needed = [False] * 4
        self.first_turn = [True] * 4
        self.no_call_yet = True
        self.temp_furiten = [False] * 4
        self.riichi_furiten = [False] * 4
        self.riichi_pending = None
        self.kan_seats = []

        self.current = self.oya
        self.drawn = None
        self.is_rinshan_draw = False
        self.after_call = False
        self.kuikae = []
        self.last_discard = None
        self.pending_kan = None
        self.call_options = {}
        self.responses = {}
        self.events = []
        self.result = None
        self.phase = 'discard'

        self._draw(self.oya)
        self._run()

    # ---------- 宝牌翻开 ----------
    def _flip_kan_dora(self):
        if self.dora_count < 5:
            ind = self.dead_wall[self.dora_count]
            self.dora_count += 1
            self._emit({'type': 'dora', 'tile': ind})

    def _flip_pending_dora(self):
        while self.pending_dora > 0:
            self.pending_dora -= 1
            self._flip_kan_dora()

    # ---------- 摸牌打牌 ----------
    def _draw(self, seat, rinshan=False):
        if rinshan:
            t = self.dead_wall[10 + self.rinshan_used]
            self.rinshan_used += 1
            self.wall_end -= 1
        else:
            t = self.wall[self.wall_pos]
            self.wall_pos += 1
        self.drawn = t
        self.current = seat
        self.is_rinshan_draw = rinshan
        self.after_call = False
        self.kuikae = []
        self.phase = 'discard'
        self._emit({'type': 'draw', 'seat': seat, 'tile': t})

    def _discard(self, seat, tile, riichi=False, tsumogiri=None):
        # 明杠/加杠的杠宝牌在打牌时翻开（早于荣和结算）
        self._flip_pending_dora()

        if self.drawn is None:
            if tsumogiri is True:
                raise ValueError('鸣牌后不能摸切')
            tsumogiri = False
            self.hands[seat].remove(tile)
            self.hands[seat].sort(key=tile_key)
        else:
            if tsumogiri is None:
                tsumogiri = (tile == self.drawn)
            if tsumogiri:
                if tile != self.drawn:
                    raise ValueError('摸切牌与刚摸到的牌不一致')
                self.drawn = None
            else:
                if tile in self.hands[seat]:
                    self.hands[seat].remove(tile)
                    self.hands[seat].append(self.drawn)
                    self.hands[seat].sort(key=tile_key)
                    self.drawn = None
                elif tile == self.drawn:
                    tsumogiri = True
                    self.drawn = None
                else:
                    raise ValueError('手里没有这张牌')

        if self.riichi[seat] and not riichi:
            self.ippatsu[seat] = False
        if riichi:
            self.riichi[seat] = True
            self.ippatsu[seat] = True
            if self.first_turn[seat] and self.no_call_yet:
                self.double_riichi[seat] = True
            self.riichi_pending = seat
            self._emit({'type': 'riichi', 'seat': seat})

        sideways = riichi or self.riichi_tile_needed[seat]
        self.riichi_tile_needed[seat] = False
        self.first_turn[seat] = False
        self.temp_furiten[seat] = False
        self.rivers[seat].append({
            'tile': tile,
            'tsumogiri': bool(tsumogiri),
            'riichi': bool(sideways),
            'called': False,
        })
        self._emit({
            'type': 'discard',
            'seat': seat,
            'tile': tile,
            'tsumogiri': bool(tsumogiri),
        })
        self.is_rinshan_draw = False
        self.last_discard = (seat, tile)

        # 检查他人能否荣和 / 碰 / 明杠 / 吃
        self.call_options = {}
        self.responses = {}
        last = self.remaining() == 0
        # 已经由多人杠满 4 次后，本打牌只能荣和，不能再鸣牌（没人荣和即四杠散了）
        four_kans_pending = (len(self.kan_seats) == 4 and len(set(self.kan_seats)) >= 2)
        for i in (1, 2, 3):
            s = (seat + i) % 4
            opts = []
            if self._can_ron(s, tile):
                opts.append({'type': 'ron', 'tile': tile})
            if not self.riichi[s] and not last and not four_kans_pending:
                same = sorted(
                    [t for t in self.hands[s] if norm(t) == norm(tile)],
                    key=tile_key,
                )
                if len(same) >= 2:
                    for combo in self._pon_combos(s, tile, same):
                        opts.append({'type': 'pon', 'tiles': combo})
                if len(same) >= 3 and self.rinshan_used < 4:
                    opts.append({'type': 'minkan', 'tiles': same[:3]})
                if i == 1 and tile[1] != 'z':
                    for combo in self._chi_combos(s, tile):
                        opts.append({'type': 'chi', 'tiles': combo})
            if opts:
                self.call_options[s] = opts
        self.phase = 'call'

    def _kuikae_tiles(self, kind, called_tile, own):
        n = int(norm(called_tile)[0])
        kuikae = [norm(called_tile)]
        if kind == 'chi':
            a, b = sorted(int(norm(t)[0]) for t in own)
            if n < a and b + 1 <= 9:
                kuikae.append(str(b + 1) + called_tile[1])
            elif n > b and a - 1 >= 1:
                kuikae.append(str(a - 1) + called_tile[1])
        return kuikae

    def _has_non_kuikae_discard(self, seat, kind, called_tile, own):
        rem = list(self.hands[seat])
        for t in own:
            rem.remove(t)
        kuikae = set(self._kuikae_tiles(kind, called_tile, own))
        return any(norm(t) not in kuikae for t in rem)

    def _pon_combos(self, seat, tile, same):
        combos = []
        seen = set()
        for i in range(len(same)):
            for j in range(i + 1, len(same)):
                pair = [same[i], same[j]]
                key = tuple(pair)
                if key in seen:
                    continue
                seen.add(key)
                if self._has_non_kuikae_discard(seat, 'pon', tile, pair):
                    combos.append(pair)
        return combos

    def _chi_combos(self, seat, tile):
        n = int(norm(tile)[0])
        s = tile[1]
        hand = self.hands[seat]
        combos = []
        seen = set()
        for a, b in ((n - 2, n - 1), (n - 1, n + 1), (n + 1, n + 2)):
            if a < 1 or b > 9:
                continue
            ta = [t for t in hand if norm(t) == str(a) + s]
            tb = [t for t in hand if norm(t) == str(b) + s]
            if ta and tb:
                for x in sorted(set(ta), key=tile_key):
                    for y in sorted(set(tb), key=tile_key):
                        pair = [x, y]
                        key = tuple(pair)
                        if key in seen:
                            continue
                        seen.add(key)
                        if self._has_non_kuikae_discard(seat, 'chi', tile, pair):
                            combos.append(pair)
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
        return {t for t in ALL_TILES if can_hu(h + [t], melds_n)}

    def _is_furiten(self, seat):
        if self.temp_furiten[seat] or self.riichi_furiten[seat]:
            return True
        h = norm_list(self.hands[seat])
        mn = self.melds_plain(seat, True)
        if len(h) + 3 * len(mn) != 13:
            return False
        for t in {norm(r['tile']) for r in self.rivers[seat]}:
            if can_hu(h + [t], mn):
                return True
        return False

    def _make_state(self, seat, is_tsumo, chankan=False, include_ura=False):
        last = self.remaining() == 0
        return {
            'riichi': self.riichi[seat],
            'ippatsu': self.ippatsu[seat],
            'haitei': is_tsumo and last and not self.is_rinshan_draw,
            'houtei': (not is_tsumo) and (not chankan) and last,
            'rinshan': is_tsumo and self.is_rinshan_draw,
            'chankan': chankan,
            'double_riichi': self.double_riichi[seat],
            'tenhou': is_tsumo and seat == self.oya and self.first_turn[seat] and self.no_call_yet,
            'chiihou': is_tsumo and seat != self.oya and self.first_turn[seat] and self.no_call_yet,
            'ankan_indices': self.ankan_indices(seat),
            'ura_dora': self.ura_dora_list() if (include_ura and self.riichi[seat]) else [],
        }

    def _win_ok(self, seat, hand14, win_tile, is_tsumo, chankan=False):
        """形能和 + 有至少 1 番真役（不含宝牌）。"""
        hn = norm_list(hand14)
        mn = self.melds_plain(seat, True)
        if not can_hu(hn, mn):
            return False
        state = self._make_state(seat, is_tsumo, chankan=chankan, include_ura=False)
        ev = evaluate_hand(
            hn, mn, norm(win_tile), is_tsumo, self.bakaze, self.jikaze(seat),
            [], state, is_oya=(seat == self.oya), rules=self.rules,
        )
        return ev['valid']

    def _can_ron(self, seat, tile, chankan=False):
        if self._is_furiten(seat):
            return False
        return self._win_ok(seat, self.hands[seat] + [tile], tile, False, chankan=chankan)

    def _can_ron_ankan(self, seat, norm_tile):
        """国士无双可抢暗杠。"""
        if self.melds[seat] or self._is_furiten(seat):
            return False
        from collections import Counter
        counts = Counter(norm_list(self.hands[seat]) + [norm_tile])
        return yaku_kokushi(counts, norm_tile) > 0

    # ---------- 合法操作 ----------
    def get_legal_actions(self, seat):
        if self.phase == 'discard' and seat == self.current:
            return self._turn_actions(seat)
        if self.phase == 'call' and seat in self.call_options and seat not in self.responses:
            return list(self.call_options[seat]) + [{'type': 'pass'}]
        return []

    def _turn_actions(self, seat):
        acts = []
        hand = self._full_hand(seat)
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
        if (not self.riichi[seat] and self.is_menzen(seat)
                and self.scores[seat] >= 1000 and self.remaining() >= 4):
            mn = self.melds_plain(seat, True)
            rt = []
            for t in sorted(set(hand), key=tile_key):
                h = list(hand)
                h.remove(t)
                if self._is_tenpai(h, mn):
                    rt.append(t)
            if rt:
                acts.append({'type': 'riichi', 'tiles': rt})

        # 暗杠、加杠
        if self.rinshan_used < 4 and self.remaining() > 0:
            counts = {}
            for t in hand:
                counts[norm(t)] = counts.get(norm(t), 0) + 1
            ankans = []
            for t in sorted(counts, key=tile_key):
                if counts[t] == 4:
                    if self.riichi[seat]:
                        if norm(self.drawn) != t or not self._riichi_ankan_ok(seat, t):
                            continue
                    ankans.append(t)
            if ankans:
                acts.append({'type': 'ankan', 'tiles': ankans})

            if not self.riichi[seat]:
                kakans = []
                for m in self.melds[seat]:
                    mt = norm(m['tiles'][0])
                    if m['type'] == 'pon' and mt in counts:
                        kakans.append(mt)
                if kakans:
                    acts.append({'type': 'kakan', 'tiles': sorted(set(kakans), key=tile_key)})

        # 九种九牌
        if self.first_turn[seat] and self.no_call_yet:
            kinds = {norm(t) for t in hand if is_yaochu(t)}
            if len(kinds) >= 9:
                acts.append({'type': 'kyuushu'})
        return acts

    def _riichi_ankan_ok(self, seat, t):
        """立直后暗杠：听牌种类不变，且杠牌在所有和牌拆法中都必须是刻子（不改变面子构成）。"""
        hand13 = norm_list(self.hands[seat])
        mn = self.melds_plain(seat, True)
        before = self._waits(hand13, mn)
        if not before:
            return False
        h_after = [x for x in norm_list(self._full_hand(seat)) if x != t]
        after = self._waits(h_after, mn + [[t] * 4])
        if before != after:
            return False
        from collections import Counter
        need_groups = 4 - len(mn)
        for w in before:
            c = Counter(hand13 + [w])
            if not mn and (yaku_chiitoitsu(c) or yaku_kokushi(c, w)):
                return False
            splits = list(split_hand(c, need_groups))
            if not splits:
                return False
            for _pair, groups in splits:
                if not any(kind == 'triplet' and rep == t for kind, rep, _ in groups):
                    return False
        return True

    # ---------- 玩家操作 ----------
    def do_action(self, seat, action, tile=None, tiles=None, tsumogiri=None):
        """执行玩家操作。action 支持 discard / riichi / tsumo / ron / chi / pon /
        minkan / ankan / kakan / kyuushu / pass（也兼容旧名 kan）。"""
        if self.phase == 'end':
            raise ValueError('这局已经结束了')
        if seat not in (0, 1, 2, 3):
            raise ValueError('座位号不合法')

        legal = self.get_legal_actions(seat)
        if not legal:
            raise ValueError('现在不该你操作')

        # 兼容旧调用方传 'kan'
        if action == 'kan':
            if self.phase == 'call':
                action = 'minkan'
            else:
                if any(a['type'] == 'ankan' and (tile is None or norm(tile) in a['tiles']) for a in legal):
                    action = 'ankan'
                elif any(a['type'] == 'kakan' and (tile is None or norm(tile) in a['tiles']) for a in legal):
                    action = 'kakan'

        types = [a['type'] for a in legal]
        if action not in types:
            raise ValueError('现在不能执行 ' + str(action))

        if self.phase == 'discard':
            if action == 'discard':
                ok = [a for a in legal if a['type'] == 'discard'][0]['tiles']
                if tile not in ok:
                    raise ValueError('不能打这张牌')
                self._discard(seat, tile, riichi=False, tsumogiri=tsumogiri)
            elif action == 'riichi':
                ok = [a for a in legal if a['type'] == 'riichi'][0]['tiles']
                if tile not in ok:
                    raise ValueError('打这张牌不能立直')
                self._discard(seat, tile, riichi=True, tsumogiri=tsumogiri)
            elif action == 'tsumo':
                self._win_tsumo(seat)
            elif action == 'ankan':
                ok = [a for a in legal if a['type'] == 'ankan'][0]['tiles']
                target = ok[0] if tile is None else norm(tile)
                if target not in ok:
                    raise ValueError('不能暗杠这张牌')
                self._ankan(seat, target)
            elif action == 'kakan':
                ok = [a for a in legal if a['type'] == 'kakan'][0]['tiles']
                target = ok[0] if tile is None else norm(tile)
                if target not in ok:
                    raise ValueError('不能加杠这张牌')
                self._kakan(seat, target)
            elif action == 'kyuushu':
                self._abort('kyuushu')
        else:
            if action in ('chi', 'pon'):
                cand = [a for a in legal if a['type'] == action]
                if tiles is None:
                    pick = cand[0]
                else:
                    if not isinstance(tiles, list) or len(tiles) != 2:
                        raise ValueError('吃/碰必须指定手里拿出的两张牌')
                    pick = None
                    for a in cand:
                        if sorted(a['tiles']) == sorted(tiles):
                            pick = a
                            break
                    if pick is None:
                        raise ValueError('没有这个吃/碰组合')
                self.responses[seat] = pick
            elif action == 'minkan':
                pick = [a for a in legal if a['type'] == 'minkan'][0]
                self.responses[seat] = pick
            else:
                self.responses[seat] = {'type': action}
            self._try_resolve()
        self._run()

    # ---------- 电脑玩家 ----------
    def _cpu_turn(self, seat):
        acts = self._turn_actions(seat)
        if any(a['type'] == 'tsumo' for a in acts):
            self._win_tsumo(seat)
            return
        if self.drawn is not None:
            self._discard(seat, self.drawn, tsumogiri=True)
        else:
            self._discard(seat, acts[0]['tiles'][-1], tsumogiri=False)

    def _cpu_response(self, seat):
        for o in self.call_options[seat]:
            if o['type'] == 'ron':
                return o
        return {'type': 'pass'}

    def _run(self):
        """电脑自动完成所有可做操作，直到轮到人类玩家或一局结束。"""
        while self.phase != 'end':
            if self.phase == 'discard':
                if self.current in self.human_seats:
                    return
                self._cpu_turn(self.current)
            elif self.phase == 'call':
                for s in list(self.call_options):
                    if s not in self.human_seats and s not in self.responses:
                        self.responses[s] = self._cpu_response(s)
                if not self._try_resolve():
                    return

    # ---------- 鸣牌与抢杠结算 ----------
    def _try_resolve(self):
        if self.phase != 'call':
            return True
        for s in self.call_options:
            if s not in self.responses:
                return False
        self._resolve_calls()
        return True

    def _mark_missed_furiten(self, actor, tile, rons, ankan_only=False):
        """有人打出或加杠/暗杠某牌而未荣和时，更新同巡振听与立直后振听（含役なし见逃）。"""
        nt = norm(tile)
        for s in range(4):
            if s == actor or s in rons:
                continue
            missed = False
            if ankan_only:
                missed = any(o['type'] == 'ron' for o in self.call_options.get(s, []))
            else:
                if any(o['type'] == 'ron' for o in self.call_options.get(s, [])):
                    missed = True
                else:
                    mn = self.melds_plain(s, True)
                    if can_hu(norm_list(self.hands[s]) + [nt], mn):
                        missed = True
            if missed:
                self.temp_furiten[s] = True
                if self.riichi[s]:
                    self.riichi_furiten[s] = True

    def _resolve_calls(self):
        resp = self.responses

        # 抢杠响应结算
        if self.pending_kan is not None:
            kind, actor, kan_tile = self.pending_kan
            order = [(actor + i) % 4 for i in (1, 2, 3)]
            rons = [s for s in order if resp.get(s, {}).get('type') == 'ron']
            self._mark_missed_furiten(actor, kan_tile, rons, ankan_only=(kind == 'ankan'))
            self.pending_kan = None
            self.call_options = {}
            self.responses = {}
            if len(rons) == 3:
                self._abort('triple_ron')
                return
            if rons:
                self._win_ron(rons, actor, kan_tile, chankan=True)
                return
            if kind == 'kakan':
                self._complete_kakan(actor, kan_tile)
            else:
                self._complete_ankan(actor, kan_tile)
            return

        discarder, tile = self.last_discard
        order = [(discarder + i) % 4 for i in (1, 2, 3)]
        rons = [s for s in order if resp.get(s, {}).get('type') == 'ron']
        self._mark_missed_furiten(discarder, tile, rons, ankan_only=False)

        if len(rons) == 3:
            self._pay_riichi_stick()
            self._abort('triple_ron')
            return
        if rons:
            # 宣言牌被荣和时，立直不成立
            if self.riichi_pending == discarder:
                self.riichi[discarder] = False
                self.double_riichi[discarder] = False
                self.ippatsu[discarder] = False
                self.riichi_pending = None
            self._win_ron(rons, discarder, tile, chankan=False)
            return

        # 碰 / 明杠 优先于 吃
        for s in order:
            r = resp.get(s, {})
            if r.get('type') in ('pon', 'minkan'):
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
            self._abort('four_riichi')
            return
        # 四风连打
        if self.no_call_yet and all(len(r) == 1 for r in self.rivers):
            first = [norm(r[0]['tile']) for r in self.rivers]
            if first[0] in ('1z', '2z', '3z', '4z') and len(set(first)) == 1:
                self._abort('four_winds')
                return
        # 四杠散了（2 人及以上累计开杠 4 次）
        if len(self.kan_seats) == 4 and len(set(self.kan_seats)) >= 2:
            self._abort('four_kans')
            return
        if self.remaining() == 0:
            self._exhaustive_draw()
            return
        self._draw((discarder + 1) % 4)

    def _interrupt(self):
        """有人鸣牌或开杠：一发、天和地和、两立直、九种九牌机会消失。"""
        self.no_call_yet = False
        self.ippatsu = [False] * 4
        self.first_turn = [False] * 4

    def _call_meld(self, seat, discarder, tile, kind, own):
        self._interrupt()
        hand = self.hands[seat]
        for t in own:
            hand.remove(t)
        hand.sort(key=tile_key)
        last_river = self.rivers[discarder][-1]
        last_river['called'] = True
        if last_river.get('riichi'):
            # 立直宣言牌被鸣走，下次打牌再横放
            self.riichi_tile_needed[discarder] = True

        meld_tiles = sorted(own + [tile], key=tile_key)
        self.melds[seat].append({
            'type': kind,
            'tiles': meld_tiles,
            'from': discarder,
            'called_tile': tile,
        })
        self._emit({
            'type': kind,
            'seat': seat,
            'tiles': list(meld_tiles),
            'from': discarder,
        })

        if kind == 'minkan':
            self.pending_dora += 1
            self.kan_seats.append(seat)
            self._draw(seat, rinshan=True)
            return

        self.current = seat
        self.drawn = None
        self.after_call = True
        self.kuikae = self._kuikae_tiles(kind, tile, own)
        self.phase = 'discard'

    def _ankan(self, seat, norm_t):
        # 之前若还有明杠/加杠待翻的杠宝牌，连续开杠时先翻开
        self._flip_pending_dora()
        opts = {}
        for i in (1, 2, 3):
            s = (seat + i) % 4
            if self._can_ron_ankan(s, norm_t):
                opts[s] = [{'type': 'ron', 'tile': norm_t}]
        if opts:
            self.pending_kan = ('ankan', seat, norm_t)
            self.call_options = opts
            self.responses = {}
            self.phase = 'call'
            return
        self._complete_ankan(seat, norm_t)

    def _complete_ankan(self, seat, norm_t):
        self._interrupt()
        if self.drawn is not None:
            self.hands[seat].append(self.drawn)
            self.drawn = None
        own = sorted([x for x in self.hands[seat] if norm(x) == norm_t], key=tile_key)
        for x in own:
            self.hands[seat].remove(x)
        self.hands[seat].sort(key=tile_key)
        self.melds[seat].append({
            'type': 'ankan',
            'tiles': own,
            'from': None,
            'called_tile': None,
        })
        self._emit({'type': 'ankan', 'seat': seat, 'tile': norm_t})
        self._flip_kan_dora()
        self.kan_seats.append(seat)
        self._draw(seat, rinshan=True)

    def _kakan(self, seat, norm_t):
        self._flip_pending_dora()
        if self.drawn is not None and norm(self.drawn) == norm_t:
            x = self.drawn
        else:
            x = [y for y in self.hands[seat] if norm(y) == norm_t][0]
        opts = {}
        for i in (1, 2, 3):
            s = (seat + i) % 4
            if self._can_ron(s, x, chankan=True):
                opts[s] = [{'type': 'ron', 'tile': x}]
        if opts:
            self.pending_kan = ('kakan', seat, x)
            self.call_options = opts
            self.responses = {}
            self.phase = 'call'
            return
        # 无人可抢杠时，也要检查是否有役なし听牌被跳过而触发同巡振听
        self._mark_missed_furiten(seat, x, [], ankan_only=False)
        self._complete_kakan(seat, x)

    def _complete_kakan(self, seat, x):
        self._interrupt()
        if self.drawn is not None:
            if x == self.drawn:
                self.drawn = None
            else:
                self.hands[seat].remove(x)
                self.hands[seat].append(self.drawn)
                self.hands[seat].sort(key=tile_key)
                self.drawn = None
        else:
            self.hands[seat].remove(x)
            self.hands[seat].sort(key=tile_key)
        nt = norm(x)
        for m in self.melds[seat]:
            if m['type'] == 'pon' and norm(m['tiles'][0]) == nt:
                m['type'] = 'kakan'
                m['tiles'] = sorted(m['tiles'] + [x], key=tile_key)
                break
        self._emit({'type': 'kakan', 'seat': seat, 'tile': nt})
        self.pending_dora += 1
        self.kan_seats.append(seat)
        self._draw(seat, rinshan=True)

    # ---------- 和牌结算 ----------
    def _score_one(self, seat, hand13, win_tile, is_tsumo, from_seat,
                   honba, kyotaku, chankan=False):
        melds = self.melds_plain(seat)
        state = self._make_state(seat, is_tsumo, chankan=chankan, include_ura=True)
        dora = self.dora_list(with_ura=False)
        is_oya = (seat == self.oya)
        ev = evaluate_hand(
            list(hand13) + [win_tile], melds, win_tile, is_tsumo,
            self.bakaze, self.jikaze(seat), dora, state,
            is_oya=is_oya, rules=self.rules,
        )
        sc = calc_score(
            ev['fu'], ev['han'], is_oya, is_tsumo, honba, kyotaku,
            kiriage_mangan=self.rules['kiriage_mangan'],
            yakuman=ev['yakuman'],
        )
        delta = [0] * 4
        delta[seat] += sc['get']
        if is_tsumo:
            for s in range(4):
                if s == seat:
                    continue
                if is_oya:
                    delta[s] -= sc['ko_pay']
                else:
                    delta[s] -= sc['oya_pay'] if s == self.oya else sc['ko_pay']
        else:
            delta[from_seat] -= sc['ron_pay']

        melds_copy = [
            {
                'type': m['type'],
                'tiles': list(m['tiles']),
                'from': m['from'],
                'called_tile': m['called_tile'],
            }
            for m in self.melds[seat]
        ]
        info = {
            'seat': seat,
            'from': from_seat,
            'hand': list(hand13),
            'melds': melds_copy,
            'win_tile': win_tile,
            'yaku': ev['yaku'],
            'han': ev['han'],
            'fu': ev['fu'],
            'yakuman': ev['yakuman'],
            'points': sc['base_points'],
            'delta': delta,
        }
        return info, delta

    def _win_tsumo(self, seat):
        win_tile = self.drawn
        hand13 = list(self.hands[seat])
        self._emit({'type': 'tsumo', 'seat': seat})
        info, delta = self._score_one(
            seat, hand13, win_tile, True, None, self.honba, self.kyotaku, chankan=False,
        )
        self.kyotaku = 0
        result = {
            'type': 'agari',
            'wins': [info],
            'dora_indicators': self.dora_indicators(),
            'uradora_indicators': self.ura_indicators() if self.riichi[seat] else [],
        }
        self._end_round(result, delta, seat == self.oya, True)

    def _win_ron(self, winners, discarder, tile, chankan=False):
        total = [0] * 4
        wins = []
        for i, s in enumerate(winners):
            self._emit({'type': 'ron', 'seat': s, 'from': discarder})
            hb = self.honba if i == 0 else 0
            kt = self.kyotaku if i == 0 else 0
            info, delta = self._score_one(
                s, list(self.hands[s]), tile, False, discarder, hb, kt, chankan=chankan,
            )
            wins.append(info)
            for k in range(4):
                total[k] += delta[k]
        self.kyotaku = 0
        any_riichi = any(self.riichi[s] for s in winners)
        result = {
            'type': 'agari',
            'wins': wins,
            'dora_indicators': self.dora_indicators(),
            'uradora_indicators': self.ura_indicators() if any_riichi else [],
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
        self._emit({'type': 'ryuukyoku', 'reason': 'exhaustive'})
        result = {
            'type': 'ryuukyoku',
            'reason': 'exhaustive',
            'tenpai': tenpai,
        }
        self._end_round(result, delta, tenpai[self.oya], False, draw=True)

    def _abort(self, reason):
        self._emit({'type': 'ryuukyoku', 'reason': reason})
        result = {
            'type': 'ryuukyoku',
            'reason': reason,
        }
        self._end_round(result, [0] * 4, True, False, draw=True)

    # ---------- 一局结束与换庄 ----------
    def _end_round(self, result, delta, renchan, is_win, draw=False):
        delta = list(delta)
        for s in range(4):
            self.scores[s] += delta[s]
        self.phase = 'end'
        self.drawn = None
        self.call_options = {}
        self.responses = {}
        self.pending_kan = None
        self.next_renchan = renchan
        self.next_honba = self.honba + 1 if (renchan or draw) else 0
        self.game_over = self._check_game_over(renchan, is_win)
        if self.game_over and self.kyotaku > 0:
            top = max(range(4), key=lambda s: (self.scores[s], -s))
            bonus = self.kyotaku * 1000
            self.scores[top] += bonus
            delta[top] += bonus
            self.kyotaku = 0
        result['delta'] = delta
        self.result = result

    def _check_game_over(self, renchan, is_win):
        if any(s < 0 for s in self.scores):
            return True
        k = self.kyoku
        base_rounds = 4 if self.length == 'tonpuu' else 8
        max_rounds = 8 if self.length == 'tonpuu' else 12
        top_seat = max(range(4), key=lambda s: (self.scores[s], -s))
        top_score = self.scores[top_seat]

        if k >= base_rounds:
            # 延长战（东风南入 / 半庄西入）：有人达到 30000 即终局，打完延长风第 4 局不连庄也终局
            if top_score >= RETURN_POINTS:
                return True
            return k == max_rounds - 1 and not renchan
        if k == base_rounds - 1:
            if renchan:
                # 和了止め：All Last 庄家和了且严格为 1 位（含起家顺同分裁定）并满 30000 点
                if is_win and top_seat == self.oya and top_score >= RETURN_POINTS:
                    return True
                return False
            return top_score >= RETURN_POINTS
        return False

    def next_round(self, wall=None):
        if self.phase != 'end':
            raise ValueError('这局还没结束')
        if self.game_over:
            raise ValueError('整场游戏已经结束了')
        if not self.next_renchan:
            self.kyoku += 1
        self.honba = self.next_honba
        self.start_round(wall)

    # ---------- 接口状态拼装 ----------
    def waiting_for(self):
        if self.phase == 'discard':
            return [self.current] if self.current in self.human_seats else []
        if self.phase == 'call':
            return sorted(
                s for s in self.call_options
                if s in self.human_seats and s not in self.responses
            )
        return []

    def _format_legal_actions(self, seat):
        if self.phase == 'end':
            return []
        res = []
        chi_opts = []
        pon_opts = []
        for a in self.get_legal_actions(seat):
            t = a['type']
            if t == 'chi':
                chi_opts.append(list(a['tiles']))
            elif t == 'pon':
                pon_opts.append(list(a['tiles']))
            elif t in ('discard', 'riichi', 'ankan', 'kakan'):
                res.append({'type': t, 'tiles': list(a['tiles'])})
            elif t in ('minkan', 'tsumo', 'ron', 'kyuushu', 'pass'):
                res.append({'type': t})
        if pon_opts:
            res.append({'type': 'pon', 'options': pon_opts})
        if chi_opts:
            res.append({'type': 'chi', 'options': chi_opts})
        return res

    def _build_hints(self, seat):
        if self.phase == 'end':
            return None
        full = self._full_hand(seat)
        melds = self.melds_plain(seat)
        visible = self.get_visible(seat)
        total = len(full) + 3 * len(melds)

        def fmt_waits(wdict):
            return [
                {'tile': t, 'left': wdict[t]}
                for t in sorted(wdict, key=tile_key)
            ]

        if total == 14:
            legal = self.get_legal_actions(seat)
            allowed = set()
            for a in legal:
                if a['type'] == 'discard':
                    allowed = set(a['tiles'])
                    break
            raw = discard_hints(full, melds, visible)
            discards = {
                t: fmt_waits(w)
                for t, w in raw.items()
                if (not allowed or t in allowed)
            }
            return {
                'waits': [],
                'furiten': False,
                'discards': discards,
            }
        elif total == 13:
            w = get_waits(full, melds, visible)
            return {
                'waits': fmt_waits(w),
                'furiten': bool(w) and self._is_furiten(seat),
                'discards': {},
            }
        return {'waits': [], 'furiten': False, 'discards': {}}

    def _format_result(self):
        if self.result is None:
            return None
        r = self.result
        if r['type'] == 'agari':
            wins = []
            for w in r['wins']:
                wins.append({
                    'seat': w['seat'],
                    'from': w['from'],
                    'hand': list(w['hand']),
                    'melds': [
                        {
                            'type': m['type'],
                            'tiles': list(m['tiles']),
                            'from': m['from'],
                            'called_tile': m['called_tile'],
                        }
                        for m in w['melds']
                    ],
                    'win_tile': w['win_tile'],
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
                'uradora_indicators': list(r['uradora_indicators']),
                'delta': list(r['delta']),
            }
        out = {
            'type': 'ryuukyoku',
            'reason': r['reason'],
            'delta': list(r['delta']),
        }
        if 'tenpai' in r:
            out['tenpai'] = list(r['tenpai'])
        return out

    def to_api_state(self, viewer=0, game_id='g1'):
        """返回严格符合 frontend/接口说明.md 的状态对象。"""
        if viewer not in (0, 1, 2, 3):
            raise ValueError('seat 必须是 0~3')
        if self.phase == 'end':
            phase = 'game_end' if self.game_over else 'round_end'
        else:
            phase = 'playing'

        players = []
        for s in range(4):
            p = {
                'seat': s,
                'name': self.player_names[s],
                'score': self.scores[s],
                'seat_wind': self.jikaze(s),
                'riichi': self.riichi[s],
                'discards': [dict(d) for d in self.rivers[s]],
                'melds': [
                    {
                        'type': m['type'],
                        'tiles': list(m['tiles']),
                        'from': m['from'],
                        'called_tile': m['called_tile'],
                    }
                    for m in self.melds[s]
                ],
                'hand_count': len(self.hands[s]),
            }
            if s == viewer:
                p['hand'] = list(self.hands[s])
            players.append(p)

        events = []
        for e in self.events:
            ec = dict(e)
            if ec['type'] == 'draw' and ec['seat'] != viewer:
                ec['tile'] = None
            events.append(ec)

        drawn = self.drawn if (self.phase == 'discard' and viewer == self.current) else None

        return {
            'version': 1,
            'game_id': str(game_id),
            'phase': phase,
            'round': {
                'wind': self.bakaze,
                'number': (self.kyoku % 4) + 1,
                'honba': self.honba,
                'riichi_sticks': self.kyotaku,
                'dealer': self.oya,
            },
            'dora_indicators': self.dora_indicators(),
            'wall_left': self.remaining(),
            'viewer': viewer,
            'turn': self.current,
            'waiting_for': self.waiting_for() if phase == 'playing' else [],
            'rules': dict(self.rules),
            'players': players,
            'drawn': drawn,
            'legal_actions': self._format_legal_actions(viewer) if phase == 'playing' else [],
            'hints': self._build_hints(viewer),
            'events': events,
            'result': self._format_result(),
        }

    # 兼容旧方法名
    def get_state(self, seat=0):
        return self.to_api_state(viewer=0 if seat is None else seat)
