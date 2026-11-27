# 学号 250207
# game.py —— 整局流程：洗牌发牌、摸打、吃碰杠、立直、流局、连庄换庄、本场、电脑玩家
#
# 用法（给 server 用）：
#   g = Game(human_seats=[0])                       # 开新游戏，自动开始东1局
#   g = Game(human_seats=[0], wall=牌山)             # 指定牌山（136 张）测试用
#   g = Game(rules={'kuitan': False}, length='hanchan')
#   g.get_legal_actions(seat)                       # 这个人现在能做什么
#   g.do_action(seat, 'discard', tile='3m', tsumogiri=False)   # 不合法会 raise ValueError
#   g.next_round()                                  # 一局结束后进下一局
#
# 约定：
# - 座位 0 是起家（东1局的庄家），之后庄家按 0->1->2->3 轮。当前庄家是 self.oya。
# - 牌在 game 里面原样保留红五 0m/0p/0s（前端就是这么写的）。
#   传给 fu / tenpai 的时候统一换成 5m，传给 yaku 算分的时候给原样的手牌（带 0m），
#   这样 250118 那边能自己数赤宝牌。
# - 传给 fu / yaku 的 hand 是“和了时的门前手牌”，包含和的那张，win_tile 另外单独传。
# - 双立直的时候 state 里 riichi 和 double_riichi 都是 True（250118 那边不会重复算）。
#
# [修改] 记号：下面注释里写了 [修改] 的地方是拼代码时改的，原因见 feedback/250207.md。

import random

from fu import calc_fu
from yaku import calc_yaku_detail
from score import calc_score
from tenpai import can_hu


START_POINTS = 25000
RETURN_POINTS = 30000   # 南入/西入/结束判断用（有人到 30000 才结束）

ALL_TILES = [str(n) + s for s in 'mps' for n in range(1, 10)] + [str(n) + 'z' for n in range(1, 8)]

# [修改] 规则开关（见 frontend/接口说明.md“规则开关”），没传的用这里的默认值
DEFAULT_RULES = {
    'aka_dora': True,         # 赤宝牌
    'kuitan': True,           # 食断
    'kiriage_mangan': False,  # 切上满贯
    'renpu_fu': 4,            # 连风牌雀头符数
}


def make_rules(rules=None):
    """把前端传来的 rules 补全成四个键都有的 dict，值不对就 raise ValueError"""
    res = dict(DEFAULT_RULES)
    for k, v in (rules or {}).items():
        if k not in DEFAULT_RULES:
            continue   # 不认识的键忽略
        if k == 'renpu_fu':
            if v not in (2, 4) or isinstance(v, bool):
                raise ValueError('rules.renpu_fu 只能是 2 或 4')
        elif not isinstance(v, bool):
            raise ValueError('rules.%s 只能是 true / false' % k)
        res[k] = v
    return res


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


def make_wall(aka=True):
    wall = []
    for s in 'mps':
        for n in range(1, 10):
            for k in range(4):
                if aka and n == 5 and k == 0:
                    wall.append('0' + s)   # 每种花色一张红五
                else:
                    wall.append(str(n) + s)
    for n in range(1, 8):
        wall += [str(n) + 'z'] * 4
    return wall


def check_wall(wall, aka=True):
    """[修改] 指定牌山的检查：136 张、牌名合法、每种不超过 4 张、红五每种最多 1 张"""
    if not isinstance(wall, list) or len(wall) != 136:
        raise ValueError('牌山要 136 张')
    counts = {}
    for t in wall:
        if (not isinstance(t, str) or len(t) != 2 or t[1] not in 'mpsz' or not t[0].isdigit()
                or (t[1] == 'z' and not '1' <= t[0] <= '7')):
            raise ValueError('牌山里有不认识的牌：%r' % (t,))
        counts[norm(t)] = counts.get(norm(t), 0) + 1
        if t[0] == '0':
            counts[t] = counts.get(t, 0) + 1
    for t in ALL_TILES:
        if counts.get(t, 0) != 4:
            raise ValueError('牌山里 %s 应该正好 4 张' % t)
    for s in 'mps':
        if counts.get('0' + s, 0) > 1:
            raise ValueError('红五每种最多 1 张')
    if not aka:
        # 没有赤宝牌时牌山里不该有红五：当普通五处理
        wall = norm_list(wall)
    return list(wall)


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
            raise ValueError('length 只能是 tonpuu 或 hanchan')
        self.rng = random.Random(seed)
        self.rules = make_rules(rules)
        self.length = length
        # [修改] 半庄战：南4 是最后一局，不够 30000 就西入；东风战：东4 最后，不够就南入
        self.last_kyoku = 3 if length == 'tonpuu' else 7
        self.max_kyoku = self.last_kyoku + 4
        self.human_seats = set(human_seats)
        self.scores = [START_POINTS] * 4
        self.kyoku = 0      # 0~3 = 东1~东4，4~7 = 南1~南4，8~11 = 西1~西4
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
        return str(min(self.kyoku // 4, 3) + 1) + 'z'

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

    # [修改] 王牌位置按接口说明：wall[122:127] 宝牌指示牌，wall[127:132] 里宝，wall[132:136] 岭上
    def dora_indicators(self):
        return [self.wall[122 + i] for i in range(self.dora_count)]

    def ura_indicators(self):
        return [self.wall[127 + i] for i in range(self.dora_count)]

    def dora_list(self):
        return [dora_from_indicator(t) for t in self.dora_indicators()]

    def ura_list(self):
        return [dora_from_indicator(t) for t in self.ura_indicators()]

    def get_visible(self, seat):
        """给听牌提示用：seat 能看到的、不在自己手里/副露里的牌。
        [修改] 原来把自己的副露也放进来了（tenpai.get_waits 又扣一次，重复扣），
        被吃碰走的河牌也在河里和副露里各算了一次。"""
        vis = []
        for s in range(4):
            vis += [r['tile'] for r in self.rivers[s] if not r['called']]
            if s != seat:
                for m in self.melds[s]:
                    vis += m['tiles']
        vis += self.dora_indicators()
        return norm_list(vis)

    def _event(self, **e):
        self.events.append(e)

    # ---------- 一局开始 ----------
    def start_round(self, wall=None):
        if wall is None:
            wall = make_wall(self.rules['aka_dora'])
            self.rng.shuffle(wall)
        else:
            wall = check_wall(wall, self.rules['aka_dora'])
        # [修改] 牌山顺序按前端接口说明：
        #   wall[0:52]   配牌，wall[13k:13k+13] 给物理座位 k（不管谁是庄家）
        #   wall[52:122] 摸牌，庄家先摸 wall[52]
        #   wall[122:136] 王牌：122~126 宝牌指示牌，127~131 里宝，132~135 岭上
        self.wall = wall
        self.wall_pos = 52
        self.wall_end = 122
        self.rinshan_used = 0
        self.dora_count = 1

        self.hands = [sorted(wall[13 * k:13 * k + 13], key=tile_key) for k in range(4)]
        self.rivers = [[] for _ in range(4)]     # 每张：{'tile', 'tsumogiri', 'riichi'(横放), 'called'(被鸣走)}
        self.melds = [[] for _ in range(4)]      # 每组：{'type', 'tiles', 'from', 'called_tile'}
        self.riichi = [False] * 4
        self.double_riichi = [False] * 4
        self.ippatsu = [False] * 4
        self.first_turn = [True] * 4      # 还没打过第一张牌（用于天和地和双立直九种九牌）
        self.no_call_yet = True           # 到现在还没有人鸣牌（暗杠也算）
        self.temp_furiten = [False] * 4   # 同巡振听
        self.riichi_furiten = [False] * 4  # 立直后见逃
        self.riichi_pending = None        # 刚宣言立直、立直棒还没放的人
        self.kan_seats = []               # 谁杠过（四杠散了用）
        self.events = []                  # [修改] 这一局的全部事件，给前端的“记录”栏

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
            t = self.wall[132 + self.rinshan_used]
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
        self.phase = 'discard'
        self._event(type='draw', seat=seat, tile=t)

    def _discard(self, seat, tile, riichi=False, tsumogiri=None):
        # [修改] 记下是不是摸切（前端要）。没说的话按“打的牌和摸的牌一样就算摸切”
        if tsumogiri is None:
            tsumogiri = self.drawn is not None and tile == self.drawn
        tsumogiri = bool(tsumogiri) and self.drawn is not None and tile == self.drawn
        hand = self.hands[seat]
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
            self._event(type='riichi', seat=seat)
        self.first_turn[seat] = False
        self.temp_furiten[seat] = False   # 同巡振听到自己打牌就解除
        self.rivers[seat].append({'tile': tile, 'tsumogiri': tsumogiri, 'riichi': riichi, 'called': False})
        self._event(type='discard', seat=seat, tile=tile, tsumogiri=tsumogiri)
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
                for p in self._pon_options(same):
                    opts.append({'type': 'pon', 'tiles': p})
                if len(same) >= 3 and self.rinshan_used < 4:
                    opts.append({'type': 'kan', 'tiles': same[:3]})
                if i == 1 and tile[1] != 'z':
                    for combo in self._chi_combos(s, tile):
                        opts.append({'type': 'chi', 'tiles': combo})
            if opts:
                self.call_options[s] = opts
        self.phase = 'call'

    def _pon_options(self, same):
        # [修改] 有红五时给“用红五 / 不用红五”两种碰法，让玩家自己选
        opts = []
        for i in range(len(same)):
            for j in range(i + 1, len(same)):
                p = sorted([same[i], same[j]], key=tile_key)
                if p not in opts:
                    opts.append(p)
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
                # 有红五的话就分两种（用不用红五）
                for x in sorted(set(ta), key=tile_key):
                    for y in sorted(set(tb), key=tile_key):
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

    def _make_state(self, seat, is_tsumo):
        last = self.remaining() == 0
        chihou = is_tsumo and seat != self.oya and self.first_turn[seat] and self.no_call_yet
        return {
            'riichi': self.riichi[seat],
            'ippatsu': self.ippatsu[seat],
            'haitei': is_tsumo and last and not self.is_rinshan_draw,
            'houtei': (not is_tsumo) and last,
            'rinshan': is_tsumo and self.is_rinshan_draw,
            'chankan': False,   # TODO 抢杠还没做，加杠直接就杠了
            'double_riichi': self.double_riichi[seat],
            'tenhou': is_tsumo and seat == self.oya and self.first_turn[seat] and self.no_call_yet,
            'chihou': chihou,
            'chiihou': chihou,  # [修改] 250118 读的键名是 chiihou，原来只传 chihou，地和永远算不出来
            # [修改] 下面三个原来没传：暗杠被当成明杠（立直暗杠后和牌会丢掉立直等门清役）
            'ankan_indices': [i for i, m in enumerate(self.melds[seat]) if m['type'] == 'ankan'],
            'kuitan': self.rules['kuitan'],
            'ura_dora': self.ura_list() if self.riichi[seat] else [],
        }

    def _win_ok(self, seat, hand14, win_tile, is_tsumo):
        """形能和 + 有役。判断有没有役的时候不传宝牌、手牌也换成 5m，这样宝牌赤宝牌不会算进去，0 番就是没役"""
        hn = norm_list(hand14)
        mn = self.melds_plain(seat, True)
        if not can_hu(hn, mn):
            return False
        state = self._make_state(seat, is_tsumo)
        state['ura_dora'] = []
        pairs, _ = calc_yaku_detail(hn, mn, norm(win_tile), is_tsumo, self.bakaze, self.jikaze(seat), [], state)
        return sum(h for _, h in pairs) > 0

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
                discards = [t for t in discards if norm(t) not in self.kuikae] or discards
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
        """action: discard / riichi / tsumo / ron / chi / pon / kan / pass / kyuushu
        tile：打哪张、杠哪张；tiles：吃/碰用手里哪两张（不传就用第一个选项）"""
        if self.phase == 'end':
            raise ValueError('这局已经结束了')
        legal = self.get_legal_actions(seat)
        types = [a['type'] for a in legal]
        if action not in types:
            raise ValueError('现在不能 ' + str(action))

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
                self._abort('kyuushu')
        else:
            if action in ('chi', 'pon', 'kan'):
                cand = [a for a in legal if a['type'] == action]
                pick = cand[0]
                if tiles is not None and action != 'kan':
                    for a in cand:
                        if sorted(a['tiles']) == sorted(tiles):
                            pick = a
                            break
                    else:
                        raise ValueError('没有这个吃法/碰法')
                self.responses[seat] = pick
            else:
                self.responses[seat] = {'type': action}
            self._try_resolve()
        self._run()

    # ---------- 电脑 ----------
    def _cpu_turn(self, seat):
        # 能和就和，不然摸什么打什么（[修改] 不再每次都把立直、杠的选项全算一遍，电脑用不到）
        if self.drawn is not None and self._win_ok(seat, self.hands[seat], self.drawn, True):
            self._win_tsumo(seat)
            return
        if self.drawn is not None and self.drawn in self.hands[seat]:
            self._discard(seat, self.drawn, tsumogiri=True)
        else:
            acts = self._turn_actions(seat)
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

        if len(rons) == 3:
            self._abort('triple_ron')
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
            self._abort('four_riichi')
            return
        # 四风连打
        if self.no_call_yet and all(len(r) == 1 for r in self.rivers):
            first = [norm(r[0]['tile']) for r in self.rivers]
            if first[0] in ('1z', '2z', '3z', '4z') and len(set(first)) == 1:
                self._abort('four_winds')
                return
        # [修改] 四杠散了：两个人以上合计开了 4 个杠，第 4 个杠之后的那张打牌没人和就流局
        if len(self.kan_seats) >= 4 and len(set(self.kan_seats)) > 1:
            self._abort('four_kans')
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
            self.melds[seat].append({'type': 'minkan', 'tiles': sorted(own + [tile], key=tile_key),
                                     'from': discarder, 'called_tile': tile})
            self._event(type='minkan', seat=seat, tiles=sorted(own + [tile], key=tile_key), **{'from': discarder})
            self._after_kan(seat)
            return
        self.melds[seat].append({'type': kind, 'tiles': sorted(own + [tile], key=tile_key),
                                 'from': discarder, 'called_tile': tile})
        self._event(type=kind, seat=seat, tiles=sorted(own + [tile], key=tile_key), **{'from': discarder})
        self.current = seat
        self.drawn = None
        self.after_call = True
        self.phase = 'discard'
        # 食替：碰的那张、吃的那张和它筋上另一头都不能马上打
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
        # [修改] 暗杠的 from / called_tile 按接口说明写 null
        self.melds[seat].append({'type': 'ankan', 'tiles': sorted(own, key=tile_key), 'from': None, 'called_tile': None})
        self._event(type='ankan', seat=seat, tile=t)
        self._after_kan(seat)

    def _kakan(self, seat, t):
        # TODO 抢杠：加杠的时候别人应该可以荣和，现在直接杠了
        self._interrupt()
        x = [y for y in self.hands[seat] if norm(y) == t][0]
        self.hands[seat].remove(x)
        self.hands[seat].sort(key=tile_key)
        for m in self.melds[seat]:
            if m['type'] == 'pon' and norm(m['tiles'][0]) == t:
                m['type'] = 'kakan'
                m['tiles'] = sorted(m['tiles'] + [x], key=tile_key)
                break
        self._event(type='kakan', seat=seat, tile=t)
        self._after_kan(seat)

    def _after_kan(self, seat):
        # TODO 天凤明杠/加杠的杠宝牌是打牌以后才翻，这里简化成杠完马上翻
        self.dora_count += 1
        self._event(type='dora', tile=self.dora_indicators()[-1])
        self.kan_seats.append(seat)
        self._draw(seat, rinshan=True)

    # ---------- 和牌结算 ----------
    def _score_one(self, seat, hand14, win_tile, is_tsumo, from_seat, honba, kyotaku):
        """[修改] 直接用 score.py 返回的 dict（原来按元组拆，和 260409 的格式对不上）；
        暗杠、食断、里宝、连风符、切上满贯、役满倍数都传下去；平和的判断交给算番，算符跟着用同一种拆法。"""
        melds = self.melds_plain(seat)
        melds_n = self.melds_plain(seat, True)
        an_gang = [norm_list(m['tiles']) for m in self.melds[seat] if m['type'] == 'ankan']
        state = self._make_state(seat, is_tsumo)
        pairs, yakuman = calc_yaku_detail(list(hand14), melds, win_tile, is_tsumo,
                                          self.bakaze, self.jikaze(seat), self.dora_list(), state)
        han = sum(h for _, h in pairs)
        names = [n for n, _ in pairs]
        if yakuman:
            fu = 0
        else:
            fu = calc_fu(norm_list(hand14), melds_n, norm(win_tile), is_tsumo, self.bakaze, self.jikaze(seat),
                         an_gang, self.rules['renpu_fu'], '平和' in names)
        is_oya = seat == self.oya
        opt = {'kiriage': self.rules['kiriage_mangan'], 'yakuman': yakuman}
        res = calc_score(fu, han, is_oya, is_tsumo, honba, kyotaku, **opt)
        bare = calc_score(fu, han, is_oya, is_tsumo, 0, 0, **opt)   # 不含本场供托，显示用
        delta = [0] * 4
        delta[seat] += res['get']
        if is_tsumo:
            for s in range(4):
                if s != seat:
                    delta[s] -= res['oya_pay'] if s == self.oya else res['ko_pay']
        else:
            delta[from_seat] -= res['ron_pay']
        hand13 = list(hand14)
        hand13.remove(win_tile)
        info = {
            'seat': seat, 'from': from_seat,
            'hand': sorted(hand13, key=tile_key),
            'melds': [dict(m) for m in self.melds[seat]],
            'win_tile': win_tile,
            'yaku': [{'name': n, 'han': h} for n, h in pairs],
            'han': han, 'fu': fu, 'yakuman': yakuman,
            'points': bare['get'],
        }
        return info, delta

    def _win_tsumo(self, seat):
        self._event(type='tsumo', seat=seat)
        info, delta = self._score_one(seat, self.hands[seat], self.drawn, True, None,
                                      self.honba, self.kyotaku)
        self.kyotaku = 0
        result = {'type': 'agari', 'wins': [info],
                  'dora_indicators': self.dora_indicators(),
                  'uradora_indicators': self.ura_indicators() if self.riichi[seat] else []}
        self._end_round(result, delta, seat == self.oya, True)

    def _win_ron(self, winners, discarder, tile):
        # 双响可以（天凤），本场和立直棒给离放铳的人最近的那个（上家取り）
        total = [0] * 4
        wins = []
        for i, s in enumerate(winners):
            self._event(type='ron', seat=s, **{'from': discarder})
            hb = self.honba if i == 0 else 0
            kt = self.kyotaku if i == 0 else 0
            info, delta = self._score_one(s, self.hands[s] + [tile], tile, False, discarder, hb, kt)
            wins.append(info)
            for k in range(4):
                total[k] += delta[k]
        self.kyotaku = 0
        any_riichi = any(self.riichi[s] for s in winners)
        result = {'type': 'agari', 'wins': wins,
                  'dora_indicators': self.dora_indicators(),
                  'uradora_indicators': self.ura_indicators() if any_riichi else []}
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
        self._event(type='ryuukyoku', reason='exhaustive')
        result = {'type': 'ryuukyoku', 'reason': 'exhaustive', 'tenpai': tenpai}
        self._end_round(result, delta, tenpai[self.oya], False, draw=True)

    def _abort(self, reason):
        # 途中流局：天凤是庄家连庄、本场+1，立直棒留着
        # [修改] reason 直接用前端的英文 key（kyuushu / four_winds / four_riichi / four_kans / triple_ron）
        self._event(type='ryuukyoku', reason=reason)
        result = {'type': 'ryuukyoku', 'reason': reason}
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
        self.drawn = None
        self.call_options = {}
        self.responses = {}
        self.next_renchan = renchan
        # 连庄或者流局本场 +1，闲家和了本场清零
        self.next_honba = self.honba + 1 if (renchan or draw) else 0
        self.game_over = self._check_game_over(renchan, is_win)
        if self.game_over:
            # 剩下的立直棒给第一名（天凤）；同分按起家顺序
            top = max(range(4), key=lambda s: (self.scores[s], -s))
            self.scores[top] += self.kyotaku * 1000
            self.kyotaku = 0
            result['scores'] = list(self.scores)
            result['game_over'] = True
            result['ranking'] = sorted(range(4), key=lambda s: (-self.scores[s], s))

    def _check_game_over(self, renchan, is_win):
        if any(s < 0 for s in self.scores):
            return True   # 被飞
        k = self.kyoku
        top = max(self.scores)
        if k > self.last_kyoku:
            # 延长（南入/西入）以后有人到 30000 就结束，延长的第 4 局打完无论如何结束
            if top >= RETURN_POINTS:
                return True
            return k >= self.max_kyoku and not renchan
        if k == self.last_kyoku:
            if renchan:
                # 和了止め：all last 庄家和了而且是第一名、30000 以上就结束（听牌止め没有）
                if is_win and self.scores[self.oya] == top and top >= RETURN_POINTS:
                    return True
                return False
            # 最后一局结束：有人 30000 以上就结束，没有就进入下一个场风
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


if __name__ == '__main__':
    # 自测：全电脑打几场，看能不能打完、点数守恒（更多测试见 tests/）
    for seed in range(5):
        for length in ('tonpuu', 'hanchan'):
            g = Game(human_seats=[], seed=seed, length=length)
            rounds = 1
            while not g.game_over:
                assert sum(g.scores) + g.kyotaku * 1000 == 100000, (seed, g.scores, g.kyotaku)
                g.next_round()
                rounds += 1
            assert sum(g.scores) == 100000, (seed, g.scores)
            print(length, 'seed', seed, '局数', rounds, g.scores)
    print('ok')
