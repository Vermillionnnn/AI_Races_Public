"""役和符：对一种拆法（含和了牌放在哪一组）算役、番、符、役满。

规则依据规则.md 第 4、6 节。挑哪种拆法最有利在 score.py 里做。
"""

from tiles import (DRAGONS, DRAGON_NAMES, GREEN, WIND_NAMES, WINDS, YAOCHU, counts, dora_from_indicator,
                   is_honor, is_terminal, is_yaochu, kind, num_of, suit_of)
from agari import decompositions, is_chiitoi, is_kokushi


class WinContext:
    """和了时的局面信息（和牌型无关的部分）。"""

    def __init__(self, *, tsumo, seat_wind, round_wind, dealer, rules, riichi=False, double_riichi=False,
                 ippatsu=False, haitei=False, houtei=False, rinshan=False, chankan=False, tenhou=False,
                 chiihou=False, dora_indicators=(), ura_indicators=()):
        self.tsumo = tsumo
        self.seat_wind = seat_wind          # 牌种编号 27..30
        self.round_wind = round_wind
        self.dealer = dealer                # 和了的人是不是庄家
        self.rules = rules
        self.riichi = riichi or double_riichi
        self.double_riichi = double_riichi
        self.ippatsu = ippatsu
        self.haitei = haitei
        self.houtei = houtei
        self.rinshan = rinshan
        self.chankan = chankan
        self.tenhou = tenhou
        self.chiihou = chiihou
        self.dora_indicators = list(dora_indicators)
        self.ura_indicators = list(ura_indicators)


def meld_kind(m):
    return min(kind(t) for t in m['tiles'])


def meld_groups(melds):
    """副露 -> [(形, 牌种, 是否明的)]，形是 seq / trip / kan。"""
    out = []
    for m in melds:
        k = meld_kind(m)
        t = m['type']
        if t == 'chi':
            out.append(('seq', k, True))
        elif t == 'pon':
            out.append(('trip', k, True))
        elif t in ('minkan', 'kakan'):
            out.append(('kan', k, True))
        else:
            out.append(('kan', k, False))
    return out


def _wait_of_seq(start, w):
    n = num_of(start)
    pos = w - start
    if pos == 1:
        return 'kanchan'
    if pos == 0:
        return 'penchan' if n == 7 else 'ryanmen'
    return 'penchan' if n == 1 else 'ryanmen'


def interpretations(concealed, win_tile, melds):
    """所有解释：(形式, 雀头, 暗手面子组, 听牌形)。形式为 std / chiitoi / kokushi。

    concealed 是手里的牌（含和了牌，不含副露）。std 的面子组是 [(形, 牌种, 是否明的)]，
    荣和时双碰完成的刻子由调用方按 tsumo 标成明刻（这里用 'ron_trip' 记下下标）。
    """
    c = counts(concealed)
    w = kind(win_tile)
    out = []
    for pair, sets in decompositions(c):
        seen = set()
        if pair == w:
            out.append(('std', pair, [(s, k, False) for s, k in sets], 'tanki', None))
        for i, (s, k) in enumerate(sets):
            if s == 'trip' and k == w:
                key = ('trip', k)
                wait = 'shanpon'
            elif s == 'seq' and k <= w <= k + 2:
                wait = _wait_of_seq(k, w)
                key = ('seq', k, wait)
            else:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(('std', pair, [(s2, k2, False) for s2, k2 in sets], wait, i))
    if not melds:
        if is_chiitoi(c):
            out.append(('chiitoi', None, None, 'tanki', None))
        if is_kokushi(c):
            out.append(('kokushi', None, None, None, None))
    return out


def _yakuman_mult(ctx, natural_double):
    """双倍役满的倍数：natural_double 是牌型本身算不算 2 倍。"""
    r = ctx.rules
    if not r['double_yakuman']:
        return 1
    if ctx.tenhou or ctx.chiihou:
        return 2 if r['tenhou_double'] else 1
    return 2 if natural_double else 1


def evaluate(interp, concealed, win_tile, melds, ctx):
    """一种解释的结果：{'yaku': [(名, 番)], 'han', 'fu', 'yakuman': [(名, 倍数)]}；
    yakuman 非空时普通役不算。宝牌由调用方加。没有役时 yaku 和 yakuman 都为空。"""
    form, pair, sets, wait, ron_idx = interp
    r = ctx.rules
    c14 = counts(concealed)
    w = kind(win_tile)
    menzen = all(m['type'] == 'ankan' for m in melds)
    allc = list(c14)
    for m in melds:
        for t in m['tiles']:
            allc[kind(t)] += 1
    kinds_used = [k for k in range(34) if allc[k]]
    c13 = list(c14)
    c13[w] -= 1

    yakuman = []
    if ctx.tenhou:
        yakuman.append(('天和', 1))
    if ctx.chiihou:
        yakuman.append(('地和', 1))
    if all(is_honor(k) for k in kinds_used):
        yakuman.append(('字一色', 1))

    if form == 'kokushi':
        mult = _yakuman_mult(ctx, all(c13[k] == 1 for k in YAOCHU))
        yakuman.append(('国士无双十三面' if mult == 2 and not (ctx.tenhou or ctx.chiihou) else '国士无双', mult))
        return {'yaku': [], 'han': 0, 'fu': 0, 'yakuman': yakuman}

    if form == 'chiitoi':
        if yakuman:
            return {'yaku': [], 'han': 0, 'fu': 0, 'yakuman': yakuman}
        yaku = _situational(ctx, menzen)
        yaku.append(('七对子', 2))
        _flush_and_terminal_yaku(yaku, kinds_used, menzen, r, melds)
        return {'yaku': yaku, 'han': sum(h for _, h in yaku), 'fu': 25, 'yakuman': []}

    # ---- 四面子一雀头
    groups = []
    for i, (s, k, _) in enumerate(sets):
        opened = (not ctx.tsumo) and ron_idx == i and s == 'trip'   # 荣和完成的刻子算明刻
        groups.append((s, k, opened))
    groups += meld_groups(melds)
    seqs = [k for s, k, _ in groups if s == 'seq']
    trips = [k for s, k, _ in groups if s != 'seq']
    kans = [k for s, k, _ in groups if s == 'kan']
    anko = sum(1 for s, k, o in groups if s != 'seq' and not o)

    if anko == 4:
        mult = _yakuman_mult(ctx, wait == 'tanki')
        yakuman.append(('四暗刻单骑' if mult == 2 and not (ctx.tenhou or ctx.chiihou) else '四暗刻', mult))
    if all(d in trips for d in DRAGONS):
        yakuman.append(('大三元', 1))
    wind_trips = [k for k in trips if k in WINDS]
    if len(wind_trips) == 4:
        yakuman.append(('大四喜', 2 if r['double_yakuman'] else 1))
    elif len(wind_trips) == 3 and pair in WINDS:
        yakuman.append(('小四喜', 1))
    if all(k in GREEN for k in kinds_used):
        yakuman.append(('绿一色', 1))
    if all(is_terminal(k) for k in kinds_used):
        yakuman.append(('清老头', 1))
    if len(kans) == 4:
        yakuman.append(('四杠子', 1))
    if not melds and len({suit_of(k) for k in kinds_used}) == 1 and kinds_used[0] < 27:
        b = suit_of(kinds_used[0]) * 9
        cs = c14[b:b + 9]
        if cs[0] >= 3 and cs[8] >= 3 and all(x >= 1 for x in cs[1:8]):
            c13s = c13[b:b + 9]
            pure = c13s == [3, 1, 1, 1, 1, 1, 1, 1, 3]
            mult = _yakuman_mult(ctx, pure)
            yakuman.append(('纯正九莲宝灯' if mult == 2 and not (ctx.tenhou or ctx.chiihou) else '九莲宝灯', mult))
    if yakuman:
        return {'yaku': [], 'han': 0, 'fu': 0, 'yakuman': yakuman}

    # ---- 普通役
    yaku = _situational(ctx, menzen)
    yakuhai_kinds = set(DRAGONS) | {ctx.seat_wind, ctx.round_wind}
    pinfu = (menzen and not melds and len(seqs) == 4 and pair not in yakuhai_kinds and wait == 'ryanmen')
    if pinfu:
        yaku.append(('平和', 1))
    if menzen:
        peiko = 0
        for k in set(seqs):
            peiko += seqs.count(k) // 2
        if peiko >= 2:
            yaku.append(('二杯口', 3))
        elif peiko == 1:
            yaku.append(('一杯口', 1))
    for d in DRAGONS:
        if d in trips:
            yaku.append(('役牌 ' + DRAGON_NAMES[d], 1))
    if ctx.seat_wind in trips:
        yaku.append(('自风 ' + WIND_NAMES[ctx.seat_wind], 1))
    if ctx.round_wind in trips:
        yaku.append(('场风 ' + WIND_NAMES[ctx.round_wind], 1))
    # 三色同顺、一气通贯
    for k in set(seqs):
        if k < 9 and (k + 9) in seqs and (k + 18) in seqs:
            yaku.append(('三色同顺', 2 if menzen else 1))
            break
    for s in range(3):
        if all(s * 9 + o in seqs for o in (0, 3, 6)):
            yaku.append(('一气通贯', 2 if menzen else 1))
            break
    # 混全带幺九、纯全带幺九（要有顺子；全是幺九刻子的是混老头）
    def has_yaochu(g):
        s, k, _ = g
        return is_yaochu(k) or (s == 'seq' and num_of(k) == 7)
    if seqs and all(has_yaochu(g) for g in groups) and is_yaochu(pair):
        if any(is_honor(k) for k in kinds_used):
            yaku.append(('混全带幺九', 2 if menzen else 1))
        else:
            yaku.append(('纯全带幺九', 3 if menzen else 2))
    if not seqs:
        yaku.append(('对对和', 2))
    if anko == 3:
        yaku.append(('三暗刻', 2))
    for n in range(9):
        if n in trips and n + 9 in trips and n + 18 in trips:
            yaku.append(('三色同刻', 2))
            break
    if len(kans) == 3:
        yaku.append(('三杠子', 2))
    if sum(1 for d in DRAGONS if d in trips) == 2 and pair in DRAGONS:
        yaku.append(('小三元', 2))
    _flush_and_terminal_yaku(yaku, kinds_used, menzen, r, melds)

    if not yaku:
        return {'yaku': [], 'han': 0, 'fu': 0, 'yakuman': []}
    fu = calc_fu(groups, pair, wait, menzen, pinfu, ctx)
    return {'yaku': yaku, 'han': sum(h for _, h in yaku), 'fu': fu, 'yakuman': []}


def _situational(ctx, menzen):
    """和牌型无关的役：立直、一发、门清自摸、海底、河底、岭上、抢杠。"""
    yaku = []
    if ctx.double_riichi:
        yaku.append(('两立直', 2))
    elif ctx.riichi:
        yaku.append(('立直', 1))
    if ctx.ippatsu and ctx.riichi:
        yaku.append(('一发', 1))
    if menzen and ctx.tsumo:
        yaku.append(('门前清自摸和', 1))
    if ctx.haitei:
        yaku.append(('海底摸月', 1))
    if ctx.houtei:
        yaku.append(('河底捞鱼', 1))
    if ctx.rinshan:
        yaku.append(('岭上开花', 1))
    if ctx.chankan:
        yaku.append(('抢杠', 1))
    return yaku


def _flush_and_terminal_yaku(yaku, kinds_used, menzen, r, melds):
    """断幺九、混老头、混一色、清一色（七对子和四面子型共用）。"""
    if all(not is_yaochu(k) for k in kinds_used) and (menzen or r['kuitan']):
        yaku.append(('断幺九', 1))
    if all(is_yaochu(k) for k in kinds_used) and any(is_honor(k) for k in kinds_used) \
            and any(not is_honor(k) for k in kinds_used):
        yaku.append(('混老头', 2))
    suits = {suit_of(k) for k in kinds_used if k < 27}
    if len(suits) == 1:
        if any(is_honor(k) for k in kinds_used):
            yaku.append(('混一色', 3 if menzen else 2))
        else:
            yaku.append(('清一色', 6 if menzen else 5))


def calc_fu(groups, pair, wait, menzen, pinfu, ctx):
    if pinfu:
        return 20 if ctx.tsumo else 30
    fu = 20
    if menzen and not ctx.tsumo:
        fu += 10
    if ctx.tsumo:
        fu += 2
    for s, k, opened in groups:
        if s == 'seq':
            continue
        v = 2
        if not opened:
            v *= 2
        if s == 'kan':
            v *= 4
        if is_yaochu(k):
            v *= 2
        fu += v
    if pair in DRAGONS:
        fu += 2
    if pair == ctx.seat_wind and pair == ctx.round_wind:
        fu += ctx.rules['renpu_fu']
    elif pair == ctx.seat_wind or pair == ctx.round_wind:
        fu += 2
    if wait in ('kanchan', 'penchan', 'tanki'):
        fu += 2
    fu = (fu + 9) // 10 * 10
    if not menzen and fu == 20:
        fu = 30
    return fu


def count_dora(all_tiles, ctx):
    """(宝牌, 赤宝牌, 里宝牌) 张数。all_tiles 是手里加副露的全部牌（杠算 4 张）。"""
    c = counts(all_tiles)
    dora = sum(c[dora_from_indicator(kind(t))] for t in ctx.dora_indicators)
    aka = sum(1 for t in all_tiles if t[0] == '0') if ctx.rules['aka_dora'] else 0
    ura = sum(c[dora_from_indicator(kind(t))] for t in ctx.ura_indicators) if ctx.riichi else 0
    return dora, aka, ura
