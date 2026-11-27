# 学号 250207
# game.py —— 整局流程：洗牌发牌、摸打、吃碰杠、立直、流局、连庄换庄、本场、电脑玩家
#
# 修改说明（qwen4-max 整理，改动较多，逐条列在这里）：
# 1. 牌山顺序改成前端《接口说明》的约定：wall[0:13]/[13:26]/[26:39]/[39:52] 固定按
#    物理座位 0/1/2/3 配牌（原来按庄家轮，第二局起就和前端对不上）；wall[52] 起庄家先摸；
#    王牌 wall[122:127] 宝牌指示牌、[127:132] 里宝、[132:136] 岭上（原来岭上放在王牌开头）。
# 2. 算分接口对齐：score.calc_score 返回 dict（原来按元组拆会 KeyError，一和牌就崩）；
#    给 yaku 传 state['ankan_indices']（暗杠下标）、state['ura_dora']（里宝）、地和键 chiihou；
#    给 fu 传 an_gang（暗杠列表）。原来暗杠没标，被当明杠，破门清、符也算错。
# 3. 符和番联合取“点数最高”的拆法（fu_candidates + yaku_candidates），不再各取各的。
# 4. 规则开关 rules：aka_dora / kuitan / kiriage_mangan / renpu_fu，整场生效并回显。
# 5. length：tonpuu 东风战 / hanchan 半庄战，固定局数 + 被飞结束（不做南入延长）。
# 6. 记录 tsumogiri（摸切）和 events 事件流，供前端显示。
# 7. 碰有多个选项（含红五）时全部列出，让玩家选；吃同理。
# 8. 补上四杠散了、抢杠（加杠时可荣和）；杠宝牌沿用“杠完立刻翻”的简化。
# 9. 终局剩余供托给第一名，并计入最后一局 delta。
#
# 用法（给 250226 接 server 用）：
#   g = Game(human_seats=[0], rules={...}, length='tonpuu')
#   g = Game(human_seats=[0], wall=牌山)   # 指定牌山（136 张）测试用
#   g.get_state(seat)                # 当前状态 dict（前端格式，version/game_id 由 server 补）
#   g.do_action(seat, 'discard', tile='3m', tsumogiri=False)
#   g.next_round()                   # 一局结束后进下一局

import random
from itertools import combinations

from fu import calc_fu, fu_candidates
from yaku import calc_yaku, yaku_candidates
from score import calc_score
from tenpai import can_hu


START_POINTS = 25000

ALL_TILES = [str(n) + s for s in 'mps' for n in range(1, 10)] + [str(n) + 'z' for n in range(1, 8)]

DEFAULT_RULES = {'aka_dora': True, 'kuitan': True, 'kiriage_mangan': False, 'renpu_fu': 4}


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
        self.rng = random.Random(seed)
        self.human_seats = set(human_seats)
        self.rules = dict(DEFAULT_RULES)
        if rules:
            for k, v in rules.items():
                if k in self.rules and v is not None:
                    self.rules[k] = v
        if self.rules['renpu_fu'] not in (2, 4):
            self.rules['renpu_fu'] = 4
        self.length = length if length in ('tonpuu', 'hanchan') else 'tonpuu'
        self.scores = [START_POINTS] * 4
        self.kyoku = 0      # 0~3 = 东1~东4，4~7 = 南1~南4
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

    def ankan_indices(self, seat):
        return [i for i, m in enumerate(self.melds[seat]) if m['type'] == 'ankan']

    def is_menzen(self, seat):
        return all(m['type'] == 'ankan' for m in self.melds[seat])

    def dora_indicators(self):
        return [self.dead_wall[i] for i in range(self.dora_count)]

    def ura_indicators(self):
        return [self.dead_wall[5 + i] for i in range(self.dora_count)]

    def dora_list(self, with_ura=False):
        res = [dora_from_indicator(t) for t in self.dora_indicators()]
        if with_ura:
            res += [dora_from_indicator(t) for t in self.ura_indicators()]
        return res

    def get_visible(self, seat):
        """听牌提示用：除自己手牌外场上能看到的牌（河 + 所有副露 + 宝牌指示牌）。
        注意含副露，tenpai.get_waits 里不再重复扣。
        被鸣走的舍张（called）已经算在副露里，河里需要跳过，否则会被扣两次。"""
        vis = []
        for s in range(4):
            vis += [r['tile'] for r in self.rivers[s] if not r['called']]
            for m in self.melds[s]:
                vis += m['tiles']
        vis += self.dora_indicators()
        return vis

    # ---------- 一局开始 ----------
    def start_round(self, wall=None):
        if wall is None:
            wall = make_wall(self.rules['aka_dora'])
            self.rng.shuffle(wall)
        else:
            wall = list(wall)
            if len(wall) != 136:
                raise ValueError('牌山要 136 张')
            if not self.rules['aka_dora']:
                wall = [norm(t) for t in wall]   # 没赤宝牌时红五当普通五
        # 牌山顺序（按前端《接口说明》）：
        #   wall[0:13]/[13:26]/[26:39]/[39:52]  物理座位 0/1/2/3 的配牌
        #   wall[52:122]  正常摸牌，当前庄家先摸 wall[52]
        #   wall[122:127] 宝牌指示牌、[127:132] 里宝、[132:136] 岭上
        self.wall = wall
        self.dead_wall = wall[122:136]
        self.wall_pos = 52
        self.wall_end = 122
        self.rinshan_used = 0
        self.dora_count = 1

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
        self.events = []
        self.pending_kakan = None
        self.chankan_mode = False
        self.four_kans_pending = False

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
    def _draw(self, seat, rinshan=False):
        if rinshan:
            t = self.dead_wall[10 + self.rinshan_used]
            self.rinshan_used += 1
            self.wall_end -= 1   # 王牌保持 14 张，海底往前挪一张
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
            tsumogiri = (tile == self.drawn)
        hand = self.hands[seat]
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
                opts.append({'type': 'ron'})
            if not self.riichi[s] and not last and not self.four_kans_pending:   # 河底/四杠散了那张不能鸣
                same = [t for t in self.hands[s] if norm(t) == norm(tile)]
                if len(same) >= 2:
                    pon_opts = [o for o in self._pon_options(same)
                                if self._discardable_after_call(s, tile, o, 'pon')]
                    if pon_opts:
                        opts.append({'type': 'pon', 'options': pon_opts})
                if len(same) >= 3 and self.rinshan_used < 4:
                    opts.append({'type': 'minkan'})
                if i == 1 and tile[1] != 'z':
                    combos = self._chi_combos(s, tile)
                    if combos:
                        opts.append({'type': 'chi', 'options': combos})
            if opts:
                self.call_options[s] = opts
        self.phase = 'call'

    def _pon_options(self, same):
        seen = set()
        opts = []
        for a, b in combinations(same, 2):
            key = tuple(sorted((a, b), key=tile_key))
            if key not in seen:
                seen.add(key)
                opts.append(list(key))
        return opts

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
                for x in sorted(set(ta), key=tile_key):
                    for y in sorted(set(tb), key=tile_key):
                        # 食替后手里一张能打的都不剩的吃法，不该让吃
                        if self._discardable_after_call(seat, tile, [x, y], 'chi'):
                            combos.append([x, y])
        return combos

    def _discardable_after_call(self, seat, tile, own, kind):
        """吃/碰后（未摸牌）手里是否还有至少一张不受食替限制、能打的牌。"""
        hand = list(self.hands[seat])
        for t in own:
            if t in hand:
                hand.remove(t)
        forbid = {norm(tile)}
        if kind == 'chi':
            a, b = sorted(int(norm(t)[0]) for t in own)
            n = int(norm(tile)[0])
            if n < a and b + 1 <= 9:
                forbid.add(str(b + 1) + tile[1])
            elif n > b and a - 1 >= 1:
                forbid.add(str(a - 1) + tile[1])
        return any(norm(t) not in forbid for t in hand)

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
        for t in set(norm(r['tile']) for r in self.rivers[seat]):
            if can_hu(h + [t], mn):
                return True
        return False

    def _make_state(self, seat, is_tsumo):
        last = self.remaining() == 0
        return {
            'riichi': self.riichi[seat],
            'ippatsu': self.ippatsu[seat],
            'haitei': is_tsumo and last and not self.is_rinshan_draw,
            'houtei': (not is_tsumo) and last and not self.chankan_mode,
            'rinshan': is_tsumo and self.is_rinshan_draw,
            'chankan': self.chankan_mode and not is_tsumo,
            'double_riichi': self.double_riichi[seat],
            'tenhou': is_tsumo and seat == self.oya and self.first_turn[seat] and self.no_call_yet,
            'chiihou': is_tsumo and seat != self.oya and self.first_turn[seat] and self.no_call_yet,
            'ankan_indices': self.ankan_indices(seat),
        }

    def _win_ok(self, seat, hand14, win_tile, is_tsumo):
        """形能和 + 有役。不传宝牌、手牌换 5m，0 番就是没役"""
        hn = norm_list(hand14)
        mn = self.melds_plain(seat, True)
        if not can_hu(hn, mn):
            return False
        state = self._make_state(seat, is_tsumo)
        yaku, han = calc_yaku(hn, mn, norm(win_tile), is_tsumo, self.bakaze,
                              self.jikaze(seat), [], state, self.rules)
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
                discards = [t for t in discards if norm(t) not in self.kuikae] or discards
        acts.append({'type': 'discard', 'tiles': discards})
        if self.after_call:
            return acts

        if self._win_ok(seat, hand, self.drawn, True):
            acts.append({'type': 'tsumo'})

        # 立直：门清、1000 点以上、牌山剩 4 张以上、打掉某张后听牌
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
            counts = {}
            for t in hand:
                counts[norm(t)] = counts.get(norm(t), 0) + 1
            ankan, kakan = [], []
            for t, c in counts.items():
                if c == 4:
                    if self.riichi[seat]:
                        if norm(self.drawn) != t or not self._riichi_ankan_ok(seat, t):
                            continue
                    ankan.append(t)
            if not self.riichi[seat]:
                for m in self.melds[seat]:
                    if m['type'] == 'pon' and norm(m['tiles'][0]) in counts:
                        kakan.append(norm(m['tiles'][0]))
            if ankan:
                acts.append({'type': 'ankan', 'tiles': ankan})
            if kakan:
                acts.append({'type': 'kakan', 'tiles': kakan})

        # 九种九牌
        if self.first_turn[seat] and self.no_call_yet:
            kinds = set(norm(t) for t in hand if is_yaochu(t))
            if len(kinds) >= 9:
                acts.append({'type': 'kyuushu'})
        return acts

    def _riichi_ankan_ok(self, seat, t):
        hand = list(self.hands[seat])
        hand.remove(self.drawn)
        mn = self.melds_plain(seat, True)
        before = self._waits(hand, mn)
        h2 = [x for x in self.hands[seat] if norm(x) != t]
        after = self._waits(h2, mn + [[t] * 4])
        return before == after and len(before) > 0

    # ---------- 玩家操作 ----------
    def do_action(self, seat, action, tile=None, tiles=None, tsumogiri=None):
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
            elif action == 'ankan':
                t = norm(tile) if tile else legal[[a['type'] for a in legal].index('ankan')]['tiles'][0]
                self._ankan(seat, t)
            elif action == 'kakan':
                t = norm(tile) if tile else legal[[a['type'] for a in legal].index('kakan')]['tiles'][0]
                self._kakan(seat, t)
            elif action == 'kyuushu':
                self._abort('kyuushu')
        else:
            if action in ('chi', 'pon'):
                cand = [a for a in legal if a['type'] == action][0]
                opts = cand['options']
                pick = opts[0]
                if tiles is not None:
                    for o in opts:
                        if sorted(o, key=tile_key) == sorted(tiles, key=tile_key):
                            pick = o
                            break
                    else:
                        raise ValueError('没有这个吃法/碰法')
                self.responses[seat] = {'type': action, 'tiles': pick}
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
        if self.drawn is not None and self.drawn in self.hands[seat]:
            self._discard(seat, self.drawn, tsumogiri=True)
        else:
            self._discard(seat, acts[0]['tiles'][-1])

    def _cpu_response(self, seat):
        for o in self.call_options[seat]:
            if o['type'] == 'ron':
                return o
        return {'type': 'pass'}

    def _run(self):
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
        # 抢杠：加杠时只可能荣和
        if self.pending_kakan:
            seat, t, x = self.pending_kakan
            order = [(seat + i) % 4 for i in (1, 2, 3)]
            rons = [s for s in order if self.responses.get(s, {}).get('type') == 'ron']
            for s, opts in self.call_options.items():
                if any(o['type'] == 'ron' for o in opts) and s not in rons:
                    self.temp_furiten[s] = True
                    if self.riichi[s]:
                        self.riichi_furiten[s] = True
            self.pending_kakan = None
            if rons:
                # 杠被抢：第四张拿走，原来的碰保留
                self.hands[seat].remove(x)
                self.hands[seat].sort(key=tile_key)
                self.chankan_mode = True
                self._win_ron(rons, seat, t)
                self.chankan_mode = False
                return
            self.chankan_mode = False
            self._do_kakan(seat, t, x)
            return

        discarder, tile = self.last_discard
        order = [(discarder + i) % 4 for i in (1, 2, 3)]
        resp = self.responses
        rons = [s for s in order if resp.get(s, {}).get('type') == 'ron']

        for s, opts in self.call_options.items():
            if any(o['type'] == 'ron' for o in opts) and s not in rons:
                self.temp_furiten[s] = True
                if self.riichi[s]:
                    self.riichi_furiten[s] = True

        if len(rons) == 3:
            self._abort('triple_ron')
            return
        if rons:
            # 立直宣言牌被荣和：立直不成立，不交棒，撤掉立直标记（含河里横放）
            if self.riichi_pending == discarder:
                self.riichi[discarder] = False
                self.double_riichi[discarder] = False
                self.ippatsu[discarder] = False
                self.rivers[discarder][-1]['riichi'] = False
                self.riichi_pending = None
            self._win_ron(rons, discarder, tile)
            return
        # 四杠散了：第 4 杠家打出的这张没人荣和就流局（上面已禁止鸣牌）
        if self.four_kans_pending:
            self.four_kans_pending = False
            self._abort('four_kans')
            return
        # 碰/杠优先于吃
        for s in order:
            r = resp.get(s, {})
            if r.get('type') in ('pon', 'minkan'):
                self._pay_riichi_stick()
                self._call_meld(s, discarder, tile, r['type'], r.get('tiles'))
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
        discarder, tile = self.last_discard
        if self._pay_riichi_stick() and all(self.riichi):
            self._abort('four_riichi')
            return
        # 四风连打
        if self.no_call_yet and all(len(r) == 1 for r in self.rivers):
            first = [norm(r[0]['tile']) for r in self.rivers]
            if first[0] in ('1z', '2z', '3z', '4z') and len(set(first)) == 1:
                self._abort('four_winds')
                return
        # 四杠散了已在 _resolve_calls 里按“第4杠家打牌”处理（four_kans_pending）
        if self.remaining() == 0:
            self._exhaustive_draw()
            return
        self._draw((discarder + 1) % 4)

    def _interrupt(self):
        self.no_call_yet = False
        self.ippatsu = [False] * 4
        self.first_turn = [False] * 4

    def _call_meld(self, seat, discarder, tile, kind, own):
        self._interrupt()
        hand = self.hands[seat]
        if kind == 'minkan':
            own = [t for t in hand if norm(t) == norm(tile)][:3]
        for t in own:
            hand.remove(t)
        hand.sort(key=tile_key)   # 鸣牌后手牌需要重新排序
        self.rivers[discarder][-1]['called'] = True
        if kind == 'minkan':
            self.melds[seat].append({'type': 'minkan', 'tiles': own + [tile],
                                     'from': discarder, 'called_tile': tile})
            self.events.append({'type': 'minkan', 'seat': seat,
                                'tiles': own + [tile], 'from': discarder})
            self._after_kan(seat)
            return
        meld_tiles = sorted(own + [tile], key=tile_key)
        self.melds[seat].append({'type': kind, 'tiles': meld_tiles,
                                 'from': discarder, 'called_tile': tile})
        self.events.append({'type': kind, 'seat': seat, 'tiles': meld_tiles, 'from': discarder})
        self.current = seat
        self.drawn = None
        self.after_call = True
        self.phase = 'discard'
        # 食替
        n = int(norm(tile)[0])
        self.kuikae = [norm(tile)]
        if kind == 'chi':
            a, b = sorted(int(norm(t)[0]) for t in own)
            if n < a and b + 1 <= 9:
                self.kuikae.append(str(b + 1) + tile[1])
            elif n > b and a - 1 >= 1:
                self.kuikae.append(str(a - 1) + tile[1])

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
        x = [y for y in self.hands[seat] if norm(y) == t][0]
        # 抢杠：别人能和这张吗。检查时就要把 chankan 置位，
        # 否则 _make_state 里 chankan=False，只有抢杠这一个役的牌会被判成 0 番不让和。
        self.chankan_mode = True
        opts = {}
        for i in (1, 2, 3):
            s = (seat + i) % 4
            if not self._is_furiten(s) and self._win_ok(s, self.hands[s] + [t], t, False):
                opts[s] = [{'type': 'ron'}]
        if opts:
            self.pending_kakan = (seat, t, x)
            self.call_options = opts
            self.responses = {}
            self.last_discard = (seat, t)
            self.phase = 'call'
            return
        self.chankan_mode = False
        self._do_kakan(seat, t, x)

    def _do_kakan(self, seat, t, x):
        self._interrupt()
        self.hands[seat].remove(x)
        self.hands[seat].sort(key=tile_key)
        for m in self.melds[seat]:
            if m['type'] == 'pon' and norm(m['tiles'][0]) == t:
                m['type'] = 'kakan'
                m['tiles'] = m['tiles'] + [x]
                break
        self.events.append({'type': 'kakan', 'seat': seat, 'tile': t})
        self._after_kan(seat)

    def _after_kan(self, seat):
        # 简化：杠完立刻翻杠宝牌（天凤明杠/加杠是打牌后才翻）
        self.dora_count += 1
        self.events.append({'type': 'dora', 'tile': self.dead_wall[self.dora_count - 1]})
        self.kan_seats.append(seat)
        # 四杠散了：两人以上合计第 4 杠后，杠家岭上摸打的那张只能荣和、不能鸣，没人荣和就流局
        if len(self.kan_seats) >= 4 and len(set(self.kan_seats)) >= 2:
            self.four_kans_pending = True
        self._draw(seat, rinshan=True)

    # ---------- 和牌结算 ----------
    def _score_one(self, seat, hand14, win_tile, is_tsumo, from_seat, honba, kyotaku):
        melds_raw = self.melds_plain(seat)
        melds_norm = self.melds_plain(seat, True)
        ankan_idx = self.ankan_indices(seat)
        an_gang = [melds_norm[i] for i in ankan_idx]
        state = self._make_state(seat, is_tsumo)
        dora = self.dora_list(with_ura=False)
        if self.riichi[seat]:
            state['ura_dora'] = [dora_from_indicator(t) for t in self.ura_indicators()]
        is_oya = seat == self.oya

        # 符和番联合取点数最高的拆法
        ycands = list(yaku_candidates(list(hand14), melds_raw, win_tile, is_tsumo,
                                      self.bakaze, self.jikaze(seat), dora, state, self.rules))
        fcands = dict(fu_candidates(norm_list(hand14), melds_norm, norm(win_tile),
                                    is_tsumo, self.bakaze, self.jikaze(seat),
                                    an_gang, self.rules['renpu_fu']))
        best = None
        for yc in ycands:
            fu = fcands.get(yc['key'])
            if fu is None:
                continue
            han, ym = yc['han'], yc['yakuman']
            base = calc_score(fu, han, is_oya, is_tsumo, 0, 0,
                              kiriage_mangan=self.rules['kiriage_mangan'], yakuman=ym)
            cand = (base['get'], han, fu, yc)
            if best is None or cand[:3] > best[:3]:
                best = cand
        if best is None:
            # 兜底：理论上不会走到
            yaku, han = calc_yaku(list(hand14), melds_raw, win_tile, is_tsumo,
                                  self.bakaze, self.jikaze(seat), dora, state, self.rules)
            fu = calc_fu(norm_list(hand14), melds_norm, norm(win_tile), is_tsumo,
                         self.bakaze, self.jikaze(seat), an_gang, self.rules['renpu_fu'])
            ym = han // 13 if han >= 13 else 0
            yc = {'yaku': [(n, 1) for n in yaku], 'han': han, 'yakuman': ym}
            best = (0, han, fu, yc)

        points, han, fu, yc = best
        ym = yc['yakuman']
        res = calc_score(fu, han, is_oya, is_tsumo, honba, kyotaku,
                         kiriage_mangan=self.rules['kiriage_mangan'], yakuman=ym)
        gain = res['get']
        delta = [0] * 4
        delta[seat] += gain
        if is_tsumo:
            for s in range(4):
                if s == seat:
                    continue
                delta[s] -= res['oya_pay'] if s == self.oya else res['ko_pay']
        else:
            delta[from_seat] -= res['ron_pay']

        hand13 = list(hand14)
        if win_tile in hand13:
            hand13.remove(win_tile)
        melds_meta = [{'type': m['type'], 'tiles': list(m['tiles']), 'from': m['from'],
                       'called_tile': m.get('called_tile')} for m in self.melds[seat]]
        info = {
            'seat': seat, 'from': from_seat, 'tile': win_tile, 'tsumo': is_tsumo,
            'hand': hand13, 'melds': melds_meta,
            'yaku': [{'name': n, 'han': h} for n, h in yc['yaku']],
            'han': han, 'fu': fu, 'yakuman': ym, 'points': points, 'delta': delta,
        }
        return info, delta

    def _win_tsumo(self, seat):
        self.events.append({'type': 'tsumo', 'seat': seat})
        info, delta = self._score_one(seat, self.hands[seat], self.drawn, True, None,
                                      self.honba, self.kyotaku)
        self.kyotaku = 0
        result = {'type': 'tsumo', 'wins': [info],
                  'dora_indicators': self.dora_indicators(),
                  'ura_indicators': self.ura_indicators() if self.riichi[seat] else []}
        self._end_round(result, delta, seat == self.oya, True)

    def _win_ron(self, winners, discarder, tile):
        # 双响可以，本场和立直棒给离放铳者下家方向最近的那位
        total = [0] * 4
        wins = []
        for i, s in enumerate(winners):
            self.events.append({'type': 'ron', 'seat': s, 'from': discarder})
            hb = self.honba if i == 0 else 0
            kt = self.kyotaku if i == 0 else 0
            info, delta = self._score_one(s, self.hands[s] + [tile], tile, False, discarder, hb, kt)
            wins.append(info)
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
        self.events.append({'type': 'ryuukyoku', 'reason': 'exhaustive'})
        result = {'type': 'ryuukyoku', 'reason': 'exhaustive', 'tenpai': tenpai}
        self._end_round(result, delta, tenpai[self.oya], False, draw=True)

    def _abort(self, reason):
        self.events.append({'type': 'ryuukyoku', 'reason': reason})
        result = {'type': 'abort', 'reason': reason}
        self._end_round(result, [0] * 4, True, False, draw=True)

    # ---------- 一局结束、换庄 ----------
    def _end_round(self, result, delta, renchan, is_win, draw=False):
        for s in range(4):
            self.scores[s] += delta[s]
        self.next_renchan = renchan
        self.next_honba = self.honba + 1 if (renchan or draw) else 0
        self.game_over = self._check_game_over(renchan, is_win)
        if self.game_over and self.kyotaku > 0:
            # 剩余供托给第一名（同分按起家顺序），计入最后一局 delta
            top = max(range(4), key=lambda s: (self.scores[s], -s))
            self.scores[top] += self.kyotaku * 1000
            delta[top] += self.kyotaku * 1000
            self.kyotaku = 0
        result['delta'] = delta
        result['scores'] = list(self.scores)
        result['renchan'] = renchan
        if self.game_over:
            result['game_over'] = True
            result['ranking'] = sorted(range(4), key=lambda s: (-self.scores[s], s))
        self.result = result
        self.phase = 'end'
        self.call_options = {}
        self.responses = {}

    def _check_game_over(self, renchan, is_win):
        if any(s < 0 for s in self.scores):
            return True   # 被飞
        last = 3 if self.length == 'tonpuu' else 7
        if self.kyoku >= last and not renchan:
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
    def get_state(self, seat):
        """前端格式的状态（version / game_id 由 server 补）。seat 视角，别人手牌藏起来。"""
        players = []
        for s in range(4):
            hand = list(self.hands[s])
            if s == self.current and self.drawn is not None and self.phase == 'discard':
                if self.drawn in hand:
                    hand.remove(self.drawn)
            # 和了结算时，赢家的手牌去掉和的那张（result 里单独给）
            if self.phase == 'end' and self.result and self.result['type'] in ('tsumo', 'ron'):
                for w in self.result['wins']:
                    if w['seat'] == s and w['tile'] in hand:
                        hand.remove(w['tile'])
            hand.sort(key=tile_key)   # 展示用的手牌始终排好序
            discards = [{'tile': r['tile'], 'riichi': r['riichi'], 'called': r['called'],
                         'tsumogiri': r.get('tsumogiri', False)} for r in self.rivers[s]]
            melds = [{'type': m['type'], 'tiles': list(m['tiles']), 'from': m['from'],
                      'called_tile': m.get('called_tile')} for m in self.melds[s]]
            p = {
                'seat': s,
                'name': '你' if s == seat else ('电脑 %d' % s if s not in self.human_seats else '座位 %d' % s),
                'score': self.scores[s],
                'seat_wind': self.jikaze(s),
                'riichi': self.riichi[s],
                'discards': discards,
                'melds': melds,
                'hand_count': len(hand),
            }
            if s == seat:
                p['hand'] = hand
            players.append(p)

        if self.phase == 'end':
            phase = 'game_end' if self.game_over else 'round_end'
        else:
            phase = 'playing'

        if self.phase == 'discard':
            waiting = [self.current] if self.current in self.human_seats else []
        elif self.phase == 'call':
            waiting = sorted(s for s in self.call_options
                             if s in self.human_seats and s not in self.responses)
        else:
            waiting = []

        # 事件流：摸牌的 tile 只有摸牌者是视角本人时才给
        events = []
        for e in self.events:
            e2 = dict(e)
            if e2['type'] == 'draw' and e2['seat'] != seat:
                e2['tile'] = None
            events.append(e2)

        return {
            'phase': phase,
            'round': {
                'wind': self.bakaze,
                'number': self.oya + 1,
                'honba': self.honba,
                'riichi_sticks': self.kyotaku,
                'dealer': self.oya,
            },
            'dora_indicators': self.dora_indicators(),
            'wall_left': self.remaining(),
            'viewer': seat,
            'turn': self.current,
            'waiting_for': waiting if phase == 'playing' else [],
            'rules': dict(self.rules),
            'players': players,
            'drawn': self.drawn if (seat == self.current and self.phase == 'discard') else None,
            'legal_actions': self.get_legal_actions(seat),
            'hints': self._build_hints(seat) if phase == 'playing' else None,
            'events': events,
            'result': self._build_result() if self.result else None,
        }

    def _build_hints(self, seat):
        from tenpai import get_waits, discard_hints
        hand = list(self.hands[seat])
        melds = self.melds_plain(seat)
        visible = self.get_visible(seat)
        total = len(hand) + 3 * len(melds)
        waits, discards = [], {}
        try:
            if total == 14:
                dh = discard_hints(hand, melds, visible)
                if self.riichi[seat]:
                    # 立直后只能摸切，别的牌不能打，提示也只留摸到的那张
                    dh = {t: ws for t, ws in dh.items() if t == self.drawn}
                discards = {t: [{'tile': w, 'left': n} for w, n in ws.items()]
                            for t, ws in dh.items()}
            elif total == 13:
                ws = get_waits(hand, melds, visible)
                waits = [{'tile': w, 'left': n} for w, n in ws.items()]
        except Exception:
            pass
        furiten = False
        try:
            if total == 13:
                furiten = self._is_furiten(seat)
            else:
                furiten = self.temp_furiten[seat] or self.riichi_furiten[seat]
        except Exception:
            pass
        return {'waits': waits, 'furiten': furiten, 'discards': discards}

    def _build_result(self):
        r = self.result
        if r['type'] in ('tsumo', 'ron'):
            wins = []
            for w in r['wins']:
                wins.append({
                    'seat': w['seat'], 'from': w['from'],
                    'hand': list(w['hand']), 'melds': w['melds'],
                    'win_tile': w['tile'], 'yaku': w['yaku'],
                    'han': w['han'], 'fu': w['fu'], 'yakuman': w['yakuman'],
                    'points': w['points'],
                })
            return {
                'type': 'agari', 'wins': wins,
                'dora_indicators': list(r['dora_indicators']),
                'uradora_indicators': list(r.get('ura_indicators') or []),
                'delta': list(r['delta']),
            }
        return {
            'type': 'ryuukyoku', 'reason': r.get('reason'),
            'tenpai': list(r.get('tenpai') or [False] * 4),
            'delta': list(r['delta']),
        }


if __name__ == '__main__':
    # 冒烟自测：全电脑打几局，看点数守恒、能不能打完
    for seed in range(10):
        g = Game(human_seats=[], seed=seed, length='hanchan')
        rounds = 1
        while not g.game_over:
            assert sum(g.scores) + g.kyotaku * 1000 == 100000, (seed, g.scores, g.kyotaku)
            g.next_round()
            rounds += 1
        assert sum(g.scores) == 100000, (seed, g.scores)
        print('seed', seed, '局数', rounds, g.scores, g.result['type'])
    print('ok')