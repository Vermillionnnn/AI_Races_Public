#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <numeric>
#include <queue>
#include <sstream>
#include <string>
#include <vector>

using namespace std;

struct LineResult {
    uint64_t black = 0;
    uint64_t white = 0;
};

class Solver {
public:
    int h, w;
    vector<vector<int>> clues[2];
    vector<uint64_t> black[2], white[2];
    vector<unsigned char> queued[2];
    queue<pair<int, int>> work;
    long long lineCalls = 0, probeCalls = 0, forced = 0, guesses = 0;
    bool probeConflict = false;

    Solver(int height, int width, vector<vector<int>> rows,
           vector<vector<int>> cols)
        : h(height), w(width) {
        clues[0] = std::move(rows);
        clues[1] = std::move(cols);
        black[0].assign(h, 0);
        white[0].assign(h, 0);
        black[1].assign(w, 0);
        white[1].assign(w, 0);
        queued[0].assign(h, 0);
        queued[1].assign(w, 0);
    }

    int length(int type) const { return type == 0 ? w : h; }
    int count(int type) const { return type == 0 ? h : w; }

    void enqueue(int type, int index) {
        if (!queued[type][index]) {
            queued[type][index] = 1;
            work.push({type, index});
        }
    }

    // Exact arc consistency for one line. f[p][k] describes valid prefixes;
    // b[p][k] describes valid suffixes, both before cell p and clue k.
    bool line(int type, int index, LineResult& result) const {
        const int n = length(type);
        ++const_cast<Solver*>(this)->lineCalls;
        const vector<int>& a = clues[type][index];
        const int m = static_cast<int>(a.size());
        const uint64_t knownBlack = black[type][index];
        const uint64_t knownWhite = white[type][index];
        const uint64_t full = (1ULL << n) - 1;
        unsigned char f[46][46] = {};
        unsigned char b[46][46] = {};
        int cover[46] = {};

        b[n][m] = 1;
        for (int p = n - 1; p >= 0; --p) {
            for (int k = m; k >= 0; --k) {
                if (!(knownBlack & (1ULL << p)) && b[p + 1][k])
                    b[p][k] = 1;
                if (k < m) {
                    int e = p + a[k];
                    if (e <= n) {
                        uint64_t mask = ((1ULL << a[k]) - 1) << p;
                        if (!(mask & knownWhite)) {
                            int q = e;
                            if (k + 1 < m) {
                                if (e < n && !(knownBlack & (1ULL << e)))
                                    q = e + 1;
                                else
                                    q = n + 1;
                            }
                            if (q <= n && b[q][k + 1])
                                b[p][k] = 1;
                        }
                    }
                }
            }
        }

        f[0][0] = 1;
        for (int p = 0; p < n; ++p) {
            for (int k = 0; k <= m; ++k) {
                if (!f[p][k]) continue;
                if (!(knownBlack & (1ULL << p)))
                    f[p + 1][k] = 1;
                if (k < m) {
                    int e = p + a[k];
                    if (e <= n) {
                        uint64_t mask = ((1ULL << a[k]) - 1) << p;
                        if (!(mask & knownWhite)) {
                            int q = e;
                            if (k + 1 < m) {
                                if (e < n && !(knownBlack & (1ULL << e)))
                                    q = e + 1;
                                else
                                    q = n + 1;
                            }
                            if (q <= n) f[q][k + 1] = 1;
                        }
                    }
                }
            }
        }

        uint64_t possibleWhite = 0;
        for (int p = 0; p < n; ++p) {
            if (knownBlack & (1ULL << p)) continue;
            for (int k = 0; k <= m; ++k) {
                if (f[p][k] && b[p + 1][k]) {
                    possibleWhite |= 1ULL << p;
                    break;
                }
            }
        }

        for (int k = 0; k < m; ++k) {
            int len = a[k];
            for (int p = 0; p + len <= n; ++p) {
                if (!f[p][k]) continue;
                uint64_t mask = ((1ULL << len) - 1) << p;
                if (mask & knownWhite) continue;
                int e = p + len;
                int q = e;
                if (k + 1 < m) {
                    if (e < n && !(knownBlack & (1ULL << e)))
                        q = e + 1;
                    else
                        continue;
                }
                if (q > n || !b[q][k + 1]) continue;
                ++cover[p];
                --cover[e];
                // f/q states skip over the mandatory separator, so its white
                // possibility is not seen by the ordinary white transition.
                if (k + 1 < m) possibleWhite |= 1ULL << e;
            }
        }
        uint64_t possibleBlack = 0;
        int active = 0;
        for (int p = 0; p < n; ++p) {
            active += cover[p];
            if (active) possibleBlack |= 1ULL << p;
        }

        if ((possibleBlack | possibleWhite) != full) return false;
        result.black = full & ~possibleWhite;
        result.white = full & ~possibleBlack;
        if ((result.black & result.white) ||
            (result.black & knownWhite) || (result.white & knownBlack))
            return false;
        return true;
    }

    bool propagate() {
        while (!work.empty()) {
            auto [type, index] = work.front();
            work.pop();
            queued[type][index] = 0;
            LineResult r;
            if (!line(type, index, r)) return false;
            uint64_t addBlack = r.black & ~black[type][index];
            uint64_t addWhite = r.white & ~white[type][index];
            if ((r.black & white[type][index]) ||
                (r.white & black[type][index]))
                return false;
            if (!addBlack && !addWhite) continue;

            black[type][index] |= addBlack;
            white[type][index] |= addWhite;
            int other = type ^ 1;
            int n = length(type);
            for (int p = 0; p < n; ++p) {
                uint64_t bit = 1ULL << p;
                uint64_t cross = 1ULL << index;
                if (addBlack & bit) {
                    if (white[other][p] & cross) return false;
                    if (!(black[other][p] & cross)) {
                        black[other][p] |= cross;
                        enqueue(other, p);
                    }
                }
                if (addWhite & bit) {
                    if (black[other][p] & cross) return false;
                    if (!(white[other][p] & cross)) {
                        white[other][p] |= cross;
                        enqueue(other, p);
                    }
                }
            }
        }
        return true;
    }

    bool complete() const {
        for (int i = 0; i < h; ++i)
            if ((black[0][i] | white[0][i]) != ((1ULL << w) - 1))
                return false;
        return true;
    }

    void restore(const vector<uint64_t>& b0, const vector<uint64_t>& w0,
                 const vector<uint64_t>& b1, const vector<uint64_t>& w1) {
        black[0] = b0;
        white[0] = w0;
        black[1] = b1;
        white[1] = w1;
        while (!work.empty()) work.pop();
        queued[0].assign(h, 0);
        queued[1].assign(w, 0);
    }

    void setGuess(int r, int c, bool isBlack) {
        uint64_t cb = 1ULL << c, cr = 1ULL << r;
        if (isBlack) {
            black[0][r] |= cb;
            black[1][c] |= cr;
        } else {
            white[0][r] |= cb;
            white[1][c] |= cr;
        }
        enqueue(0, r);
        enqueue(1, c);
    }

    // Try both values at unknown cells. A contradictory value proves the
    // other one and often unlocks the whole puzzle without a real branch.
    // On entry and on a no-progress exit, the grid is fully propagated.
    bool probe() {
        vector<uint64_t> b0 = black[0], w0 = white[0];
        vector<uint64_t> b1 = black[1], w1 = white[1];
        uint32_t ways[2][45];
        for (int type = 0; type < 2; ++type)
            for (int i = 0; i < count(type); ++i)
                ways[type][i] = lineWays(type, i);
        struct Candidate { uint64_t score; unsigned char r, c; };
        vector<Candidate> cells;
        for (int r = 0; r < h; ++r)
            for (int c = 0; c < w; ++c)
                if (!((black[0][r] | white[0][r]) & (1ULL << c)))
                    cells.push_back({uint64_t(ways[0][r]) * ways[1][c],
                                     static_cast<unsigned char>(r),
                                     static_cast<unsigned char>(c)});
        sort(cells.begin(), cells.end(), [](const Candidate& x, const Candidate& y) {
            return x.score < y.score;
        });
        bool progress = false;
        for (const Candidate& cell : cells) {
            int r = cell.r, c = cell.c;
            uint64_t bit = 1ULL << c;
            if ((black[0][r] | white[0][r]) & bit) continue;
            bool contradicted = false;
            for (int value = 0; value < 2; ++value) {
                ++probeCalls;
                restore(b0, w0, b1, w1);
                setGuess(r, c, value == 0);
                if (!propagate()) {
                    restore(b0, w0, b1, w1);
                    setGuess(r, c, value != 0);
                    if (!propagate()) {
                        probeConflict = true;
                        return false;
                    }
                    ++forced;
                    progress = contradicted = true;
                    b0 = black[0]; w0 = white[0];
                    b1 = black[1]; w1 = white[1];
                    break;
                }
            }
            if (!contradicted) restore(b0, w0, b1, w1);
            if (complete()) return true;
        }
        return progress;
    }

    uint32_t lineWays(int type, int index) const {
        const int n = length(type);
        const vector<int>& a = clues[type][index];
        const int m = static_cast<int>(a.size());
        const uint64_t kb = black[type][index], kw = white[type][index];
        uint32_t d[46][46] = {};
        constexpr uint32_t CAP = 1000000;
        d[n][m] = 1;
        for (int p = n - 1; p >= 0; --p) {
            for (int k = m; k >= 0; --k) {
                uint64_t total = 0;
                if (!(kb & (1ULL << p))) total += d[p + 1][k];
                if (k < m) {
                    int e = p + a[k];
                    if (e <= n && !((((1ULL << a[k]) - 1) << p) & kw)) {
                        int q = e;
                        if (k + 1 < m) {
                            if (e < n && !(kb & (1ULL << e))) q = e + 1;
                            else q = n + 1;
                        }
                        if (q <= n) total += d[q][k + 1];
                    }
                }
                d[p][k] = static_cast<uint32_t>(min<uint64_t>(total, CAP));
            }
        }
        return d[0][0];
    }

    bool generate(int type, int index, int p, int k, uint64_t pattern,
                  uint64_t kb, uint64_t kw,
                  const vector<uint64_t>& b0, const vector<uint64_t>& w0,
                  const vector<uint64_t>& b1, const vector<uint64_t>& w1) {
        const int n = length(type);
        const vector<int>& a = clues[type][index];
        const int m = static_cast<int>(a.size());
        if (p == n) {
            if (k != m) return false;
            restore(b0, w0, b1, w1);
            for (int i = 0; i < n; ++i) {
                uint64_t bit = 1ULL << i, cross = 1ULL << index;
                bool isBlack = pattern & bit;
                int other = type ^ 1;
                if (isBlack) {
                    black[type][index] |= bit;
                    black[other][i] |= cross;
                } else {
                    white[type][index] |= bit;
                    white[other][i] |= cross;
                }
                enqueue(other, i);
            }
            enqueue(type, index);
            return dfs();
        }
        // White first tends to avoid filling the many singleton blocks too early.
        if (!(kb & (1ULL << p)) &&
            generate(type, index, p + 1, k, pattern, kb, kw, b0, w0, b1, w1))
            return true;
        if (k < m) {
            int e = p + a[k];
            uint64_t mask = e <= n ? (((1ULL << a[k]) - 1) << p) : 0;
            if (e <= n && !(mask & kw)) {
                int q = e;
                if (k + 1 < m) {
                    if (e < n && !(kb & (1ULL << e))) q = e + 1;
                    else q = n + 1;
                }
                if (q <= n && generate(type, index, q, k + 1, pattern | mask,
                                       kb, kw, b0, w0, b1, w1))
                    return true;
            }
        }
        return false;
    }

    bool dfs() {
        if (!propagate()) return false;
        probeConflict = false;
        while (!complete() && probe()) {}
        if (probeConflict) return false;
        if (complete()) return true;
        ++guesses;

        int bestType = -1, bestIndex = -1;
        uint32_t bestWays = 1000001;
        for (int type = 0; type < 2; ++type) {
            uint64_t full = (1ULL << length(type)) - 1;
            for (int i = 0; i < count(type); ++i) {
                if ((black[type][i] | white[type][i]) == full) continue;
                uint32_t ways = lineWays(type, i);
                if (ways == 0) return false;
                if (ways < bestWays) {
                    bestWays = ways;
                    bestType = type;
                    bestIndex = i;
                    if (ways == 2) break;
                }
            }
            if (bestWays == 2) break;
        }
        if (bestType < 0) return false;
        vector<uint64_t> b0 = black[0], w0 = white[0];
        vector<uint64_t> b1 = black[1], w1 = white[1];
        uint64_t kb = black[bestType][bestIndex];
        uint64_t kw = white[bestType][bestIndex];
        bool ok = generate(bestType, bestIndex, 0, 0, 0, kb, kw, b0, w0, b1, w1);
        if (!ok) restore(b0, w0, b1, w1);
        return ok;
    }

    bool solve() {
        for (int r = 0; r < h; ++r) enqueue(0, r);
        for (int c = 0; c < w; ++c) enqueue(1, c);
        return dfs();
    }
};

static vector<int> parseClues(const string& text) {
    vector<int> result;
    istringstream in(text);
    int x;
    while (in >> x) {
        if (x != 0) result.push_back(x);
    }
    return result;
}

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    string line;
    while (getline(cin, line)) {
        if (line.empty()) continue;
        istringstream header(line);
        string tag, id;
        int h, w;
        if (!(header >> tag >> id >> h >> w) || tag != "PUZZLE") continue;
        vector<vector<int>> rows(h), cols(w);
        for (auto& clue : rows) {
            getline(cin, line);
            clue = parseClues(line);
        }
        for (auto& clue : cols) {
            getline(cin, line);
            clue = parseClues(line);
        }
        Solver solver(h, w, std::move(rows), std::move(cols));
        bool solved = solver.solve();
        cerr << id << " lines=" << solver.lineCalls << " probes=" << solver.probeCalls
             << " forced=" << solver.forced << " guesses=" << solver.guesses << '\n';
        if (!solved) {
            cout << "UNSOLVED " << id << '\n' << flush;
            continue;
        }
        cout << "SOLUTION " << id << '\n';
        for (int r = 0; r < h; ++r) {
            for (int c = 0; c < w; ++c)
                cout << ((solver.black[0][r] & (1ULL << c)) ? '#' : '.');
            cout << '\n';
        }
        cout << flush;
    }
    return 0;
}
