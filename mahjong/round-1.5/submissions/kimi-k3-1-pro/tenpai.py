# 学号: 260522
# 听牌提示模块：判断能不能和、听什么牌、还剩几张、打哪张能听

ALL_TILES = (
    [f"{i}m" for i in range(1, 10)]
    + [f"{i}p" for i in range(1, 10)]
    + [f"{i}s" for i in range(1, 10)]
    + [f"{i}z" for i in range(1, 8)]
)

YAOCHU = {
    "1m", "9m", "1p", "9p", "1s", "9s",
    "1z", "2z", "3z", "4z", "5z", "6z", "7z",
}


def _norm(tile):
    # 红五 0m/0p/0s 统一当成 5m/5p/5s 来算牌型
    if tile == "0m":
        return "5m"
    if tile == "0p":
        return "5p"
    if tile == "0s":
        return "5s"
    return tile


def _count_tiles(tiles):
    counts = {}
    for t in tiles:
        nt = _norm(t)
        counts[nt] = counts.get(nt, 0) + 1
    return counts


def _can_form_mentsu(counts, need):
    if need == 0:
        return True

    # 找第一张还有剩余的牌，按顺序试刻子和顺子
    first = None
    for t in ALL_TILES:
        if counts.get(t, 0) > 0:
            first = t
            break

    if first is None:
        return False

    # 1. 试刻子（三张一样的）
    if counts[first] >= 3:
        counts[first] -= 3
        if _can_form_mentsu(counts, need - 1):
            counts[first] += 3
            return True
        counts[first] += 3

    # 2. 试顺子（数牌且数字 <= 7）
    num = int(first[0])
    suit = first[1]
    if suit != "z" and num <= 7:
        t2 = f"{num + 1}{suit}"
        t3 = f"{num + 2}{suit}"
        if counts.get(t2, 0) >= 1 and counts.get(t3, 0) >= 1:
            counts[first] -= 1
            counts[t2] -= 1
            counts[t3] -= 1
            if _can_form_mentsu(counts, need - 1):
                counts[first] += 1
                counts[t2] += 1
                counts[t3] += 1
                return True
            counts[first] += 1
            counts[t2] += 1
            counts[t3] += 1

    return False


def _is_chiitoitsu(counts):
    # 七对子：7 种不同的对子（4张一样的不能算两对）
    if len(counts) != 7:
        return False
    for c in counts.values():
        if c != 2:
            return False
    return True


def _is_kokushi(counts):
    # 国士无双（十三幺）：13种幺九牌都有，其中一种有2张
    if len(counts) != 13:
        return False
    has_pair = False
    for t in YAOCHU:
        c = counts.get(t, 0)
        if c == 0:
            return False
        if c == 2:
            has_pair = True
    return has_pair


def can_hu(hand, melds=None):
    """能不能和（14 张，含副露折算）"""
    if melds is None:
        melds = []

    # 暗杠也是4张放进 melds 里，但每组副露在算牌型时按3张算
    if len(hand) + 3 * len(melds) != 14:
        return False

    counts = _count_tiles(hand)

    # 自己手里+副露里同一种牌不可能超过4张（防止听牌枚举时算出第5张）
    total_counts = dict(counts)
    for m in melds:
        for t in m:
            nt = _norm(t)
            total_counts[nt] = total_counts.get(nt, 0) + 1
    for c in total_counts.values():
        if c > 4:
            return False

    # 没有副露时才判断七对子和国士无双
    if len(melds) == 0:
        if _is_chiitoitsu(counts) or _is_kokushi(counts):
            return True

    # 一般牌型：枚举雀头（对子），剩下的凑 4 - len(melds) 组面子
    need_mentsu = 4 - len(melds)
    for t in ALL_TILES:
        if counts.get(t, 0) >= 2:
            counts[t] -= 2
            if _can_form_mentsu(counts, need_mentsu):
                counts[t] += 2
                return True
            counts[t] += 2

    return False


def get_waits(hand, melds=None, visible=None):
    """13 张时听哪些牌，还剩几张。visible 是场上能看到的牌
    返回 dict，例如 {'1m': 3, '4m': 2}
    """
    if melds is None:
        melds = []
    if visible is None:
        visible = []

    if len(hand) + 3 * len(melds) != 13:
        return {}

    # 老师说 剩几张 = 4 - 自己手里的 - 牌河里的，这里把 hand、melds 和 visible 里的都扣掉
    used = _count_tiles(hand)
    for m in melds:
        for t in m:
            nt = _norm(t)
            used[nt] = used.get(nt, 0) + 1
    for t in visible:
        nt = _norm(t)
        used[nt] = used.get(nt, 0) + 1

    waits = {}
    for t in ALL_TILES:
        if can_hu(hand + [t], melds):
            left = 4 - used.get(t, 0)
            if left < 0:
                left = 0
            waits[t] = left

    return waits


def discard_hints(hand, melds=None, visible=None):
    """14 张时打哪张能听牌
    返回 dict：{要打的牌: {听的牌: 剩几张}}
    """
    if melds is None:
        melds = []
    if visible is None:
        visible = []

    if len(hand) + 3 * len(melds) != 14:
        return {}

    hints = {}
    seen = set()
    for i, tile in enumerate(hand):
        if tile in seen:
            continue
        seen.add(tile)
        rest = hand[:i] + hand[i + 1:]
        # 模拟打出后，这张牌会进入牌河；若被鸣走也会进入他家副露，可见牌中要计一次。
        waits = get_waits(rest, melds, list(visible) + [tile])
        if waits:
            hints[tile] = waits

    return hints


if __name__ == "__main__":
    # 简单自测几组牌
    h1 = ["1m", "2m", "3m", "4p", "0p", "6p", "7s", "8s", "9s", "1z", "1z", "1z", "2z", "2z"]
    print("一般和牌:", can_hu(h1, []))

    h2 = ["1m", "1m", "2m", "2m", "3p", "3p", "4p", "4p", "5s", "5s", "6s", "6s", "7z", "7z"]
    print("七对子:", can_hu(h2, []))

    h3 = ["1m", "9m", "1p", "9p", "1s", "9s", "1z", "2z", "3z", "4z", "5z", "6z", "7z", "1m"]
    print("国士无双:", can_hu(h3, []))

    h_wait = ["1m", "2m", "3m", "4m", "5m", "6m", "7p", "8p", "9p", "2s", "3s", "5z", "5z"]
    print("13张听牌:", get_waits(h_wait, [], ["1s", "4s"]))

    h_discard = ["1m", "2m", "3m", "4m", "5m", "6m", "7p", "8p", "9p", "2s", "3s", "5z", "5z", "9z" if False else "7z"]
    print("14张打牌提示:", discard_hints(h_discard, [], ["1s"]))
