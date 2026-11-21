#include <iostream>
#include <vector>
#include <string>
#include <sstream>
#include <cstdint>
#include <cstring>
#include <algorithm>
#include <chrono>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <queue>

using namespace std;

struct LineClues {
    int k = 0;
    int len = 0;
    int c[32];
    int b[32];
    int s[32];
    uint64_t valid_pos_mask[32];
};

struct BoardState {
    uint64_t row1[48], row0[48];
    uint64_t col1[48], col0[48];
    uint64_t dirty_rows = 0;
    uint64_t dirty_cols = 0;
    int solved_count = 0;
};

struct Puzzle {
    string id;
    int H = 0, W = 0;
    LineClues rows[48];
    LineClues cols[48];
};

static inline uint64_t smear_left(uint64_t x, int c) {
    int d = c - 1;
    if (d <= 0) return x;
    if (d >= 1) x |= x << 1;
    if (d >= 3) x |= x << 2;
    if (d >= 7) x |= x << 4;
    if (d >= 15) x |= x << 8;
    if (d >= 31) x |= x << 16;
    int b = 31 - __builtin_clz(c);
    return x | (x << (c - (1 << b)));
}

struct Solver {
    const Puzzle& puz;
    uint64_t maskH, maskW;
    int total_cells;

    Solver(const Puzzle& p) : puz(p) {
        maskH = (p.H == 64) ? ~0ULL : ((1ULL << p.H) - 1);
        maskW = (p.W == 64) ? ~0ULL : ((1ULL << p.W) - 1);
        total_cells = p.H * p.W;
    }

    inline bool solve_line(const LineClues& lc, uint64_t known1, uint64_t known0,
                           uint64_t& out1, uint64_t& out0) {
        const int L = lc.len;
        const uint64_t maskL = (L == 64) ? ~0ULL : ((1ULL << L) - 1);
        if (lc.k == 0) {
            if (known1 != 0) return false;
            out1 = 0;
            out0 = maskL;
            return true;
        }

        uint64_t z[6];
        z[0] = known0;
        z[1] = z[0] | (z[0] >> 1);
        z[2] = z[1] | (z[1] >> 2);
        z[3] = z[2] | (z[2] >> 4);
        z[4] = z[3] | (z[3] >> 8);
        z[5] = z[4] | (z[4] >> 16);

        const uint64_t free0_ext = ~known1;
        const uint64_t free = free0_ext & maskL;
        const uint64_t prev_white = (free0_ext << 1) | 1ULL;

        uint64_t F[32];
        const int k = lc.k;
        {
            int c = lc.c[0];
            int b = lc.b[0];
            int s = lc.s[0];
            uint64_t valid_start = ~(z[b] | (z[b] >> s)) & prev_white & (free0_ext >> c) & lc.valid_pos_mask[0];
            uint64_t S = 1ULL;
            uint64_t r = S | ((free + (S & free)) ^ free);
            F[0] = r & valid_start;
            if (!F[0]) return false;
        }

        for (int j = 1; j < k; ++j) {
            int c = lc.c[j];
            int b = lc.b[j];
            int s = lc.s[j];
            uint64_t valid_start = ~(z[b] | (z[b] >> s)) & prev_white & (free0_ext >> c) & lc.valid_pos_mask[j];
            uint64_t S = F[j - 1] << (lc.c[j - 1] + 1);
            uint64_t r = S | ((free + (S & free)) ^ free);
            F[j] = r & valid_start;
            if (!F[j]) return false;
        }

        uint64_t B = F[k - 1];
        if (known1 != 0) {
            int last1 = 63 - __builtin_clzll(known1);
            int min_p = last1 - lc.c[k - 1] + 1;
            if (min_p > 0) {
                B &= ~((1ULL << min_p) - 1);
            }
        }
        if (!B) return false;

        uint64_t f1 = free;
        uint64_t f2 = f1 & (f1 >> 1);
        uint64_t f4 = f2 & (f2 >> 2);
        uint64_t f8 = f4 & (f4 >> 4);
        uint64_t f16 = f8 & (f8 >> 8);
        uint64_t f32 = f16 & (f16 >> 16);

        uint64_t all_black = smear_left(B, lc.c[k - 1]);
        int min_last_end = __builtin_ctzll(B) + lc.c[k - 1];
        uint64_t all_white = (min_last_end >= 64) ? 0ULL : ((~((1ULL << min_last_end) - 1)) & maskL);

        for (int j = k - 1; j >= 1; --j) {
            uint64_t X = B;
            X |= (X >> 1) & f1;
            X |= (X >> 2) & f2;
            X |= (X >> 4) & f4;
            X |= (X >> 8) & f8;
            X |= (X >> 16) & f16;
            X |= (X >> 32) & f32;

            int prev_c = lc.c[j - 1];
            uint64_t prev_B = F[j - 1] & (X >> (prev_c + 1));
            if (!prev_B) return false;

            uint64_t S_valid = prev_B << (prev_c + 1);
            uint64_t r_valid = S_valid | ((free + (S_valid & free)) ^ free);
            all_white |= r_valid & (X >> 1) & free;

            all_white |= (prev_B << prev_c);
            all_black |= smear_left(prev_B, prev_c);
            B = prev_B;
        }

        int max_first_start = 63 - __builtin_clzll(B);
        if (max_first_start > 0) {
            all_white |= (1ULL << max_first_start) - 1;
        }

        out1 = (~all_white) & maskL;
        out0 = (~all_black) & maskL;
        if ((out1 & known0) || (out0 & known1) || (out1 & out0)) return false;
        return true;
    }

    bool propagate(BoardState& st) {
        while (st.dirty_rows | st.dirty_cols) {
            while (st.dirty_rows) {
                int r = __builtin_ctzll(st.dirty_rows);
                st.dirty_rows &= st.dirty_rows - 1;

                uint64_t out1, out0;
                if (!solve_line(puz.rows[r], st.row1[r], st.row0[r], out1, out0)) {
                    return false;
                }
                uint64_t new1 = out1 & ~st.row1[r];
                uint64_t new0 = out0 & ~st.row0[r];
                uint64_t nw = new1 | new0;
                if (nw) {
                    st.row1[r] |= new1;
                    st.row0[r] |= new0;
                    st.dirty_cols |= nw;
                    st.solved_count += __builtin_popcountll(nw);
                    uint64_t bit = 1ULL << r;
                    for (uint64_t m = new1; m; m &= m - 1) {
                        st.col1[__builtin_ctzll(m)] |= bit;
                    }
                    for (uint64_t m = new0; m; m &= m - 1) {
                        st.col0[__builtin_ctzll(m)] |= bit;
                    }
                }
            }
            while (st.dirty_cols) {
                int c = __builtin_ctzll(st.dirty_cols);
                st.dirty_cols &= st.dirty_cols - 1;

                uint64_t out1, out0;
                if (!solve_line(puz.cols[c], st.col1[c], st.col0[c], out1, out0)) {
                    return false;
                }
                uint64_t new1 = out1 & ~st.col1[c];
                uint64_t new0 = out0 & ~st.col0[c];
                uint64_t nw = new1 | new0;
                if (nw) {
                    st.col1[c] |= new1;
                    st.col0[c] |= new0;
                    st.dirty_rows |= nw;
                    st.solved_count += __builtin_popcountll(nw);
                    uint64_t bit = 1ULL << c;
                    for (uint64_t m = new1; m; m &= m - 1) {
                        st.row1[__builtin_ctzll(m)] |= bit;
                    }
                    for (uint64_t m = new0; m; m &= m - 1) {
                        st.row0[__builtin_ctzll(m)] |= bit;
                    }
                }
            }
        }
        return true;
    }

    inline void set_cell(BoardState& st, int r, int c, int val) {
        if (val == 1) {
            st.row1[r] |= (1ULL << c);
            st.col1[c] |= (1ULL << r);
        } else {
            st.row0[r] |= (1ULL << c);
            st.col0[c] |= (1ULL << r);
        }
        st.solved_count++;
        st.dirty_rows |= (1ULL << r);
        st.dirty_cols |= (1ULL << c);
    }

    inline uint64_t kn_col(const BoardState& st, int c) const {
        return st.col1[c] | st.col0[c];
    }

    bool probe_and_select(BoardState& st, int depth, BoardState& out_first, BoardState& out_second, bool& solved_now) {
        solved_now = false;
        while (true) {
            if (st.solved_count == total_cells) {
                solved_now = true;
                return true;
            }
            int base_solved = st.solved_count;

            uint32_t cands[2048];
            int nc = 0;
            int row_unk[48], col_unk[48];
            for (int r = 0; r < puz.H; ++r) row_unk[r] = puz.W - __builtin_popcountll(st.row1[r] | st.row0[r]);
            for (int c = 0; c < puz.W; ++c) col_unk[c] = puz.H - __builtin_popcountll(st.col1[c] | st.col0[c]);

            for (int r = 0; r < puz.H; ++r) {
                uint64_t kn = st.row1[r] | st.row0[r];
                uint64_t unk = (~kn) & maskW;
                if (!unk) continue;
                uint64_t adj_r = ((kn << 1) | (kn >> 1)) & unk;
                for (uint64_t m = unk; m; m &= m - 1) {
                    int c = __builtin_ctzll(m);
                    uint64_t kc = kn_col(st, c);
                    int adj = ((adj_r >> c) & 1) + ((r > 0 && ((kc >> (r - 1)) & 1)) ? 1 : 0)
                              + ((r + 1 < puz.H && ((kc >> (r + 1)) & 1)) ? 1 : 0);
                    uint32_t prio = (uint32_t)((row_unk[r] + col_unk[c]) - adj * 8 + 64);
                    cands[nc++] = (prio << 12) | (r << 6) | c;
                }
            }
            int max_lim = (depth == 0) ? 240 : 44;
            int limit = min(nc, max_lim);
            partial_sort(cands, cands + limit, cands + nc);

            bool progress = false;
            double best_score = -1.0;

            for (int i = 0; i < limit; ++i) {
                int r = (cands[i] >> 6) & 63;
                int c = cands[i] & 63;
                if (((st.row1[r] | st.row0[r]) >> c) & 1ULL) continue;

                BoardState st1 = st;
                set_cell(st1, r, c, 1);
                bool ok1 = propagate(st1);

                BoardState st0 = st;
                set_cell(st0, r, c, 0);
                bool ok0 = propagate(st0);

                if (!ok1 && !ok0) return false;
                if (!ok1) {
                    st = st0;
                    progress = true;
                    break;
                }
                if (!ok0) {
                    st = st1;
                    progress = true;
                    break;
                }

                int g1 = st1.solved_count - base_solved;
                int g0 = st0.solved_count - base_solved;

                if (g1 > 1 && g0 > 1) {
                    bool merged = false;
                    for (int rr = 0; rr < puz.H; ++rr) {
                        uint64_t common1 = (st1.row1[rr] & st0.row1[rr]) & ~st.row1[rr];
                        uint64_t common0 = (st1.row0[rr] & st0.row0[rr]) & ~st.row0[rr];
                        uint64_t nw = common1 | common0;
                        if (nw) {
                            merged = true;
                            st.row1[rr] |= common1;
                            st.row0[rr] |= common0;
                            st.solved_count += __builtin_popcountll(nw);
                            st.dirty_rows |= (1ULL << rr);
                            st.dirty_cols |= nw;
                            uint64_t bit = 1ULL << rr;
                            for (uint64_t m = common1; m; m &= m - 1) st.col1[__builtin_ctzll(m)] |= bit;
                            for (uint64_t m = common0; m; m &= m - 1) st.col0[__builtin_ctzll(m)] |= bit;
                        }
                    }
                    if (merged) {
                        if (!propagate(st)) return false;
                        progress = true;
                        break;
                    }
                }

                double score = (double)(g1) * (double)(g0);
                if (score > best_score) {
                    best_score = score;
                    if (g1 >= g0) {
                        out_first = st1;
                        out_second = st0;
                    } else {
                        out_first = st0;
                        out_second = st1;
                    }
                }
            }
            if (!progress) break;
        }
        return true;
    }

    bool dfs(BoardState& st, int depth = 0) {
        BoardState first_st, second_st;
        bool solved_now = false;
        if (!probe_and_select(st, depth, first_st, second_st, solved_now)) {
            return false;
        }
        if (solved_now) return true;

        if (dfs(first_st, depth + 1)) {
            st = first_st;
            return true;
        }
        if (dfs(second_st, depth + 1)) {
            st = second_st;
            return true;
        }
        return false;
    }
};

static void init_line_clues(LineClues& lc, int len, const vector<int>& nums) {
    lc.len = len;
    if (nums.size() == 1 && nums[0] == 0) {
        lc.k = 0;
        return;
    }
    lc.k = (int)nums.size();
    for (int j = 0; j < lc.k; ++j) {
        int c = nums[j];
        lc.c[j] = c;
        int b = 31 - __builtin_clz(c);
        lc.b[j] = b;
        lc.s[j] = c - (1 << b);
    }
    int rem = 0;
    for (int j = lc.k - 1; j >= 0; --j) {
        int max_start = len - lc.c[j] - rem;
        if (max_start < 0) max_start = -1;
        lc.valid_pos_mask[j] = (max_start >= 63) ? ~0ULL : ((max_start < 0) ? 0ULL : ((1ULL << (max_start + 1)) - 1));
        rem += lc.c[j] + 1;
    }
}

bool read_puzzle(istream& in, Puzzle& puz) {
    string tag;
    while (in >> tag) {
        if (tag == "PUZZLE") break;
    }
    if (!in || tag != "PUZZLE") return false;
    in >> puz.id >> puz.H >> puz.W;
    string line;
    getline(in, line);
    for (int r = 0; r < puz.H; ++r) {
        getline(in, line);
        stringstream ss(line);
        vector<int> nums;
        int x;
        while (ss >> x) nums.push_back(x);
        init_line_clues(puz.rows[r], puz.W, nums);
    }
    for (int c = 0; c < puz.W; ++c) {
        getline(in, line);
        stringstream ss(line);
        vector<int> nums;
        int x;
        while (ss >> x) nums.push_back(x);
        init_line_clues(puz.cols[c], puz.H, nums);
    }
    return true;
}

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    mutex q_mtx, out_mtx;
    condition_variable q_cv;
    queue<Puzzle> q;
    bool eof_reached = false;

    auto worker = [&]() {
        while (true) {
            Puzzle puz;
            {
                unique_lock<mutex> lk(q_mtx);
                q_cv.wait(lk, [&]() { return !q.empty() || eof_reached; });
                if (q.empty() && eof_reached) break;
                puz = q.front();
                q.pop();
            }
            Solver solver(puz);
            BoardState st{};
            st.dirty_rows = solver.maskH;
            st.dirty_cols = solver.maskW;
            bool ok = solver.propagate(st) && solver.dfs(st, 0);

            ostringstream oss;
            if (ok) {
                oss << "SOLUTION " << puz.id << "\n";
                for (int r = 0; r < puz.H; ++r) {
                    for (int c = 0; c < puz.W; ++c) {
                        oss << (((st.row1[r] >> c) & 1ULL) ? '#' : '.');
                    }
                    oss << "\n";
                }
            } else {
                oss << "UNSOLVED " << puz.id << "\n";
            }
            {
                lock_guard<mutex> lk(out_mtx);
                cout << oss.str();
                cout.flush();
            }
        }
    };

    vector<thread> pool;
    for (int i = 0; i < 2; ++i) pool.emplace_back(worker);

    Puzzle puz;
    while (read_puzzle(cin, puz)) {
        {
            lock_guard<mutex> lk(q_mtx);
            q.push(puz);
        }
        q_cv.notify_one();
    }
    {
        lock_guard<mutex> lk(q_mtx);
        eof_reached = true;
    }
    q_cv.notify_all();
    for (auto& t : pool) t.join();
    return 0;
}
