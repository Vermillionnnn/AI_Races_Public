#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <numeric>
#include <queue>
#include <random>
#include <fstream>
#include <thread>
#include <mutex>
#include <atomic>
#include <chrono>
#include <filesystem>
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
    long long firstProbes = 0, firstGuesses = 0, firstLines = 0;
    int solutions = 0;
    vector<uint64_t> firstGrid;
    bool probeConflict = false;
    bool aborted = false;
    bool stopAfterFirst = false;
    bool useProbes = true;
    long long guessLimit = 1000;

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
        if (useProbes) while (!complete() && probe()) {}
        if (probeConflict) return false;
        if (complete()) {
            if (solutions == 0) {
                firstGrid = black[0];
                firstProbes = probeCalls;
                firstGuesses = guesses;
                firstLines = lineCalls;
            }
            ++solutions;
            return stopAfterFirst || solutions >= 2;
        }
        ++guesses;
        if (guesses > guessLimit) {
            aborted = true;
            return true;
        }

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

static vector<int> blocks(uint64_t bits, int n) {
    vector<int> out;
    int run = 0;
    for (int i = 0; i < n; ++i) {
        if (bits & (1ULL << i)) ++run;
        else if (run) { out.push_back(run); run = 0; }
    }
    if (run) out.push_back(run);
    return out;
}

struct Candidate {
    int serial = 0, h = 0, w = 0;
    vector<uint64_t> grid;
    vector<vector<int>> rows, cols;
    long long score = 0, probes = 0, guesses = 0, lines = 0;
};

static void writeClue(ostream& out, const vector<int>& clue) {
    if (clue.empty()) { out << '0'; return; }
    for (size_t i = 0; i < clue.size(); ++i) {
        if (i) out << ' ';
        out << clue[i];
    }
}

static int variantsMain(int threadCount, int baseCount, int variantsEach) {
    ifstream puzzles(std::filesystem::path(u8"题目.txt"));
    ifstream answers(std::filesystem::path(u8"答案.txt"));
    vector<Candidate> bases;
    string line;
    for (int i = 0; i < baseCount; ++i) {
        Candidate c;
        string id;
        if (!getline(puzzles, line)) return 2;
        istringstream header(line);
        if (!(header >> id >> id >> c.h >> c.w)) return 2;
        for (int j = 0; j < c.h + c.w; ++j) getline(puzzles, line);
        if (!getline(answers, line)) return 2;
        for (int r = 0; r < c.h; ++r) {
            if (!getline(answers, line)) return 2;
            uint64_t bits = 0;
            for (int col = 0; col < c.w; ++col)
                if (line[col] == '#') bits |= 1ULL << col;
            c.grid.push_back(bits);
        }
        for (int r = 0; r < c.h; ++r) c.rows.push_back(blocks(c.grid[r], c.w));
        for (int col = 0; col < c.w; ++col) {
            uint64_t bits = 0;
            for (int r = 0; r < c.h; ++r) if (c.grid[r] & (1ULL << col)) bits |= 1ULL << r;
            c.cols.push_back(blocks(bits, c.h));
        }
        bases.push_back(std::move(c));
    }
    puzzles.close(); answers.close();
    int total = baseCount * variantsEach;
    atomic<int> next(0), finished(0);
    mutex mu;
    vector<Candidate> accepted;
    auto worker = [&]() {
        while (true) {
            int serial = next++;
            if (serial >= total) break;
            int bi = serial % baseCount;
            const Candidate& base = bases[bi];
            mt19937_64 rng(0xd1b54a32d192ed03ULL * (serial + 1));
            vector<int> pr(base.h), pc(base.w);
            iota(pr.begin(), pr.end(), 0); iota(pc.begin(), pc.end(), 0);
            shuffle(pr.begin(), pr.end(), rng); shuffle(pc.begin(), pc.end(), rng);
            Candidate c;
            c.serial = serial; c.h = base.h; c.w = base.w; c.grid.resize(c.h);
            for (int r = 0; r < c.h; ++r) {
                for (int col = 0; col < c.w; ++col)
                    if (base.grid[pr[r]] & (1ULL << pc[col])) c.grid[r] |= 1ULL << col;
                c.rows.push_back(blocks(c.grid[r], c.w));
            }
            for (int col = 0; col < c.w; ++col) {
                uint64_t bits = 0;
                for (int r = 0; r < c.h; ++r) if (c.grid[r] & (1ULL << col)) bits |= 1ULL << r;
                c.cols.push_back(blocks(bits, c.h));
            }
            Solver solver(c.h, c.w, c.rows, c.cols);
            solver.stopAfterFirst = true; solver.guessLimit = 5000;
            solver.solve();
            if (solver.solutions == 1 && !solver.aborted && solver.firstGrid == c.grid) {
                c.probes = solver.firstProbes; c.guesses = solver.firstGuesses;
                c.lines = solver.firstLines; c.score = c.probes + 1000 * c.guesses;
                lock_guard<mutex> lock(mu); accepted.push_back(std::move(c));
            }
            if (++finished % 50 == 0) {
                lock_guard<mutex> lock(mu);
                cerr << "variants=" << finished << "/" << total << " usable=" << accepted.size() << '\n';
            }
        }
    };
    vector<thread> threads;
    for (int i = 0; i < threadCount; ++i) threads.emplace_back(worker);
    for (auto& t : threads) t.join();
    sort(accepted.begin(), accepted.end(), [](const Candidate& a, const Candidate& b) {
        return a.score > b.score;
    });
    cerr << "variant accepted=" << accepted.size() << '\n';
    if (accepted.size() < 120) return 2;
    accepted.resize(120);
    ofstream outPuzzles(std::filesystem::path(u8"题目.txt"));
    ofstream outAnswers(std::filesystem::path(u8"答案.txt"));
    for (int i = 0; i < 120; ++i) {
        const Candidate& c = accepted[i];
        outPuzzles << "PUZZLE k2-" << (i + 1) << ' ' << c.h << ' ' << c.w << '\n';
        for (const auto& clue : c.rows) { writeClue(outPuzzles, clue); outPuzzles << '\n'; }
        for (const auto& clue : c.cols) { writeClue(outPuzzles, clue); outPuzzles << '\n'; }
        outAnswers << "SOLUTION k2-" << (i + 1) << '\n';
        for (int r = 0; r < c.h; ++r) {
            for (int col = 0; col < c.w; ++col)
                outAnswers << ((c.grid[r] & (1ULL << col)) ? '#' : '.');
            outAnswers << '\n';
        }
        cerr << (i + 1) << " src=" << c.serial << " size=" << c.h << 'x' << c.w
             << " score=" << c.score << " probes=" << c.probes << " guesses=" << c.guesses << '\n';
    }
    return 0;
}

int main(int argc, char** argv) {
    if (argc > 1 && string(argv[1]) == "variants")
        return variantsMain(argc > 2 ? atoi(argv[2]) : 8,
                            argc > 3 ? atoi(argv[3]) : 8,
                            argc > 4 ? atoi(argv[4]) : 160);
    int total = argc > 1 ? atoi(argv[1]) : 240;
    int threadCount = argc > 2 ? atoi(argv[2]) : 8;
    int minSize = argc > 3 ? atoi(argv[3]) : 40;
    int maxSize = argc > 4 ? atoi(argv[4]) : 45;
    int density = argc > 5 ? atoi(argv[5]) : 50;
    uint64_t seed = argc > 6 ? stoull(argv[6]) : 1;
    long long guessLimit = argc > 7 ? atoll(argv[7]) : 1000;
    long long proofLimit = argc > 8 ? atoll(argv[8]) : 5000;
    long long minGuesses = argc > 9 ? atoll(argv[9]) : 2;
    long long minProbes = argc > 10 ? atoll(argv[10]) : 1000;
    atomic<int> next(0), finished(0);
    mutex mu;
    vector<Candidate> accepted;
    auto worker = [&]() {
        while (true) {
            int serial = next++;
            if (serial >= total) break;
            mt19937_64 rng(seed + 0x9e3779b97f4a7c15ULL * (serial + 1));
            int h = minSize + rng() % (maxSize - minSize + 1);
            int w = minSize + rng() % (maxSize - minSize + 1);
            Candidate c;
            c.serial = serial; c.h = h; c.w = w;
            c.grid.resize(h);
            for (int r = 0; r < h; ++r) {
                uint64_t bits = 0;
                for (int col = 0; col < w; ++col)
                    if (static_cast<int>(rng() % 100) < density) bits |= 1ULL << col;
                c.grid[r] = bits;
            }
            for (int r = 0; r < h; ++r) c.rows.push_back(blocks(c.grid[r], w));
            for (int col = 0; col < w; ++col) {
                uint64_t bits = 0;
                for (int r = 0; r < h; ++r) if (c.grid[r] & (1ULL << col)) bits |= 1ULL << r;
                c.cols.push_back(blocks(bits, h));
            }
            Solver quick(h, w, c.rows, c.cols);
            quick.guessLimit = guessLimit;
            quick.stopAfterFirst = true;
            quick.solve();
            bool hard = quick.firstGuesses >= minGuesses || quick.firstProbes >= minProbes;
            if (quick.solutions == 1 && !quick.aborted && quick.firstGrid == c.grid && hard) {
                Solver proof(h, w, c.rows, c.cols);
                proof.useProbes = false;
                proof.guessLimit = proofLimit;
                proof.solve();
                if (proof.solutions == 1 && !proof.aborted && proof.firstGrid == c.grid) {
                    c.probes = quick.firstProbes;
                    c.guesses = quick.firstGuesses;
                    c.lines = quick.firstLines;
                    c.score = c.probes + 1000 * c.guesses;
                    lock_guard<mutex> lock(mu);
                    accepted.push_back(std::move(c));
                }
            }
            int done = ++finished;
            if (done % 10 == 0) {
                lock_guard<mutex> lock(mu);
                cerr << "done=" << done << "/" << total << " unique=" << accepted.size()
                     << " last(sol=" << quick.solutions << ",abort=" << quick.aborted
                     << ",p=" << quick.firstProbes << ",g=" << quick.firstGuesses << ")\n";
            }
        }
    };
    vector<thread> threads;
    for (int i = 0; i < threadCount; ++i) threads.emplace_back(worker);
    for (auto& t : threads) t.join();
    sort(accepted.begin(), accepted.end(), [](const Candidate& a, const Candidate& b) {
        return a.score > b.score;
    });
    cerr << "accepted=" << accepted.size() << '\n';
    if (accepted.size() < 120) return 2;
    accepted.resize(120);
    ofstream puzzles(std::filesystem::path(u8"题目.txt"));
    ofstream answers(std::filesystem::path(u8"答案.txt"));
    for (int i = 0; i < 120; ++i) {
        const Candidate& c = accepted[i];
        puzzles << "PUZZLE k2-" << (i + 1) << ' ' << c.h << ' ' << c.w << '\n';
        for (const auto& clue : c.rows) { writeClue(puzzles, clue); puzzles << '\n'; }
        for (const auto& clue : c.cols) { writeClue(puzzles, clue); puzzles << '\n'; }
        answers << "SOLUTION k2-" << (i + 1) << '\n';
        for (int r = 0; r < c.h; ++r) {
            for (int col = 0; col < c.w; ++col)
                answers << ((c.grid[r] & (1ULL << col)) ? '#' : '.');
            answers << '\n';
        }
        cerr << (i + 1) << " src=" << c.serial << " size=" << c.h << 'x' << c.w
             << " score=" << c.score << " probes=" << c.probes << " guesses=" << c.guesses << '\n';
    }
    return 0;
}
