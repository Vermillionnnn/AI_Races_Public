// Nonogram puzzle generator (round 2 overtime: can also continue climbing from an existing answers file): hill-climbs random grids towards puzzles that are
// expensive for a probing+DFS solver, keeping only grids whose uniqueness is proven by an
// exhaustive probing+DFS solution count. Single source file, standard library only.
#ifdef _MSC_VER
#define _CRT_SECURE_NO_WARNINGS
#endif
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <string>
#include <vector>
#include <deque>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <atomic>
#include <memory>
#include <unordered_set>
#ifdef _MSC_VER
#include <intrin.h>
#endif

typedef uint64_t u64;

static inline int ctz64(u64 x) {
#ifdef _MSC_VER
    unsigned long i; _BitScanForward64(&i, x); return (int)i;
#else
    return __builtin_ctzll(x);
#endif
}
static inline int popc64(u64 x) {
#ifdef _MSC_VER
    return (int)__popcnt64(x);
#elif defined(__POPCNT__)
    return __builtin_popcountll(x);
#else
    x = x - ((x >> 1) & 0x5555555555555555ULL);
    x = (x & 0x3333333333333333ULL) + ((x >> 2) & 0x3333333333333333ULL);
    x = (x + (x >> 4)) & 0x0F0F0F0F0F0F0F0FULL;
    return (int)((x * 0x0101010101010101ULL) >> 56);
#endif
}
static inline u64 rev64(u64 x) {
    x = ((x >> 1) & 0x5555555555555555ULL) | ((x & 0x5555555555555555ULL) << 1);
    x = ((x >> 2) & 0x3333333333333333ULL) | ((x & 0x3333333333333333ULL) << 2);
    x = ((x >> 4) & 0x0F0F0F0F0F0F0F0FULL) | ((x & 0x0F0F0F0F0F0F0F0FULL) << 4);
#ifdef _MSC_VER
    return _byteswap_uint64(x);
#else
    return __builtin_bswap64(x);
#endif
}

static const int MAXN = 62;     // max line length supported (needs n+3 <= 64)
static const int MAXL = 2 * MAXN;
static const int MAXK = 32;
#ifndef CACHESZ
#define CACHESZ (1 << 14)
#endif
#ifndef SKIPMODE
#define SKIPMODE 1
#endif

struct Line {
    int n, k, maxc;
    int c[MAXK];
    int rc[MAXK];
};

// forward DP over a line with sentinel whites at both ends (length L = n + 2).
// f[j] = set of prefix lengths i such that cells [0,i) hold the first j blocks
// (each block followed by its white separator).
static inline bool fwd(u64 B, u64 W, int L, const int* c, int k, int maxc, u64* f, u64* V) {
    const u64 maskL = (1ULL << L) - 1;
    const u64 A = ~B & maskL;
    const u64 noW = ~W & maskL;
    u64 Rc[MAXN + 2];
    Rc[1] = noW;
    for (int t = 2; t <= maxc; t++) Rc[t] = Rc[t - 1] & (noW >> (t - 1));
    u64 x = 1;
    f[0] = x | ((A + (x & A)) ^ A);
    for (int j = 0; j < k; j++) {
        int cj = c[j];
        u64 v = Rc[cj] & (A >> cj);
        V[j] = v;
        x = (f[j] & v) << (cj + 1);
        if (!x) return false;
        f[j + 1] = x | ((A + (x & A)) ^ A);
    }
    return (f[k] >> L) & 1;
}

// returns false on contradiction. gB/gW are known black/white masks (n bits).
static bool solveLine(const Line& ln, u64 gB, u64 gW, u64& oB, u64& oW) {
    const int n = ln.n, L = n + 2, k = ln.k;
    const u64 maskL = (1ULL << L) - 1;
    const u64 B = gB << 1;
    const u64 W = (gW << 1) | 1ULL | (1ULL << (n + 1));
    u64 f[MAXK + 1], V[MAXK], fr[MAXK + 1], Vr[MAXK];
    if (!fwd(B, W, L, ln.c, k, ln.maxc, f, V)) return false;
    const u64 rB = rev64(B) >> (64 - L), rW = rev64(W) >> (64 - L);
    if (!fwd(rB, rW, L, ln.rc, k, ln.maxc, fr, Vr)) return false;
    const u64 A = ~B & maskL;
    u64 blk = 0, wht = 0;
    for (int j = 0; j <= k; j++) {
        u64 G = rev64(fr[k - j]) >> (63 - L);  // suffix-start positions for blocks j..k-1
        wht |= f[j] & G & A;
        if (j > 0) {
            int c = ln.c[j - 1];
            u64 P = f[j - 1] & V[j - 1] & (G >> c);
            wht |= P << c;
            u64 s = P; int len = 1;
            while (len < c) { int sh = len < c - len ? len : c - len; s |= s << sh; len += sh; }
            blk |= s;
        }
    }
    const u64 real = ((1ULL << n) - 1) << 1;
    u64 mb = blk & ~wht & real, mw = wht & ~blk & real;
    if (((blk | wht) & real) != real) return false;
    oB = mb >> 1; oW = mw >> 1;
    return true;
}

struct State {
    u64 B[MAXL], W[MAXL];
    int unknown;
};

struct Solver {
    int h, w, nl;
    Line lines[MAXL];
    u64 rowMask, colMask;
    // propagation scratch
    int q[MAXL * 4];
    bool inq[MAXL];
    long long lineCalls = 0, probes = 0, guesses = 0;
    State sol;
    bool found = false;
    struct CE { u64 kB, kW, oB, oW; };
    CE* cache = nullptr;
    long long hits = 0;
    unsigned gen = 0; u64 genTag = 0;
    const std::atomic<bool>* stopA = nullptr;   // job done flag
    const std::atomic<int>* stopQ = nullptr;    // helper: abort when new work queued
    bool flip = false, aborted = false;
    inline bool shouldStop() {
        if (stopA && stopA->load(std::memory_order_relaxed)) return true;
        if (stopQ && stopQ->load(std::memory_order_relaxed) > 0) return true;
        return false;
    }

    std::unordered_set<u64>* distinct = nullptr;
    inline bool cachedLine(int i, u64 b, u64 wm, u64& nb, u64& nw) {
        u64 kw = wm | ((u64)i << 56);
        if (distinct) { u64 hk = (b * 0x9E3779B97F4A7C15ULL) ^ (kw * 0xC2B2AE3D27D4EB4FULL); hk ^= hk >> 31; hk *= 0xD6E8FEB86659FD93ULL; distinct->insert(hk ^ (hk >> 32)); }
        u64 kb = b | genTag;
        u64 hsh = (kb * 0x9E3779B97F4A7C15ULL) ^ (kw * 0xC2B2AE3D27D4EB4FULL);
        CE& e = cache[(hsh ^ (hsh >> 29)) & (CACHESZ - 1)];
        if (e.kB == kb && e.kW == kw) {
            hits++;
            if (e.oB == ~0ULL) return false;
            nb = e.oB; nw = e.oW; return true;
        }
        bool ok = solveLine(lines[i], b, wm, nb, nw);
        e.kB = kb; e.kW = kw;
        if (ok) { e.oB = nb; e.oW = nw; } else { e.oB = ~0ULL; e.oW = ~0ULL; }
        return ok;
    }

    void init(int H, int Wd, const std::vector<std::vector<int>>& clues) {
        if (!cache) { cache = new CE[CACHESZ]; memset(cache, 0xff, sizeof(CE) * CACHESZ); gen = 0; }
        gen++;
        if (gen >= 0xFFFF) { memset(cache, 0xff, sizeof(CE) * CACHESZ); gen = 1; }
        genTag = (u64)gen << 48;
        h = H; w = Wd; nl = h + w;
        rowMask = (w >= 64) ? ~0ULL : ((1ULL << w) - 1);
        colMask = (h >= 64) ? ~0ULL : ((1ULL << h) - 1);
        for (int i = 0; i < nl; i++) {
            Line& ln = lines[i];
            ln.n = (i < h) ? w : h;
            ln.k = 0;
            for (int v : clues[i]) if (v > 0 && ln.k < MAXK) ln.c[ln.k++] = v > ln.n + 1 ? ln.n + 1 : v;
            for (int j = 0; j < ln.k; j++) ln.rc[j] = ln.c[ln.k - 1 - j];
            ln.maxc = 1;
            for (int j = 0; j < ln.k; j++) if (ln.c[j] > ln.maxc) ln.maxc = ln.c[j];
        }
    }

    // propagate with given dirty lines
    bool propagate(State& s, const int* dirty, int nd) {
        int head = 0, tail = 0;
        const int QS = MAXL * 4;
        memset(inq, 0, sizeof(bool) * nl);
        for (int i = 0; i < nd; i++) { int d = dirty[i]; if (!inq[d]) { inq[d] = true; q[tail] = d; tail = (tail + 1) % QS; } }
        while (head != tail) {
            int i = q[head]; head = (head + 1) % QS; inq[i] = false;
            u64 nb, nw;
            lineCalls++;
            if (!cachedLine(i, s.B[i], s.W[i], nb, nw)) return false;
            u64 aB = nb & ~s.B[i], aW = nw & ~s.W[i];
            if (aB | aW) {
                s.B[i] |= aB; s.W[i] |= aW;
                s.unknown -= popc64(aB | aW);
                int base, idx;
                if (i < h) { base = h; idx = i; } else { base = 0; idx = i - h; }
                u64 bit = 1ULL << idx;
                u64 m = aB;
                while (m) { int t = ctz64(m); m &= m - 1; int o = base + t; s.B[o] |= bit; if (!inq[o]) { inq[o] = true; q[tail] = o; tail = (tail + 1) % QS; } }
                m = aW;
                while (m) { int t = ctz64(m); m &= m - 1; int o = base + t; s.W[o] |= bit; if (!inq[o]) { inq[o] = true; q[tail] = o; tail = (tail + 1) % QS; } }
            }
        }
        return true;
    }

    inline void setCell(State& s, int r, int c, bool black) {
        if (black) { s.B[r] |= 1ULL << c; s.B[h + c] |= 1ULL << r; }
        else { s.W[r] |= 1ULL << c; s.W[h + c] |= 1ULL << r; }
        s.unknown--;
    }

    bool assignProp(State& s, int r, int c, bool black) {
        setCell(s, r, c, black);
        int d[2] = { r, h + c };
        return propagate(s, d, 2);
    }

    inline void cp(State& d, const State& s) {
        memcpy(d.B, s.B, sizeof(u64) * nl);
        memcpy(d.W, s.W, sizeof(u64) * nl);
        d.unknown = s.unknown;
    }

    // ---------------- exhaustive solution counting (stops at 2) ----------------
    std::vector<std::vector<u64>> sols;
    long long budget = 0;
    bool over = false;

    void addSol(const State& s) {
        std::vector<u64> g(s.B, s.B + h);
        for (auto& x : sols) if (x == g) return;
        sols.push_back(g);
    }

    // returns false when the global search must stop (2 solutions or budget exceeded)
    bool cnt(State& s) {
        if (over || sols.size() >= 2) return false;
        if (s.unknown == 0) { addSol(s); return sols.size() < 2; }
        State t1, t0;
        int bestR = -1, bestC = -1; long long bestScore = -1;
        for (;;) {
            bool changed = false;
            bestR = -1; bestScore = -1;
            for (int r = 0; r < h; r++) {
                u64 unk = ~(s.B[r] | s.W[r]) & rowMask;
                while (unk) {
                    int c = ctz64(unk); unk &= unk - 1;
                    if ((s.B[r] | s.W[r]) >> c & 1) continue;
                    probes++;
                    if (probes > budget) { over = true; return false; }
                    cp(t1, s); bool ok1 = assignProp(t1, r, c, true);
                    cp(t0, s); bool ok0 = assignProp(t0, r, c, false);
                    if (!ok1 && !ok0) return true;          // dead subtree
                    if (!ok1 || !ok0) {
                        cp(s, ok1 ? t1 : t0); changed = true;
                        if (s.unknown == 0) { addSol(s); return sols.size() < 2; }
                        unk &= ~(s.B[r] | s.W[r]);
                        continue;
                    }
                    if (t1.unknown == 0) { addSol(t1); if (sols.size() >= 2) return false; }
                    if (t0.unknown == 0) { addSol(t0); if (sols.size() >= 2) return false; }
                    int dirty[MAXL]; int nd = 0; u64 colsTouched = 0;
                    for (int i = 0; i < h; i++) {
                        u64 cb = t1.B[i] & t0.B[i] & ~s.B[i];
                        u64 cw = t1.W[i] & t0.W[i] & ~s.W[i];
                        if (cb | cw) {
                            colsTouched |= cb | cw;
                            u64 m = cb;
                            while (m) { int cc = ctz64(m); m &= m - 1; setCell(s, i, cc, true); }
                            m = cw;
                            while (m) { int cc = ctz64(m); m &= m - 1; setCell(s, i, cc, false); }
                            dirty[nd++] = i;
                        }
                    }
                    if (nd) {
                        while (colsTouched) { int cc = ctz64(colsTouched); colsTouched &= colsTouched - 1; dirty[nd++] = h + cc; }
                        if (!propagate(s, dirty, nd)) return true;
                        if (s.unknown == 0) { addSol(s); return sols.size() < 2; }
                        changed = true;
                        unk &= ~(s.B[r] | s.W[r]);
                    }
                    long long g1 = s.unknown - t1.unknown, g0 = s.unknown - t0.unknown;
                    long long score = (g1 + 1) * (g0 + 1);
                    if (score > bestScore) { bestScore = score; bestR = r; bestC = c; }
                }
            }
            if (!changed) break;
        }
        if (bestR < 0) return true;
        guesses++;
        for (int v = 0; v < 2; v++) {
            State t; cp(t, s);
            if (assignProp(t, bestR, bestC, v == 0)) {
                if (!cnt(t)) return false;
            }
        }
        return true;
    }

    // ---------------- first-solution search in the scored solver's order ----------------
    // probe rows with fewest unknowns first, score = (min gain, max gain) lexicographic,
    // first strictly-better cell wins, branch on the side with more gain first.
    bool tdone = false;
    long long nDistinct = 0;
    bool tdfs(State& s) {
        if (over || tdone) return false;
        if (s.unknown == 0) { tdone = true; return false; }
        State t1, t0;
        int bestR = -1, bestC = -1; long long bMin = -1, bMax = -1;
        int order[MAXN];
        for (;;) {
            bool changed = false;
            bestR = -1; bMin = -1; bMax = -1;
            int no = 0;
            for (int r = 0; r < h; r++) if (~(s.B[r] | s.W[r]) & rowMask) order[no++] = r;
            for (int a = 1; a < no; a++) {   // stable insertion sort by unknown count
                int x = order[a], kx = popc64(~(s.B[x] | s.W[x]) & rowMask), b = a - 1;
                while (b >= 0 && popc64(~(s.B[order[b]] | s.W[order[b]]) & rowMask) > kx) { order[b + 1] = order[b]; b--; }
                order[b + 1] = x;
            }
            for (int oi = 0; oi < no; oi++) {
                int r = order[oi];
                u64 unk = ~(s.B[r] | s.W[r]) & rowMask;
                while (unk) {
                    int c = ctz64(unk); unk &= unk - 1;
                    if ((s.B[r] | s.W[r]) >> c & 1) continue;
                    probes++;
                    if (probes > budget) { over = true; return false; }
                    cp(t1, s); bool ok1 = assignProp(t1, r, c, true);
                    cp(t0, s); bool ok0 = assignProp(t0, r, c, false);
                    if (!ok1 && !ok0) return true;
                    if (!ok1 || !ok0) {
                        cp(s, ok1 ? t1 : t0); changed = true;
                        if (s.unknown == 0) { tdone = true; return false; }
                        continue;
                    }
                    if (t1.unknown == 0 || t0.unknown == 0) { tdone = true; return false; }
                    int dirty[MAXL]; int nd = 0; u64 colsTouched = 0;
                    for (int i = 0; i < h; i++) {
                        u64 cb = t1.B[i] & t0.B[i] & ~s.B[i];
                        u64 cw = t1.W[i] & t0.W[i] & ~s.W[i];
                        if (cb | cw) {
                            colsTouched |= cb | cw;
                            u64 m = cb;
                            while (m) { int cc = ctz64(m); m &= m - 1; setCell(s, i, cc, true); }
                            m = cw;
                            while (m) { int cc = ctz64(m); m &= m - 1; setCell(s, i, cc, false); }
                            dirty[nd++] = i;
                        }
                    }
                    if (nd) {
                        while (colsTouched) { int cc = ctz64(colsTouched); colsTouched &= colsTouched - 1; dirty[nd++] = h + cc; }
                        if (!propagate(s, dirty, nd)) return true;
                        if (s.unknown == 0) { tdone = true; return false; }
                        changed = true;
                        continue;
                    }
                    long long g1 = s.unknown - t1.unknown, g0 = s.unknown - t0.unknown;
                    long long mn = g1 < g0 ? g1 : g0, mx = g1 < g0 ? g0 : g1;
                    if (mn > bMin || (mn == bMin && mx > bMax)) { bMin = mn; bMax = mx; bestR = r; bestC = c; }
                }
            }
            if (!changed) break;
        }
        if (bestR < 0) return true;
        guesses++;
        State tb, tw; cp(tb, s); cp(tw, s);
        bool okb = assignProp(tb, bestR, bestC, true), okw = assignProp(tw, bestR, bestC, false);
        long long gb = s.unknown - tb.unknown, gw = s.unknown - tw.unknown;
        bool blackFirst = gb >= gw;
        for (int v = 0; v < 2; v++) {
            bool black = (v == 0) ? blackFirst : !blackFirst;
            State& t = black ? tb : tw;
            if (black ? okb : okw) { if (!tdfs(t)) return false; }
        }
        return true;
    }

    // work of the first-solution search; returns -1 if over budget
    double firstWork(long long probeBudget) {
        over = false; tdone = false; budget = probeBudget;
        lineCalls = probes = guesses = hits = 0;
        State s; memset(&s, 0, sizeof(s));
        s.unknown = h * w;
        int dirty[MAXL];
        for (int i = 0; i < nl; i++) dirty[i] = i;
        std::unordered_set<u64> ds; ds.reserve(1 << 16); distinct = &ds;
        if (propagate(s, dirty, nl)) tdfs(s);
        distinct = nullptr;
        nDistinct = (long long)ds.size();
        if (over) return -1;
        // rough single-thread CPython cost model (seconds): new line states are solved,
        // every line visit costs a dict lookup + bookkeeping, every probe two board copies.
        return nDistinct * 20e-6 + (double)lineCalls * 1.5e-6 + (double)probes * 15e-6;
    }

    // 0 = unique, 1 = multiple, 2 = no solution, 3 = budget exceeded
    int countSolutions(long long probeBudget) {
        sols.clear(); over = false; budget = probeBudget;
        lineCalls = probes = guesses = hits = 0;
        State s; memset(&s, 0, sizeof(s));
        s.unknown = h * w;
        int dirty[MAXL];
        for (int i = 0; i < nl; i++) dirty[i] = i;
        if (propagate(s, dirty, nl)) cnt(s);
        if (over) return 3;
        if (sols.size() >= 2) return 1;
        if (sols.empty()) return 2;
        return 0;
    }
};

// ---------------- generator ----------------
#include <random>
#include <chrono>

static std::vector<int> clueOf(const std::vector<char>& g, int start, int step, int n) {
    std::vector<int> v; int run = 0;
    for (int i = 0; i < n; i++) {
        if (g[start + i * step]) run++;
        else if (run) { v.push_back(run); run = 0; }
    }
    if (run) v.push_back(run);
    return v;
}

struct Eval { int status; double work; long long probes, guesses, misses; };
static int g_mode = 0;   // 0: first-solution work in the scored solver's order; 1: exhaustive search-tree probes

static Eval evaluate(Solver& S, const std::vector<char>& g, int h, int w, long long budget) {
    std::vector<std::vector<int>> clues;
    for (int r = 0; r < h; r++) clues.push_back(clueOf(g, r * w, 1, w));
    for (int c = 0; c < w; c++) clues.push_back(clueOf(g, c, w, h));
    S.init(h, w, clues);
    Eval e;
    e.status = S.countSolutions(budget);
    e.probes = S.probes; e.guesses = S.guesses; e.misses = S.lineCalls - S.hits;
    e.work = 0;
    if (e.status == 0) {   // sanity: the unique solution must be the generating grid
        for (int r = 0; r < h; r++) {
            u64 m = 0;
            for (int c = 0; c < w; c++) if (g[r * w + c]) m |= 1ULL << c;
            if (S.sols[0][r] != m) { e.status = 9; break; }
        }
    }
    if (e.status == 0 && g_mode == 1) { e.work = (double)S.probes; return e; }
    if (e.status == 0) {
        double fw = S.firstWork(budget);
        if (fw < 0) e.status = 3;
        else { e.work = fw; e.probes = S.probes; e.guesses = S.guesses; e.misses = S.nDistinct; }
    }
    return e;
}

static std::string clueStr(const std::vector<int>& v) {
    if (v.empty()) return "0";
    std::string s;
    for (size_t i = 0; i < v.size(); i++) { if (i) s += ' '; s += std::to_string(v[i]); }
    return s;
}

int main(int argc, char** argv) {
    if (argc < 7) { fprintf(stderr, "usage: gen <seed> <count> <h> <w> <seconds-per-puzzle> <prefix> [probe-budget] [density] [target-work] [mode] [seed-answers-file] [first-index]\n"); return 1; }
    unsigned long long seed = strtoull(argv[1], 0, 10);
    int count = atoi(argv[2]), h = atoi(argv[3]), w = atoi(argv[4]);
    double secs = atof(argv[5]);
    std::string prefix = argv[6];
    long long budget = argc > 7 ? atoll(argv[7]) : 400000;
    double dens = argc > 8 ? atof(argv[8]) : 0.5;
    double target = argc > 9 ? atof(argv[9]) : 1e18;
    // optional: start from grids of an existing answers file, grids [first, first+count)
    std::vector<std::vector<char>> seeds; std::vector<int> sh, sw;
    if (argc > 11) {
        g_mode = atoi(argv[10]);
        FILE* fi = fopen(argv[11], "r"); int first = argc > 12 ? atoi(argv[12]) : 0;
        char buf[256]; std::vector<std::string> cur; int k = -1;
        std::vector<std::vector<std::string>> all;
        while (fi && fgets(buf, sizeof buf, fi)) {
            std::string l(buf); while (!l.empty() && (l.back() == '\n' || l.back() == '\r')) l.pop_back();
            if (l.rfind("SOLUTION ", 0) == 0) { all.emplace_back(); k++; } else if (!l.empty() && k >= 0) all[k].push_back(l);
        }
        for (int i = first; i < first + count && i < (int)all.size(); i++) {
            std::vector<char> gg; for (auto& row : all[i]) for (char ch : row) gg.push_back(ch == '#');
            seeds.push_back(gg); sh.push_back((int)all[i].size()); sw.push_back((int)all[i][0].size());
        }
    }
    std::mt19937_64 rng(seed);
    Solver* S = new Solver();
    std::string pz = prefix + "_puzzles.txt", an = prefix + "_answers.txt";
    FILE* fp = fopen(pz.c_str(), "w"); FILE* fa = fopen(an.c_str(), "w");
    for (int idx = 0; idx < count; idx++) {
        auto t0 = std::chrono::steady_clock::now();
        if (!seeds.empty()) { h = sh[idx]; w = sw[idx]; }
        std::vector<char> g(h * w);
        Eval cur;
        if (!seeds.empty()) {
            g = seeds[idx];
            cur = evaluate(*S, g, h, w, budget * 4);
            if (cur.status != 0) { fprintf(stderr, "seed %d not provable within budget, skipped\n", idx); continue; }
        }
        else for (;;) {
            for (auto& x : g) x = (rng() % 1000000) < dens * 1000000;
            cur = evaluate(*S, g, h, w, budget);
            if (cur.status == 0) break;
        }
        long long iters = 0, acc = 0;
        for (;;) {
            double el = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
            if (el > secs || cur.work >= target) break;
            iters++;
            int nf = 1 + (rng() % 3 == 0);
            int cells[2];
            for (int k = 0; k < nf; k++) { cells[k] = rng() % (h * w); g[cells[k]] ^= 1; }
            Eval e = evaluate(*S, g, h, w, budget);
            if (e.status == 0 && e.work >= cur.work) { cur = e; acc++; }
            else for (int k = nf - 1; k >= 0; k--) g[cells[k]] ^= 1;
        }
        // final re-verification with a larger budget
        Eval fin = evaluate(*S, g, h, w, budget * 4);
        if (fin.status != 0) { if (seeds.empty()) idx--; continue; }
        std::string id = prefix + "-" + std::to_string(idx);
        fprintf(fp, "PUZZLE %s %d %d\n", id.c_str(), h, w);
        for (int r = 0; r < h; r++) fprintf(fp, "%s\n", clueStr(clueOf(g, r * w, 1, w)).c_str());
        for (int c = 0; c < w; c++) fprintf(fp, "%s\n", clueStr(clueOf(g, c, w, h)).c_str());
        fprintf(fa, "SOLUTION %s\n", id.c_str());
        for (int r = 0; r < h; r++) { for (int c = 0; c < w; c++) fputc(g[r * w + c] ? '#' : '.', fa); fputc('\n', fa); }
        fflush(fp); fflush(fa);
        int blacks = 0; for (char x : g) blacks += x;
        fprintf(stderr, "%s score=%.2f probes=%lld guesses=%lld distinct=%lld iters=%lld acc=%lld dens=%.3f\n",
                id.c_str(), fin.work, fin.probes, fin.guesses, fin.misses, iters, acc, blacks / (double)(h * w));
    }
    fclose(fp); fclose(fa);
    return 0;
}
