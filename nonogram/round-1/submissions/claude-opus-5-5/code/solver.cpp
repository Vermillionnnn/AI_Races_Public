// Nonogram solver: bit-parallel line DP + queue propagation + probing + DFS.
// Single source file, standard library only. Two worker threads solve puzzles in parallel.
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

    inline bool cachedLine(int i, u64 b, u64 wm, u64& nb, u64& nw) {
        u64 kw = wm | ((u64)i << 56);
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

    // s is propagated. returns true if solution found (stored in sol).
    bool dfs(State& s) {
        if (s.unknown == 0) { sol = s; found = true; return true; }
        State t1, t0;
        u64 okB[MAXN], okW[MAXN];
        int bestR = -1, bestC = -1; long long bestScore = -1; bool bestFirstBlack = true;
        bool full = false;
        for (;;) {
            bool changed = false;
            bestR = -1; bestScore = -1;
            memset(okB, 0, sizeof(u64) * h);
            memset(okW, 0, sizeof(u64) * h);
            for (int r = 0; r < h; r++) {
                u64 unk = ~(s.B[r] | s.W[r]) & rowMask;
                while (unk) {
                    int c = ctz64(unk); unk &= unk - 1;
                    if ((s.B[r] | s.W[r]) >> c & 1) continue;
                    bool skB = !full && (okB[r] >> c & 1), skW = !full && (okW[r] >> c & 1);
                    if (skB && skW) continue;
                    probes++;
                    if (shouldStop()) { aborted = true; return false; }
                    bool ok1 = true, ok0 = true;
                    if (!skB) {
                        cp(t1, s); ok1 = assignProp(t1, r, c, true);
                        if (ok1) {
                            if (t1.unknown == 0) { sol = t1; found = true; return true; }
                            for (int i = 0; i < h; i++) { okB[i] |= t1.B[i] & ~s.B[i]; okW[i] |= t1.W[i] & ~s.W[i]; }
                        }
                    }
                    if (!skW) {
                        cp(t0, s); ok0 = assignProp(t0, r, c, false);
                        if (ok0) {
                            if (t0.unknown == 0) { sol = t0; found = true; return true; }
                            for (int i = 0; i < h; i++) { okB[i] |= t0.B[i] & ~s.B[i]; okW[i] |= t0.W[i] & ~s.W[i]; }
                        }
                    }
                    if (!ok1 && !ok0) return false;
                    if (!ok1) {
                        if (skW) { cp(t0, s); if (!assignProp(t0, r, c, false)) return false; }
                        cp(s, t0); changed = true; unk &= ~(s.B[r] | s.W[r]);
                        if (s.unknown == 0) { sol = s; found = true; return true; }
                        continue;
                    }
                    if (!ok0) {
                        if (skB) { cp(t1, s); if (!assignProp(t1, r, c, true)) return false; }
                        cp(s, t1); changed = true; unk &= ~(s.B[r] | s.W[r]);
                        if (s.unknown == 0) { sol = s; found = true; return true; }
                        continue;
                    }
                    if (skB || skW) continue;
                    // intersection of both outcomes
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
                        if (!propagate(s, dirty, nd)) return false; // should not happen
                        if (s.unknown == 0) { sol = s; found = true; return true; }
                        changed = true;
                        unk &= ~(s.B[r] | s.W[r]);
                    }
                    long long g1 = s.unknown - t1.unknown, g0 = s.unknown - t0.unknown;
#ifndef SCOREMODE
#define SCOREMODE 0
#endif
#if SCOREMODE == 0
                    long long score = (g1 + 1) * (g0 + 1);
#elif SCOREMODE == 1
                    long long score = (g1 < g0 ? g1 : g0) * 4096 + (g1 > g0 ? g1 : g0);
#else
                    long long score = g1 + g0;
#endif
                    if (score > bestScore) { bestScore = score; bestR = r; bestC = c; bestFirstBlack = g1 < g0; }
                }
            }
            if (!changed) {
                if (full || SKIPMODE == 0) break;
                full = true;
            } else if (SKIPMODE == 0) full = true; else full = false;
        }
        if (bestR < 0) return false;
        guesses++;
        for (int pass = 0; pass < 2; pass++) {
            bool v = ((pass == 0) ? bestFirstBlack : !bestFirstBlack) ^ flip;
            State t; cp(t, s);
            if (assignProp(t, bestR, bestC, v)) {
                if (dfs(t)) return true;
                if (aborted) return false;
            }
        }
        return false;
    }

    bool solve() {
        State s;
        memset(&s, 0, sizeof(s));
        s.unknown = h * w;
        int dirty[MAXL];
        for (int i = 0; i < nl; i++) dirty[i] = i;
        if (!propagate(s, dirty, nl)) return false;
        return dfs(s);
    }

    bool verify() const {
        for (int i = 0; i < nl; i++) {
            const Line& ln = lines[i];
            u64 m = sol.B[i];
            int j = 0;
            for (int p = 0; p < ln.n;) {
                if (m >> p & 1) {
                    int q2 = p; while (q2 < ln.n && (m >> q2 & 1)) q2++;
                    if (j >= ln.k || ln.c[j] != q2 - p) return false;
                    j++; p = q2;
                } else p++;
            }
            if (j != ln.k) return false;
            u64 full = (ln.n >= 64) ? ~0ULL : ((1ULL << ln.n) - 1);
            if ((sol.B[i] | sol.W[i]) != full) return false;
            if (sol.B[i] & sol.W[i]) return false;
        }
        return true;
    }
};

struct Puzzle {
    std::string id;
    int h, w;
    std::vector<std::vector<int>> clues;
    bool bad = false;
};

struct Job {
    Puzzle* p;
    std::atomic<bool> done{false};
    bool helped = false;
    ~Job() { delete p; }
};

static std::mutex qmu, outmu;
static std::condition_variable qcv;
static std::deque<std::shared_ptr<Job>> pq;
static std::vector<std::shared_ptr<Job>> active;
static std::atomic<int> queued{0};
static bool inputDone = false;

static void emit(const std::string& s) {
    std::lock_guard<std::mutex> lk(outmu);
    fwrite(s.data(), 1, s.size(), stdout);
    fflush(stdout);
}

static std::shared_ptr<Job> findHelpable() {
    for (auto& j : active) if (!j->helped && !j->done.load()) return j;
    return nullptr;
}

static void worker() {
    Solver* S = new Solver();
    for (;;) {
        std::shared_ptr<Job> job; bool helper = false;
        {
            std::unique_lock<std::mutex> lk(qmu);
            qcv.wait(lk, [] { return !pq.empty() || inputDone || findHelpable() != nullptr; });
            if (!pq.empty()) {
                job = pq.front(); pq.pop_front(); queued--;
                active.push_back(job);
            } else if ((job = findHelpable()) != nullptr) {
                job->helped = true; helper = true;
            } else break;
        }
        qcv.notify_all();
        Puzzle* p = job->p;
        bool ok = false, definitive = true;
        if (!p->bad && p->h > 0 && p->w > 0 && p->h <= MAXN && p->w <= MAXN) {
            S->found = false; S->aborted = false;
            S->flip = helper;
            S->stopA = &job->done;
            S->stopQ = helper ? &queued : nullptr;
            S->init(p->h, p->w, p->clues);
            S->lineCalls = S->probes = S->guesses = S->hits = 0;
            bool r = S->solve();
            if (S->aborted) definitive = false;
            ok = r && S->found && S->verify();
            if (getenv("NGSTATS")) fprintf(stderr, "%s helper=%d aborted=%d lines=%lld hits=%lld probes=%lld guesses=%lld\n", p->id.c_str(), (int)helper, (int)S->aborted, S->lineCalls, S->hits, S->probes, S->guesses);
        }
        if (definitive && !job->done.exchange(true)) {
            std::string out;
            if (ok) {
                out.reserve((p->w + 1) * p->h + 64);
                out += "SOLUTION "; out += p->id; out += '\n';
                for (int r = 0; r < p->h; r++) {
                    for (int c = 0; c < p->w; c++) out += (S->sol.B[r] >> c & 1) ? '#' : '.';
                    out += '\n';
                }
            } else {
                out = "UNSOLVED " + p->id + "\n";
            }
            emit(out);
        }
        {
            std::lock_guard<std::mutex> lk(qmu);
            if (helper) { if (!job->done.load()) job->helped = false; }
            else {
                for (size_t i = 0; i < active.size(); i++) if (active[i] == job) { active.erase(active.begin() + i); break; }
            }
        }
        qcv.notify_all();
    }
    delete S;
}

static bool readLine(std::string& s) {
    s.clear();
    char buf[4096];
    for (;;) {
        if (!fgets(buf, sizeof(buf), stdin)) return !s.empty();
        s += buf;
        if (!s.empty() && s.back() == '\n') break;
    }
    while (!s.empty() && (s.back() == '\n' || s.back() == '\r' || s.back() == ' ' || s.back() == '\t')) s.pop_back();
    return true;
}

static std::vector<int> parseInts(const std::string& s) {
    std::vector<int> v;
    const char* p = s.c_str();
    while (*p) {
        while (*p == ' ' || *p == '\t') p++;
        if (!*p) break;
        char* e;
        long x = strtol(p, &e, 10);
        if (e == p) { p++; continue; }
        v.push_back((int)x);
        p = e;
    }
    return v;
}

int main() {
    unsigned nthreads = 2;
    std::vector<std::thread> th;
    for (unsigned i = 0; i < nthreads; i++) th.emplace_back(worker);
    std::string line;
    while (readLine(line)) {
        if (line.compare(0, 7, "PUZZLE ") != 0) continue;
        Puzzle* p = new Puzzle();
        std::shared_ptr<Job> job = std::make_shared<Job>(); job->p = p;
        char idbuf[1024]; int h = 0, w = 0;
        if (sscanf(line.c_str() + 7, "%1023s %d %d", idbuf, &h, &w) < 3) { p->bad = true; }
        p->id = idbuf; p->h = h; p->w = w;
        int nlines = h + w;
        if (nlines < 0 || nlines > 4 * MAXN + 1000000) nlines = 0;
        for (int i = 0; i < nlines; i++) {
            std::string cl;
            if (!readLine(cl)) { p->bad = true; break; }
            p->clues.push_back(parseInts(cl));
        }
        {
            std::lock_guard<std::mutex> lk(qmu);
            pq.push_back(job);
            queued++;
        }
        qcv.notify_one();
    }
    {
        std::lock_guard<std::mutex> lk(qmu);
        inputDone = true;
    }
    qcv.notify_all();
    for (auto& t : th) t.join();
    return 0;
}
