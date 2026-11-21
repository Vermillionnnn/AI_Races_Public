#!/usr/bin/env python3
"""乌龟：纯 Python 数织求解程序（单文件、单线程、只用标准库）。

算法：位并行单行推理 + 工作队列传播 + 两色试填到不动点 + 按试填收益选格的深度优先搜索。
协议见 player-kit/格式.md：从标准输入一道接一道读题，读完一道就解，解完立即输出并 flush。

    python3 solver.py [--time-limit 秒] [--stats] < 题目.txt
"""
import sys
import time


class Contradiction(Exception):
    pass


class Timeout(Exception):
    pass


# ---------------------------------------------------------------- 单行推理
#
# 一条线有 n 格，位 i 表示第 i 格。末尾第 n 位补一个虚拟白格，第 n+1 位是“终点”。
# 光标 p 表示“前面的格子都已安排好，下一块最早从 p 开始”。
#   F[j]  前向：放完前 j 块后光标可能停的位置
#   Bk[j] 后向：从这个光标出发能放下第 j..k-1 块
# 光标越过一个非黑格前进一步；块 j 放在起点 p 后光标跳到 p+L+1（块后一格必须白）。

def fill_steps(not_black, n):
    """Kogge-Stone 倍增用的掩码：P_s 第 p 位为 1 表示 p..p+s-1 都不是黑格。"""
    steps = []
    s, P = 1, not_black
    while s <= n + 1:
        steps.append((s, P))
        P &= P >> s
        s <<= 1
    return steps


def fill_fwd(X, steps, full):
    for s, P in steps:
        X |= (X & P) << s
    return X & full


def fill_bwd(X, steps):
    for s, P in steps:
        X |= (X >> s) & P
    return X


def runs(X, L):
    """X 中从 p 开始连续 L 个位都为 1 的起点 p 的集合。"""
    s = 1
    while s < L:
        t = s if s <= L - s else L - s
        X &= X >> t
        s += t
    return X


def expand(V, L):
    """把每个起点 p 展开成 p..p+L-1。"""
    s = 1
    while s < L:
        t = s if s <= L - s else L - s
        V |= V << t
        s += t
    return V


def solve_line(clue, n, B, W):
    """已知黑 B、已知白 W，返回推理后的 (B, W)；无解返回 None。"""
    cells = (1 << n) - 1
    full = (1 << (n + 2)) - 1
    not_black = full & ~B
    not_white = cells & ~W
    steps = fill_steps(not_black, n)
    k = len(clue)

    # 每种块长的可放起点：L 格都不是白、块后一格不是黑（第 n 格是虚拟白格）
    starts = {}
    for L in clue:
        if L not in starts:
            starts[L] = runs(not_white, L) & ~(B >> L)
    S = [starts[L] for L in clue]

    F = [0] * (k + 1)
    X = fill_fwd(1, steps, full)
    F[0] = X
    for j in range(k):
        X = fill_fwd((X & S[j]) << (clue[j] + 1), steps, full)
        F[j + 1] = X
    if not (X >> (n + 1)) & 1:
        return None

    Bk = fill_bwd(1 << (n + 1), steps)
    can_black = 0
    can_white = F[k] & (Bk >> 1)
    for j in range(k - 1, -1, -1):
        L = clue[j]
        E = S[j] & (Bk >> (L + 1))      # 后面能接上的起点
        V = F[j] & E                    # 前后都能接上的起点
        can_black |= expand(V, L)
        can_white |= V << L             # 块后的分隔白格
        Bk = fill_bwd(E, steps)
        can_white |= F[j] & (Bk >> 1)   # 光标停在某格上、越过它（留白）还能放下其余块
    can_white &= cells & ~B
    return can_black & ~can_white, can_white & ~can_black


# ---------------------------------------------------------------- 整盘
#
# 盘面状态是四个列表：rb/rw 是每行的已知黑/已知白（位 c 表示第 c 列），
# cb/cw 是每列的已知黑/已知白（位 r 表示第 r 行）。行和列两份同步维护。

class Puzzle:
    def __init__(self, h, w, rows, cols, time_limit):
        self.h, self.w = h, w
        self.rows, self.cols = rows, cols
        self.row_full = (1 << w) - 1
        self.col_full = (1 << h) - 1
        self.row_cache = [dict() for _ in range(h)]
        self.col_cache = [dict() for _ in range(w)]
        self.probe_cache = {}
        self.deadline = time.monotonic() + time_limit
        self.lines = self.probes = self.guesses = self.backtracks = 0

    # -------- 传播
    def line(self, cache, clue, n, B, W):
        key = (B, W)
        res = cache.get(key)
        if res is None:
            self.lines += 1
            res = solve_line(clue, n, B, W)
            if res is None:
                res = False
            cache[key] = res
        if res is False:
            raise Contradiction
        return res

    def propagate(self, st, dirty_rows, dirty_cols, touched=None):
        """就地传播到不动点，返回新推出的格数；矛盾时抛 Contradiction。touched 收集读过的行列。"""
        rb, rw, cb, cw = st
        gained = 0
        rows, cols = self.rows, self.cols
        h, w = self.h, self.w
        row_cache, col_cache = self.row_cache, self.col_cache
        while dirty_rows or dirty_cols:
            if dirty_rows:
                todo, dirty_rows = dirty_rows, set()
                if touched is not None:
                    touched[0].update(todo)
                for r in todo:
                    B, W = rb[r], rw[r]
                    nB, nW = self.line(row_cache[r], rows[r], w, B, W)
                    dB, dW = nB & ~B, nW & ~W
                    if dB or dW:
                        gained += (dB | dW).bit_count()
                        rb[r], rw[r] = nB, nW
                        bit = 1 << r
                        while dB:
                            low = dB & -dB
                            c = low.bit_length() - 1
                            cb[c] |= bit
                            dirty_cols.add(c)
                            dB ^= low
                        while dW:
                            low = dW & -dW
                            c = low.bit_length() - 1
                            cw[c] |= bit
                            dirty_cols.add(c)
                            dW ^= low
            if dirty_cols:
                todo, dirty_cols = dirty_cols, set()
                if touched is not None:
                    touched[1].update(todo)
                for c in todo:
                    B, W = cb[c], cw[c]
                    nB, nW = self.line(col_cache[c], cols[c], h, B, W)
                    dB, dW = nB & ~B, nW & ~W
                    if dB or dW:
                        gained += (dB | dW).bit_count()
                        cb[c], cw[c] = nB, nW
                        bit = 1 << c
                        while dB:
                            low = dB & -dB
                            r = low.bit_length() - 1
                            rb[r] |= bit
                            dirty_rows.add(r)
                            dB ^= low
                        while dW:
                            low = dW & -dW
                            r = low.bit_length() - 1
                            rw[r] |= bit
                            dirty_rows.add(r)
                            dW ^= low
        return gained

    def solved(self, st):
        full = self.row_full
        return all((b | x) == full for b, x in zip(st[0], st[1]))

    def assign(self, st, r, c, black, touched=None):
        """复制盘面，把 (r,c) 定为黑/白并传播。返回 (新盘面, 推出格数)；矛盾时新盘面为 None。"""
        rb, rw, cb, cw = st
        new = [rb[:], rw[:], cb[:], cw[:]]
        if black:
            new[0][r] |= 1 << c
            new[2][c] |= 1 << r
        else:
            new[1][r] |= 1 << c
            new[3][c] |= 1 << r
        try:
            return new, 1 + self.propagate(new, {r}, {c}, touched)
        except Contradiction:
            return None, 0

    # -------- 试填
    def probe_cell(self, st, r, c):
        """两色试填 (r,c)。返回 (黑的结果, 白的结果, 收益, 读过的行列)。
        收益是 (较弱一边推出的格数, 较强一边推出的格数)。"""
        self.probes += 1
        touched = (set(), set())
        sb, gb = self.assign(st, r, c, True, touched)
        sw, gw = self.assign(st, r, c, False, touched)
        return sb, sw, (min(gb, gw), max(gb, gw)), touched

    def cached_useless(self, st, r, c):
        """上次试填 (r,c) 没推出东西，且它读过的行列都没变，就不用再试。"""
        entry = self.probe_cache.get((r, c))
        if entry is None:
            return None
        trows, tcols, score = entry
        rb, rw, cb, cw = st
        for i, b, x in trows:
            if rb[i] != b or rw[i] != x:
                return None
        for i, b, x in tcols:
            if cb[i] != b or cw[i] != x:
                return None
        return score

    def probe_fixpoint(self, st):
        """反复试填到不动点。返回 (盘面, 分支格)；已解完时分支格为 None；矛盾抛 Contradiction。"""
        while True:
            if time.monotonic() > self.deadline:
                raise Timeout
            progress = False
            best, best_score = None, (-1, -1)
            for r in self.probe_order(st):
                unknown = self.row_full & ~(st[0][r] | st[1][r])
                while unknown:
                    low = unknown & -unknown
                    c = low.bit_length() - 1
                    unknown ^= low
                    if (st[0][r] | st[1][r]) & low:
                        continue                  # 这一轮里已经被推出来了
                    score = self.cached_useless(st, r, c)
                    if score is None:
                        sb, sw, score, touched = self.probe_cell(st, r, c)
                        if sb is None and sw is None:
                            raise Contradiction
                        if sb is None or sw is None:
                            st = sw if sb is None else sb
                            progress = True
                            if self.solved(st):
                                return st, None
                            continue
                        if self.solved(sb):
                            return sb, None
                        if self.solved(sw):
                            return sw, None
                        if self.merge_common(st, sb, sw):
                            progress = True
                            if self.solved(st):
                                return st, None
                            continue
                        rb, rw, cb, cw = st
                        self.probe_cache[(r, c)] = (
                            [(i, rb[i], rw[i]) for i in touched[0]],
                            [(i, cb[i], cw[i]) for i in touched[1]],
                            score)
                    if score > best_score:
                        best, best_score = (r, c), score
            if not progress:
                return st, best

    def probe_order(self, st):
        """未知格少的行先试：这些行更容易被逼出矛盾。"""
        full = self.row_full
        order = [(((st[0][r] | st[1][r]) ^ full).bit_count(), r) for r in range(self.h)]
        order.sort()
        return [r for n, r in order if n]

    def merge_common(self, st, sb, sw):
        """两色都可行时，把两边共同推出的格并进 st 并传播。有新格返回 True。"""
        rb, rw, cb, cw = st
        dirty_rows, dirty_cols = set(), set()
        for r in range(self.h):
            nB = sb[0][r] & sw[0][r] & ~rb[r]
            nW = sb[1][r] & sw[1][r] & ~rw[r]
            if nB or nW:
                rb[r] |= nB
                rw[r] |= nW
                dirty_rows.add(r)
                bit = 1 << r
                for d, side in ((nB, cb), (nW, cw)):
                    while d:
                        low = d & -d
                        c = low.bit_length() - 1
                        side[c] |= bit
                        dirty_cols.add(c)
                        d ^= low
        if not dirty_rows:
            return False
        self.propagate(st, dirty_rows, dirty_cols)
        return True

    # -------- 搜索
    def search(self, st):
        """深度优先：传播 + 试填，还解不完就按试填收益选格分支。"""
        st, cell = self.probe_fixpoint(st)
        if cell is None:
            return st
        r, c = cell
        self.probes += 1
        sb, gb = self.assign(st, r, c, True)
        sw, gw = self.assign(st, r, c, False)
        branches = [sb, sw] if gb >= gw else [sw, sb]   # 推出格多的一边先试
        for child in branches:
            if child is None:
                continue
            self.guesses += 1
            try:
                return self.search(child)
            except Contradiction:
                self.backtracks += 1
        raise Contradiction

    def solve(self):
        h, w = self.h, self.w
        st = [[0] * h, [0] * h, [0] * w, [0] * w]
        self.propagate(st, set(range(h)), set(range(w)))
        if self.solved(st):
            return st
        return self.search(st)

    def check(self, st):
        """输出前核对全部线索。"""
        def blocks(bits, n):
            out, run = [], 0
            for i in range(n):
                if (bits >> i) & 1:
                    run += 1
                elif run:
                    out.append(run)
                    run = 0
            if run:
                out.append(run)
            return tuple(out)
        rb = st[0]
        if any(blocks(rb[r], self.w) != self.rows[r] for r in range(self.h)):
            return False
        for c in range(self.w):
            col = 0
            for r in range(self.h):
                if (rb[r] >> c) & 1:
                    col |= 1 << r
            if blocks(col, self.h) != self.cols[c]:
                return False
        return True


# ---------------------------------------------------------------- 输入输出

def read_puzzles(stream):
    """逐道产出 (id, h, w, 行线索, 列线索)；读完一道就交出去，不等文件尾。"""
    while True:
        line = stream.readline()
        if not line:
            return
        parts = line.split()
        if not parts or parts[0] != "PUZZLE":
            continue
        pid, h, w = parts[1], int(parts[2]), int(parts[3])
        clues = []
        for _ in range(h + w):
            clues.append(tuple(int(x) for x in stream.readline().split() if int(x) > 0))
        yield pid, h, w, clues[:h], clues[h:]


def main():
    args = sys.argv[1:]
    time_limit = 120.0
    stats = "--stats" in args
    if "--time-limit" in args:
        time_limit = float(args[args.index("--time-limit") + 1])
    out = sys.stdout
    for pid, h, w, rows, cols in read_puzzles(sys.stdin):
        t0 = time.monotonic()
        p = Puzzle(h, w, rows, cols, time_limit)
        try:
            st = p.solve()
        except (Contradiction, Timeout):
            st = None
        ms = int((time.monotonic() - t0) * 1000)
        if stats:
            out.write("STATS lines=%d probes=%d guesses=%d backtracks=%d ms=%d\n"
                      % (p.lines, p.probes, p.guesses, p.backtracks, ms))
        if st is not None and p.check(st):
            grid = ["".join("#" if (st[0][r] >> c) & 1 else "." for c in range(w)) for r in range(h)]
            out.write("SOLUTION %s\n%s\n" % (pid, "\n".join(grid)))
        else:
            out.write("UNSOLVED %s\n" % pid)
        out.flush()


if __name__ == "__main__":
    main()
