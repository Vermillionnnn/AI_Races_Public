# 学号 250118

from collections import Counter
from dataclasses import dataclass


SUITS = "mps"
WINDS = {"1z": "东", "2z": "南", "3z": "西", "4z": "北"}
DRAGONS = {"5z": "白", "6z": "发", "7z": "中"}
HONORS = set(WINDS) | set(DRAGONS)
TERMINALS = {n + suit for n in "19" for suit in SUITS}
ORPHANS = TERMINALS | HONORS
TILES = {n + suit for n in "123456789" for suit in SUITS} | HONORS
GREENS = {"2s", "3s", "4s", "6s", "8s", "6z"}
RED_FIVES = {"0m", "0p", "0s"}
DORA_NAMES = {"宝牌", "赤宝牌", "里宝牌"}


@dataclass(frozen=True)
class HandShape:
    kind: str
    pair: str | None = None
    groups: tuple = ()
    wait: tuple = ()


@dataclass(frozen=True)
class YakuOption:
    shape: HandShape
    entries: tuple
    yakuman: int = 0

    @property
    def han(self):
        return sum(han for _, han in self.entries)


def normal_tile(tile):
    if tile in RED_FIVES:
        return "5" + tile[1]
    return tile


def sequence(start):
    rank = int(start[0])
    return tuple(str(rank + i) + start[1] for i in range(3))


# 面子用 (类型, 代表牌, 是否明的) 表示，顺子的代表牌是最小那张。
def split_groups(counts, left):
    if left == 0:
        if not any(counts.values()):
            yield []
        return

    first = min((tile for tile in counts if counts[tile] > 0), default=None)
    if first is None:
        return
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


def tile_yaku(tiles, closed, kuitan):
    suits = {tile[1] for tile in tiles}
    checks = [
        ((closed or kuitan) and yaku_tanyao(tiles), "断幺九", 1),
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
        elif jikaze in WINDS and jikaze != "1z" and (
                state.get("chiihou") or state.get("chihou")):
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


def dora_yaku(raw_tiles, dora, closed, state):
    counts = Counter(normal_tile(tile) for tile in raw_tiles)
    ordinary = sum(counts[normal_tile(tile)] for tile in dora)
    red = sum(tile in RED_FIVES for tile in raw_tiles) if state.get("aka_dora", True) else 0
    ura = 0
    if closed and (state.get("riichi") or state.get("double_riichi")):
        ura = sum(counts[normal_tile(tile)] for tile in state.get("ura_dora", []))
    return [
        (name, n)
        for name, n in [("宝牌", ordinary), ("赤宝牌", red), ("里宝牌", ura)]
        if n
    ]


def parse_hand(hand, melds, win_tile, ankan_indices=()):
    """规范化和牌形，同时保留赤宝牌原值供计番。"""
    groups_from_melds = read_melds(melds, ankan_indices)
    if groups_from_melds is None or len(melds) > 4 or normal_tile(win_tile) not in TILES:
        return None

    size = 14 - 3 * len(melds)
    if len(hand) == size - 1:
        hand = list(hand) + [win_tile]
    elif len(hand) != size or win_tile not in hand:
        return None

    raw_tiles = list(hand) + [tile for meld in melds for tile in meld]
    all_counts = Counter(normal_tile(tile) for tile in raw_tiles)
    if not all_counts.keys() <= TILES or any(n > 4 for n in all_counts.values()):
        return None
    return raw_tiles, Counter(normal_tile(tile) for tile in hand), groups_from_melds, normal_tile(win_tile)


def hand_shapes(hand_counts, groups_from_melds, win_tile):
    """列出每种有效拆法，并且标记和牌落在哪一组。"""
    if not groups_from_melds:
        if yaku_kokushi(hand_counts, win_tile):
            yield HandShape("thirteen_orphans")
        if yaku_chiitoitsu(hand_counts):
            yield HandShape("seven_pairs")
    for pair, hand_groups in split_hand(hand_counts, 4 - len(groups_from_melds)):
        groups = tuple(hand_groups + groups_from_melds)
        for wait in dict.fromkeys(winning_places(pair, hand_groups, win_tile)):
            yield HandShape("standard", pair, groups, wait)


def scoring_options(hand, melds, win_tile, is_tsumo, bakaze, jikaze, dora, state):
    """给每个有役的拆法保留番数、役满和拆牌位置，供点数模块比较。"""
    state = state or {}
    melds = melds or []
    parsed = parse_hand(hand, melds, win_tile, state.get("ankan_indices", ()))
    if parsed is None:
        return
    raw_tiles, hand_counts, open_groups, win_tile = parsed
    tiles = {normal_tile(tile) for tile in raw_tiles}
    closed = not any(is_open for _, _, is_open in open_groups)
    common = situation_yaku(closed, is_tsumo, state) + tile_yaku(tiles, closed, state.get("kuitan", True))
    common_yakuman = tile_yakuman(tiles, is_tsumo, melds, jikaze, state)
    if not melds and (chuuren := yaku_chuuren(hand_counts, win_tile)):
        name = "纯正九莲宝灯" if chuuren == 2 else "九莲宝灯"
        common_yakuman.append((name, chuuren))
    bonuses = dora_yaku(raw_tiles, dora or [], closed, state)
    kans = sum(kind == "kan" for kind, _, _ in open_groups)

    for shape in hand_shapes(hand_counts, open_groups, win_tile):
        yaku = list(common)
        yakuman = list(common_yakuman)
        if shape.kind == "thirteen_orphans":
            times = yaku_kokushi(hand_counts, win_tile)
            name = "国士无双十三面" if times == 2 else "国士无双"
            yakuman.append((name, times))
        elif shape.kind == "seven_pairs":
            yaku.append(("七对子", 2))
        else:
            sequences = [tile for kind, tile, _ in shape.groups if kind == "sequence"]
            triplets = {tile for kind, tile, _ in shape.groups if kind != "sequence"}
            concealed = sum(kind != "sequence" and not is_open for kind, _, is_open in shape.groups)
            # 荣和补成的刻子算明刻，但门前清还在。
            concealed -= not is_tsumo and shape.wait[0] == "triplet"
            yakuman += group_yakuman(shape.pair, triplets, concealed, kans, shape.wait)
            yaku += group_yaku(shape.pair, shape.groups, sequences, triplets, concealed, kans,
                               closed, tiles, shape.wait, win_tile, bakaze, jikaze)
        if yakuman:
            yield YakuOption(shape, tuple((name, 13 * times) for name, times in yakuman),
                             sum(times for _, times in yakuman))
        elif yaku:
            yield YakuOption(shape, tuple(yaku + bonuses))


def calc_yaku(hand, melds, win_tile, is_tsumo, bakaze, jikaze, dora, state):
    """返回 (役名列表, 总番数)。hand 可含或不含和牌，dora 用实际宝牌。"""
    best = max(scoring_options(hand, melds, win_tile, is_tsumo, bakaze, jikaze, dora, state),
               key=lambda option: (bool(option.yakuman), option.han), default=None)
    if best is None:
        return [], 0
    return [f"{name}{han}" if name in DORA_NAMES else name for name, han in best.entries], best.han
