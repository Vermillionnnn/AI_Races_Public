// Nonogram solver — GLM-5.3
// Bitmask two-sided line DP (with virtual trailing white cell), dirty-queue
// constraint propagation, DFS search with propagation + node budget.
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <io.h>

#if defined(_MSC_VER)
#include <intrin.h>
static inline int ctz64(uint64_t x) { unsigned long i; _BitScanForward64(&i, x); return (int)i; }
#else
static inline int ctz64(uint64_t x) { return __builtin_ctzll(x); }
#endif

static const int MAXD = 48;   // max dimension (spec: 40..45)
static const int MAXB = 26;   // max blocks per line
static const int STR  = 48;   // grid row stride

struct Clues {
    int h, w;
    char id[80];
    int rblk[MAXD][MAXB]; int rlen[MAXD];
    int cblk[MAXD][MAXB]; int clen[MAXD];
};

// ------------------------- input -------------------------
static char inbuf[1 << 16];
static int inlen = 0, inpos = 0;

static inline int gc() {
    if (inpos >= inlen) {
        long n = _read(0, inbuf, (unsigned)sizeof(inbuf));
        if (n <= 0) { inlen = 0; return -1; }
        inlen = (int)n; inpos = 0;
    }
    return (unsigned char)inbuf[inpos++];
}

static bool readLine(char *dst, int cap) {
    int c = gc();
    if (c < 0) return false;
    int len = 0;
    while (c >= 0 && c != '\n') {
        if (c != '\r' && len < cap - 1) dst[len++] = (char)c;
        c = gc();
    }
    dst[len] = 0;
    return true;
}

static void parseClueLine(const char *s, int *dst, int &n) {
    n = 0;
    while (*s) {
        if (*s >= '0' && *s <= '9') {
            int v = 0;
            while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; }
            if (v > 0 && n < MAXB) dst[n++] = v;
        } else s++;
    }
}

static bool parsePuzzle(Clues &q) {
    static char line[16384];
    while (true) {
        if (!readLine(line, sizeof line)) return false;
        if (!memcmp(line, "PUZZLE", 6) && (line[6] == ' ' || line[6] == 0)) break;
    }
    char *p = line + 6;
    while (*p == ' ' || *p == '\t') p++;
    char *d = q.id;
    while (*p && *p != ' ' && *p != '\t') *d++ = *p++;
    *d = 0;
    while (*p == ' ' || *p == '\t') p++;
    q.h = (int)strtol(p, &p, 10);
    while (*p == ' ' || *p == '\t') p++;
    q.w = (int)strtol(p, &p, 10);
    if (q.h < 1 || q.h > MAXD || q.w < 1 || q.w > MAXD) return false;
    for (int r = 0; r < q.h; r++) {
        if (!readLine(line, sizeof line)) return false;
        parseClueLine(line, q.rblk[r], q.rlen[r]);
    }
    for (int c = 0; c < q.w; c++) {
        if (!readLine(line, sizeof line)) return false;
        parseClueLine(line, q.cblk[c], q.clen[c]);
    }
    return true;
}

// ------------------------- line solver -------------------------
// Bit i = cell i for i in [0,n); bit n = virtual white cell appended.
// State positions 0..n+1 (prefix [0,i) / suffix [i,n]).
// Returns false on contradiction; fills fB/fW = forced black/white (real cells).
static inline uint64_t smearDown(uint64_t x, int d) {
    if (d >= 32) { x |= x >> 32; d -= 32; }
    if (d >= 16) { x |= x >> 16; d -= 16; }
    if (d >= 8)  { x |= x >> 8;  d -= 8; }
    if (d >= 4)  { x |= x >> 4;  d -= 4; }
    if (d >= 2)  { x |= x >> 2;  d -= 2; }
    if (d >= 1)  { x |= x >> 1; }
    return x;
}
static inline uint64_t smearUp(uint64_t x, int d) {
    if (d >= 32) { x |= x << 32; d -= 32; }
    if (d >= 16) { x |= x << 16; d -= 16; }
    if (d >= 8)  { x |= x << 8;  d -= 8; }
    if (d >= 4)  { x |= x << 4;  d -= 4; }
    if (d >= 2)  { x |= x << 2;  d -= 2; }
    if (d >= 1)  { x |= x << 1; }
    return x;
}

static bool lineSolve(int n, const int *blk, int m, unsigned char *cells,
                      uint64_t &fB, uint64_t &fW) {
    const uint64_t cellBits = ((uint64_t)1 << (n + 1)) - 1; // cell positions 0..n
    const uint64_t allBits  = ((uint64_t)1 << (n + 2)) - 1; // state positions 0..n+1
    uint64_t K = 0, B = 0; // black-known / white-known
    for (int i = 0; i < n; i++) {
        if (cells[i] == 1) K |= (uint64_t)1 << i;
        else if (cells[i] == 2) B |= (uint64_t)1 << i;
    }
    B |= (uint64_t)1 << n; // virtual trailing white
    uint64_t W = cellBits & ~K; // white-allowed cells

    // closure masks: md_k[i] = cells [i, i+2^k) all white-allowed
    uint64_t md1 = W;
    uint64_t md2 = md1 & (md1 >> 1);
    uint64_t md4 = md2 & (md2 >> 2);
    uint64_t md8 = md4 & (md4 >> 4);
    uint64_t md16 = md8 & (md8 >> 8);
    uint64_t md32 = md16 & (md16 >> 16);
    uint64_t mu1 = W << 1;
    uint64_t mu2 = mu1 & (mu1 << 1);
    uint64_t mu4 = mu2 & (mu2 << 2);
    uint64_t mu8 = mu4 & (mu4 << 4);
    uint64_t mu16 = mu8 & (mu8 << 8);
    uint64_t mu32 = mu16 & (mu16 << 16);

    uint64_t A[MAXB]; // valid block-start positions per block
    for (int j = 0; j < m; j++) A[j] = ~smearDown(B, blk[j] - 1) & cellBits;

    // backward feasibility g[j]: bit i = suffix cells [i,n] fillable with blocks [j,m)
    uint64_t g[MAXB + 1];
    int lastK = -1;
    for (int i = n - 1; i >= 0; i--) if ((K >> i) & 1) { lastK = i; break; }
    g[m] = allBits & ~(((uint64_t)1 << (lastK + 1)) - 1);
    for (int j = m - 1; j >= 0; j--) {
        int L = blk[j];
        uint64_t t = (g[j + 1] >> (L + 1)) & A[j] & (W >> L);
        t |= (t >> 1) & md1;   t |= (t >> 2) & md2;
        t |= (t >> 4) & md4;   t |= (t >> 8) & md8;
        t |= (t >> 16) & md16; t |= (t >> 32) & md32;
        g[j] = t;
    }
    if (!(g[0] & 1)) return false;

    // forward reachability F[j]: bit i = prefix [0,i) fillable with blocks [0,j), white-ending
    uint64_t F[MAXB + 1];
    int firstK = n + 1;
    for (int i = 0; i < n; i++) if ((K >> i) & 1) { firstK = i; break; }
    F[0] = ((uint64_t)1 << (firstK + 1)) - 1;
    uint64_t blackCan = 0, whiteCan = 0;
    whiteCan |= ((F[0] & g[0]) >> 1) & W;
    for (int j = 0; j < m; j++) {
        int L = blk[j];
        uint64_t S = F[j] & A[j];
        uint64_t sep = S & (W >> L); // start s: block [s,s+L), separator cell s+L white-allowed
        blackCan |= smearUp(sep & (g[j + 1] >> (L + 1)), L - 1);
        uint64_t t = sep << (L + 1);
        t |= (t << 1) & mu1;   t |= (t << 2) & mu2;
        t |= (t << 4) & mu4;   t |= (t << 8) & mu8;
        t |= (t << 16) & mu16; t |= (t << 32) & mu32;
        F[j + 1] = t;
        whiteCan |= ((F[j + 1] & g[j + 1]) >> 1) & W;
    }

    uint64_t realBits = ((uint64_t)1 << n) - 1;
    uint64_t unk = realBits & ~(K | B);
    fB = unk & ~whiteCan;
    fW = unk & ~blackCan;
    return true;
}

// ------------------------- propagation -------------------------
struct Ctx {
    const Clues *q;
    unsigned char cell[MAXD * MAXD]; // 0 unknown, 1 black, 2 white
    uint64_t dirtyR, dirtyC;
};

static bool propagate(Ctx &x) {
    const Clues &q = *x.q;
    uint64_t fB, fW;
    static unsigned char tmp[MAXD];
    while (x.dirtyR | x.dirtyC) {
        if (x.dirtyR) {
            int r = ctz64(x.dirtyR);
            x.dirtyR &= x.dirtyR - 1;
            if (!lineSolve(q.w, q.rblk[r], q.rlen[r], &x.cell[r * STR], fB, fW)) {
                fprintf(stderr, "FAIL row %d n=%d m=%d cells:", r, q.w, q.rlen[r]);
                for (int i = 0; i < q.w; i++) fprintf(stderr, " %d", x.cell[r * STR + i]);
                fprintf(stderr, " blk:");
                for (int i = 0; i < q.rlen[r]; i++) fprintf(stderr, " %d", q.rblk[r][i]);
                fprintf(stderr, "\n");
                return false;
            }
            uint64_t ch = fB | fW;
            while (ch) {
                int c = ctz64(ch); ch &= ch - 1;
                x.cell[r * STR + c] = ((fB >> c) & 1) ? 1 : 2;
                x.dirtyC |= (uint64_t)1 << c;
            }
        } else {
            int c = ctz64(x.dirtyC);
            x.dirtyC &= x.dirtyC - 1;
            for (int r = 0; r < q.h; r++) tmp[r] = x.cell[r * STR + c];
            if (!lineSolve(q.h, q.cblk[c], q.clen[c], tmp, fB, fW)) {
                fprintf(stderr, "FAIL col %d n=%d m=%d cells:", c, q.h, q.clen[c]);
                for (int i = 0; i < q.h; i++) fprintf(stderr, " %d", tmp[i]);
                fprintf(stderr, " blk:");
                for (int i = 0; i < q.clen[c]; i++) fprintf(stderr, " %d", q.cblk[c][i]);
                fprintf(stderr, "\n");
                return false;
            }
            uint64_t ch = fB | fW;
            while (ch) {
                int r = ctz64(ch); ch &= ch - 1;
                x.cell[r * STR + c] = ((fB >> r) & 1) ? 1 : 2;
                x.dirtyR |= (uint64_t)1 << r;
            }
        }
    }
    return true;
}

// ------------------------- search -------------------------
static int gBudget;

static bool search(Ctx &x, int depth) {
    const Clues &q = *x.q;
    int rowUnk[MAXD] = {0}, colUnk[MAXD] = {0};
    int total = 0;
    for (int r = 0; r < q.h; r++)
        for (int c = 0; c < q.w; c++)
            if (!x.cell[r * STR + c]) { rowUnk[r]++; colUnk[c]++; total++; }
    if (total == 0) return true;
    if (depth >= 60 || --gBudget < 0) return false;
    int bestr = -1, bestc = -1, best = 1 << 30;
    for (int r = 0; r < q.h; r++) {
        if (!rowUnk[r]) continue;
        for (int c = 0; c < q.w; c++)
            if (!x.cell[r * STR + c]) {
                int sc = rowUnk[r] + colUnk[c];
                if (sc < best) { best = sc; bestr = r; bestc = c; }
            }
    }
    unsigned char saved[MAXD * MAXD];
    memcpy(saved, x.cell, sizeof saved);
    for (int color = 1; color <= 2; color++) {
        x.cell[bestr * STR + bestc] = (unsigned char)color;
        x.dirtyR = (uint64_t)1 << bestr;
        x.dirtyC = (uint64_t)1 << bestc;
        if (propagate(x) && search(x, depth + 1)) return true;
        memcpy(x.cell, saved, sizeof saved);
        if (gBudget < 0) return false;
    }
    return false;
}

// ------------------------- verify & emit -------------------------
static bool verifyLine(int n, const unsigned char *cells, const int *blk, int m) {
    int j = 0, run = 0;
    for (int i = 0; i <= n; i++) {
        int v = (i < n) ? cells[i] : 0;
        if (v == 1) run++;
        else if (run) { if (j >= m || blk[j] != run) return false; j++; run = 0; }
    }
    return j == m;
}
static bool verifyAll(const Ctx &x) {
    const Clues &q = *x.q;
    static unsigned char tmp[MAXD];
    for (int r = 0; r < q.h; r++)
        if (!verifyLine(q.w, &x.cell[r * STR], q.rblk[r], q.rlen[r])) return false;
    for (int c = 0; c < q.w; c++) {
        for (int r = 0; r < q.h; r++) tmp[r] = x.cell[r * STR + c];
        if (!verifyLine(q.h, tmp, q.cblk[c], q.clen[c])) return false;
    }
    return true;
}

static void emit(const Clues &q, const unsigned char *cell, bool ok) {
    static char obuf[128 + MAXD * (MAXD + 1)];
    int len = 0;
    if (ok) {
        len += sprintf(obuf + len, "SOLUTION %s\n", q.id);
        for (int r = 0; r < q.h; r++) {
            for (int c = 0; c < q.w; c++) obuf[len++] = cell[r * STR + c] == 1 ? '#' : '.';
            obuf[len++] = '\n';
        }
    } else {
        len += sprintf(obuf + len, "UNSOLVED %s\n", q.id);
    }
    fwrite(obuf, 1, len, stdout);
    fflush(stdout);
}

static bool solvePuzzle(Ctx &x) {
    const Clues &q = *x.q;
    memset(x.cell, 0, sizeof x.cell);
    x.dirtyR = ((uint64_t)1 << q.h) - 1;
    x.dirtyC = ((uint64_t)1 << q.w) - 1;
    if (!propagate(x)) { fprintf(stderr, "STAGE prop-fail %s\n", q.id); return false; }
    gBudget = 5000;
    if (!search(x, 0)) { fprintf(stderr, "STAGE search-fail %s\n", q.id); return false; }
    if (!verifyAll(x)) { fprintf(stderr, "STAGE verify-fail %s\n", q.id); return false; }
    return true; // paranoia: never emit an unverified grid
}

int main() {
    Clues q;
    Ctx x;
    x.q = &q;
    while (parsePuzzle(q))
        emit(q, x.cell, solvePuzzle(x));
    return 0;
}
