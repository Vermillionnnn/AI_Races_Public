// Nonogram speed solver — single file, C++20, standard library only.
// Build: g++ -O2 -std=c++20 solver.cpp -o solver.exe
// Run:   solver.exe  (reads puzzles from stdin, writes answers to stdout)
//
// Algorithm:
//  * Each line (row/col) is solved with a bit-parallel DP that computes the
//    intersection of ALL completions consistent with the clues and the known
//    cells, in O(n*k) time using uint64 masks (n <= 63).
//  * Constraint propagation with a dirty-line queue.
//  * When propagation stalls, branch on a cell of the most constrained line
//    (smallest slack), trying black first; full state restore on backtrack.
//  * Two worker threads solve puzzles in parallel; the main thread parses
//    stdin incrementally so solving starts before EOF. Each answer is written
//    as one contiguous block and flushed immediately.

#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <chrono>
#include <bit>

using u64 = uint64_t;
static const int MAXN = 64;      // supports lines up to 63 cells
static const int MAXK = 32;      // max blocks per line for n <= 63
static const int MAXL = 2 * MAXN;

struct Line {
    int cl[MAXK];
    int k = 0;
    int sum = 0;
    int slack = 0;               // n - sum - (k-1), filled at parse time
};

struct Puzzle {
    char id[128];
    int h = 0, w = 0;
    Line rows[MAXN], cols[MAXN];
};

// ---------------- fast incremental stdin reader ----------------
struct Reader {
    static const int SZ = 1 << 16;
    char buf[SZ];
    int p = 0, n = 0;
    int gc() {
        if (p == n) {
            n = (int)fread(buf, 1, SZ, stdin);
            p = 0;
            if (n <= 0) return -1;
        }
        return (unsigned char)buf[p++];
    }
    // one line without trailing \r\n; false at EOF with no content
    bool line(std::string& s) {
        s.clear();
        int c;
        while ((c = gc()) != -1) {
            if (c == '\n') break;
            if (c != '\r') s.push_back((char)c);
        }
        return c != -1 || !s.empty();
    }
};

static void parseClues(const std::string& s, Line& ln, int n) {
    ln.k = 0; ln.sum = 0;
    const char* p = s.c_str();
    while (*p) {
        while (*p == ' ' || *p == '\t') ++p;
        if (!*p) break;
        int v = (int)strtol(p, (char**)&p, 10);
        if (v > 0) { ln.cl[ln.k++] = v; ln.sum += v; }
    }
    ln.slack = n - ln.sum - (ln.k > 0 ? ln.k - 1 : 0);
}

static bool parsePuzzle(Reader& rd, Puzzle& pz) {
    std::string s;
    for (;;) {
        if (!rd.line(s)) return false;
        if (s.compare(0, 6, "PUZZLE") == 0) break;
    }
    int h, w;
    if (sscanf(s.c_str(), "PUZZLE %127s %d %d", pz.id, &h, &w) != 3) return false;
    if (h < 1 || w < 1 || h >= MAXN || w >= MAXN) return false;
    pz.h = h; pz.w = w;
    for (int r = 0; r < h; ++r) { rd.line(s); parseClues(s, pz.rows[r], w); }
    for (int c = 0; c < w; ++c) { rd.line(s); parseClues(s, pz.cols[c], h); }
    return true;
}

// ---------------- line solver ----------------
// rm[d] = mask of positions starting a run of (1<<d) consecutive non-black cells
static inline void buildRuns(u64 A, u64 rm[6]) {
    rm[0] = A;
    rm[1] = rm[0] & (rm[0] >> 1);
    rm[2] = rm[1] & (rm[1] >> 2);
    rm[3] = rm[2] & (rm[2] >> 4);
    rm[4] = rm[3] & (rm[3] >> 8);
    rm[5] = rm[4] & (rm[4] >> 16);
}
// extend set of positions rightward through non-black cells (doubling)
static inline u64 closeF(u64 x, const u64 rm[6], u64 posMask) {
    x |= (x & rm[0]) << 1;
    x |= (x & rm[1]) << 2;
    x |= (x & rm[2]) << 4;
    x |= (x & rm[3]) << 8;
    x |= (x & rm[4]) << 16;
    x |= (x & rm[5]) << 32;
    return x & posMask;
}
// extend leftward
static inline u64 closeB(u64 x, const u64 rm[6], u64 posMask) {
    x |= (x >> 1) & rm[0];
    x |= (x >> 2) & rm[1];
    x |= (x >> 4) & rm[2];
    x |= (x >> 8) & rm[3];
    x |= (x >> 16) & rm[4];
    x |= (x >> 32) & rm[5];
    return x & posMask;
}

struct Solver {
    const Puzzle* pz;
    int h, w;
    u64 RB[MAXN], RW[MAXN], CB[MAXN], CW[MAXN];
    u64 rowFull, colFull;
    int q[256]; int qh = 0, qt = 0;   // ring buffer; inq caps pending at MAXL < 256
    bool inq[MAXL];
    long long nlines = 0, guesses = 0, backtracks = 0;
    bool gaveUp = false;

    void init(const Puzzle* p) {
        pz = p; h = p->h; w = p->w;
        rowFull = (w == 64) ? ~0ULL : ((1ULL << w) - 1);
        colFull = (h == 64) ? ~0ULL : ((1ULL << h) - 1);
        for (int r = 0; r < h; ++r) { RB[r] = 0; RW[r] = 0; }
        for (int c = 0; c < w; ++c) { CB[c] = 0; CW[c] = 0; }
        qh = qt = 0;
        memset(inq, 0, sizeof(inq));
        for (int i = 0; i < h + w; ++i) enqueue(i);
    }

    inline void enqueue(int idx) {
        if (!inq[idx]) { inq[idx] = true; q[qt++ & 255] = idx; }
    }

    // Solve one line fully; update perpendicular lines. false = contradiction.
    bool solveLine(int idx) {
        ++nlines;
        const Line* ln;
        int n;
        u64 B, W, full;
        bool isRow = idx < h;
        if (isRow) { ln = &pz->rows[idx]; n = w; B = RB[idx]; W = RW[idx]; full = rowFull; }
        else { int c = idx - h; ln = &pz->cols[c]; n = h; B = CB[c]; W = CW[c]; full = colFull; }
        if ((B | W) == full) return true;

        const u64 posMask = full | (1ULL << n);
        const u64 A = ~B & full;
        u64 rm[6];
        buildRuns(A, rm);
        const int k = ln->k;
        u64 preW[MAXK + 1], preB[MAXK + 1], sufW[MAXK + 1], sufB[MAXK + 1], vs[MAXK];

        // forward DP
        preB[0] = 0;
        preW[0] = closeF(1, rm, posMask);
        for (int j = 0; j < k; ++j) {
            int b = ln->cl[j];
            u64 bm = (1ULL << b) - 1;
            u64 starts = preW[j], valid = 0;
            while (starts) {
                int s = std::countr_zero(starts);
                starts &= starts - 1;
                if (!((W >> s) & bm)) valid |= 1ULL << s;
            }
            vs[j] = valid;
            preB[j + 1] = (valid << b) & posMask;
            // white-ended prefixes: first white cell after the block must be free
            preW[j + 1] = closeF((preB[j + 1] & A) << 1, rm, posMask);
        }
        if (!((preW[k] | preB[k]) & (1ULL << n))) return false;

        // backward DP
        sufB[k] = 0;
        sufW[k] = closeB(1ULL << n, rm, posMask);
        for (int j = k - 1; j >= 0; --j) {
            int b = ln->cl[j];
            u64 bm = (1ULL << b) - 1;
            u64 ts = sufW[j + 1], valid = 0;
            while (ts) {
                int t = std::countr_zero(ts);
                ts &= ts - 1;
                int s = t - b;
                if (s >= 0 && !((W >> s) & bm)) valid |= 1ULL << s;
            }
            sufB[j] = valid;
            sufW[j] = closeB((sufB[j] >> 1) & A, rm, posMask);
        }

        // cells that can be white / black in some completion
        u64 wp = 0;
        for (int j = 0; j <= k; ++j) wp |= (preW[j] | preB[j]) & sufW[j];
        wp &= full;
        u64 bp = 0;
        for (int j = 0; j < k; ++j) {
            int b = ln->cl[j];
            u64 bm = (1ULL << b) - 1;
            u64 starts = vs[j] & (sufW[j + 1] >> b);
            while (starts) {
                int s = std::countr_zero(starts);
                starts &= starts - 1;
                bp |= bm << s;
            }
        }
        bp &= full;

        u64 newB = full & ~wp;
        u64 newW = full & ~bp;
        if ((newB & W) || (newW & B)) return false;
        u64 dB = newB & ~B, dW = newW & ~W;
        if (!(dB | dW)) return true;

        if (isRow) {
            int r = idx;
            RB[r] |= dB; RW[r] |= dW;
            u64 d = dB | dW;
            while (d) {
                int c = std::countr_zero(d);
                d &= d - 1;
                u64 bit = 1ULL << r;
                if (dB & (1ULL << c)) { CB[c] |= bit; CW[c] &= ~bit; }
                else { CW[c] |= bit; CB[c] &= ~bit; }
                enqueue(h + c);
            }
        } else {
            int c = idx - h;
            CB[c] |= dB; CW[c] |= dW;
            u64 d = dB | dW;
            while (d) {
                int r = std::countr_zero(d);
                d &= d - 1;
                u64 bit = 1ULL << c;
                if (dB & (1ULL << r)) { RB[r] |= bit; RW[r] &= ~bit; }
                else { RW[r] |= bit; RB[r] &= ~bit; }
                enqueue(r);
            }
        }
        return true;
    }

    bool propagate() {
        while (qh != qt) {
            int idx = q[qh++ & 255];
            inq[idx] = false;
            if (!solveLine(idx)) return false;
        }
        qh = qt = 0;
        return true;
    }

    // pick branch cell: unknown cell in the line with smallest slack,
    // preferring cells adjacent to known cells
    bool pickCell(int& br, int& bc) {
        int bestSlack = 1 << 30, bestIdx = -1;
        for (int r = 0; r < h; ++r) {
            u64 unk = rowFull & ~(RB[r] | RW[r]);
            if (unk && pz->rows[r].slack < bestSlack) { bestSlack = pz->rows[r].slack; bestIdx = r; }
        }
        for (int c = 0; c < w; ++c) {
            u64 unk = colFull & ~(CB[c] | CW[c]);
            if (unk && pz->cols[c].slack < bestSlack) { bestSlack = pz->cols[c].slack; bestIdx = h + c; }
        }
        if (bestIdx < 0) return false;
        u64 B, W, unk;
        int n;
        bool isRow = bestIdx < h;
        if (isRow) { B = RB[bestIdx]; W = RW[bestIdx]; unk = rowFull & ~(B | W); n = w; }
        else { int c = bestIdx - h; B = CB[c]; W = CW[c]; unk = colFull & ~(B | W); n = h; }
        int bestScore = -1, bestPos = -1;
        u64 d = unk;
        while (d) {
            int p = std::countr_zero(d);
            d &= d - 1;
            int score = 0;
            if (p > 0 && ((B | W) & (1ULL << (p - 1)))) ++score;
            if (p + 1 < n && ((B | W) & (1ULL << (p + 1)))) ++score;
            if (score > bestScore) { bestScore = score; bestPos = p; }
        }
        if (isRow) { br = bestIdx; bc = bestPos; }
        else { br = bestPos; bc = bestIdx - h; }
        return true;
    }

    void setCell(int r, int c, bool black) {
        u64 rb = 1ULL << c, cb = 1ULL << r;
        if (black) { RB[r] |= rb; RW[r] &= ~rb; CB[c] |= cb; CW[c] &= ~cb; }
        else { RW[r] |= rb; RB[r] &= ~rb; CW[c] |= cb; CB[c] &= ~cb; }
        enqueue(r); enqueue(h + c);
    }

    bool search() {
        if (guesses > 50000) { gaveUp = true; return false; }
        if (!propagate()) return false;
        int br, bc;
        if (!pickCell(br, bc)) return true;   // solved
        u64 sRB[MAXN], sRW[MAXN], sCB[MAXN], sCW[MAXN];
        memcpy(sRB, RB, sizeof(u64) * h);
        memcpy(sRW, RW, sizeof(u64) * h);
        memcpy(sCB, CB, sizeof(u64) * w);
        memcpy(sCW, CW, sizeof(u64) * w);
        ++guesses;
        setCell(br, bc, true);
        if (search()) return true;
        ++backtracks;
        memcpy(RB, sRB, sizeof(u64) * h);
        memcpy(RW, sRW, sizeof(u64) * h);
        memcpy(CB, sCB, sizeof(u64) * w);
        memcpy(CW, sCW, sizeof(u64) * w);
        qh = qt = 0; memset(inq, 0, sizeof(inq));
        setCell(br, bc, false);
        if (search()) return true;
        memcpy(RB, sRB, sizeof(u64) * h);
        memcpy(RW, sRW, sizeof(u64) * h);
        memcpy(CB, sCB, sizeof(u64) * w);
        memcpy(CW, sCW, sizeof(u64) * w);
        qh = qt = 0; memset(inq, 0, sizeof(inq));
        return false;
    }
};

// ---------------- output ----------------
static std::mutex outM;

// safety net: verify the grid against every clue before claiming SOLUTION
static bool verifyGrid(const Puzzle* pz, const u64 RB[MAXN]) {
    for (int r = 0; r < pz->h; ++r) {
        const Line& ln = pz->rows[r];
        int j = 0, run = 0;
        for (int c = 0; c <= pz->w; ++c) {
            bool black = c < pz->w && (RB[r] & (1ULL << c));
            if (black) ++run;
            else if (run) { if (j >= ln.k || ln.cl[j] != run) return false; ++j; run = 0; }
        }
        if (j != ln.k) return false;
    }
    for (int c = 0; c < pz->w; ++c) {
        const Line& ln = pz->cols[c];
        int j = 0, run = 0;
        for (int r = 0; r <= pz->h; ++r) {
            bool black = r < pz->h && (RB[r] & (1ULL << c));
            if (black) ++run;
            else if (run) { if (j >= ln.k || ln.cl[j] != run) return false; ++j; run = 0; }
        }
        if (j != ln.k) return false;
    }
    return true;
}

static void solveAndOutput(const Puzzle* pz) {
    auto t0 = std::chrono::steady_clock::now();
    Solver sv;
    sv.init(pz);
    bool ok = sv.search();
    if (ok && !verifyGrid(pz, sv.RB)) ok = false;
    auto t1 = std::chrono::steady_clock::now();
    long long ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
    fprintf(stderr, "[solver] %s %s ms=%lld lines=%lld guesses=%lld backtracks=%lld\n",
            pz->id, ok ? "OK" : "FAIL", ms, sv.nlines, sv.guesses, sv.backtracks);

    std::string out;
    out.reserve(64 + pz->h * (pz->w + 1));
    char tmp[256];
    snprintf(tmp, sizeof(tmp), "STATS lines=%lld probes=0 guesses=%lld backtracks=%lld ms=%lld\n",
             sv.nlines, sv.guesses, sv.backtracks, ms);
    out += tmp;
    if (ok) {
        out += "SOLUTION ";
        out += pz->id;
        out += '\n';
        for (int r = 0; r < pz->h; ++r) {
            u64 bits = sv.RB[r];
            for (int c = 0; c < pz->w; ++c) out += (bits & (1ULL << c)) ? '#' : '.';
            out += '\n';
        }
    } else {
        out += "UNSOLVED ";
        out += pz->id;
        out += '\n';
    }
    std::lock_guard<std::mutex> lk(outM);
    fwrite(out.data(), 1, out.size(), stdout);
    fflush(stdout);
}

// ---------------- main: reader + 2 workers ----------------
int main() {
    static Reader rd;
    std::mutex m;
    std::condition_variable cv;
    std::vector<Puzzle*> pending;
    bool eof = false;

    auto worker = [&]() {
        for (;;) {
            Puzzle* pz = nullptr;
            {
                std::unique_lock<std::mutex> lk(m);
                cv.wait(lk, [&] { return eof || !pending.empty(); });
                if (pending.empty()) { if (eof) return; continue; }
                pz = pending.back();
                pending.pop_back();
            }
            solveAndOutput(pz);
            delete pz;
        }
    };
    std::thread t1(worker), t2(worker);

    Puzzle tmp;
    while (parsePuzzle(rd, tmp)) {
        Puzzle* pz = new Puzzle(tmp);
        {
            std::lock_guard<std::mutex> lk(m);
            pending.push_back(pz);
        }
        cv.notify_one();
    }
    {
        std::lock_guard<std::mutex> lk(m);
        eof = true;
    }
    cv.notify_all();
    t1.join();
    t2.join();
    return 0;
}
