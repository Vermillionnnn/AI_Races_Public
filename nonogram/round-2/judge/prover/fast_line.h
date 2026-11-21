// Bitset line solver wrapped in a namespace; the filtering algorithm is unchanged.
#pragma once
#include <cstdint>
namespace nonogen_fast {
// 单行推理（完备）：位运算版的前向/后向动态规划。
// prover.h 用这个头文件。
//
// 记号：一行长 n（n <= 62），格子编号 0..n-1。为了让两端的处理和中间一样，
// 在左右各补一个"必白"的虚拟格，补完后格子编号 0..n+1（原格 c 对应补后 c+1）。
// "位置" p 表示前 p 个格子已经摆好、下一块可以从格子 p 开始，取值 0..n+1，
// 一个 64 位整数就放得下（n+2 <= 64）。
//
//   F[j] 的第 p 位：格子 [0,p) 恰好放下前 j 块，且格子 p-1 是白的。
//   H[j] 的第 p 位：格子 [p,n+2) 恰好放下第 j..k-1 块，且格子 p 是白的。
//
// 那么：格子 c 能白 <=> 存在 j，F[j] 含 c+1 且 H[j] 含 c；
//       第 j 块能从 p 开始 <=> F[j] 含 p，格子 p..p+L-1 都能黑，H[j+1] 含 p+L。
// 每个 F[j]/H[j] 用几次整数运算算出，一行总共 O(k * log n) 次运算。

typedef uint64_t u64;

static const int MAXN = 62;   // 支持的最大行列长度
static const int MAXK = 32;   // 一行最多 (62+1)/2 = 31 块

struct Clue {
    int n = 0, k = 0;
    int len[MAXK];
    u64 full = 0;  // 低 n 位全 1
};

// 从种子位置向右扩展：位置 p 在、格子 p 能白，则位置 p+1 也在。
// 用加法进位一次填满每段连续的"能白"格（每段从段内最低的种子填到段尾的下一位）。
static inline u64 closeRight(u64 S, u64 A) { return S | ((A + (S & A)) ^ A); }

// 向左扩展：位置 p+1 在、格子 p 能白，则位置 p 也在。进位只能往高位走，
// 所以用 Kogge-Stone 式的倍增，6 步覆盖 64 位。
static inline u64 closeLeft(u64 X, u64 P) {
    X |= P & (X >> 1);  P &= P >> 1;
    X |= P & (X >> 2);  P &= P >> 2;
    X |= P & (X >> 4);  P &= P >> 4;
    X |= P & (X >> 8);  P &= P >> 8;
    X |= P & (X >> 16); P &= P >> 16;
    X |= P & (X >> 32);
    return X;
}

// 第 p 位为 1 当且仅当 C 的第 p..p+L-1 位全是 1（长 L 的块能从 p 开始全涂黑）。
static inline u64 runStarts(u64 C, int L) {
    u64 x = C;
    int len = 1;
    while (len < L) {
        int s = len < L - len ? len : L - len;
        x &= x >> s;
        len += s;
    }
    return x;
}

// 把每个起点 p 涂成 [p, p+L)。
static inline u64 smear(u64 V, int L) {
    u64 x = V;
    int len = 1;
    while (len < L) {
        int s = len < L - len ? len : L - len;
        x |= x << s;
        len += s;
    }
    return x;
}

// 输入已知黑格 kb、已知白格 kw（互不相交，只用低 n 位）。
// 无解返回 false；否则 ob/ow 为推理后的全部已知黑/白格（包含原来已知的）。
static inline bool lineSolve(const Clue& c, u64 kb, u64 kw, u64& ob, u64& ow) {
    const int n = c.n, k = c.k;
    const u64 om = c.full;
    const u64 canB = (~kw & om) << 1;
    const u64 canW = ((~kb & om) << 1) | 1ULL | (1ULL << (n + 1));
    const u64 pos = (n + 2 >= 64) ? ~0ULL : ((1ULL << (n + 2)) - 1);
    u64 F[MAXK + 1], H[MAXK + 1], S[MAXK];
    F[0] = closeRight(2ULL, canW) & pos;
    for (int j = 0; j < k; j++) {
        const int L = c.len[j];
        S[j] = runStarts(canB, L);
        u64 st = F[j] & S[j] & (canW >> L);  // 第 j 块可行的起点（只看左边）
        if (!st) return false;
        // 新位置 p+L+1 最大是 n+2，超出 pos 的那一位丢掉也没关系：
        // 只有最后一块贴着右端时才到 n+2，而 F[k] 只用到 n+1 及以下。
        F[j + 1] = closeRight((st << (L + 1)) & pos, canW) & pos;
    }
    H[k] = closeLeft(1ULL << (n + 1), canW);
    for (int j = k - 1; j >= 0; j--) {
        const int L = c.len[j];
        u64 sd = ((S[j] & (H[j + 1] >> L)) >> 1) & canW;
        H[j] = closeLeft(sd, canW);
    }
    u64 cw = 0, cb = 0;
    for (int j = 0; j <= k; j++) cw |= (F[j] >> 1) & H[j];
    for (int j = 0; j < k; j++) {
        const int L = c.len[j];
        u64 V = F[j] & S[j] & (H[j + 1] >> L);
        cb |= smear(V, L);
    }
    cb = (cb >> 1) & om;
    cw = (cw >> 1) & om;
    if ((cb | cw) != om) return false;
    ob = cb & ~cw;
    ow = cw & ~cb;
    return true;
}

} // namespace nonogen_fast
