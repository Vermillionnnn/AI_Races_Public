# 学号 250118

from collections import Counter


SUITS = "mps"
WINDS = {"1z": "东", "2z": "南", "3z": "西", "4z": "北"}
DRAGONS = {"5z": "白", "6z": "发", "7z": "中"}
HONORS = set(WINDS) | set(DRAGONS)
TERMINALS = {n + suit for n in "19" for suit in SUITS}
ORPHANS = TERMINALS | HONORS
TILES = {n + suit for n in "123456789" for suit in SUITS} | HONORS
GREENS = {"2s", "3s", "4s", "6s", "8s", "6z"}
RED_FIVES = {"0m", "0p", "0s"}


def normal_tile(tile):
    if tile in RED_FIVES:
        return "5" + tile[1]
    return tile


def sequence(start):
    rank = int(start[0])
    return tuple(str(rank + i) + start[1] for i in range(3))


# 面子用 (类型, 代表牌, 是否明的) 表示，顺子的代表牌是最小那张。
def split_groups(counts, left):
    # 除了让正常递归及时结束，也避免非法牌数在 min() 处崩溃。
    if left < 0 or any(n < 0 for n in counts.values()):
        return
    remaining = sum(counts.values())
    if remaining != 3 * left:
        return
    if left == 0:
        yield []
        return

    first = min(tile for tile in counts if counts[tile] > 0)
    choices = []
    if counts[first] >= 3:
        choices.append(("triplet", (first,) * 3))
    if first[1] in SUITS and first[0] <= "7":
        tiles = sequence(first)
        if all(counts[tile] > 0 for tile in tiles):
            choices.append(("sequence", tiles))

    for kind, tiles in choices:
        counts.subtract(tiles)
        for rest in split_groups(counts, left - 1):
            yield [(kind, first, False)] + rest
        counts.update(tiles)


def split_hand(counts, groups_needed):
    for pair in counts:
        if counts[pair] >= 2:
            rest = counts.copy()
            rest[pair] -= 2
            for groups in split_groups(rest, groups_needed):
                yield pair, groups


def read_melds(melds, ankan_indices):
    groups = []
    for i, meld in enumerate(melds):
        tiles = sorted(normal_tile(tile) for tile in meld)
        if any(tile not in TILES for tile in tiles):
            return None

        if len(tiles) == 4 and tiles[0] == tiles[-1]:
            groups.append(("kan", tiles[0], i not in ankan_indices))
        elif len(tiles) == 3 and tiles[0] == tiles[-1]:
            groups.append(("triplet", tiles[0], True))
        elif (len(tiles) == 3 and tiles[0][1] in SUITS
              and tuple(tiles) == sequence(tiles[0])):
            groups.append(("sequence", tiles[0], True))
        else:
            return None
    return groups


def winning_places(pair, groups, win_tile):
    if pair == win_tile:
        yield "pair", None
    for kind, tile, _ in groups:
        if kind == "triplet" and tile == win_tile:
            yield "triplet", tile
        elif kind == "sequence" and win_tile in sequence(tile):
            yield "sequence", tile


def yaku_tanyao(tiles):
    return not tiles & ORPHANS


def yaku_pinfu(closed, pair, sequences, wait, win_tile, bakaze, jikaze):
    if not closed or len(sequences) != 4:
        return False
    if pair in DRAGONS or pair in (bakaze, jikaze):
        return False
    kind, start = wait
    if kind != "sequence":
        return False
    low, _, high = sequence(start)
    return (win_tile == low and low[0] != "7"
            or win_tile == high and low[0] != "1")


def yaku_iipeikou(closed, pairs_of_sequences):
    return closed and pairs_of_sequences == 1


def yaku_ryanpeikou(closed, pairs_of_sequences):
    return closed and pairs_of_sequences == 2


def yaku_yakuhai(triplets, bakaze, jikaze):
    result = [("役牌 " + name, 1) for tile, name in DRAGONS.items()
              if tile in triplets]
    if bakaze in WINDS and bakaze in triplets:
        result.append(("场风 " + WINDS[bakaze], 1))
    if jikaze in WINDS and jikaze in triplets:
        result.append(("自风 " + WINDS[jikaze], 1))
    return result


def yaku_chiitoitsu(counts):
    return len(counts) == 7 and all(n == 2 for n in counts.values())


def yaku_toitoi(triplets):
    return len(triplets) == 4


def yaku_sanankou(concealed_triplets):
    return concealed_triplets == 3


def yaku_sankantsu(kans):
    return kans == 3


def yaku_sanshoku_doujun(sequences):
    starts = set(sequences)
    return any(all(n + suit in starts for suit in SUITS) for n in "1234567")


def yaku_sanshoku_doukou(triplets):
    return any(all(n + suit in triplets for suit in SUITS) for n in "123456789")


def yaku_ittsuu(sequences):
    starts = set(sequences)
    return any(all(n + suit in starts for n in "147") for suit in SUITS)


def outside_hand(pair, groups):
    return pair in ORPHANS and all(
        tile[0] in "17" if kind == "sequence" else tile in ORPHANS
        for kind, tile, _ in groups
    )


def yaku_chanta(pair, groups, sequences, tiles):
    return sequences and tiles & HONORS and outside_hand(pair, groups)


def yaku_junchan(pair, groups, sequences, tiles):
    return sequences and not tiles & HONORS and outside_hand(pair, groups)


def yaku_honroutou(tiles):
    return tiles <= ORPHANS


def yaku_shousangen(pair, triplets):
    return pair in DRAGONS and len(triplets & DRAGONS.keys()) == 2


def yaku_honitsu(suits):
    return len(suits) == 2 and "z" in suits


def yaku_chinitsu(suits):
    return len(suits) == 1 and "z" not in suits


def yaku_kokushi(counts, win_tile):
    if counts.keys() == ORPHANS:
        return 2 if counts[win_tile] == 2 else 1
    return 0


def yaku_suuankou(concealed_triplets, wait):
    if concealed_triplets == 4:
        return 2 if wait[0] == "pair" else 1
    return 0


def yaku_chuuren(counts, win_tile):
    suit = win_tile[1]
    if suit not in SUITS or any(tile[1] != suit for tile in counts):
        return 0
    base = Counter(n + suit for n in "1112345678999")
    if any(counts[tile] < n for tile, n in base.items()):
        return 0
    return 2 if counts[win_tile] > base[win_tile] else 1


def yaku_daisangen(triplets):
    return DRAGONS.keys() <= triplets


def yaku_shousuushii(pair, triplets):
    return pair in WINDS and len(triplets & WINDS.keys()) == 3


def yaku_daisuushii(triplets):
    return WINDS.keys() <= triplets


def yaku_tsuuiisou(tiles):
    return tiles <= HONORS


def yaku_chinroutou(tiles):
    return tiles <= TERMINALS


def yaku_ryuuiisou(tiles):
    return tiles <= GREENS


def yaku_suukantsu(kans):
    return kans == 4


def situation_yaku(closed, is_tsumo, state):
    result = []
    if closed:
        if state.get("double_riichi"):
            result.append(("两立直", 2))
        elif state.get("riichi"):
            result.append(("立直", 1))
        if state.get("ippatsu") and (state.get("riichi") or state.get("double_riichi")):
            result.append(("一发", 1))
        if is_tsumo:
            result.append(("门前清自摸和", 1))

    if is_tsumo:
        if state.get("rinshan"):
            result.append(("岭上开花", 1))
        elif state.get("haitei"):
            result.append(("海底摸月", 1))
    else:
        if state.get("chankan"):
            result.append(("抢杠", 1))
        elif state.get("houtei"):
            result.append(("河底捞鱼", 1))
    return result


def tile_yaku(tiles, closed):
    suits = {tile[1] for tile in tiles}
    checks = [
        (yaku_tanyao(tiles), "断幺九", 1),
        (yaku_honroutou(tiles), "混老头", 2),
        (yaku_honitsu(suits), "混一色", 3 if closed else 2),
        (yaku_chinitsu(suits), "清一色", 6 if closed else 5),
    ]
    return [(name, han) for ok, name, han in checks if ok]


def group_yaku(pair, groups, sequences, triplets, concealed_triplets, kans,
               closed, tiles, wait, win_tile, bakaze, jikaze):
    seq_pairs = sum(n // 2 for n in Counter(sequences).values())
    checks = [
        (yaku_pinfu(closed, pair, sequences, wait, win_tile, bakaze, jikaze), "平和", 1),
        (yaku_iipeikou(closed, seq_pairs), "一杯口", 1),
        (yaku_ryanpeikou(closed, seq_pairs), "二杯口", 3),
        (yaku_toitoi(triplets), "对对和", 2),
        (yaku_sanankou(concealed_triplets), "三暗刻", 2),
        (yaku_sankantsu(kans), "三杠子", 2),
        (yaku_sanshoku_doujun(sequences), "三色同顺", 2 if closed else 1),
        (yaku_sanshoku_doukou(triplets), "三色同刻", 2),
        (yaku_ittsuu(sequences), "一气通贯", 2 if closed else 1),
        (yaku_chanta(pair, groups, sequences, tiles), "混全带幺九", 2 if closed else 1),
        (yaku_junchan(pair, groups, sequences, tiles), "纯全带幺九", 3 if closed else 2),
        (yaku_shousangen(pair, triplets), "小三元", 2),
    ]
    return yaku_yakuhai(triplets, bakaze, jikaze) + [
        (name, han) for ok, name, han in checks if ok
    ]


def tile_yakuman(tiles, is_tsumo, melds, jikaze, state):
    result = []
    if is_tsumo and not melds:
        if jikaze == "1z" and state.get("tenhou"):
            result.append(("天和", 1))
        elif (jikaze in WINDS and jikaze != "1z"
              and (state.get("chihou") or state.get("chiihou"))):
            result.append(("地和", 1))
    for ok, name in [
        (yaku_tsuuiisou(tiles), "字一色"),
        (yaku_chinroutou(tiles), "清老头"),
        (yaku_ryuuiisou(tiles), "绿一色"),
    ]:
        if ok:
            result.append((name, 1))
    return result


def group_yakuman(pair, triplets, concealed_triplets, kans, wait):
    result = []
    for ok, name, times in [
        (yaku_daisangen(triplets), "大三元", 1),
        (yaku_shousuushii(pair, triplets), "小四喜", 1),
        (yaku_daisuushii(triplets), "大四喜", 2),
        (yaku_suukantsu(kans), "四杠子", 1),
    ]:
        if ok:
            result.append((name, times))
    suuankou = yaku_suuankou(concealed_triplets, wait)
    if suuankou:
        result.append(("四暗刻单骑" if suuankou == 2 else "四暗刻", suuankou))
    return result


def dora_yaku(raw_tiles, dora, closed, state, aka_dora=True):
    counts = Counter(normal_tile(tile) for tile in raw_tiles)
    ordinary = sum(counts[normal_tile(tile)] for tile in dora)
    red = sum(tile in RED_FIVES for tile in raw_tiles) if aka_dora else 0
    ura = 0
    if closed and (state.get("riichi") or state.get("double_riichi")):
        ura = sum(counts[normal_tile(tile)]
                  for tile in (state.get("ura_dora") or []))
    return [
        (f"{name}{n}", n)
        for name, n in [("宝牌", ordinary), ("赤宝牌", red), ("里宝牌", ura)]
        if n
    ]


def _total_han(yaku):
    return sum(han for _, han in yaku)


def calc_hand_details(hand, melds, win_tile, is_tsumo, bakaze, jikaze,
                      dora, state, rules=None):
    """返回 ([{'name': 役名, 'han': 番数}, ...], 总番数, 符数)。

    番和符来自同一个拆法及听牌位置；普通形和七对子也一起比较。
    选择顺序为先比较不含宝牌的番数，再比较该拆法的符数。
    参数与 calc_yaku_detailed 相同，rules 另支持 renpu_fu。
    """
    state = state or {}
    rules = rules or {}
    melds = melds or []
    groups_from_melds = read_melds(
        melds, state.get("ankan_indices") or []
    )
    if groups_from_melds is None or len(melds) > 4:
        return [], 0, 0

    size = 14 - 3 * len(melds)
    if len(hand) == size - 1:
        hand = list(hand) + [win_tile]
    elif len(hand) != size or win_tile not in hand:
        return [], 0, 0

    raw_tiles = list(hand) + [tile for meld in melds for tile in meld]
    all_counts = Counter(normal_tile(tile) for tile in raw_tiles)
    tiles = set(all_counts)
    if not tiles <= TILES or any(n > 4 for n in all_counts.values()):
        return [], 0, 0

    win_tile = normal_tile(win_tile)
    hand_counts = Counter(normal_tile(tile) for tile in hand)
    # 任务书的四张牌看不出明暗，没标暗杠的就当明杠。
    closed = not any(is_open for _, _, is_open in groups_from_melds)
    common = situation_yaku(closed, is_tsumo, state) + tile_yaku(tiles, closed)
    if not closed and not rules.get("kuitan", True):
        common = [item for item in common if item[0] != "断幺九"]
    common_yakuman = tile_yakuman(tiles, is_tsumo, melds, jikaze, state)

    from fu import calc_fu

    ankan_indices = [
        i for i in (state.get("ankan_indices") or [])
        if 0 <= i < len(melds)
    ]
    an_gang = [melds[i] for i in ankan_indices]
    renpu_fu = rules.get("renpu_fu", 4)
    best_yaku, best_yaku_key, best_yaku_fu = [], None, 0
    best_yakuman, best_yakuman_key, best_yakuman_fu = [], None, 0

    def consider(yaku, yakuman, shape):
        nonlocal best_yaku, best_yaku_key, best_yaku_fu
        nonlocal best_yakuman, best_yakuman_key, best_yakuman_fu
        fu = calc_fu(
            hand, melds, win_tile, is_tsumo, bakaze, jikaze,
            an_gang=an_gang, renpu_fu=renpu_fu, _shape=shape
        )
        key = (_total_han(yaku), fu)
        if best_yaku_key is None or key > best_yaku_key:
            best_yaku, best_yaku_key, best_yaku_fu = yaku, key, fu
        if yakuman:
            # 役满不按符区分；同番时保留原来的候选顺序。
            yakuman_key = _total_han(yakuman)
            if best_yakuman_key is None or yakuman_key > best_yakuman_key:
                best_yakuman = yakuman
                best_yakuman_key = yakuman_key
                best_yakuman_fu = fu

    if not melds:
        kokushi = yaku_kokushi(hand_counts, win_tile)
        if kokushi:
            name = "国士无双十三面" if kokushi == 2 else "国士无双"
            candidate = common_yakuman + [(name, kokushi)]
            consider([], candidate, ("kokushi",))
        if yaku_chiitoitsu(hand_counts):
            candidate = common + [("七对子", 2)]
            consider(candidate, common_yakuman, ("chiitoitsu",))

        chuuren = yaku_chuuren(hand_counts, win_tile)
        if chuuren:
            name = "纯正九莲宝灯" if chuuren == 2 else "九莲宝灯"
            candidate = common_yakuman + [(name, chuuren)]
            consider([], candidate, ("auto",))

    kans = sum(kind == "kan" for kind, _, _ in groups_from_melds)
    for pair, hand_groups in split_hand(hand_counts, 4 - len(melds)):
        groups = hand_groups + groups_from_melds
        sequences = [tile for kind, tile, _ in groups if kind == "sequence"]
        triplets = {tile for kind, tile, _ in groups if kind != "sequence"}
        concealed = sum(kind != "sequence" and not is_open for kind, _, is_open in groups)
        fu_groups = [
            ("ke" if kind == "triplet" else "shun", tile)
            for kind, tile, _ in hand_groups
        ]
        for wait in winning_places(pair, hand_groups, win_tile):
            # 荣和补成的刻子不算暗刻，但门前清还在。
            concealed_triplets = concealed - (not is_tsumo and wait[0] == "triplet")
            yakuman = common_yakuman + group_yakuman(
                pair, triplets, concealed_triplets, kans, wait
            )
            yaku = common + group_yaku(
                pair, groups, sequences, triplets, concealed_triplets, kans,
                closed, tiles, wait, win_tile, bakaze, jikaze
            )
            consider(yaku, yakuman, ("general", pair, fu_groups, wait))

    if best_yakuman:
        # 双倍和复合役满一起算，每倍用 13 番传给算点。
        result = [(name, 13 * times) for name, times in best_yakuman]
        fu = best_yakuman_fu
    else:
        # 宝牌只加番，不能在没有任何役时单独构成和牌。
        if not best_yaku:
            return [], 0, best_yaku_fu
        result = best_yaku + dora_yaku(
            raw_tiles, dora or [], closed, state,
            aka_dora=rules.get("aka_dora", True)
        )
        fu = best_yaku_fu
    return ([{"name": name, "han": han} for name, han in result],
            _total_han(result), fu)


def calc_yaku_detailed(hand, melds, win_tile, is_tsumo, bakaze, jikaze,
                       dora, state, rules=None):
    """返回 ([{'name': 役名, 'han': 番数}, ...], 总番数)。

    hand 只放手里没摊开的牌；和牌可以单传，也可以已经在 hand 里。
    dora 和 state['ura_dora'] 分别传实际宝牌、实际里宝牌列表。
    state 可加 ankan_indices（暗杠在 melds 里的下标，从 0 开始）、
    chihou/chiihou（地和）和 ura_dora。rules 支持 kuitan、aka_dora、renpu_fu。
    需要同时取符时使用 calc_hand_details，避免重复枚举拆法。
    """
    detailed, han, _ = calc_hand_details(
        hand, melds, win_tile, is_tsumo, bakaze, jikaze, dora, state, rules
    )
    return detailed, han


def calc_yaku(hand, melds, win_tile, is_tsumo, bakaze, jikaze, dora, state,
              rules=None):
    """返回 (役名字符串列表, 总番数)，参数与 calc_yaku_detailed 相同。"""
    detailed, han = calc_yaku_detailed(
        hand, melds, win_tile, is_tsumo, bakaze, jikaze, dora, state, rules
    )
    return [item["name"] for item in detailed], han
