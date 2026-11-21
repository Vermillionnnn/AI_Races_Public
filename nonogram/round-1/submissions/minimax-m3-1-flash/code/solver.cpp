// Nonogram solver - fast bitmask line-DP solver with propagation + backtracking.
// Reads puzzles from stdin (one after another), writes "SOLUTION <id>" + grid, flushes.
//
// Build (MinGW g++):  g++ -O2 -std=c++17 solver.cpp -o solver.exe
// Build (MSVC):      cl /O2 /std:c++17 /EHsc /Fe:solver.exe solver.cpp
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <vector>
#include <string>

#if defined(_MSC_VER)
#  include <intrin.h>
static inline int ctz64(uint64_t x)  { unsigned long i; _BitScanForward64(&i, x); return (int)i; }
static inline int clz64(uint64_t x)  { unsigned long i; _BitScanReverse64(&i, x); return 63 - (int)i; }
static inline int popcnt64(uint64_t x){ return __popcnt64(x); }
#else
static inline int ctz64(uint64_t x)  { return __builtin_ctzll(x); }
static inline int clz64(uint64_t x)  { return 63 - __builtin_clzll(x); }
static inline int popcnt64(uint64_t x){ return __builtin_popcountll(x); }
#endif

typedef uint64_t u64;
static const int MAXL = 64;   // max line length / max blocks per line

static inline u64 fullMask(int L) { return (L >= 64) ? ~0ULL : ((1ULL << L) - 1); }

// ------------------------------------------------------------------
// line solving
// ------------------------------------------------------------------
// A line has length L, block list cl[0..k-1], known-filled mask F, known-empty mask E.
// forwardDP computes for each block i the set of start positions s such that blocks
// 0..i-1 can be laid out before s (all known filled cells covered, no known empty cell
// covered, gaps of >= 1 cell with no filled cell in them).  Bit s of out[i] is set.
// backwardDP does the mirror image (suffix feasibility), returned in original coordinates.
static void forwardDP(int L, const int *cl, int k, u64 F, u64 E, u64 *out, int *prefF) {
    u64 NE = ~E & fullMask(L);
    prefF[0] = 0;
    for (int x = 0; x < L; x++) prefF[x + 1] = prefF[x] + (int)((F >> x) & 1ULL);
    u64 prev = 0;              // possible end+1 positions of block i-1
    bool first = true;
    for (int i = 0; i < k; i++) {
        int c = cl[i];
        u64 w = NE;
        for (int j = 1; j < c; j++) w &= (NE >> j);   // window of c cells free of known empties
        if (c <= L) w &= (1ULL << (L - c + 1)) - 1; else w = 0;
        u64 cand = 0;
        if (first) {
            u64 ww = w;
            while (ww) { int s = ctz64(ww); ww &= ww - 1; if (prefF[s] == 0) cand |= 1ULL << s; }
        } else {
            u64 ww = w;
            while (ww) {
                int s = ctz64(ww); ww &= ww - 1;
                u64 m = prev & ((1ULL << s) - 1);      // ends e <= s-1
                if (!m) continue;
                int e = clz64(m);                     // largest such e
                if (prefF[s] == prefF[e]) cand |= 1ULL << s;   // gap [e,s) holds no filled cell
            }
        }
        out[i] = cand;
        prev = cand << c;
        first = false;
    }
}

static u64 revMask(u64 m, int L) {
    u64 r = 0;
    while (m) { int i = ctz64(m); r |= 1ULL << (L - 1 - i); m &= m - 1; }
    return r;
}

static void backwardDP(int L, const int *cl, int k, u64 F, u64 E, u64 *out, int *prefF, u64 *tmp) {
    int clr[MAXL];
    for (int i = 0; i < k; i++) clr[i] = cl[k - 1 - i];
    forwardDP(L, clr, k, revMask(F, L), revMask(E, L), tmp, prefF);
    for (int i = 0; i < k; i++) {
        int j = k - 1 - i, c = cl[i];
        u64 v = tmp[j], res = 0;
        while (v) { int sr = ctz64(v); v &= v - 1; res |= 1ULL << (L - c - sr); }
        out[i] = res;
    }
}

// Deduces forced cells of one line.  Returns false on contradiction.
// outF: cells that must be filled.  outE: cells that must be empty.
static bool deduceLine(int L, const int *cl, int k, u64 F, u64 E, u64 &outF, u64 &outE) {
    u64 full = fullMask(L);
    if (k == 0) {
        if (F) return false;
        outF = 0; outE = full & ~E;
        return true;
    }
    int prefF[MAXL + 1], pref2[MAXL + 1];
    u64 fw[MAXL], bw[MAXL], tmp[MAXL];
    forwardDP(L, cl, k, F, E, fw, prefF);
    backwardDP(L, cl, k, F, E, bw, pref2, tmp);
    u64 possibly = 0, must = 0;
    for (int i = 0; i < k; i++) {
        u64 v = fw[i] & bw[i];
        if (!v) return false;                       // block cannot be placed -> contradiction
        int mn = ctz64(v), mx = clz64(v), c = cl[i];
        if (mx <= mn + c - 1) must |= ((1ULL << (mn + c - mx)) - 1) << mx;  // cells covered in every placement
        if ((v & (v + 1)) == 0) {                  // contiguous start set
            possibly |= ((1ULL << (mx + c - mn)) - 1) << mn;
        } else {
            u64 vv = v;
            while (vv) { int s = ctz64(vv); vv &= vv - 1; possibly |= ((1ULL << c) - 1) << s; }
        }
    }
    if (F & ~possibly) return false;               // a filled cell is not covered by any block
    if (must & E) return false;                    // cell forced both filled and empty
    outF = must & ~F;
    outE = full & ~possibly & ~E;
    return true;
}

// ------------------------------------------------------------------
// puzzle state
// ------------------------------------------------------------------
struct Clues {
    int h, w;
    int rcl[MAXL][MAXL]; int rn[MAXL];
    int ccl[MAXL][MAXL]; int cn[MAXL];
};

struct State {
    u64 rowF[MAXL], rowE[MAXL], colF[MAXL], colE[MAXL];
    bool dirtyR[MAXL], dirtyC[MAXL];
};

// ------------------------------------------------------------------
// propagation
// ------------------------------------------------------------------
static bool propagate(const Clues &C, State &S) {
    static const int QUEUE_MAX = 1 << 16;
    static int q[QUEUE_MAX];
    bool *dirtyR = S.dirtyR, *dirtyC = S.dirtyC;
    int qh = 0, qt = 0;
    for (int r = 0; r < C.h; r++) if (dirtyR[r]) { dirtyR[r] = false; q[qt++] = r; }
    for (int c = 0; c < C.w; c++) if (dirtyC[c]) { dirtyC[c] = false; q[qt++] = MAXL + c; }
    while (qh < qt) {
        int item = q[qh++];
        if (item < MAXL) {
            int r = item;
            u64 F = S.rowF[r], E = S.rowE[r], nf, ne;
            if (!deduceLine(C.w, C.rcl[r], C.rn[r], F, E, nf, ne)) return false;
            u64 newF = nf & ~F, newE = ne & ~E;
            if (!(newF | newE)) continue;
            S.rowF[r] = F | nf; S.rowE[r] = E | ne;
            while (newF) {
                int c = ctz64(newF); newF &= newF - 1;
                S.colF[c] |= 1ULL << r;
                if (!dirtyC[c]) { dirtyC[c] = true; q[qt++] = MAXL + c; }
            }
            while (newE) {
                int c = ctz64(newE); newE &= newE - 1;
                S.colE[c] |= 1ULL << r;
                if (!dirtyC[c]) { dirtyC[c] = true; q[qt++] = MAXL + c; }
            }
            dirtyR[r] = true; q[qt++] = r;   // new knowledge may allow more deductions here
        } else {
            int c = item - MAXL;
            u64 F = S.colF[c], E = S.colE[c], nf, ne;
            if (!deduceLine(C.h, C.ccl[c], C.cn[c], F, E, nf, ne)) return false;
            u64 newF = nf & ~F, newE = ne & ~E;
            if (!(newF | newE)) continue;
            S.colF[c] = F | nf; S.colE[c] = E | ne;
            while (newF) {
                int r = ctz64(newF); newF &= newF - 1;
                S.rowF[r] |= 1ULL << c;
                if (!dirtyR[r]) { dirtyR[r] = true; q[qt++] = r; }
            }
            while (newE) {
                int r = ctz64(newE); newE &= newE - 1;
                S.rowE[r] |= 1ULL << c;
                if (!dirtyR[r]) { dirtyR[r] = true; q[qt++] = r; }
            }
            dirtyC[c] = true; q[qt++] = MAXL + c;   // new knowledge may allow more deductions here
        }
    }
    return true;
}

// ------------------------------------------------------------------
// line solution enumeration (for branching)
// ------------------------------------------------------------------
struct EnumCtx {
    int L, k, cl[MAXL];
    u64 valid[MAXL];
    int prefF[MAXL + 1];
    u64 cur;
    u64 *sols;
    int nsol, limit, nodes;
    bool overflow;
    void dfs(int i, int prevEnd) {
        if (nsol >= limit || overflow) { overflow = true; return; }
        if (++nodes > 20000) { overflow = true; return; }
        if (i == k) { sols[nsol++] = cur; return; }
        u64 v = valid[i];
        int c = cl[i];
        while (v) {
            int s = ctz64(v); v &= v - 1;
            if (i == 0) { if (prefF[s] != 0) continue; }
            else { if (s < prevEnd + 1) continue; if (prefF[s] != prefF[prevEnd]) continue; }
            u64 span = ((1ULL << c) - 1) << s;
            cur |= span;
            dfs(i + 1, s + c);
            cur &= ~span;
            if (nsol >= limit || overflow) { overflow = true; return; }
        }
    }
};

static int enumerateSolutions(int L, const int *cl, int k, u64 F, u64 E, u64 *sols, int limit, bool &overflow) {
    overflow = false;
    if (k == 0) {
        if (F) { overflow = true; return 0; }
        sols[0] = 0; return 1;
    }
    int prefF[MAXL + 1], pref2[MAXL + 1];
    u64 fw[MAXL], bw[MAXL], tmp[MAXL];
    forwardDP(L, cl, k, F, E, fw, prefF);
    backwardDP(L, cl, k, F, E, bw, pref2, tmp);
    EnumCtx ec;
    ec.L = L; ec.k = k; ec.cur = 0; ec.sols = sols; ec.nsol = 0; ec.limit = limit;
    ec.nodes = 0; ec.overflow = false;
    for (int i = 0; i < k; i++) {
        ec.cl[i] = cl[i];
        ec.valid[i] = fw[i] & bw[i];
        if (!ec.valid[i]) { overflow = true; return 0; }
    }
    for (int x = 0; x <= L; x++) ec.prefF[x] = prefF[x];
    ec.dfs(0, 0);
    overflow = ec.overflow;
    return ec.nsol;
}

// ------------------------------------------------------------------
// search
// ------------------------------------------------------------------
static long long g_nodes = 0;
static const int MAXDEPTH = 2100;
static State gstack[MAXDEPTH];
static u64 gsols[MAXDEPTH][64];
// per-depth scratch (kept out of the stack frames: the recursion is deep)
static u64 gfw[MAXDEPTH][MAXL], gbw[MAXDEPTH][MAXL], gtmp[MAXDEPTH][MAXL], gvalid[MAXDEPTH][MAXL];
static int gpre[MAXDEPTH][MAXL + 1], gpre2[MAXDEPTH][MAXL + 1], gcnt[MAXDEPTH][MAXL];

// Pick the cell of a line that is most likely filled (most placements cover it),
// and return the count of placements covering it.
static int bestGuessCell(int L, const int *cl, int k, u64 F, u64 E, int *outCount) {
    int prefF[MAXL + 1], pref2[MAXL + 1];
    u64 fw[MAXL], bw[MAXL], tmp[MAXL];
    forwardDP(L, cl, k, F, E, fw, prefF);
    backwardDP(L, cl, k, F, E, bw, pref2, tmp);
    int cnt[MAXL];
    for (int x = 0; x < L; x++) cnt[x] = 0;
    u64 unk = fullMask(L) & ~(F | E);
    for (int i = 0; i < k; i++) {
        u64 v = fw[i] & bw[i];
        int c = cl[i];
        while (v) {
            int s = ctz64(v); v &= v - 1;
            for (int x = s; x < s + c && x < L; x++) cnt[x]++;
        }
    }
    int best = -1, bestCnt = -1;
    for (int x = 0; x < L; x++) if ((unk >> x) & 1ULL) { if (cnt[x] > bestCnt) { bestCnt = cnt[x]; best = x; } }
    *outCount = bestCnt;
    return best;
}

static bool search(const Clues &C, State &S, int depth) {
    if (depth >= MAXDEPTH) return false;
    if (++g_nodes > 100000000LL) return false;
    if (!propagate(C, S)) return false;

    int maxU = 0, bestR = -1, bestC = -1, minUR = 1 << 30, minUC = 1 << 30;
    for (int r = 0; r < C.h; r++) {
        int u = popcnt64(fullMask(C.w) & ~(S.rowF[r] | S.rowE[r]));
        if (u > maxU) maxU = u;
        if (u > 0 && u < minUR) { minUR = u; bestR = r; }
    }
    for (int c = 0; c < C.w; c++) {
        int u = popcnt64(fullMask(C.h) & ~(S.colF[c] | S.colE[c]));
        if (u > maxU) maxU = u;
        if (u > 0 && u < minUC) { minUC = u; bestC = c; }
    }
    if (maxU == 0) return true;   // every cell determined

    bool useRow = (minUR <= minUC);
    int L = useRow ? C.w : C.h;
    const int *cl = useRow ? C.rcl[bestR] : C.ccl[bestC];
    int k = useRow ? C.rn[bestR] : C.cn[bestC];
    u64 lF = useRow ? S.rowF[bestR] : S.colF[bestC];
    u64 lE = useRow ? S.rowE[bestR] : S.colE[bestC];

    // exact per-line DP: valid start positions of every block
    u64 *fw = gfw[depth], *bw = gbw[depth], *tmp = gtmp[depth], *valid = gvalid[depth];
    int *prefF = gpre[depth], *pref2 = gpre2[depth], *cnt = gcnt[depth];
    forwardDP(L, cl, k, lF, lE, fw, prefF);
    backwardDP(L, cl, k, lF, lE, bw, pref2, tmp);
    long long prod = 1;
    for (int i = 0; i < k; i++) {
        valid[i] = fw[i] & bw[i];
        if (!valid[i]) return false;                  // contradiction
        cnt[i] = popcnt64(valid[i]);
        prod *= cnt[i];
        if (prod > 4096) prod = 4097;
    }

    // 1) whole-line branching when the line has only few solutions
    if (prod <= 64) {
        bool ov = false;
        u64 *sols = gsols[depth];
        int n = enumerateSolutions(L, cl, k, lF, lE, sols, 64, ov);
        if (n > 1 && !ov) {
            State *save = &gstack[depth];
            *save = S;
            for (int i = 0; i < n; i++) {
                u64 sol = sols[i];
                if (useRow) {
                    u64 fm = sol & ~S.rowF[bestR];
                    u64 em = (~sol & fullMask(C.w)) & ~S.rowE[bestR] & ~S.rowF[bestR];
                    S.rowF[bestR] |= sol; S.rowE[bestR] |= em;
                    while (fm) { int c = ctz64(fm); fm &= fm - 1; S.colF[c] |= 1ULL << bestR; S.dirtyC[c] = true; }
                    while (em) { int c = ctz64(em); em &= em - 1; S.colE[c] |= 1ULL << bestR; S.dirtyC[c] = true; }
                } else {
                    u64 fm = sol & ~S.colF[bestC];
                    u64 em = (~sol & fullMask(C.h)) & ~S.colE[bestC] & ~S.colF[bestC];
                    S.colF[bestC] |= sol; S.colE[bestC] |= em;
                    while (fm) { int r = ctz64(fm); fm &= fm - 1; S.rowF[r] |= 1ULL << bestC; S.dirtyR[r] = true; }
                    while (em) { int r = ctz64(em); em &= em - 1; S.rowE[r] |= 1ULL << bestC; S.dirtyR[r] = true; }
                }
                if (search(C, S, depth + 1)) return true;
                S = *save;
            }
            return false;
        }
    }

    // 2) branch on the block of that line with the fewest possible positions
    int bi = -1, bc = 1 << 30;
    for (int i = 0; i < k; i++) if (cnt[i] >= 2 && cnt[i] < bc) { bc = cnt[i]; bi = i; }
    if (bi >= 0 && bc <= 1) {   // block-position branching (kept off: measured slower than cell guessing)
        State *save = &gstack[depth];
        *save = S;
        int bc2 = cl[bi];
        u64 v = valid[bi];
        while (v) {
            int s = ctz64(v); v &= v - 1;
            u64 span = ((1ULL << bc2) - 1) << s;
            if (useRow) {
                u64 fm = span & ~S.rowF[bestR];
                S.rowF[bestR] |= span;
                S.dirtyR[bestR] = true;
                while (fm) { int c = ctz64(fm); fm &= fm - 1; S.colF[c] |= 1ULL << bestR; S.dirtyC[c] = true; }
            } else {
                u64 fm = span & ~S.colF[bestC];
                S.colF[bestC] |= span;
                S.dirtyC[bestC] = true;
                while (fm) { int r = ctz64(fm); fm &= fm - 1; S.rowF[r] |= 1ULL << bestC; S.dirtyR[r] = true; }
            }
            if (search(C, S, depth + 1)) return true;
            S = *save;
        }
        return false;
    }

    // 3) otherwise guess a single cell of that line
    int gcount = 0;
    int gc = bestGuessCell(L, cl, k, lF, lE, &gcount);
    if (gc < 0) return false;
    int cr = useRow ? bestR : gc;
    int cc = useRow ? gc : bestC;
    State *save = &gstack[depth];
    *save = S;
    // guess filled first (most likely)
    S.rowF[cr] |= 1ULL << cc; S.colF[cc] |= 1ULL << cr;
    S.dirtyC[cc] = true; S.dirtyR[cr] = true;
    if (search(C, S, depth + 1)) return true;
    S = *save;
    S.rowE[cr] |= 1ULL << cc; S.colE[cc] |= 1ULL << cr;
    S.dirtyC[cc] = true; S.dirtyR[cr] = true;
    if (search(C, S, depth + 1)) return true;
    S = *save;
    return false;
}

// ------------------------------------------------------------------
// input parsing / output
// ------------------------------------------------------------------
static char g_line[1 << 16];

static int parseClueLine(char *s, int *out) {
    int n = 0;
    while (*s) {
        while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') s++;
        if (!*s) break;
        int v = 0;
        while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; }
        out[n++] = v;
        if (n >= MAXL) break;
    }
    if (n == 1 && out[0] == 0) n = 0;   // "0" means empty (all white) line
    return n;
}

int main() {
    std::vector<char> id;
    Clues C; State S;
    char *outbuf = (char *)malloc(1 << 16);
    while (fgets(g_line, sizeof(g_line), stdin)) {
        if (g_line[0] != 'P') continue;
        int h = 0, w = 0;
        char pid[256];
        if (sscanf(g_line, "PUZZLE %255s %d %d", pid, &h, &w) != 3) continue;
        C.h = h; C.w = w;
        int cl[MAXL];
        for (int r = 0; r < h; r++) {
            if (!fgets(g_line, sizeof(g_line), stdin)) return 0;
            C.rn[r] = parseClueLine(g_line, C.rcl[r]);
        }
        for (int c = 0; c < w; c++) {
            if (!fgets(g_line, sizeof(g_line), stdin)) return 0;
            C.cn[c] = parseClueLine(g_line, C.ccl[c]);
        }
        memset(&S, 0, sizeof(State));
        for (int r = 0; r < h; r++) S.dirtyR[r] = true;
        for (int c = 0; c < w; c++) S.dirtyC[c] = true;
        bool ok = search(C, S, 0);
        if (ok) {
            int len = snprintf(outbuf, 1 << 16, "SOLUTION %s\n", pid);
            for (int r = 0; r < h; r++) {
                u64 f = S.rowF[r];
                for (int c = 0; c < w; c++) outbuf[len++] = ((f >> c) & 1ULL) ? '#' : '.';
                outbuf[len++] = '\n';
            }
            fwrite(outbuf, 1, len, stdout);
        } else {
            int len = snprintf(outbuf, 1 << 16, "UNSOLVED %s\n", pid);
            fwrite(outbuf, 1, len, stdout);
        }
        fflush(stdout);
    }
    return 0;
}
