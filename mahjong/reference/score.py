"""点数：基本点、封顶、挑最有利的拆法、和了时谁付多少（规则.md 第 3 节“包”、第 7 节）。"""

from tiles import counts
from agari import is_agari
from yaku_fu import count_dora, evaluate, interpretations


def ceil100(x):
    return -(-x // 100) * 100


def base_points(han, fu, rules):
    """普通役的基本点（累计役满算 8000）。"""
    if han >= 13 and rules['kazoe_yakuman']:
        return 8000
    if han >= 11:
        return 6000
    if han >= 8:
        return 4000
    if han >= 6:
        return 3000
    b = fu * 2 ** (han + 2)
    if han >= 5 or b > 2000:
        return 2000
    if rules['kiriage_mangan'] and ((han == 4 and fu == 30) or (han == 3 and fu == 60)):
        return 2000
    return b


def hand_value(base, dealer, tsumo):
    """这手牌本身值多少点（不含本场、供托）：荣和是放铳者付的数，自摸是三家合计。"""
    if not tsumo:
        return ceil100(base * (6 if dealer else 4))
    if dealer:
        return 3 * ceil100(base * 2)
    return ceil100(base * 2) + 2 * ceil100(base)


def best_win(concealed, win_tile, melds, ctx):
    """和了的最好算法。concealed 是手里的牌（含和了牌）。
    返回 dict（yaku、han、fu、yakuman、yakuman_items、base、points），没有役或不是和了型时返回 None。"""
    c = counts(concealed)
    if not is_agari(c, len(melds)):
        return None
    all_tiles = list(concealed)
    for m in melds:
        all_tiles += m['tiles']
    dora, aka, ura = count_dora(all_tiles, ctx)
    rules = ctx.rules
    best = None
    for interp in interpretations(concealed, win_tile, melds):
        ev = evaluate(interp, concealed, win_tile, melds, ctx)
        if ev['yakuman']:
            items = ev['yakuman']
            if not rules['composite_yakuman']:
                items = [max(items, key=lambda x: x[1])]
            total = sum(m for _, m in items)
            res = {
                'yaku': [(n, 13 * m) for n, m in items],
                'han': 13 * total, 'fu': 0, 'yakuman': total, 'yakuman_items': items,
                'base': 8000 * total,
            }
        elif ev['yaku']:
            yaku = list(ev['yaku'])
            if dora:
                yaku.append(('宝牌', dora))
            if aka:
                yaku.append(('赤宝牌', aka))
            if ura:
                yaku.append(('里宝牌', ura))
            han = sum(h for _, h in yaku)
            res = {'yaku': yaku, 'han': han, 'fu': ev['fu'], 'yakuman': 0, 'yakuman_items': [],
                   'base': base_points(han, ev['fu'], rules)}
        else:
            continue
        res['points'] = hand_value(res['base'], ctx.dealer, ctx.tsumo)
        key = (res['points'], res['han'], res['fu'])
        if best is None or key > best[0]:
            best = (key, res)
    return best[1] if best else None


# ---------------------------------------------------------------- 付点

PAO_YAKU = {'大三元', '大四喜'}


def win_payments(win, winner, dealer, tsumo, loser, honba, pao_seat, rules):
    """一位和了者的付点（不含供托）。返回四个座位的变化量。

    win: best_win 的结果；loser: 荣和时的放铳者；honba: 这一位要收的本场数（一炮双响时只有第一位收）；
    pao_seat: 这手牌里有包的役（大三元/大四喜）时负责的座位，否则 None。
    """
    delta = [0, 0, 0, 0]
    is_dealer = winner == dealer
    pao_mult = 0
    if pao_seat is not None and rules['pao'] and win['yakuman']:
        pao_mult = sum(m for n, m in win['yakuman_items'] if n in PAO_YAKU)
    rest_base = win['base'] - 8000 * pao_mult
    pao_base = 8000 * pao_mult

    def pay(frm, amount):
        delta[frm] -= amount
        delta[winner] += amount

    # 不归包的部分：正常付
    if rest_base:
        if tsumo:
            for s in range(4):
                if s == winner:
                    continue
                pay(s, ceil100(rest_base * 2) if (is_dealer or s == dealer) else ceil100(rest_base))
        else:
            pay(loser, ceil100(rest_base * (6 if is_dealer else 4)))
    # 包的部分
    if pao_base:
        full = pao_base * (6 if is_dealer else 4)
        if tsumo or loser == pao_seat:
            pay(pao_seat, full)
        else:
            pay(loser, full // 2)
            pay(pao_seat, full // 2)
    # 本场：包的时候由实际付钱的人按同样的比例付
    if honba:
        if pao_mult:
            if tsumo or loser == pao_seat:
                pay(pao_seat, 300 * honba)
            else:
                pay(loser, 150 * honba)
                pay(pao_seat, 150 * honba)
        elif tsumo:
            for s in range(4):
                if s != winner:
                    pay(s, 100 * honba)
        else:
            pay(loser, 300 * honba)
    return delta
