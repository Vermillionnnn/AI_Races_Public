"""牌的写法和基本工具。

牌在接口里写成两个字符（见 接口说明.md“牌怎么写”）：'1m'..'9m'、'1p'..'9p'、'1s'..'9s'、
红五 '0m' '0p' '0s'、字牌 '1z'..'7z'（东南西北白发中）。
内部算牌型时用“牌种”编号 0..33：万 0-8、筒 9-17、索 18-26、字 27-33；红五和普通五同一种。
"""

import re

TILE_RE = re.compile(r'^([0-9][mps]|[1-7]z)$')
SUITS = 'mpsz'

EAST, SOUTH, WEST, NORTH = 27, 28, 29, 30
HAKU, HATSU, CHUN = 31, 32, 33
WINDS = (EAST, SOUTH, WEST, NORTH)
DRAGONS = (HAKU, HATSU, CHUN)
YAOCHU = tuple([0, 8, 9, 17, 18, 26] + list(range(27, 34)))
GREEN = (19, 20, 21, 23, 25, HATSU)  # 2 3 4 6 8 索、发


def valid(t):
    return isinstance(t, str) and bool(TILE_RE.match(t))


def kind(t):
    """'0m' -> 4（五万），'7z' -> 33。"""
    n = int(t[0]) or 5
    return SUITS.index(t[1]) * 9 + n - 1


def kind_str(k):
    """牌种的写法，五一律写普通的 '5m'。"""
    return '%d%s' % (k % 9 + 1, SUITS[k // 9])


def is_red(t):
    return t[0] == '0'


def is_honor(k):
    return k >= 27


def is_terminal(k):
    return k < 27 and k % 9 in (0, 8)


def is_yaochu(k):
    return k >= 27 or k % 9 in (0, 8)


def suit_of(k):
    return k // 9


def num_of(k):
    return k % 9 + 1


def sort_key(t):
    n = int(t[0])
    return (SUITS.index(t[1]), n or 5, 1 if n == 0 else 0)


def sort_tiles(tiles):
    return sorted(tiles, key=sort_key)


def counts(tiles):
    """牌（字符串）列表 -> 34 种的张数。"""
    c = [0] * 34
    for t in tiles:
        c[kind(t)] += 1
    return c


def dora_from_indicator(k):
    """宝牌指示牌的下一张：9 的下一张是 1，东南西北循环，白发中循环。"""
    if k < 27:
        return k - 8 if k % 9 == 8 else k + 1
    if k <= NORTH:
        return EAST if k == NORTH else k + 1
    return HAKU if k == CHUN else k + 1


def full_set(aka=True):
    """136 张。aka=True 时每种花色的四张五里有一张红五。"""
    tiles = []
    for s in 'mps':
        for n in range(1, 10):
            for i in range(4):
                tiles.append('0' + s if (aka and n == 5 and i == 0) else '%d%s' % (n, s))
    for n in range(1, 8):
        tiles += ['%dz' % n] * 4
    return tiles


def wind_tile(w):
    """风的牌种编号 -> 写法：27 -> '1z'。"""
    return kind_str(w)


WIND_NAMES = {EAST: '东', SOUTH: '南', WEST: '西', NORTH: '北'}
DRAGON_NAMES = {HAKU: '白', HATSU: '发', CHUN: '中'}
