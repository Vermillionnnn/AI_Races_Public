// Nonogram puzzle generator (round 2): random grid -> repair to a unique solution -> hill-climb on search cost.
// The solver core (bit-parallel line solver, propagation, probe screening) is my own round-1 code.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <bit>
#include <string>
#include <vector>
#include <deque>
#include <thread>
#include <mutex>
#include <condition_variable>

typedef uint64_t u64;
static const int MAXN = 64;
static const int MAXK = 34;

struct Line {
    int n, k;
    u64 full;
    int len[MAXK];
    int rlen[MAXK];
    int maxL;
};

#if defined(_MSC_VER) && !defined(__clang__)
static inline u64 bswap64(u64 x) { return _byteswap_uint64(x); }
#else
static inline u64 bswap64(u64 x) { return __builtin_bswap64(x); }
#endif

static inline u64 rev64(u64 x) {
    x = bswap64(x);
    x = ((x >> 4) & 0x0F0F0F0F0F0F0F0FULL) | ((x & 0x0F0F0F0F0F0F0F0FULL) << 4);
    x = ((x >> 2) & 0x3333333333333333ULL) | ((x & 0x3333333333333333ULL) << 2);
    x = ((x >> 1) & 0x5555555555555555ULL) | ((x & 0x5555555555555555ULL) << 1);
    return x;
}

// Returns false on contradiction. nB/nW: cells forced black/white (supersets of B/W).
static inline bool solveLine(const Line& ln, u64 B, u64 W, u64& nB, u64& nW) {
    const int n = ln.n, k = ln.k;
    const u64 full = ln.full;
    if (k == 0) {
        if (B) return false;
        nB = 0; nW = full; return true;
    }
    const u64 M = ~W & full;   // may be black
    const u64 NB = ~B & full;  // may be white
    const int maxL = ln.maxL;
    u64 F[MAXK], ST[MAXK], G[MAXK];
    u64 cs1[MAXN + 1];  // cs1[L]: starts s with cells s..s+L-1 all possibly black
    cs1[1] = M;
    for (int L = 2; L <= maxL; L++) cs1[L] = cs1[L - 1] & (cs1[L - 1] >> 1);
    u64 f = B ? (((B & (0 - B)) << 1) - 1) : ((full << 1) | 1);
    F[0] = f;
    {
        u64 pre = f;
        for (int j = 1; j <= k; j++) {
            const int L = ln.len[j - 1];
            u64 st = cs1[L] & pre;
            if (!st) return false;
            ST[j] = st;
            u64 E = st << L;
            f = ((NB + (E & NB)) ^ NB) | E;
            F[j] = f;
            pre = (f & NB) << 1;
        }
    }
    if (!((f >> n) & 1)) return false;
    // backward pass on the reversed line
    {
        const int rsh = 64 - n;
        const u64 Br = rev64(B) >> rsh, Wr = rev64(W) >> rsh;
        const u64 Mr = ~Wr & full, NBr = ~Br & full;
        f = Br ? (((Br & (0 - Br)) << 1) - 1) : ((full << 1) | 1);
        G[k] = rev64(f) >> (rsh - 1);
        u64 pre = f;
        cs1[1] = Mr;
        for (int L = 2; L <= maxL; L++) cs1[L] = cs1[L - 1] & (cs1[L - 1] >> 1);
        for (int j = 1; j <= k; j++) {
            const int L = ln.rlen[j - 1];
            u64 st = cs1[L] & pre;
            if (!st) return false;
            u64 E = st << L;
            f = ((NBr + (E & NBr)) ^ NBr) | E;
            G[k - j] = rev64(f) >> (rsh - 1);
            pre = (f & NBr) << 1;
        }
    }
    u64 canW = F[0] & (G[0] >> 1);
    // cs1 reused: cs1[L] = union of feasible starts of blocks with length L
    for (int L = 1; L <= maxL; L++) cs1[L] = 0;
    for (int j = 1; j < k; j++) {
        const int L = ln.len[j - 1];
        const u64 g1 = G[j] >> 1;
        canW |= F[j] & g1;
        cs1[L] |= ST[j] & ((g1 & NB) >> L);
    }
    {
        const int L = ln.len[k - 1];
        canW |= F[k] & (G[k] >> 1);
        cs1[L] |= ST[k] & (G[k] >> L);
    }
    u64 canB = 0, U = 0;
    for (int L = maxL; L >= 1; L--) { U |= cs1[L]; canB |= U << (L - 1); }
    canW &= NB;
    if ((canW | canB) != full) return false;
    nB = full & ~canW;
    nW = full & ~canB;
    return true;
}

struct CEnt { u64 B, W, nB, nW; u64 key; };

struct Puzzle {
    std::string id;
    int h, w;
    CEnt* cache;   // per-worker line-solve cache
    u64 kbase;     // per-puzzle key prefix
    Line rows[MAXN], cols[MAXN];
};

struct State {
    u64 rB[MAXN], rW[MAXN], cB[MAXN], cW[MAXN];
    u64 dr, dc;
    u64 tr, tc;   // lines read (solved) since reset
    u64 xr, xc;   // lines changed since reset
    int unknown;
};

static inline void copyState(const Puzzle& p, State& d, const State& s) {
    memcpy(d.rB, s.rB, sizeof(u64) * p.h);
    memcpy(d.rW, s.rW, sizeof(u64) * p.h);
    memcpy(d.cB, s.cB, sizeof(u64) * p.w);
    memcpy(d.cW, s.cW, sizeof(u64) * p.w);
    d.dr = s.dr; d.dc = s.dc; d.unknown = s.unknown;
    d.tr = d.tc = d.xr = d.xc = 0;
}

static const int CBITS = 15;

static inline bool solveCached(CEnt* cache, u64 key, const Line& ln, u64 B, u64 W, u64& nB, u64& nW) {
    u64 h = (B * 0x9E3779B97F4A7C15ULL) ^ (W * 0xC2B2AE3D27D4EB4FULL) ^ (key * 0x165667B19E3779F9ULL);
    h ^= h >> 29;
    h *= 0xBF58476D1CE4E5B9ULL;
    CEnt& e = cache[h >> (64 - CBITS)];
    if (e.B == B && e.W == W && e.key == key) {
        nB = e.nB; nW = e.nW;
        return nB != ~0ULL;
    }
    bool ok = solveLine(ln, B, W, nB, nW);
    e.B = B; e.W = W; e.key = key;
    if (ok) { e.nB = nB; e.nW = nW; } else { e.nB = ~0ULL; e.nW = 0; }
    return ok;
}

static bool propagate(const Puzzle& p, State& s) {
    CEnt* const cache = p.cache;
    const u64 kbase = p.kbase;
    while (s.dr | s.dc) {
        while (s.dr) {
            int r = std::countr_zero(s.dr);
            s.dr &= s.dr - 1;
            s.tr |= 1ULL << r;
            u64 nB, nW;
            if (!solveCached(cache, kbase | (u64)r, p.rows[r], s.rB[r], s.rW[r], nB, nW)) return false;
            u64 dB = nB & ~s.rB[r], dW = nW & ~s.rW[r];
            if (dB | dW) {
                s.rB[r] = nB; s.rW[r] = nW;
                s.unknown -= std::popcount(dB | dW);
                s.dc |= dB | dW;
                s.xc |= dB | dW;
                const u64 bit = 1ULL << r;
                s.xr |= bit;
                while (dB) { int c = std::countr_zero(dB); dB &= dB - 1; s.cB[c] |= bit; }
                while (dW) { int c = std::countr_zero(dW); dW &= dW - 1; s.cW[c] |= bit; }
            }
        }
        while (s.dc) {
            int c = std::countr_zero(s.dc);
            s.dc &= s.dc - 1;
            s.tc |= 1ULL << c;
            u64 nB, nW;
            if (!solveCached(cache, kbase | (u64)(128 + c), p.cols[c], s.cB[c], s.cW[c], nB, nW)) return false;
            u64 dB = nB & ~s.cB[c], dW = nW & ~s.cW[c];
            if (dB | dW) {
                s.cB[c] = nB; s.cW[c] = nW;
                s.unknown -= std::popcount(dB | dW);
                s.dr |= dB | dW;
                s.xr |= dB | dW;
                const u64 bit = 1ULL << c;
                s.xc |= bit;
                while (dB) { int r = std::countr_zero(dB); dB &= dB - 1; s.rB[r] |= bit; }
                while (dW) { int r = std::countr_zero(dW); dW &= dW - 1; s.rW[r] |= bit; }
            }
        }
    }
    return true;
}

static inline void setCell(State& s, int r, int c, int black) {
    if (black) { s.rB[r] |= 1ULL << c; s.cB[c] |= 1ULL << r; }
    else { s.rW[r] |= 1ULL << c; s.cW[c] |= 1ULL << r; }
    s.dr |= 1ULL << r; s.dc |= 1ULL << c;
    s.xr |= 1ULL << r; s.xc |= 1ULL << c;
    s.unknown--;
}

// Cached probe result for one cell: valid while none of the lines it read has changed.
struct Rec { u64 tr, tc; int score; int valid; };

static inline void invalidate(std::vector<Rec>& rec, u64 xr, u64 xc) {
    Rec* q = rec.data();
    const size_t n = rec.size();
    for (size_t i = 0; i < n; i++)
        if ((q[i].tr & xr) | (q[i].tc & xc)) q[i].valid = 0;
}

// Probe screening without copying the state: 0 = contradiction, 1 = no deduction beyond the cell, 2 = needs full propagation
static inline int quickProbe(const Puzzle& p, const State& s, int r, int c, int black) {
    if (s.unknown <= 1) return 2;
    CEnt* const cache = p.cache;
    const u64 kbase = p.kbase;
    u64 rb = s.rB[r], rw = s.rW[r], cb = s.cB[c], cw = s.cW[c];
    if (black) { rb |= 1ULL << c; cb |= 1ULL << r; }
    else { rw |= 1ULL << c; cw |= 1ULL << r; }
    u64 nB, nW;
    if (!solveCached(cache, kbase | (u64)r, p.rows[r], rb, rw, nB, nW)) return 0;
    if (nB != rb || nW != rw) return 2;
    if (!solveCached(cache, kbase | (u64)(128 + c), p.cols[c], cb, cw, nB, nW)) return 0;
    if (nB != cb || nW != cw) return 2;
    return 1;
}

// ---------------------------------------------------------------- solution counting search
#include <algorithm>
#include <random>

struct Ctx {
    const Puzzle* p;
    bool rev;            // mode 1 only: try the smaller-gain branch first (worst case over branch luck)
    int mode;            // 1 = same policy family as the scored solver (rows with fewest unknowns first,
                         //     lexicographic (min,max) gain, larger-gain branch first); 0 = row-major, product score, black first
    long probes, budget;
    long firstProbes;    // probes spent when the first solution was found
    long nodes, firstNodes;
    int nsol;            // number of solutions found (stops at 2)
    bool over;           // budget exceeded
    State sol[2];
};

static inline bool done(const Ctx& cx) { return cx.nsol >= 2 || cx.over; }

static void record(Ctx& cx, const State& s) {
    if (cx.nsol < 2) copyState(*cx.p, cx.sol[cx.nsol], s);
    if (cx.nsol == 0) { cx.firstProbes = cx.probes; cx.firstNodes = cx.nodes; }
    cx.nsol++;
}

// s must be propagated, consistent and unsolved. Enumerates all solutions below s (until 2 are known).
static void search(Ctx& cx, State& s, std::vector<Rec>& rec) {
    const Puzzle& p = *cx.p;
    cx.nodes++;
    State a, b;
    const int w = p.w, h = p.h;
    std::vector<int> ord;
    for (;;) {
        bool progress = false;
        ord.clear();
        if (cx.mode == 1) {
            std::vector<std::pair<int, int>> rr;
            for (int r = 0; r < h; r++) {
                int n = std::popcount(p.rows[r].full & ~(s.rB[r] | s.rW[r]));
                if (n) rr.push_back({n, r});
            }
            std::sort(rr.begin(), rr.end());
            for (auto& pr : rr) {
                int r = pr.second;
                u64 unk = p.rows[r].full & ~(s.rB[r] | s.rW[r]);
                while (unk) { int c = std::countr_zero(unk); unk &= unk - 1; ord.push_back(r * w + c); }
            }
        } else {
            for (int r = 0; r < h; r++) {
                u64 unk = p.rows[r].full & ~(s.rB[r] | s.rW[r]);
                while (unk) { int c = std::countr_zero(unk); unk &= unk - 1; ord.push_back(r * w + c); }
            }
        }
        for (size_t oi = 0; oi < ord.size(); oi++) {
            const int r = ord[oi] / w, c = ord[oi] % w;
            if (((s.rB[r] | s.rW[r]) >> c) & 1) continue;
            Rec& rc = rec[r * w + c];
            if (rc.valid) continue;
            if (++cx.probes > cx.budget) { cx.over = true; return; }
            const int qa = quickProbe(p, s, r, c, 1);
            bool oka = qa != 0;
            if (qa == 2) {
                copyState(p, a, s); setCell(a, r, c, 1);
                oka = propagate(p, a);
                if (oka && a.unknown == 0) { record(cx, a); if (done(cx)) return; oka = false; }
            }
            if (!oka) {
                s.xr = s.xc = 0;
                setCell(s, r, c, 0);
                if (!propagate(p, s)) return;
                if (s.unknown == 0) { record(cx, s); return; }
                invalidate(rec, s.xr, s.xc);
                progress = true; continue;
            }
            const int qb = quickProbe(p, s, r, c, 0);
            bool okb = qb != 0;
            if (qb == 2) {
                copyState(p, b, s); setCell(b, r, c, 0);
                okb = propagate(p, b);
                if (okb && b.unknown == 0) { record(cx, b); if (done(cx)) return; okb = false; }
            }
            if (!okb) {
                s.xr = s.xc = 0;
                setCell(s, r, c, 1);
                if (!propagate(p, s)) return;
                if (s.unknown == 0) { record(cx, s); return; }
                invalidate(rec, s.xr, s.xc);
                progress = true; continue;
            }
            bool any = false;
            u64 chg = (qa == 2 && qb == 2) ? (a.xr & b.xr) : 0;
            while (chg) {
                int i = std::countr_zero(chg); chg &= chg - 1;
                u64 nb = a.rB[i] & b.rB[i] & ~s.rB[i];
                u64 nw = a.rW[i] & b.rW[i] & ~s.rW[i];
                if (nb | nw) {
                    if (!any) { any = true; s.xr = s.xc = 0; }
                    s.rB[i] |= nb; s.rW[i] |= nw;
                    s.unknown -= std::popcount(nb | nw);
                    s.dr |= 1ULL << i; s.dc |= nb | nw;
                    s.xr |= 1ULL << i; s.xc |= nb | nw;
                    const u64 bit = 1ULL << i;
                    while (nb) { int cc = std::countr_zero(nb); nb &= nb - 1; s.cB[cc] |= bit; }
                    while (nw) { int cc = std::countr_zero(nw); nw &= nw - 1; s.cW[cc] |= bit; }
                }
            }
            if (any) {
                if (!propagate(p, s)) return;
                if (s.unknown == 0) { record(cx, s); return; }
                invalidate(rec, s.xr, s.xc);
                progress = true;
                continue;
            }
            int da = 1, db = 1;
            rc.tr = 1ULL << r; rc.tc = 1ULL << c;
            if (qa == 2) { da = s.unknown - a.unknown; rc.tr |= a.tr; rc.tc |= a.tc; }
            if (qb == 2) { db = s.unknown - b.unknown; rc.tr |= b.tr; rc.tc |= b.tc; }
            if (cx.mode == 1) rc.score = (da < db ? da : db) * 10000 + (da > db ? da : db);
            else rc.score = (da + 1) * (db + 1);
            rc.valid = 1;
        }
        if (!progress) break;
    }
    int best = -1, bestScore = -1;
    for (size_t oi = 0; oi < ord.size(); oi++) {
        const int r = ord[oi] / w, c = ord[oi] % w;
        if (((s.rB[r] | s.rW[r]) >> c) & 1) continue;
        if (rec[ord[oi]].score > bestScore) { bestScore = rec[ord[oi]].score; best = ord[oi]; }
    }
    if (best < 0) return;
    const int br = best / w, bc = best % w;
    cx.probes++;
    copyState(p, a, s); setCell(a, br, bc, 1);
    bool oka = propagate(p, a);
    copyState(p, b, s); setCell(b, br, bc, 0);
    bool okb = propagate(p, b);
    int ga = oka ? s.unknown - a.unknown : 0, gb = okb ? s.unknown - b.unknown : 0;
    bool blackFirst = cx.mode == 1 ? ((ga >= gb) != cx.rev) : true;
    for (int t = 0; t < 2; t++) {
        const bool useA = (t == 0) == blackFirst;
        State& ch = useA ? a : b;
        if (!(useA ? oka : okb)) continue;
        if (ch.unknown == 0) { record(cx, ch); if (done(cx)) return; continue; }
        std::vector<Rec> rec2(rec);
        invalidate(rec2, ch.xr, ch.xc);
        search(cx, ch, rec2);
        if (done(cx)) return;
    }
}

static thread_local Ctx* gcx = nullptr;
static CEnt* gcache = nullptr;
static u64 ggen = 0;

// Counts solutions of p (up to 2) within a probe budget. Result in *gcx.
static Ctx& countSolutions(Puzzle& p, int mode, long budget, bool rev = false) {
    if (!gcx) gcx = new Ctx();
    if (!gcache) gcache = (CEnt*)calloc((size_t)1 << CBITS, sizeof(CEnt));
    Ctx& cx = *gcx;
    p.cache = gcache; p.kbase = (++ggen) << 8;
    cx.p = &p; cx.mode = mode; cx.rev = rev; cx.probes = 0; cx.budget = budget; cx.firstProbes = 0;
    cx.nodes = 0; cx.firstNodes = 0; cx.nsol = 0; cx.over = false;
    static State s;
    memset(&s, 0, sizeof(s));
    s.dr = (1ULL << p.h) - 1; s.dc = (1ULL << p.w) - 1;
    s.unknown = p.h * p.w;
    if (!propagate(p, s)) return cx;
    if (s.unknown == 0) { record(cx, s); return cx; }
    std::vector<Rec> rec((size_t)p.h * p.w, Rec{0, 0, 0, 0});
    search(cx, s, rec);
    return cx;
}

// ---------------------------------------------------------------- puzzles from grids
typedef std::vector<u64> Grid;   // one bitmask per row

static void setLine(Line& ln, int n, u64 bits) {
    ln.n = n; ln.k = 0; ln.full = (1ULL << n) - 1; ln.maxL = 0;
    int run = 0;
    for (int i = 0; i <= n; i++) {
        if (i < n && ((bits >> i) & 1)) run++;
        else if (run) { ln.len[ln.k++] = run; if (run > ln.maxL) ln.maxL = run; run = 0; }
    }
    for (int i = 0; i < ln.k; i++) ln.rlen[i] = ln.len[ln.k - 1 - i];
}

static void buildPuzzle(Puzzle& p, int h, int w, const Grid& g) {
    p.h = h; p.w = w;
    for (int r = 0; r < h; r++) setLine(p.rows[r], w, g[r]);
    for (int c = 0; c < w; c++) {
        u64 x = 0;
        for (int r = 0; r < h; r++) x |= ((g[r] >> c) & 1) << r;
        setLine(p.cols[c], h, x);
    }
}

static std::mt19937_64 rng;
static Puzzle gp;

// Makes the grid's puzzle uniquely solvable by flipping cells where two solutions differ.
// Returns 1 on success (F/T filled), 0 if it did not converge, -1 if the budget was exceeded.
static int repair(int h, int w, Grid& g, int maxIter, long budget, long& F, long& T) {
    for (int it = 0; it < maxIter; it++) {
        buildPuzzle(gp, h, w, g);
        Ctx& cx = countSolutions(gp, 1, budget);
        if (cx.over) return -1;
        if (cx.nsol == 0) return 0;   // cannot happen: g itself is a solution
        if (cx.nsol == 1) { F = cx.firstProbes; T = cx.probes; return 1; }
        std::vector<int> diff;
        for (int r = 0; r < h; r++) {
            u64 d = cx.sol[0].rB[r] ^ cx.sol[1].rB[r];
            while (d) { int c = std::countr_zero(d); d &= d - 1; diff.push_back(r * w + c); }
        }
        const State& base = cx.sol[rng() & 1];
        for (int r = 0; r < h; r++) g[r] = base.rB[r];
        int cell = diff[rng() % diff.size()];
        g[cell / w] ^= 1ULL << (cell % w);
    }
    return 0;
}

// Objective = min(first-solution probes with normal branch order, with reversed branch order). -1 if not evaluable.
static long objective(int h, int w, Grid& g, int maxIter, long budget, long floorF, long& F, long& Frev, long& T) {
    int rc = repair(h, w, g, maxIter, budget, F, T);
    if (rc != 1) return -1;
    if (F < floorF) return F;            // early reject, skip the second evaluation
    buildPuzzle(gp, h, w, g);
    Ctx& cx = countSolutions(gp, 1, budget, true);
    if (cx.over || cx.nsol != 1) return -1;
    Frev = cx.firstProbes;
    return F < Frev ? F : Frev;
}

static void emit(const char* tag, long chain, int h, int w, const Grid& g, long F, long Frev, long T) {
    printf("%s %ld %d %d %ld %ld %ld\n", tag, chain, h, w, F, Frev, T);
    for (int r = 0; r < h; r++) {
        for (int c = 0; c < w; c++) putchar(((g[r] >> c) & 1) ? '#' : '.');
        putchar('\n');
    }
    fflush(stdout);
}

// brute-force cross-check of the counting search on tiny puzzles
static int selfTest(int rounds) {
    int bad = 0;
    for (int t = 0; t < rounds; t++) {
        int h = 2 + rng() % 4, w = 2 + rng() % 4;
        if (h * w > 20) w = 4;
        Grid g(h);
        for (int r = 0; r < h; r++) g[r] = rng() & ((1ULL << w) - 1);
        buildPuzzle(gp, h, w, g);
        // brute force
        int cnt = 0;
        Puzzle* q = new Puzzle();
        for (u64 m = 0; m < (1ULL << (h * w)) && cnt < 2; m++) {
            Grid x(h);
            for (int r = 0; r < h; r++) x[r] = (m >> (r * w)) & ((1ULL << w) - 1);
            bool ok = true;
            for (int r = 0; r < h && ok; r++) {
                Line ln; setLine(ln, w, x[r]);
                ok = ln.k == gp.rows[r].k && !memcmp(ln.len, gp.rows[r].len, sizeof(int) * ln.k);
            }
            for (int c = 0; c < w && ok; c++) {
                u64 col = 0;
                for (int r = 0; r < h; r++) col |= ((x[r] >> c) & 1) << r;
                Line ln; setLine(ln, h, col);
                ok = ln.k == gp.cols[c].k && !memcmp(ln.len, gp.cols[c].len, sizeof(int) * ln.k);
            }
            if (ok) cnt++;
        }
        delete q;
        for (int mode = 0; mode < 2; mode++) {
            Ctx& cx = countSolutions(gp, mode, 1000000);
            int got = cx.nsol > 2 ? 2 : cx.nsol;
            if (got != cnt || cx.over) { bad++; fprintf(stderr, "MISMATCH h=%d w=%d mode=%d brute=%d got=%d\n", h, w, mode, cnt, got); }
        }
    }
    fprintf(stderr, "selftest rounds=%d mismatches=%d\n", rounds, bad);
    return bad;
}

// verify mode: read puzzles (text format) from stdin, count solutions with both policies
static bool readClue(FILE* f, Line& ln, int n) {
    static char buf[4096];
    if (!fgets(buf, sizeof(buf), f)) return false;
    ln.n = n; ln.k = 0; ln.full = (1ULL << n) - 1; ln.maxL = 0;
    const char* q = buf;
    for (;;) {
        while (*q == ' ' || *q == '\r' || *q == '\n') q++;
        if (!*q) break;
        int v = 0;
        while (*q >= '0' && *q <= '9') { v = v * 10 + (*q - '0'); q++; }
        if (v > 0) { ln.len[ln.k++] = v; if (v > ln.maxL) ln.maxL = v; }
    }
    for (int i = 0; i < ln.k; i++) ln.rlen[i] = ln.len[ln.k - 1 - i];
    return true;
}

static int verifyMode(long budget) {
    char id[256]; int h, w; int n = 0, uniq = 0;
    static char hdr[4096];
    while (fgets(hdr, sizeof(hdr), stdin)) {
        if (sscanf(hdr, "PUZZLE %200s %d %d", id, &h, &w) != 3) continue;
        gp.h = h; gp.w = w;
        for (int r = 0; r < h; r++) readClue(stdin, gp.rows[r], w);
        for (int c = 0; c < w; c++) readClue(stdin, gp.cols[c], h);
        n++;
        long F[2], T[2]; int ns[2]; bool ov[2];
        std::string solText;
        for (int mode = 1; mode >= 0; mode--) {
            Ctx& cx = countSolutions(gp, mode, budget);
            F[mode] = cx.firstProbes; T[mode] = cx.probes; ns[mode] = cx.nsol; ov[mode] = cx.over;
            if (mode == 1 && cx.nsol >= 1) {
                for (int r = 0; r < h; r++) {
                    for (int c = 0; c < w; c++) solText += ((cx.sol[0].rB[r] >> c) & 1) ? '#' : '.';
                    solText += '\n';
                }
            }
        }
        bool ok = ns[0] == 1 && ns[1] == 1 && !ov[0] && !ov[1];
        uniq += ok;
        printf("VERIFY %s %d %d %s F1=%ld T1=%ld F0=%ld T0=%ld\n%s", id, h, w, ok ? "UNIQUE" : "NOT-PROVEN", F[1], T[1], F[0], T[0], solText.c_str());
        fflush(stdout);
    }
    fprintf(stderr, "verified %d puzzles, unique %d\n", n, uniq);
    return uniq == n ? 0 : 1;
}

// linetest mode: "n k l1..lk B W" per line on stdin -> "X" (contradiction) or "nB nW"; used to cross-check
// the line solver against an independent brute-force script.
static int lineTestMode() {
    int n, k;
    while (scanf("%d %d", &n, &k) == 2) {
        Line ln; ln.n = n; ln.k = k; ln.full = (1ULL << n) - 1; ln.maxL = 0;
        for (int i = 0; i < k; i++) { scanf("%d", &ln.len[i]); if (ln.len[i] > ln.maxL) ln.maxL = ln.len[i]; }
        for (int i = 0; i < k; i++) ln.rlen[i] = ln.len[k - 1 - i];
        unsigned long long B, W;
        scanf("%llu %llu", &B, &W);
        u64 nB = 0, nW = 0;
        if (!solveLine(ln, B, W, nB, nW)) printf("X\n");
        else printf("%llu %llu\n", (unsigned long long)nB, (unsigned long long)nW);
    }
    return 0;
}

int main(int argc, char** argv) {
    if (argc >= 2 && !strcmp(argv[1], "linetest")) return lineTestMode();
    if (argc >= 2 && !strcmp(argv[1], "selftest")) { rng.seed(12345); return selfTest(argc > 2 ? atoi(argv[2]) : 300) ? 1 : 0; }
    if (argc >= 2 && !strcmp(argv[1], "verify")) return verifyMode(argc > 2 ? atol(argv[2]) : 50000000L);
    if (argc < 9) {
        fprintf(stderr, "usage: gen <seed> <seconds> <nmin> <nmax> <density%%> <budget> <target> <emitMin>\n       gen selftest [rounds]\n       gen verify [budget] < puzzles.txt\n");
        return 2;
    }
    const u64 seed = strtoull(argv[1], 0, 10);
    const double seconds = atof(argv[2]);
    const int nmin = atoi(argv[3]), nmax = atoi(argv[4]);
    const int dens = atoi(argv[5]);
    const long budget = atol(argv[6]), target = atol(argv[7]), emitMin = atol(argv[8]);
    rng.seed(seed);
    const clock_t t0 = clock();
    auto elapsed = [&] { return (double)(clock() - t0) / CLOCKS_PER_SEC; };
    long chain = seed * 100000;
    while (elapsed() < seconds) {
        chain++;
        const int h = nmin + rng() % (nmax - nmin + 1), w = nmin + rng() % (nmax - nmin + 1);
        Grid g(h);
        for (int r = 0; r < h; r++) {
            g[r] = 0;
            for (int c = 0; c < w; c++) if ((int)(rng() % 100) < dens) g[r] |= 1ULL << c;
        }
        long F = 0, Fr = 0, T = 0;
        long obj = objective(h, w, g, 400, budget / 4, 0, F, Fr, T);
        fprintf(stderr, "chain %ld %dx%d start obj=%ld F=%ld Fr=%ld T=%ld t=%.1f\n", chain, h, w, obj, F, Fr, T, elapsed());
        if (obj < 0) continue;
        long best = obj;
        if (obj >= emitMin) emit("CAND", chain, h, w, g, F, Fr, T);
        int stale = 0;
        while (best < target && stale < 80 && elapsed() < seconds) {
            Grid cand = g;
            int m = 1 + rng() % 3;
            for (int i = 0; i < m; i++) { int cell = rng() % (h * w); cand[cell / w] ^= 1ULL << (cell % w); }
            long F2 = 0, Fr2 = 0, T2 = 0;
            long obj2 = objective(h, w, cand, 60, budget, obj - obj / 10, F2, Fr2, T2);
            if (obj2 >= 0 && obj2 * 10 >= obj * 9 && Fr2 > 0) {
                g = cand; obj = obj2;
                if (obj > best) {
                    best = obj; stale = 0;
                    if (obj >= emitMin) emit("CAND", chain, h, w, g, F2, Fr2, T2);
                } else stale++;
            } else stale++;
        }
        fprintf(stderr, "chain %ld end best=%ld t=%.1f\n", chain, best, elapsed());
    }
    return 0;
}
