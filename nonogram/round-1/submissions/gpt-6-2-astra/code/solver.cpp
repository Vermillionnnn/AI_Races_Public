#include <algorithm>
#include <array>
#include <bit>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <iostream>
#include <mutex>
#include <charconv>
#include <string>
#include <thread>
#include <utility>
#include <vector>

using Bits = std::uint64_t;
constexpr int Max = 50;
Bits bit(int i) { return Bits{1} << i; }
Bits low(int n) { return bit(n) - 1; }

Bits reverse_bits(Bits x) {
    constexpr Bits m1 = 0x5555555555555555ULL;
    constexpr Bits m2 = 0x3333333333333333ULL;
    constexpr Bits m4 = 0x0f0f0f0f0f0f0f0fULL;
    x = ((x >> 1) & m1) | ((x & m1) << 1);
    x = ((x >> 2) & m2) | ((x & m2) << 2);
    x = ((x >> 4) & m4) | ((x & m4) << 4);
    x = ((x >> 8) & 0x00ff00ff00ff00ffULL) | ((x & 0x00ff00ff00ff00ffULL) << 8);
    x = ((x >> 16) & 0x0000ffff0000ffffULL) | ((x & 0x0000ffff0000ffffULL) << 16);
    return (x >> 32) | (x << 32);
}

// Reach every boundary accessible from a seed by crossing zero or more white cells.
// Unsigned addition propagates a carry across each contiguous chain of passable edges.
Bits close_white(Bits seeds, Bits pass) {
    return seeds | ((pass + (seeds & pass)) ^ pass);
}
Bits spread(Bits starts, int k) {
    while (k > 1) {
        int half = k / 2;
        starts |= starts << half;
        k -= half;
    }
    return starts;
}

struct Marks { Bits black, white; };
struct Line {
    int n{}, count{};
    std::array<int, Max> runs{};
    Bits mask{};
    struct Entry { Bits black, white, out_black, out_white; };
    static constexpr int Slots = 256;
    std::array<Entry, Slots> table;

    // All single-cell trials on a stable line share the same base assignment.
    Marks base{}, saved[2][Max];
    Bits valid[2]{};
    bool assume(Marks original, int j, bool black, Marks &out) {
        if (original.black!=base.black || original.white!=base.white) {
            base=original; valid[0]=valid[1]=0;
        }
        Bits cell=bit(j);
        if (!(valid[black]&cell)) {
            valid[black]|=cell;
            (black?original.black:original.white)|=cell;
            Marks result;
            if (!analyze(original,result)) result={~Bits{},0};
            saved[black][j]=result;
        }
        out=saved[black][j];
        return out.black!=~Bits{};
    }
    // Prefix and suffix states describe all placements, indexed by cell boundary.
    // A white cell joins a complete prefix to a complete suffix. A black cell
    // belongs to a run whose start and end are reachable from opposite sides.
    bool analyze(Marks m, Marks &out) {
        Bits key = m.black * 0x9e3779b97f4a7c15ULL + m.white * 0xd6e8feb86659fd93ULL;
        Entry &e = table[key >> (64 - 8)];
        if (e.black == m.black && e.white == m.white) {
            out = {e.out_black, e.out_white};
            return out.black != ~Bits{};
        }
        Bits starts[Max], prefix[Max+1], allowed[Max+1];
        Bits pass = mask ^ m.black;
        Bits can_black = mask ^ m.white;
        allowed[1] = can_black;
        int built = 1;
        Bits ends = 1;
        for (int i = 0; i < count; ++i) {
            int k = runs[i];
            while (built < k) {
                allowed[built+1] = (allowed[built] >> 1) & can_black;
                ++built;
            }
            prefix[i] = close_white(ends, pass);
            Bits next = i ? (prefix[i] & pass) << 1 : prefix[0];
            starts[i] = next & allowed[k];
            ends = starts[i] << k;
            if (!ends) break;
        }
        prefix[count] = close_white(ends, pass);
        if (!(prefix[count] & bit(n))) {
            e = {m.black,m.white,~Bits{},0};
            return false;
        }
        const int shift = 63 - n;
        auto mirror = [shift](Bits v) { return reverse_bits(v) >> shift; };
        Bits reverse_pass = mirror(pass) >> 1;
        Bits reverse_allowed[Max+1];
        reverse_allowed[1] = mirror(can_black) >> 1;
        for (int j=1;j<built;++j) reverse_allowed[j+1] = (reverse_allowed[j] >> 1) & reverse_allowed[1];
        Bits suffix_ends = 1;
        Bits blacks = 0, whites = 0;
        for (int i = count; i >= 0; --i) {
            Bits free = close_white(suffix_ends, reverse_pass);
            Bits original = mirror(free);
            whites |= prefix[i] & (original >> 1);
            if (!i) break;
            int k = runs[i-1];
            Bits next = i == count ? original : (original >> 1) & pass;
            Bits valid = starts[i-1] & (next >> k);
            blacks |= spread(valid, k);
            Bits reverse_next = i == count ? free : (free & reverse_pass) << 1;
            suffix_ends = (reverse_next & reverse_allowed[k]) << k;
        }
        out = {mask ^ (whites & pass), mask ^ blacks};
        e = {m.black, m.white, out.black, out.white};
        return true;
    }
};

struct Puzzle {
    std::string id;
    int h{}, w{};
    std::vector<std::vector<int>> clues;
    bool valid{};
};
struct Board {
    Marks marks[2][Max];
    Bits dirty[2];
    int known;
};
struct Solver {
    const Puzzle &p;
    int size[2];
    std::vector<Line> lines[2];
    explicit Solver(const Puzzle &input) : p(input), size{p.h,p.w} {
        for (int d = 0; d < 2; ++d) {
            lines[d].resize(size[d]);
            for (int i = 0; i < size[d]; ++i) {
                auto &l = lines[d][i];
                auto &clue = p.clues[(d ? p.h : 0)+i];
                l.n = size[1-d]; l.mask = low(l.n); l.count = int(clue.size());
                std::copy(clue.begin(),clue.end(),l.runs.begin());
                for (auto &e : l.table) e.black = ~Bits{};
            }
        }
    }
    void assign(Board &s, int r, int c, bool black) {
        if (black) { s.marks[0][r].black |= bit(c); s.marks[1][c].black |= bit(r); }
        else { s.marks[0][r].white |= bit(c); s.marks[1][c].white |= bit(r); }
        s.dirty[0] |= bit(r); s.dirty[1] |= bit(c); ++s.known;
    }
    void project(Board &s,int d,int i,Marks out) {
        auto &m=s.marks[d][i];
        Bits add_b = out.black & ~m.black, add_w = out.white & ~m.white;
        Bits change = add_b | add_w;
        s.known += std::popcount(change);
        s.dirty[1-d] |= change;
        m = out;
        while (add_b) {
            s.marks[1-d][std::countr_zero(add_b)].black |= bit(i);
            add_b &= add_b - 1;
        }
        while (add_w) {
            s.marks[1-d][std::countr_zero(add_w)].white |= bit(i);
            add_w &= add_w - 1;
        }
    }
    bool propagate(Board &s) {
        while (s.dirty[0] | s.dirty[1]) {
            for (int d = 0; d < 2; ++d) {
                Bits todo = s.dirty[d];
                s.dirty[d] = 0;
                while (todo) {
                    int i = std::countr_zero(todo);
                    todo &= todo - 1;
                    auto &m = s.marks[d][i];
                    Marks out;
                    if (!lines[d][i].analyze(m,out)) return false;
                    project(s,d,i,out);
                }
            }
        }
        return true;
    }

    struct Move { int score, r, c; };
    std::vector<Move> moves(const Board &s) {
        int scores[2][Max][Max];
        for (int d = 0; d < 2; ++d) {
            for (int i = 0; i < size[d]; ++i) {
                auto m = s.marks[d][i];
                int n = size[1-d];
                Bits unknown = low(n) & ~(m.black | m.white);
                int base = (n - std::popcount(unknown)) / 4;
                for (Bits todo = unknown; todo; todo &= todo-1) {
                    int j = std::countr_zero(todo);
                    int adj_black = std::popcount(((bit(j) << 1) | (bit(j) >> 1)) & m.black);
                    int adj_known = 2 - std::popcount(((bit(j) << 1) | (bit(j) >> 1)) & unknown);
                    scores[d][i][j] = base + adj_black * 8 + adj_known * 4 + (j==0 || j==n-1)*5;
                }
            }
        }
        std::vector<Move> v;
        v.reserve(p.h*p.w - s.known);
        for (int r=0;r<p.h;++r) {
            auto m=s.marks[0][r];
            for (Bits t=low(p.w)&~(m.black|m.white); t; t &= t-1) {
                int c=std::countr_zero(t);
                v.push_back({scores[0][r][c]+scores[1][c][r],r,c});
            }
        }
        std::sort(v.begin(),v.end(),[](Move a,Move b){return a.score>b.score;});
        return v;
    }
    // A one-cell hypothesis often changes neither incident line. Keep those
    // cases out of the board-copy and propagation paths.
    int probe(const Board &s,int r,int c,bool black,Board &trial) {
        Marks row=s.marks[0][r], col=s.marks[1][c];
        (black?row.black:row.white) |= bit(c);
        (black?col.black:col.white) |= bit(r);
        Marks new_row,new_col;
        if (!lines[0][r].assume(s.marks[0][r],c,black,new_row) || !lines[1][c].assume(s.marks[1][c],r,black,new_col)) return -1;
        if ((new_row.black|new_row.white)==(row.black|row.white) &&
            (new_col.black|new_col.white)==(col.black|col.white)) return 1;
        trial=s;
        trial.marks[0][r]=row; trial.marks[1][c]=col; ++trial.known;
        project(trial,0,r,new_row);
        project(trial,1,c,new_col);
        return propagate(trial) ? trial.known-s.known : -1;
    }
    // Explore a branch to completion. Alternatives live on the heap so deep
    // searches do not consume a Windows worker thread's limited call stack.
    bool search(Board &s, std::vector<Board> &alternatives) {
        while (s.known < p.h*p.w) {
            auto choices=moves(s);
            Move branch{};
            int best=-1;
            bool changed=false;
            Marks seen[Max]{};
            std::reverse(choices.begin(), choices.end());
            Bits pending[Max]{};
            // New information changes which neighboring assumptions are worth testing.
            auto nearby=[&](const Board &old) {
                Bits delta[Max+2]{};
                for (int i=0;i<p.h;++i) {
                    auto a=s.marks[0][i], b=old.marks[0][i];
                    delta[i+1]=(a.black|a.white) ^ (b.black|b.white);
                }
                for (int i=0;i<p.h;++i) {
                    Bits near=(delta[i+1]<<1)|(delta[i+1]>>1)|delta[i]|delta[i+2];
                    near &= low(p.w) & ~(s.marks[0][i].black | s.marks[0][i].white);
                    for (Bits t=near & ~pending[i];t;t&=t-1) choices.push_back({0,i,std::countr_zero(t)});
                    pending[i] |= near;
                    seen[i].black &= ~near;
                    seen[i].white &= ~near;
                }
            };
            while (!choices.empty()) {
                Move move=choices.back(); choices.pop_back();
                pending[move.r] &= ~bit(move.c);
                int r=move.r, c=move.c;
                Bits cell=bit(c);
                if ((s.marks[0][r].black | s.marks[0][r].white) & cell) continue;
                bool test_a=!(seen[r].black & cell);
                bool test_b=!(seen[r].white & cell);
                if (!test_a && !test_b) continue;
                Board a, b;
                // Previously observed colors only affect probe order. They never
                // become permanent assignments without a deduction or a branch.
                auto test=[&](bool black,Board &trial) {
                    int gain=probe(s,r,c,black,trial);
                    if (gain>1) {
                        for (int i=0;i<p.h;++i) {
                            seen[i].black |= trial.marks[0][i].black;
                            seen[i].white |= trial.marks[0][i].white;
                        }
                    }
                    return gain;
                };
                int ga=test_a?test(true,a):0;
                if (ga<0) {
                    Board old=s;
                    assign(s,r,c,false);
                    if (!propagate(s)) return false;
                    nearby(old);
                    changed = true;
                    continue;
                }
                if (ga > 1 && s.known + ga == p.h*p.w) {
                    s = a;
                    return true;
                }
                int gb=test_b?test(false,b):0;
                if (gb<0) {
                    Board old=s;
                    if (ga>1) s=a;
                    else {
                        assign(s, r, c, true);
                        if (!propagate(s)) return false;
                    }
                    nearby(old);
                    changed = true;
                    continue;
                }
                if (gb > 1 && s.known + gb == p.h*p.w) {
                    s = b;
                    return true;
                }
                if (!(ga && gb)) continue;
                if (!changed) {
                    int score=std::min(ga,gb)*4096+std::max(ga,gb);
                    if (score>best) {best=score;branch=move;}
                }
                if (ga==1 || gb==1) continue;
                // Anything implied by both colors holds on the original board.
                bool common=false; Board old=s;
                for (int i=0;i<p.h;++i) {
                    auto m=s.marks[0][i];
                    Bits black=a.marks[0][i].black & b.marks[0][i].black & ~m.black;
                    Bits white=a.marks[0][i].white & b.marks[0][i].white & ~m.white;
                    for (Bits t = black | white; t; t &= t - 1) {
                        int col = std::countr_zero(t);
                        assign(s, i, col, (black & bit(col)) != 0);
                    }
                    common |= bool(black|white);
                }
                if (common) {
                    if (!propagate(s)) return false;
                    nearby(old);
                    changed = true;
                }
            }
            if (changed) continue;
            if (best < 0) {
                for (int r = 0; r < p.h; ++r) {
                    const Marks &m = s.marks[0][r];
                    Bits unknown = low(p.w) & ~(m.black | m.white);
                    if (unknown) {
                        branch = {0, r, std::countr_zero(unknown)};
                        break;
                    }
                }
            }
            Board preferred=s, alternate=s;
            assign(preferred,branch.r,branch.c,true);
            assign(alternate,branch.r,branch.c,false);
            bool can_black = propagate(preferred);
            bool can_white = propagate(alternate);
            if (!can_black && !can_white) return false;
            if (!can_black) {
                s = alternate;
            } else if (!can_white) {
                s = preferred;
            } else {
                if (preferred.known < alternate.known) std::swap(preferred,alternate);
                alternatives.push_back(alternate);
                s = preferred;
            }
        }
        return true;
    }
    bool matches_clues(const Board &s) const {
        for (int d=0;d<2;++d) {
            for (int i=0;i<size[d];++i) {
                const auto &clue = lines[d][i];
                int count=0, length=0;
                for (int j=0;j<=clue.n;++j) {
                    if (j<clue.n && (d ? (s.marks[0][j].black & bit(i)) : (s.marks[0][i].black & bit(j)))) {
                        ++length;
                    } else if (length) {
                        if (count==clue.count || length!=clue.runs[count++]) return false;
                        length=0;
                    }
                }
                if (count!=clue.count) return false;
            }
        }
        return true;
    }
    std::string solve() {
        Board s{};
        s.dirty[0]=low(p.h); s.dirty[1]=low(p.w);
        if (!propagate(s)) return "UNSOLVED "+p.id+"\n";
        std::vector<Board> alternatives;
        while (!search(s,alternatives) || !matches_clues(s)) {
            if (alternatives.empty()) return "UNSOLVED "+p.id+"\n";
            s=alternatives.back();
            alternatives.pop_back();
        }
        std::string out="SOLUTION "+p.id+"\n";
        for (int r=0;r<p.h;++r) {
            for (int c=0;c<p.w;++c) out+=s.marks[0][r].black & bit(c) ? '#' : '.';
            out+='\n';
        }
        return out;
    }
};

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    std::deque<Puzzle> queue;
    std::mutex mutex, output;
    std::condition_variable ready;
    bool done=false;
    auto worker=[&] {
        while (true) {
            Puzzle p;
            {
                std::unique_lock lock(mutex);
                ready.wait(lock,[&]{return done || !queue.empty();});
                if (queue.empty()) return;
                p=std::move(queue.front()); queue.pop_front();
            }
            std::string result = p.valid ? Solver(p).solve() : "UNSOLVED "+p.id+"\n";
            std::lock_guard lock(output);
            std::cout << result << std::flush;
        }
    };
    std::thread a(worker), b(worker);
    Puzzle p;
    std::string header,line;
    while (std::cin >> header >> p.id >> p.h >> p.w) {
        if (header!="PUZZLE" || p.h<1 || p.h>Max || p.w<1 || p.w>Max) break;
        std::getline(std::cin,line);
        p.clues.assign(p.h+p.w,{});
        p.valid=true;
        bool complete=true;
        for (int i=0;i<p.h+p.w;++i) {
            if (!std::getline(std::cin,line)) { complete=false; break; }
            auto &clue=p.clues[i];
            const char *cursor=line.data(), *end=cursor+line.size();
            int span=0, limit=i<p.h?p.w:p.h;
            while (cursor<end) {
                if (*cursor==' ' || *cursor=='\t' || *cursor=='\r') { ++cursor; continue; }
                int k=0;
                auto num=std::from_chars(cursor,end,k);
                if (num.ec!=std::errc() || k<0 || k>limit) { p.valid=false; break; }
                cursor=num.ptr;
                if (!k) continue;
                span+=k+!clue.empty();
                if (span>limit) { p.valid=false; break; }
                clue.push_back(k);
            }
        }
        if (!complete) break;
        {
            std::lock_guard lock(mutex);
            queue.push_back(std::move(p));
        }
        ready.notify_one();
    }
    {
        std::lock_guard lock(mutex);
        done = true;
    }
    ready.notify_all();
    a.join();
    b.join();
    return 0;
}
