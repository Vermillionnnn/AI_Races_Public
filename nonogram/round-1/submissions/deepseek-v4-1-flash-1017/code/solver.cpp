// Nonogram solver - single source file, standard library only.
// Strategy: exact (generalized arc consistent) line propagation with bitmasks,
// queue driven constraint propagation, DFS branch and bound with
// "fewest line patterns" branching and per-cell probability split.
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>
#include <deque>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <chrono>

#if defined(_MSC_VER)
#include <intrin.h>
static inline int ctz32(uint32_t x) { unsigned long i; _BitScanForward(&i, (unsigned long)x); return (int)i; }
static inline int ctz64(uint64_t x) { unsigned long i; _BitScanForward64(&i, (unsigned __int64)x); return (int)i; }
#else
static inline int ctz32(uint32_t x) { return __builtin_ctz(x); }
static inline int ctz64(uint64_t x) { return __builtin_ctzll(x); }
#endif

static const int MAXN = 48;
static const int MAXK = 26;

struct LineClue {
    int n;
    int k;
    int b[MAXK];
};

struct Puzzle {
    std::string id;
    int h, w;
    LineClue rows[MAXN];
    LineClue cols[MAXN];
};

// ---------------------------------------------------------------------------
// Exact line solver.  Returns false when the line has no valid pattern.
// outB/outW are the union of black/white cells over all valid patterns.
// ---------------------------------------------------------------------------
static bool lineSolve(const LineClue& L, uint64_t black, uint64_t white,
                      uint64_t& outB, uint64_t& outW)
{
    const int n = L.n;
    const int k = L.k;
    const uint64_t all = (n >= 64) ? ~0ULL : ((1ULL << n) - 1ULL);
    if (k == 0) {
        if (black & all) return false;
        outB = 0;
        outW = all;
        return true;
    }
    uint32_t F[MAXN + 1], B[MAXN + 1];
    memset(F, 0, sizeof(uint32_t) * (size_t)(n + 1));
    memset(B, 0, sizeof(uint32_t) * (size_t)(n + 1));
    const uint32_t jmask = (k >= 32) ? 0xFFFFFFFFu : ((1u << k) - 1u);

    F[0] = 1u;
    for (int i = 0; i < n; ++i) {
        uint32_t cur = F[i];
        if (!cur) continue;
        if (!((black >> i) & 1ULL)) F[i + 1] |= cur;
        uint32_t m = cur & jmask;
        while (m) {
            const int j = ctz32(m);
            m &= m - 1;
            const int len = L.b[j];
            const int e = i + len;
            if (e > n) continue;
            if ((((1ULL << len) - 1ULL) << i) & white) continue;
            const uint32_t bit = 1u << (j + 1);
            if (e == n) F[n] |= bit;
            else if (!((black >> e) & 1ULL)) F[e + 1] |= bit;
        }
    }
    if (!((F[n] >> k) & 1u)) return false;

    B[n] = (1u << k);
    for (int i = n - 1; i >= 0; --i) {
        uint32_t r = 0;
        if (!((black >> i) & 1ULL)) r |= B[i + 1];
        {
            for (int j = 0; j < k; ++j) {
                const int len = L.b[j];
                const int e = i + len;
                if (e > n) continue;
                if ((((1ULL << len) - 1ULL) << i) & white) continue;
                bool good;
                if (e == n) good = (j + 1 == k);
                else good = (!((black >> e) & 1ULL)) && (((B[e + 1] >> (j + 1)) & 1u) != 0);
                if (good) r |= 1u << j;
            }
        }
        B[i] = r;
    }

    uint64_t canBlack = 0, canWhite = 0;
    for (int i = 0; i < n; ++i) {
        if (!((black >> i) & 1ULL) && (F[i] & B[i + 1])) canWhite |= 1ULL << i;
    }

    int diff[MAXN + 1];
    memset(diff, 0, sizeof(int) * (size_t)(n + 1));
    for (int i = 0; i < n; ++i) {
        if ((white >> i) & 1ULL) continue;
        uint32_t m = F[i] & jmask;
        if (!m) continue;
        while (m) {
            const int j = ctz32(m);
            m &= m - 1;
            const int len = L.b[j];
            const int e = i + len;
            if (e > n) continue;
            if ((((1ULL << len) - 1ULL) << i) & white) continue;
            bool good;
            if (e == n) good = (j + 1 == k);
            else good = (!((black >> e) & 1ULL)) && (((B[e + 1] >> (j + 1)) & 1u) != 0);
            if (good) {
                diff[i]++;
                diff[e]--;
                if (e < n) canWhite |= 1ULL << e;
            }
        }
    }
    int acc = 0;
    for (int i = 0; i < n; ++i) {
        acc += diff[i];
        if (acc > 0) canBlack |= 1ULL << i;
    }
    canBlack |= black;
    canWhite |= white;

    const uint64_t forcedW = all & ~canBlack;
    const uint64_t forcedB = all & ~canWhite;
    if (forcedW & forcedB) return false;
    if ((forcedW & black) || (forcedB & white)) return false;
    outB = black | forcedB;
    outW = white | forcedW;
    return true;
}

// number of patterns completing a line (double, exact-ish)
static double countPatterns(const LineClue& L, uint64_t black, uint64_t white)
{
    const int n = L.n, k = L.k;
    if (k == 0) return (black & ((1ULL << n) - 1ULL)) ? 0.0 : 1.0;
    static const int D = MAXK;
    double G[MAXN + 1][MAXK];
    for (int i = 0; i <= n; ++i) memset(G[i], 0, sizeof(double) * (size_t)(k + 1));
    G[0][0] = 1.0;
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j <= k; ++j) {
            const double v = G[i][j];
            if (v == 0.0) continue;
            if (!((black >> i) & 1ULL)) G[i + 1][j] += v;
            if (j < k) {
                const int len = L.b[j], e = i + len;
                if (e <= n && !((((1ULL << len) - 1ULL) << i) & white)) {
                    if (e == n) { if (j + 1 == k) G[n][k] += v; }
                    else if (!((black >> e) & 1ULL)) G[e + 1][j + 1] += v;
                }
            }
        }
    }
    return G[n][k];
}

// Per-cell black counts for a line; fills bc[0..n-1] (number of patterns with
// that cell black).  total is the number of patterns.
static void cellStats(const LineClue& L, uint64_t black, uint64_t white,
                      double* bc, double& total)
{
    const int n = L.n, k = L.k;
    total = 0.0;
    for (int i = 0; i < n; ++i) bc[i] = 0.0;
    if (k == 0) { total = (black & ((1ULL << n) - 1ULL)) ? 0.0 : 1.0; return; }
    double G[MAXN + 1][MAXK], H[MAXN + 1][MAXK];
    for (int i = 0; i <= n; ++i) {
        memset(G[i], 0, sizeof(double) * (size_t)(k + 1));
        memset(H[i], 0, sizeof(double) * (size_t)(k + 1));
    }
    G[0][0] = 1.0;
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j <= k; ++j) {
            const double v = G[i][j];
            if (v == 0.0) continue;
            if (!((black >> i) & 1ULL)) G[i + 1][j] += v;
            if (j < k) {
                const int len = L.b[j], e = i + len;
                if (e <= n && !((((1ULL << len) - 1ULL) << i) & white)) {
                    if (e == n) { if (j + 1 == k) G[n][k] += v; }
                    else if (!((black >> e) & 1ULL)) G[e + 1][j + 1] += v;
                }
            }
        }
    }
    total = G[n][k];
    H[n][k] = 1.0;
    for (int i = n - 1; i >= 0; --i) {
        for (int j = k; j >= 0; --j) {
            double v = 0.0;
            if (!((black >> i) & 1ULL)) v += H[i + 1][j];
            if (j < k) {
                const int len = L.b[j], e = i + len;
                if (e <= n && !((((1ULL << len) - 1ULL) << i) & white)) {
                    if (e == n) { if (j + 1 == k) v += 1.0; }
                    else if (!((black >> e) & 1ULL)) v += H[e + 1][j + 1];
                }
            }
            H[i][j] = v;
        }
    }
    if (total <= 0.0) return;
    double diff[MAXN + 1];
    memset(diff, 0, sizeof(double) * (size_t)(n + 1));
    for (int i = 0; i < n; ++i) {
        if ((white >> i) & 1ULL) continue;
        {
            for (int j = 0; j < k; ++j) {
                const double g = G[i][j];
                if (g == 0.0) continue;
                const int len = L.b[j], e = i + len;
                if (e > n) continue;
                if ((((1ULL << len) - 1ULL) << i) & white) continue;
                double h = 0.0;
                if (e == n) { if (j + 1 == k) h = 1.0; }
                else if (!((black >> e) & 1ULL)) h = H[e + 1][j + 1];
                if (h > 0.0) {
                    const double v = g * h;
                    diff[i] += v;
                    diff[e] -= v;
                }
            }
        }
    }
    double acc = 0.0;
    for (int i = 0; i < n; ++i) { acc += diff[i]; bc[i] = acc; }
}

// ---------------------------------------------------------------------------
struct GridSolver {
    const Puzzle* pz;
    int h, w;
    uint64_t rB[MAXN], rW[MAXN], cB[MAXN], cW[MAXN];
    uint64_t rowAll, colAll;
    int q[512];
    int qh, qt;
    bool inQ[2][MAXN];

    void init(const Puzzle& p) {
        pz = &p;
        h = p.h; w = p.w;
        memset(rB, 0, sizeof(rB)); memset(rW, 0, sizeof(rW));
        memset(cB, 0, sizeof(cB)); memset(cW, 0, sizeof(cW));
        rowAll = (1ULL << w) - 1ULL;
        colAll = (1ULL << h) - 1ULL;
        qh = qt = 0;
        memset(inQ, 0, sizeof(inQ));
        for (int i = 0; i < h; ++i) pushRow(i);
        for (int i = 0; i < w; ++i) pushCol(i);
    }
    inline void pushRow(int i) { if (!inQ[0][i]) { inQ[0][i] = true; q[qt & 511] = i; ++qt; } }
    inline void pushCol(int i) { if (!inQ[1][i]) { inQ[1][i] = true; q[qt & 511] = 64 + i; ++qt; } }

    bool propagate() {
        while (qh != qt) {
            const int code = q[qh & 511];
            ++qh;
            const int idx = code & 63;
            if (code < 64) {
                inQ[0][idx] = false;
                uint64_t nb, nw;
                if (!lineSolve(pz->rows[idx], rB[idx], rW[idx], nb, nw)) return false;
                if (nb & nw) return false;
                uint64_t db = nb & ~rB[idx];
                uint64_t dw = nw & ~rW[idx];
                if (!db && !dw) continue;
                rB[idx] = nb; rW[idx] = nw;
                while (db) {
                    const int c = ctz64(db); db &= db - 1;
                    const uint64_t bit = 1ULL << idx;
                    cB[c] |= bit; cW[c] &= ~bit;
                    pushCol(c);
                }
                while (dw) {
                    const int c = ctz64(dw); dw &= dw - 1;
                    const uint64_t bit = 1ULL << idx;
                    cW[c] |= bit; cB[c] &= ~bit;
                    pushCol(c);
                }
            } else {
                inQ[1][idx] = false;
                uint64_t nb, nw;
                if (!lineSolve(pz->cols[idx], cB[idx], cW[idx], nb, nw)) return false;
                if (nb & nw) return false;
                uint64_t db = nb & ~cB[idx];
                uint64_t dw = nw & ~cW[idx];
                if (!db && !dw) continue;
                cB[idx] = nb; cW[idx] = nw;
                while (db) {
                    const int r = ctz64(db); db &= db - 1;
                    const uint64_t bit = 1ULL << idx;
                    rB[r] |= bit; rW[r] &= ~bit;
                    pushRow(r);
                }
                while (dw) {
                    const int r = ctz64(dw); dw &= dw - 1;
                    const uint64_t bit = 1ULL << idx;
                    rW[r] |= bit; rB[r] &= ~bit;
                    pushRow(r);
                }
            }
        }
        return true;
    }

    bool complete() const {
        for (int r = 0; r < h; ++r)
            if ((rB[r] | rW[r]) != rowAll) return false;
        return true;
    }

    void setCell(int r, int c, bool black) {
        const uint64_t bit = 1ULL << c;
        if (black) { rB[r] |= bit; rW[r] &= ~bit; }
        else { rW[r] |= bit; rB[r] &= ~bit; }
        const uint64_t rbit = 1ULL << r;
        if (black) { cB[c] |= rbit; cW[c] &= ~rbit; }
        else { cW[c] |= rbit; cB[c] &= ~rbit; }
        pushRow(r);
        pushCol(c);
    }
};

static thread_local long long g_nodes = 0;
static const long long g_nodeLimit = 250000;

static bool searchGrid(GridSolver& g, int depth)
{
    if (++g_nodes > g_nodeLimit) return false;
    if (g.complete()) return true;
    if (depth > 300) return false;

    const Puzzle& p = *g.pz;
    // choose the line with the fewest patterns
    double best = 1e300;
    int bestCol = -1, bestIdx = -1;
    for (int r = 0; r < g.h; ++r) {
        if ((g.rB[r] | g.rW[r]) == g.rowAll) continue;
        const double c = countPatterns(p.rows[r], g.rB[r], g.rW[r]);
        if (c < best) { best = c; bestCol = 0; bestIdx = r; }
        if (c == 0.0) return false;
    }
    for (int c = 0; c < g.w; ++c) {
        if ((g.cB[c] | g.cW[c]) == g.colAll) continue;
        const double c2 = countPatterns(p.cols[c], g.cB[c], g.cW[c]);
        if (c2 < best) { best = c2; bestCol = 1; bestIdx = c; }
        if (c2 == 0.0) return false;
    }
    if (bestIdx < 0) return false;

    // pick cell inside chosen line whose black probability is closest to 1/2
    static thread_local double bc[MAXN];
    double total = 0.0;
    int n = 0;
    uint64_t decidedMask = 0;
    uint64_t undecided = 0;
    uint64_t bm = 0, wm = 0;
    if (bestCol == 0) {
        n = g.w;
        cellStats(p.rows[bestIdx], g.rB[bestIdx], g.rW[bestIdx], bc, total);
        decidedMask = g.rB[bestIdx] | g.rW[bestIdx];
        bm = g.rB[bestIdx]; wm = g.rW[bestIdx];
    } else {
        n = g.h;
        cellStats(p.cols[bestIdx], g.cB[bestIdx], g.cW[bestIdx], bc, total);
        decidedMask = g.cB[bestIdx] | g.cW[bestIdx];
        bm = g.cB[bestIdx]; wm = g.cW[bestIdx];
    }
    if (total <= 0.0) return false;
    int pickCell = -1;
    double bestScore = 2.0;
    bool pickBlack = false;
    static int variant = -1;
    if (variant < 0) { const char* e = getenv("NONO_VAR"); variant = e ? atoi(e) : 0; }
    if (variant == 0) {
        for (int i = 0; i < n; ++i) {
            if ((decidedMask >> i) & 1ULL) continue;
            const double pr = bc[i] / total;
            const double sc = (pr > 0.5) ? pr : (1.0 - pr);
            if (sc < bestScore) { bestScore = sc; pickCell = i; pickBlack = (pr >= 0.5); }
        }
    } else if (variant == 1) {
        bestScore = -1.0;
        for (int i = 0; i < n; ++i) {
            if ((decidedMask >> i) & 1ULL) continue;
            const double pr = bc[i] / total;
            const double sc = (pr > 0.5) ? pr : (1.0 - pr);
            if (sc > bestScore) { bestScore = sc; pickCell = i; pickBlack = (pr >= 0.5); }
        }
    } else {
        bestScore = -1.0;
        for (int i = 0; i < n; ++i) {
            if ((decidedMask >> i) & 1ULL) continue;
            const double pr = bc[i] / total;
            const double sc = (pr > 0.5) ? pr : (1.0 - pr);
            if (sc >= 0.25 && sc > bestScore) { bestScore = sc; pickCell = i; pickBlack = (pr >= 0.5); }
        }
        if (pickCell < 0) {
            bestScore = 2.0;
            for (int i = 0; i < n; ++i) {
                if ((decidedMask >> i) & 1ULL) continue;
                const double pr = bc[i] / total;
                const double sc = (pr > 0.5) ? pr : (1.0 - pr);
                if (sc < bestScore) { bestScore = sc; pickCell = i; pickBlack = (pr >= 0.5); }
            }
        }
    }
    if (pickCell < 0) return false;

    const int rr = (bestCol == 0) ? bestIdx : pickCell;
    const int cc = (bestCol == 0) ? pickCell : bestIdx;

    GridSolver save = g;
    const bool order[2] = { pickBlack, !pickBlack };
    for (int t = 0; t < 2; ++t) {
        g.setCell(rr, cc, order[t]);
        if (g.propagate() && searchGrid(g, depth + 1)) return true;
        g = save;
    }
    return false;
}

static bool verifySolution(const Puzzle& p, const GridSolver& g)
{
    for (int r = 0; r < p.h; ++r) {
        uint64_t b = g.rB[r];
        if (!lineSolve(p.rows[r], b, ~b & ((1ULL << p.w) - 1ULL), b, b)) return false;
    }
    for (int c = 0; c < p.w; ++c) {
        uint64_t b = g.cB[c];
        if (!lineSolve(p.cols[c], b, ~b & ((1ULL << p.h) - 1ULL), b, b)) return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
static std::mutex g_qmtx;
static std::condition_variable g_qcv;
static std::deque<Puzzle> g_queue;
static bool g_done = false;
static std::mutex g_outmtx;

static void worker()
{
    for (;;) {
        Puzzle p;
        {
            std::unique_lock<std::mutex> lk(g_qmtx);
            g_qcv.wait(lk, [] { return !g_queue.empty() || g_done; });
            if (g_queue.empty()) {
                if (g_done) return;
                continue;
            }
            p = std::move(g_queue.front());
            g_queue.pop_front();
        }
        GridSolver gs;
        gs.init(p);
        g_nodes = 0;
        bool ok = false;
        bool propOk = false;
        std::string out;
        const auto t0 = std::chrono::steady_clock::now();
        if (gs.propagate()) {
            propOk = true;
            ok = searchGrid(gs, 0);
            if (ok && !verifySolution(p, gs)) ok = false;
        }
        const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
        if (getenv("NONO_DEBUG")) fprintf(stderr, "dbg %s propOk=%d ok=%d nodes=%lld ms=%.2f\n", p.id.c_str(), (int)propOk, (int)ok, g_nodes, ms);
        if (ok) {
            out.reserve(64 + (size_t)p.h * (size_t)(p.w + 1));
            out += "SOLUTION ";
            out += p.id;
            out += '\n';
            for (int r = 0; r < p.h; ++r) {
                for (int c = 0; c < p.w; ++c)
                    out += ((gs.rB[r] >> c) & 1ULL) ? '#' : '.';
                out += '\n';
            }
        } else {
            out += "UNSOLVED ";
            out += p.id;
            out += '\n';
        }
        {
            std::lock_guard<std::mutex> lk(g_outmtx);
            fwrite(out.data(), 1, out.size(), stdout);
            fflush(stdout);
        }
    }
}

static void parseClue(const std::string& line, LineClue& L, int n)
{
    L.n = n;
    L.k = 0;
    const char* s = line.c_str();
    while (*s) {
        while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') ++s;
        if (!*s) break;
        char* endp = nullptr;
        const long v = strtol(s, &endp, 10);
        if (endp == s) break;
        s = endp;
        if (v > 0 && L.k < MAXK) L.b[L.k++] = (int)v;
    }
}

int main()
{
    std::vector<std::thread> threads;
    for (int t = 0; t < 2; ++t) threads.emplace_back(worker);

    std::string line;
    bool eof = false;
    while (!eof) {
        if (!std::getline(std::cin, line)) break;
        while (!line.empty() && (line.back() == '\r' || line.back() == '\n')) line.pop_back();
        if (line.size() < 7 || line.compare(0, 7, "PUZZLE ") != 0) continue;
        Puzzle p;
        {
            const char* s = line.c_str() + 7;
            while (*s == ' ') ++s;
            const char* start = s;
            while (*s && *s != ' ') ++s;
            p.id.assign(start, (size_t)(s - start));
            char* endp = nullptr;
            p.h = (int)strtol(s, &endp, 10); s = endp;
            p.w = (int)strtol(s, &endp, 10);
            if (p.h <= 0 || p.w <= 0 || p.h > MAXN || p.w > MAXN) continue;
        }
        for (int i = 0; i < p.h; ++i) {
            if (!std::getline(std::cin, line)) { eof = true; break; }
            parseClue(line, p.rows[i], p.w);
        }
        if (eof) break;
        for (int i = 0; i < p.w; ++i) {
            if (!std::getline(std::cin, line)) { eof = true; break; }
            parseClue(line, p.cols[i], p.h);
        }
        if (eof) break;
        if (getenv("NONO_DEBUG")) {
            fprintf(stderr, "puzzle %s %dx%d rows:", p.id.c_str(), p.h, p.w);
            for (int i = 0; i < p.h; ++i) { fprintf(stderr, " ["); for (int j = 0; j < p.rows[i].k; ++j) fprintf(stderr, "%d ", p.rows[i].b[j]); fprintf(stderr, "]"); }
            fprintf(stderr, " cols:");
            for (int i = 0; i < p.w; ++i) { fprintf(stderr, " ["); for (int j = 0; j < p.cols[i].k; ++j) fprintf(stderr, "%d ", p.cols[i].b[j]); fprintf(stderr, "]"); }
            fprintf(stderr, "\n");
        }
        {
            std::lock_guard<std::mutex> lk(g_qmtx);
            g_queue.push_back(std::move(p));
        }
        g_qcv.notify_one();
    }

    {
        std::lock_guard<std::mutex> lk(g_qmtx);
        g_done = true;
    }
    g_qcv.notify_all();
    for (auto& t : threads) t.join();
    return 0;
}




