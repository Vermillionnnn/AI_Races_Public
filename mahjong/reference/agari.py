"""牌型：和了判定、拆牌枚举、听牌、向听数。

这里只看牌种张数（34 格的列表），不管红五、役和点数。
c 是手里（不含副露）的张数；n_melds 是副露组数（暗杠也算一组）。
"""

from functools import lru_cache

from tiles import YAOCHU


# ---------------------------------------------------------------- 和了判定

def _all_sets(c):
    """c 能不能全部拆成面子（不要雀头）。按花色从小到大：最小的牌 r = 张数 % 3 张只能做顺子的头。"""
    c = list(c)
    for s in range(3):
        b = s * 9
        for i in range(9):
            n = c[b + i]
            if n < 0:
                return False
            r = n % 3
            if r:
                if i > 6:
                    return False
                c[b + i + 1] -= r
                c[b + i + 2] -= r
                if c[b + i + 1] < 0 or c[b + i + 2] < 0:
                    return False
    for k in range(27, 34):
        if c[k] % 3:
            return False
    return True


def is_standard(c):
    """四面子一雀头型（面子数随副露减少）。"""
    if sum(c) % 3 != 2:
        return False
    for p in range(34):
        if c[p] >= 2:
            c2 = list(c)
            c2[p] -= 2
            if _all_sets(c2):
                return True
    return False


def is_chiitoi(c):
    """七对子：正好七种牌各两张（四张同种不算两对）。"""
    return sum(c) == 14 and sum(1 for x in c if x == 2) == 7


def is_kokushi(c):
    return sum(c) == 14 and all(c[k] >= 1 for k in YAOCHU) and sum(c[k] for k in YAOCHU) == 14


@lru_cache(maxsize=200000)
def _is_agari_t(ct, n_melds):
    c = list(ct)
    if is_standard(c):
        return True
    if n_melds == 0 and (is_chiitoi(c) or is_kokushi(c)):
        return True
    return False


def is_agari(c, n_melds):
    return _is_agari_t(tuple(c), n_melds)


def _candidates(c, n_melds):
    """可能成为和了牌的牌种：手里有的、同花色差 1-2 的；门清时再加上全部幺九（国士）。"""
    cand = set(YAOCHU) if n_melds == 0 else set()
    for k in range(34):
        if c[k]:
            cand.add(k)
            if k < 27:
                for d in (-2, -1, 1, 2):
                    j = k + d
                    if 0 <= j < 27 and j // 9 == k // 9:
                        cand.add(j)
    return sorted(cand)


@lru_cache(maxsize=100000)
def _waits_t(ct, n_melds):
    c = list(ct)
    res = []
    for k in _candidates(ct, n_melds):
        if c[k] >= 4:          # 第五张不存在：听的牌四张全在自己手里不算听
            continue
        c[k] += 1
        if _is_agari_t(tuple(c), n_melds):
            res.append(k)
        c[k] -= 1
    return tuple(res)


def waits(c, n_melds):
    """13 张形（3n+1）的手听哪些牌种。手里已经有 4 张的牌种不算。"""
    return _waits_t(tuple(c), n_melds)


# ---------------------------------------------------------------- 拆牌枚举（算点用）

def _sets_all(c, start):
    """把 c 拆成面子的全部方法；返回 [[('seq'|'trip', 牌种), ...], ...]。"""
    k = start
    while k < 34 and c[k] == 0:
        k += 1
    if k == 34:
        return [[]]
    res = []
    if c[k] >= 3:
        c[k] -= 3
        for rest in _sets_all(c, k):
            res.append([('trip', k)] + rest)
        c[k] += 3
    if k < 27 and k % 9 <= 6 and c[k + 1] and c[k + 2]:
        c[k] -= 1
        c[k + 1] -= 1
        c[k + 2] -= 1
        for rest in _sets_all(c, k):
            res.append([('seq', k)] + rest)
        c[k] += 1
        c[k + 1] += 1
        c[k + 2] += 1
    return res


def decompositions(c):
    """一雀头加若干面子的所有拆法：[(雀头牌种, [('seq'|'trip', 牌种), ...]), ...]，不含七对子、国士。"""
    out = []
    if sum(c) % 3 != 2:
        return out
    c = list(c)
    for p in range(34):
        if c[p] >= 2:
            c[p] -= 2
            for sets in _sets_all(c, 0):
                out.append((p, sets))
            c[p] += 2
    return out


# ---------------------------------------------------------------- 向听数（电脑玩家用）

def _prune(states):
    """去掉被别的状态全面压过的 (面子, 搭子, 雀头)。"""
    lst = sorted(states, reverse=True)
    keep = []
    for s in lst:
        if not any(o[0] >= s[0] and o[1] >= s[1] and o[2] >= s[2] for o in keep):
            keep.append(s)
    return frozenset(keep)


@lru_cache(maxsize=None)
def _suit_states(cnt):
    """一种花色（9 格）能凑出的 (面子数, 搭子数, 有没有雀头)。"""
    i = 0
    while i < 9 and cnt[i] == 0:
        i += 1
    if i == 9:
        return frozenset([(0, 0, 0)])
    c = list(cnt)
    res = set()

    def sub(changes, dm, dt, dp):
        for j, d in changes:
            c[j] -= d
        for m, t, p in _suit_states(tuple(c)):
            if p + dp <= 1:
                res.add((m + dm, t + dt, p + dp))
        for j, d in changes:
            c[j] += d

    sub([(i, 1)], 0, 0, 0)                      # 当孤张
    if c[i] >= 2:
        sub([(i, 2)], 0, 1, 0)                  # 对子当搭子
        sub([(i, 2)], 0, 0, 1)                  # 对子当雀头
    if c[i] >= 3:
        sub([(i, 3)], 1, 0, 0)
    if i <= 6 and c[i + 1] and c[i + 2]:
        sub([(i, 1), (i + 1, 1), (i + 2, 1)], 1, 0, 0)
    if i <= 7 and c[i + 1]:
        sub([(i, 1), (i + 1, 1)], 0, 1, 0)
    if i <= 6 and c[i + 2]:
        sub([(i, 1), (i + 2, 1)], 0, 1, 0)
    return _prune(res)


@lru_cache(maxsize=None)
def _combine(a, b):
    res = set()
    for m1, t1, p1 in a:
        for m2, t2, p2 in b:
            if p1 + p2 <= 1:
                res.add((m1 + m2, t1 + t2, p1 + p2))
    return _prune(res)


@lru_cache(maxsize=200000)
def _shanten_t(ct, n_melds):
    states = _combine(_combine(_suit_states(ct[0:9]), _suit_states(ct[9:18])), _suit_states(ct[18:27]))
    h3 = sum(1 for k in range(27, 34) if ct[k] >= 3)
    h2 = sum(1 for k in range(27, 34) if ct[k] == 2)
    best = 8
    for m, t, p in states:
        opts = [(m + h3, t + h2, p)]
        if h2 and not p:
            opts.append((m + h3, t + h2 - 1, 1))
        for m2, t2, p2 in opts:
            m2 += n_melds
            t2 = min(t2, 4 - m2) if m2 <= 4 else 0
            best = min(best, 8 - 2 * m2 - t2 - p2)
    if n_melds == 0:
        pairs = sum(1 for x in ct if x >= 2)
        kinds = sum(1 for x in ct if x >= 1)
        best = min(best, 6 - pairs + max(0, 7 - kinds))
        y = sum(1 for k in YAOCHU if ct[k])
        yp = any(ct[k] >= 2 for k in YAOCHU)
        best = min(best, 13 - y - (1 if yp else 0))
    return best


def shanten(c, n_melds):
    """向听数：-1 和了，0 听牌。"""
    return _shanten_t(tuple(c), n_melds)
