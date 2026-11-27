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
#
# 【拼装修复 glm-5-3】这个文件我改了这些地方（详见 说明.md）：
# - 牌山布局按前端《接口说明.md》来：配牌按物理座位 0~3 各 wall[0:13] 等，
#   宝牌指示牌 = wall[122:127]，里宝指示牌 = wall[127:132]，岭上牌 = wall[132:136]。
# - new_game 传进来的 rules（赤宝牌/食断/切上满贯/连风符）存到 self.rules，
#   算番算符算点的时候往下传；没有赤宝牌时牌山不放 0m/0p/0s。
# - 暗杠的信息传给 yaku（state['ankan_indices']）和 fu（an_gang 参数），
#   里宝牌指示牌放进 state['ura_dora']，不然暗杠/立直会白丢役。
# - 立直后暗杠的判断修正（原来的写法 260522 的 can_hu 算出来永远是“不能杠”）。
# - 支持东风战 / 半庄战（length），南入以后西入。
# - 双立直被别人鸣牌后要取消。
# - 记录 events（给前端的记录栏）和每张打牌的 tsumogiri。
# - 补上四杠散了、抢杠（加杠时别人可以荣和）。
# - result 里每手牌的 points 不含本场供托（前端按接口说明显示）。

import random

try:
    from fu import calc_fu
    from yaku import calc_yaku
    from score import calc_score
    from tenpai import can_hu
except ImportError:
    # 别人的文件还没交的时候先这样，自测用最下面 __main__ 里的假函数
    calc_fu = calc_yaku = calc_score = can_hu = None


START_POINTS = 25000
RETURN_POINTS = 30000   # 延长战结束判断用（天凤：有人到 30000 才结束）

# 规则开关默认值（前端没传就用这套；说明见《接口说明.md》“规则开关”）
DEFAULT_RULES = {
    'aka_dora': True,
    'kuitan': True,
    'kiriage_mangan': False,
    'renpu_fu': 2,
}

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
                if n == 5 and k == 0:
                    wall.append('0' + s if aka_dora else '5' + s)   # 每种花色一张红五
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
        # 东风战：东1~东4，没人到30000点南入；半庄战：东1~南4，没人到30000点西入
        self.length = 'hanchan' if length == 'hanchan' else 'tonpuu'
        self.main_rounds = 8 if self.length == 'hanchan' else 4
        self.scores = [START_POINTS] * 4
        self.kyoku = 0      # 0~3 = 东1~东4，4~7 = 南1~南4，8~11 = 延长战西1~西4
        self.honba = 0
        self.kyotaku = 0    # 场上的立直棒（根数）
        self.game_over = False
        self.result = None
        self.events = []    # 这一局的事件记录（给前端记录栏）
        self.start_round(wall)

    # ---------- 小工具 ----------
    @property
    def oya(self):
        return self.kyoku % 4

    @property
    def bakaze(self):
        return str(self.kyoku // 4 + 1) + 'z'   # 东1z 南2z 西3z（延长战）

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
        # 布局按《接口说明.md》：wall[122:127] 宝牌指示牌，wall[127:132] 里宝指示牌，wall[132:136] 岭上牌
        return [self.dead_wall[i] for i in range(self.dora_count)]

    def ura_indicators(self):
        return [self.dead_wall[5 + i] for i in range(self.dora_count)]

    def dora_list(self, with_ura=False):
        res = [dora_from_indicator(t) for t in self.dora_indicators()]
        if with_ura:
            res += [dora_from_indicator(t) for t in self.ura_indicators()]
        return res

    def get_visible(self, seat):
        """给听牌提示用：场上能看到的牌（牌河 + 所有副露 + 宝牌指示牌），不含自己手牌"""
        vis = []
        for s in range(4):
            vis += [r['tile'] for r in self.rivers[s]]
            for m in self.melds[s]:
                vis += m['tiles']
        vis += self.dora_indicators()
        return norm_list(vis)

    # ---------- 一局开始 ----------
    def start_round(self, wall=None):
        if wall is None:
            wall = make_wall(self.rules.get('aka_dora', True))
            self.rng.shuffle(wall)
        else:
            wall = list(wall)
            if len(wall) != 136:
                raise ValueError('牌山要 136 张')
        # 牌山布局（《接口说明.md》“指定牌山”，拼装修正）：
        #   wall[0:52]   配牌，按物理座位：wall[0:13] 座位0、wall[13:26] 座位1、wall[26:39] 座位2、wall[39:52] 座位3
        #   wall[52:122] 摸牌，从当前庄家开始按顺序摸
        #   wall[122:136] 王牌 14 张：
        #       wall[122:127] 宝牌指示牌（开局翻 wall[122]，每杠一次翻下一张）
        #       wall[127:132] 对应的里宝牌指示牌
        #       wall[132:136] 岭上牌，开杠后依次摸
        #   每开一次杠，正常摸牌的最后一张少一张（wall_end 往前挪）
        self.wall = wall
        self.dead_wall = wall[122:136]
        self.wall_pos = 52
        self.wall_end = 122
        self.rinshan_used = 0
        self.dora_count = 1

        self.hands = [[] for _ in range(4)]
        for seat in range(4):
            self.hands[seat] = sorted(wall[13 * seat:13 * seat + 13], key=tile_key)
        self.rivers = [[] for _ in range(4)]     # 每张：{'tile', 'riichi'(横放), 'called'(被鸣走)}
        self.melds = [[] for _ in range(4)]      # 每组：{'type', 'tiles', 'from'}
        self.riichi = [False] * 4
        self.double_riichi = [False] * 4
        self.ippatsu = [False] * 4
        self.first_turn = [True] * 4      # 还没打过第一张牌（用于天和地和双立直九种九牌）
        self.no_call_yet = True           # 到现在还没有人鸣牌（暗杠也算）
        self.temp_furiten = [False] * 4   # 同巡振听
        self.riichi_furiten = [False] * 4  # 立直后见逃
        self.riichi_pending = None        # 刚宣言立直、立直棒还没放的人
        self.kan_seats = []               # 谁杠过（四杠散了用）
        self.kakan_pending = None         # 加杠后等人抢杠：(座位, 杠的牌)
        self.four_kans_pending = False    # 第四次杠已打出、没人荣和就算四杠散了

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
            t = self.dead_wall[10 + self.rinshan_used]   # 岭上牌在 wall[132:136]
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
        self._log({'type': 'draw', 'seat': seat, 'tile': t})

    def _log(self, e):
        self.events.append(e)

    def _discard(self, seat, tile, riichi=False, tsumogiri=False):
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
            self._log({'type': 'riichi', 'seat': seat})
        self.first_turn[seat] = False
        self.temp_furiten[seat] = False   # 同巡振听到自己打牌就解除
        self.rivers[seat].append({'tile': tile, 'riichi': riichi, 'called': False,
                                  'tsumogiri': tsumogiri})
        self._log({'type': 'discard', 'seat': seat, 'tile': tile, 'tsumogiri': tsumogiri})
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
                    opts.append({'type': 'pon', 'tiles': self._pick_pon_tiles(same)})
                if len(same) >= 3 and self.rinshan_used < 4:
                    opts.append({'type': 'kan', 'tiles': same[:3]})
                if i == 1 and tile[1] != 'z':
                    for combo in self._chi_combos(s, tile):
                        opts.append({'type': 'chi', 'tiles': combo})
            if opts:
                self.call_options[s] = opts
        self.phase = 'call'

    def _pick_pon_tiles(self, same):
        # 有红五优先用红五（碰出去也是赤宝牌，一样算）
        same = sorted(same, key=lambda t: t[0] != '0')
        return same[:2]

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
        ankan_indices = [i for i, m in enumerate(self.melds[seat]) if m['type'] == 'ankan']
        state = {
            'riichi': self.riichi[seat],
            'ippatsu': self.ippatsu[seat],
            'haitei': is_tsumo and last and not self.is_rinshan_draw,
            'houtei': (not is_tsumo) and last,
            'rinshan': is_tsumo and self.is_rinshan_draw,
            'chankan': False,   # 抢杠在 _kakan 里处理，荣和时改成 True
            'double_riichi': self.double_riichi[seat],
            'tenhou': is_tsumo and seat == self.oya and self.first_turn[seat] and self.no_call_yet,
            'chihou': is_tsumo and seat != self.oya and self.first_turn[seat] and self.no_call_yet,
            'rules': dict(self.rules),
            # 250118 的 yaku.py 和 260331 的 fu.py 都需要知道哪些副露是暗杠
            'ankan_indices': ankan_indices,
        }
        if self.riichi[seat]:
            # 里宝牌单独传，250118 那边好按“里宝牌 N 番”列出来
            # （指示牌要换算成实际的宝牌再传）
            state['ura_dora'] = [dora_from_indicator(t) for t in self.ura_indicators()]
        return state

    def _win_ok(self, seat, hand14, win_tile, is_tsumo):
        """形能和 + 有役。判断有没有役的时候不传宝牌、手牌也换成 5m，这样宝牌赤宝牌不会算进去，0 番就是没役"""
        hn = norm_list(hand14)
        mn = self.melds_plain(seat, True)
        if not can_hu(hn, mn):
            return False
        state = self._make_state(seat, is_tsumo)
        yaku, han = calc_yaku(hn, mn, norm(win_tile), is_tsumo, self.bakaze, self.jikaze(seat), [], state)
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
        """立直后暗杠：杠了以后听的牌不变才行。
        拼装修复：原来拿“9 张手牌 + 4 张暗杠”去调 260522 的 can_hu，
        张数对不上（can_hu 要求 13 + 3×副露数 = 14），永远返回不能杠。
        正确做法：暗杠后还要摸一张岭上替代牌，把替代牌也枚举进去再比听牌集合。"""
        hand = list(self.hands[seat])          # 14 张（含刚摸的）
        hand.remove(self.drawn)
        mn = self.melds_plain(seat, True)
        before = self._waits(hand, mn)
        if not before:
            return False
        h9 = [x for x in hand if norm(x) != t]          # 13 - 4 = 9 张
        if len(h9) != len(hand) - 4:
            return False
        melds_after = mn + [[t] * 4]
        after = set()
        for y in ALL_TILES:                             # 岭上摸什么
            for x in ALL_TILES:                         # 之后听什么
                if can_hu(norm_list(h9 + [y, x]), melds_after):
                    after.add(x)
        return before == after

    # ---------- 玩家操作 ----------
    def do_action(self, seat, action, tile=None, tiles=None, tsumogiri=False):
        """action: discard / riichi / tsumo / ron / chi / pon / kan / pass / kyuushu
        tile：打哪张、杠哪张；tiles：吃/碰用手里哪两张（不传就用第一个选项）
        tsumogiri：打的是不是刚摸的那张（tile 和 drawn 相同时靠它区分）"""
        if self.phase == 'end':
            raise ValueError('这局已经结束了')
        legal = self.get_legal_actions(seat)
        types = [a['type'] for a in legal]
        if action not in types:
            raise ValueError('现在不能 ' + action)

        if self.phase == 'discard':
            if action in ('discard', 'riichi'):
                ok = [a for a in legal if a['type'] == action][0]['tiles']
                if tile not in ok:
                    raise ValueError('不能打这张' if action == 'discard' else '打这张不能立直')
                # 前端没带 tsumogiri 时，按“tile 和 drawn 相同就算摸切”处理
                tg = tsumogiri or (tile == self.drawn)
                self._discard(seat, tile, riichi=(action == 'riichi'), tsumogiri=tg)
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

        if len(rons) == 3:
            self._abort('三家和')
            return
        # 拼装新增：加杠被抢杠（抢杠和）
        if self.kakan_pending is not None:
            seat, ktile = self.kakan_pending
            self.kakan_pending = None
            if rons:
                self._win_ron(rons, seat, ktile, chankan=True)
                return
            self._after_kan(seat)
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
        # 拼装新增：四杠散了（第四次杠的那张打出去没人荣和）
        if self.four_kans_pending:
            self.four_kans_pending = False
            self._abort('四杠散了')
            return
        # 四风连打
        if self.no_call_yet and all(len(r) == 1 for r in self.rivers):
            first = [norm(r[0]['tile']) for r in self.rivers]
            if first[0] in ('1z', '2z', '3z', '4z') and len(set(first)) == 1:
                self._abort('四风连打')
                return
        # 流局满贯没做（见 说明.md 的“还没做的”）
        if self.remaining() == 0:
            self._exhaustive_draw()
            return
        self._draw((discarder + 1) % 4)

    def _interrupt(self):
        """有人鸣牌：一发、天和地和、双立直的机会都没了"""
        self.no_call_yet = False
        self.ippatsu = [False] * 4
        self.first_turn = [False] * 4
        # 拼装修复：立直宣言之后又有人鸣牌，双立直就不成立了
        self.double_riichi = [False] * 4

    def _call_meld(self, seat, discarder, tile, kind, own):
        self._interrupt()
        hand = self.hands[seat]
        for t in own:
            hand.remove(t)
        self.rivers[discarder][-1]['called'] = True
        if kind == 'kan':
            self._log({'type': 'minkan', 'seat': seat, 'tiles': own + [tile], 'from': discarder})
            self.melds[seat].append({'type': 'minkan', 'tiles': own + [tile], 'from': discarder})
            self._after_kan(seat)
            return
        self._log({'type': kind, 'seat': seat, 'tiles': sorted(own + [tile], key=tile_key), 'from': discarder})
        self.melds[seat].append({'type': kind, 'tiles': sorted(own + [tile], key=tile_key),
                                 'from': discarder, 'called_tile': tile})
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
        self.melds[seat].append({'type': 'ankan', 'tiles': own, 'from': seat, 'called_tile': None})
        self._log({'type': 'ankan', 'seat': seat, 'tile': t})
        self._after_kan(seat)

    def _kakan(self, seat, t):
        # 拼装新增：加杠时别人可以抢杠（荣和这张）
        self._interrupt()
        x = [y for y in self.hands[seat] if norm(y) == t][0]
        self.hands[seat].remove(x)
        self.hands[seat].sort(key=tile_key)
        for m in self.melds[seat]:
            if m['type'] == 'pon' and norm(m['tiles'][0]) == t:
                m['type'] = 'kakan'
                m['tiles'] = m['tiles'] + [x]
                break
        self._log({'type': 'kakan', 'seat': seat, 'tile': t})
        opts = {}
        for i in (1, 2, 3):
            s = (seat + i) % 4
            if self._can_ron(s, t):
                opts[s] = [{'type': 'ron', 'tile': t}]
        if opts:
            self.call_options = opts
            self.responses = {}
            self.kakan_pending = (seat, t)
            self.phase = 'call'
            return
        self._after_kan(seat)

    def _after_kan(self, seat):
        # TODO 天凤明杠/加杠的杠宝牌是打牌以后才翻，这里简化成杠完马上翻
        self.dora_count += 1
        self._log({'type': 'dora', 'tile': self.dora_indicators()[-1]})
        self.kan_seats.append(seat)
        # 拼装新增：四杠散了（四家杠齐了，第五个指示牌翻开前流局；
        # 第四次杠的人先摸岭上，能和就和，打出的牌没人荣和才算四杠散了）
        if self.rinshan_used >= 4 and len(set(self.kan_seats)) == 4:
            self.four_kans_pending = True
        self._draw(seat, rinshan=True)

    # ---------- 和牌结算 ----------
    def _parse_score(self, res, is_oya, is_tsumo):
        """260409 说返回“和的人得多少、别人各付多少”，我按 (得分, 各付) 接。
        子家自摸时 各付 应该是 (庄家付, 闲家付)；如果只给了一个数就当大家都付这么多。"""
        gain, pay = res[0], res[1]
        if isinstance(pay, (list, tuple)):
            if len(pay) >= 2:
                return gain, pay[0], pay[1]
            pay = pay[0]
        return gain, pay, pay

    def _score_one(self, seat, hand14, win_tile, is_tsumo, from_seat, honba, kyotaku, chankan=False):
        melds = self.melds_plain(seat)
        state = self._make_state(seat, is_tsumo)
        if chankan:
            state['chankan'] = True
        dora = self.dora_list(with_ura=False)
        yaku, han = calc_yaku(list(hand14), melds, win_tile, is_tsumo,
                              self.bakaze, self.jikaze(seat), dora, state)
        fu = calc_fu(norm_list(hand14), self.melds_plain(seat, True), norm(win_tile),
                     is_tsumo, self.bakaze, self.jikaze(seat),
                     an_gang=[norm_list(self.melds[seat][i]['tiles'])
                              for i in state['ankan_indices']],
                     rules=dict(self.rules))
        is_oya = seat == self.oya
        res = calc_score(fu, han, is_oya, is_tsumo, honba, kyotaku, rules=dict(self.rules))
        gain, pay_oya, pay_ko = self._parse_score(res, is_oya, is_tsumo)
        # 前端要的 points 是“这手牌本身值多少”，不含本场和供托
        _, base_oya, base_ko = self._parse_score(
            calc_score(fu, han, is_oya, is_tsumo, 0, 0, rules=dict(self.rules)), is_oya, is_tsumo)
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
            'yaku': yaku, 'han': han, 'fu': fu, 'delta': delta,
            # 这手牌本身的点数（不含本场供托）：荣和=放铳付的；自摸=三家付的合计
            'points': base_oya if not is_tsumo else base_oya + 2 * base_ko,
        }
        return info, delta

    def _win_tsumo(self, seat):
        self._log({'type': 'tsumo', 'seat': seat})
        info, delta = self._score_one(seat, self.hands[seat], self.drawn, True, None,
                                      self.honba, self.kyotaku)
        self.kyotaku = 0
        result = {'type': 'tsumo', 'wins': [info],
                  'dora_indicators': self.dora_indicators(),
                  'ura_indicators': self.ura_indicators() if self.riichi[seat] else []}
        self._end_round(result, delta, seat == self.oya, True)

    def _win_ron(self, winners, discarder, tile, chankan=False):
        # 双响可以（天凤），本场和立直棒给离放铳的人最近的那个（上家取り）
        self._log({'type': 'ron', 'seat': winners[0], 'from': discarder})
        total = [0] * 4
        wins = []
        for i, s in enumerate(winners):
            hb = self.honba if i == 0 else 0
            kt = self.kyotaku if i == 0 else 0
            info, delta = self._score_one(s, self.hands[s] + [tile], tile, False, discarder,
                                          hb, kt, chankan=chankan)
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
        self._log({'type': 'ryuukyoku', 'reason': 'exhaustive'})
        self._end_round(result, delta, tenpai[self.oya], False, draw=True)

    def _abort(self, reason):
        # 途中流局：天凤是庄家连庄、本场+1，立直棒留着
        key = {'荒牌流局': 'exhaustive', '九种九牌': 'kyuushu', '四杠散了': 'four_kans',
               '四家立直': 'four_riichi', '四风连打': 'four_winds', '三家和': 'triple_ron'}.get(reason, reason)
        self._log({'type': 'ryuukyoku', 'reason': key})
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
        main_last = self.main_rounds - 1          # 东4 / 南4
        ext_last = self.main_rounds + 3           # 延长战的最后一局
        if k == main_last:
            # all last：庄家和了而且是第一、30000 以上就结束（和了止め）
            if renchan and is_win and self.scores[self.oya] == top and top >= RETURN_POINTS:
                return True
            if not renchan:
                # 打完主赛：有人 30000 以上就结束，没有就西入延长
                return top >= RETURN_POINTS
            return False
        if k > main_last:
            # 延长战：有人到 30000 就结束，打完最后一局也结束
            if top >= RETURN_POINTS:
                return True
            return k == ext_last and not renchan
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
                'melds': [{'type': m['type'], 'tiles': list(m['tiles']), 'from': m['from']} for m in self.melds[s]],
                'riichi': self.riichi[s],
            }
            if seat is None or seat == s or self.phase == 'end':
                p['hand'] = list(self.hands[s])
            else:
                p['hand_count'] = len(self.hands[s])
            players.append(p)
        names = ['东', '南', '西']
        return {
            'round': {
                'name': names[min(self.kyoku // 4, 2)] + str(self.oya + 1) + '局',
                'kyoku': self.kyoku,
                'bakaze': self.bakaze,
                'oya': self.oya,
                'honba': self.honba,
                'kyotaku': self.kyotaku,
            },
            'rules': dict(self.rules),
            'length': self.length,
            'dora': self.dora_list(),
            'dora_indicators': self.dora_indicators(),
            'remaining': self.remaining(),
            'current': self.current,
            'drawn': self.drawn,
            'phase': self.phase,
            'last_discard': self.last_discard,
            'players': players,
            'legal_actions': self.get_legal_actions(seat) if seat is not None else [],
            'events': list(self.events),
            'result': self.result,
            'game_over': self.game_over,
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

    def fake_calc_fu(hand, melds, win_tile, is_tsumo, bakaze, jikaze, an_gang=None, rules=None):
        return 30

    def fake_calc_score(fu, han, is_oya, is_tsumo, honba, kyotaku, rules=None):
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
