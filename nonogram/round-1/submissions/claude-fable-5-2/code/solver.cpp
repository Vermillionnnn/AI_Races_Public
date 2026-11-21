// Nonogram speed solver: bit-parallel line solver + propagation + probing + DFS, 2 worker threads.
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

// s must be propagated, consistent and unsolved. 1 = solved (s holds solution), 0 = contradiction
static int search(const Puzzle& p, State& s, std::vector<Rec>& rec, int depth) {
    State a, b;
    const int w = p.w;
    std::vector<int> ord, sorted;
    std::vector<unsigned char> key;
    for (;;) {
        bool progress = false;
        // visit order: cells with more known neighbours first
        int cnt[5] = {0, 0, 0, 0, 0};
        ord.clear(); key.clear();
        for (int r = 0; r < p.h; r++) {
            const u64 kn = s.rB[r] | s.rW[r];
            const u64 up = r > 0 ? (s.rB[r - 1] | s.rW[r - 1]) : ~0ULL;
            const u64 dn = r + 1 < p.h ? (s.rB[r + 1] | s.rW[r + 1]) : ~0ULL;
            const u64 lf = (kn << 1) | 1, rt = (kn >> 1) | (1ULL << (w - 1));
            u64 unk = p.rows[r].full & ~kn;
            while (unk) {
                int c = std::countr_zero(unk);
                unk &= unk - 1;
                if (rec[r * w + c].valid) continue;
                int nk = (int)((up >> c) & 1) + (int)((dn >> c) & 1) + (int)((lf >> c) & 1) + (int)((rt >> c) & 1);
                ord.push_back(r * w + c); key.push_back((unsigned char)nk); cnt[nk]++;
            }
        }
        int pos[5]; pos[4] = 0; pos[3] = cnt[4]; pos[2] = pos[3] + cnt[3]; pos[1] = pos[2] + cnt[2]; pos[0] = pos[1] + cnt[1];
        sorted.resize(ord.size());
        for (size_t i = 0; i < ord.size(); i++) sorted[pos[key[i]]++] = ord[i];
        {
            int nprog = 0;  // after 16 changes the order is stale: start a new pass
            for (size_t oi = 0; oi < sorted.size() && nprog < 16; oi++) {
                const int r = sorted[oi] / w, c = sorted[oi] % w;
                if (((s.rB[r] | s.rW[r]) >> c) & 1) continue;
                Rec& rc = rec[r * w + c];
                if (rc.valid) continue;
                const int qa = quickProbe(p, s, r, c, 1);
                bool oka = qa != 0;
                if (qa == 2) {
                    copyState(p, a, s); setCell(a, r, c, 1);
                    oka = propagate(p, a);
                    if (oka && a.unknown == 0) { copyState(p, s, a); return 1; }
                }
                if (!oka) {
                    s.xr = s.xc = 0;
                    setCell(s, r, c, 0);
                    if (!propagate(p, s)) return 0;
                    if (s.unknown == 0) return 1;
                    invalidate(rec, s.xr, s.xc);
                    progress = true; nprog++; continue;
                }
                const int qb = quickProbe(p, s, r, c, 0);
                bool okb = qb != 0;
                if (qb == 2) {
                    copyState(p, b, s); setCell(b, r, c, 0);
                    okb = propagate(p, b);
                    if (okb && b.unknown == 0) { copyState(p, s, b); return 1; }
                }
                if (!okb) {
                    s.xr = s.xc = 0;
                    setCell(s, r, c, 1);
                    if (!propagate(p, s)) return 0;
                    if (s.unknown == 0) return 1;
                    invalidate(rec, s.xr, s.xc);
                    progress = true; nprog++; continue;
                }
                // merge common deductions
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
                    if (!propagate(p, s)) return 0;
                    if (s.unknown == 0) return 1;
                    invalidate(rec, s.xr, s.xc);
                    progress = true; nprog++;
                    continue;
                }
                int da = 1, db = 1;
                rc.tr = 1ULL << r; rc.tc = 1ULL << c;
                if (qa == 2) { da = s.unknown - a.unknown; rc.tr |= a.tr; rc.tc |= a.tc; }
                if (qb == 2) { db = s.unknown - b.unknown; rc.tr |= b.tr; rc.tc |= b.tc; }
                rc.score = (da + 1) * (db + 1);
                rc.valid = 1;
            }
        }
        if (!progress) break;
    }
    int bestR = -1, bestC = -1, bestScore = -1;
    for (int r = 0; r < p.h; r++) {
        u64 unk = p.rows[r].full & ~(s.rB[r] | s.rW[r]);
        while (unk) {
            int c = std::countr_zero(unk);
            unk &= unk - 1;
            const Rec& rc = rec[r * w + c];
            if (rc.score > bestScore) { bestScore = rc.score; bestR = r; bestC = c; }
        }
    }
    if (bestScore < 0) return 0;
    {
        copyState(p, a, s); setCell(a, bestR, bestC, 1);
        if (propagate(p, a)) {
            if (a.unknown == 0) { copyState(p, s, a); return 1; }
            std::vector<Rec> rec2(rec);
            invalidate(rec2, a.xr, a.xc);
            if (search(p, a, rec2, depth + 1)) { copyState(p, s, a); return 1; }
        }
    }
    s.xr = s.xc = 0;
    setCell(s, bestR, bestC, 0);
    if (!propagate(p, s)) return 0;
    if (s.unknown == 0) return 1;
    invalidate(rec, s.xr, s.xc);
    return search(p, s, rec, depth + 1);
}

static int solveRec(const Puzzle& p, State& s, int depth) {
    if (!propagate(p, s)) return 0;
    if (s.unknown == 0) return 1;
    std::vector<Rec> rec((size_t)p.h * p.w, Rec{0, 0, 0, 0});
    return search(p, s, rec, depth);
}

static bool verify(const Puzzle& p, const State& s) {
    for (int r = 0; r < p.h; r++) {
        const Line& ln = p.rows[r];
        u64 x = s.rB[r]; int j = 0;
        while (x) {
            int st = std::countr_zero(x);
            int L = std::countr_one(x >> st);
            if (j >= ln.k || ln.len[j] != L) return false;
            j++;
            x = (x >> st >> L) << st << L;
        }
        if (j != ln.k) return false;
    }
    for (int c = 0; c < p.w; c++) {
        const Line& ln = p.cols[c];
        u64 x = 0;
        for (int r = 0; r < p.h; r++) x |= ((s.rB[r] >> c) & 1) << r;
        int j = 0;
        while (x) {
            int st = std::countr_zero(x);
            int L = std::countr_one(x >> st);
            if (j >= ln.k || ln.len[j] != L) return false;
            j++;
            x = (x >> st >> L) << st << L;
        }
        if (j != ln.k) return false;
    }
    return true;
}

static std::mutex outMu;

static void solvePuzzle(Puzzle& p, CEnt* cache, u64 gen) {
    p.cache = cache; p.kbase = gen << 8;
    std::string out;
    bool ok = false;
    static thread_local State s;
    if (p.h >= 1 && p.w >= 1 && p.h <= 62 && p.w <= 62) {
        memset(&s, 0, sizeof(s));
        s.dr = (p.h == 64) ? ~0ULL : ((1ULL << p.h) - 1);
        s.dc = (1ULL << p.w) - 1;
        s.unknown = p.h * p.w;
        ok = solveRec(p, s, 0) == 1 && s.unknown == 0 && verify(p, s);
    }
    if (ok) {
        out.reserve(p.id.size() + 16 + (size_t)p.h * (p.w + 1));
        out += "SOLUTION "; out += p.id; out += '\n';
        for (int r = 0; r < p.h; r++) {
            u64 x = s.rB[r];
            for (int c = 0; c < p.w; c++) out += ((x >> c) & 1) ? '#' : '.';
            out += '\n';
        }
    } else {
        out = "UNSOLVED " + p.id + "\n";
    }
    std::lock_guard<std::mutex> lk(outMu);
    fwrite(out.data(), 1, out.size(), stdout);
    fflush(stdout);
}

static std::mutex qMu;
static std::condition_variable qCv;
static std::deque<Puzzle*> q;
static bool inputDone = false;

static void worker() {
    CEnt* cache = (CEnt*)calloc((size_t)1 << CBITS, sizeof(CEnt));
    u64 gen = 0;
    if (!cache) return;
    for (;;) {
        Puzzle* p;
        {
            std::unique_lock<std::mutex> lk(qMu);
            qCv.wait(lk, [] { return !q.empty() || inputDone; });
            if (q.empty()) return;
            p = q.front(); q.pop_front();
        }
        solvePuzzle(*p, cache, ++gen);
        delete p;
    }
}

static bool parseClue(const char* buf, Line& ln, int n) {
    ln.n = n; ln.k = 0;
    ln.full = (n >= 64) ? ~0ULL : ((1ULL << n) - 1);
    const char* q2 = buf;
    int sum = 0;
    for (;;) {
        while (*q2 == ' ' || *q2 == '\t' || *q2 == '\r' || *q2 == '\n') q2++;
        if (!*q2) break;
        if (*q2 < '0' || *q2 > '9') return false;
        int v = 0;
        while (*q2 >= '0' && *q2 <= '9') { v = v * 10 + (*q2 - '0'); q2++; if (v > 1000) return false; }
        if (v > 0) {
            if (ln.k >= MAXK - 1) return false;
            ln.len[ln.k++] = v; sum += v;
        }
    }
    if (sum + ln.k - 1 > n) return false;
    ln.maxL = 0;
    for (int i = 0; i < ln.k; i++) {
        ln.rlen[i] = ln.len[ln.k - 1 - i];
        if (ln.len[i] > ln.maxL) ln.maxL = ln.len[i];
    }
    return true;
}

int main() {
    static char buf[1 << 16];
    std::thread t1(worker), t2(worker);
    bool have = fgets(buf, sizeof(buf), stdin) != nullptr;
    while (have) {
        if (strncmp(buf, "PUZZLE ", 7) != 0) { have = fgets(buf, sizeof(buf), stdin) != nullptr; continue; }
        char idb[4096]; int h = 0, w = 0;
        if (sscanf(buf + 7, "%4000s %d %d", idb, &h, &w) < 1) { have = fgets(buf, sizeof(buf), stdin) != nullptr; continue; }
        Puzzle* p = new Puzzle();
        p->id = idb; p->h = h; p->w = w;
        bool good = (h >= 1 && w >= 1 && h <= 62 && w <= 62);
        int total = (h > 0 ? h : 0) + (w > 0 ? w : 0);
        int i = 0;
        have = false;
        bool nextHeader = false;
        for (; i < total; i++) {
            if (!fgets(buf, sizeof(buf), stdin)) break;
            if (strncmp(buf, "PUZZLE ", 7) == 0) { nextHeader = true; break; }
            if (good) {
                if (i < h) { if (!parseClue(buf, p->rows[i], w)) good = false; }
                else { if (!parseClue(buf, p->cols[i - h], h)) good = false; }
            }
        }
        if (i < total) good = false;
        if (!good) { p->h = 0; p->w = 0; }
        {
            std::lock_guard<std::mutex> lk(qMu);
            q.push_back(p);
        }
        qCv.notify_one();
        if (nextHeader) have = true;
        else have = fgets(buf, sizeof(buf), stdin) != nullptr;
    }
    {
        std::lock_guard<std::mutex> lk(qMu);
        inputDone = true;
    }
    qCv.notify_all();
    t1.join(); t2.join();
    return 0;
}
