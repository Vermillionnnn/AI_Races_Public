#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <cstdint>
#include <exception>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <random>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace {

using Bits = std::uint64_t;
constexpr int maxSide = 45;
constexpr int maxRuns = (maxSide + 1) / 2;

constexpr Bits bit(int index) { return Bits{1} << index; }
constexpr Bits lowBits(int count) { return bit(count) - 1; }

int popFirst(Bits& bits) {
    const int index = std::countr_zero(bits);
    bits &= bits - 1;
    return index;
}

struct Cells {
    Bits black = 0;
    Bits white = 0;

    Bits known() const { return black | white; }
};

struct Clue {
    std::array<int, maxRuns> runs{};
    std::array<Bits, maxRuns> startBounds{};
    Bits mask = 0;
    int count = 0;
    int maxRun = 0;
    int length = 0;

    void init(Bits black, int lineLength) {
        length = lineLength;
        mask = lowBits(length);
        int span = 0;
        for (Bits remaining = black; remaining;) {
            remaining >>= std::countr_zero(remaining);
            const int run = std::countr_one(remaining);
            remaining >>= run;
            runs[count++] = run;
            span += run + 1;
            maxRun = std::max(maxRun, run);
        }
        if (count) {
            const int slack = length - (span - 1);
            int first = 0;
            for (int i = 0; i < count; ++i) {
                startBounds[i] = lowBits(slack + 1) << first;
                first += runs[i] + 1;
            }
        }
    }

    bool matches(Bits black) const {
        for (int i = 0; i < count; ++i) {
            if (!black) {
                return false;
            }
            black >>= std::countr_zero(black);
            if (std::countr_one(black) != runs[i]) {
                return false;
            }
            black >>= runs[i];
        }
        return black == 0;
    }
};

using Grid = std::array<Bits, maxSide>;

struct Puzzle {
    int height;
    int width;
    std::array<Clue, maxSide> rows;
    std::array<Clue, maxSide> cols;

    Puzzle(const Grid& grid, int h, int w) : height(h), width(w) {
        Grid columns{};
        for (int r = 0; r < height; ++r) {
            rows[r].init(grid[r], width);
            for (Bits black = grid[r]; black;) {
                columns[popFirst(black)] |= bit(r);
            }
        }
        for (int c = 0; c < width; ++c) {
            cols[c].init(columns[c], height);
        }
    }
};

// A carry crosses a cell exactly when a white cell is allowed there.
Bits extendRight(Bits seeds, Bits pass) {
    return seeds | ((pass + (pass & seeds)) ^ pass);
}

struct LeftClosure {
    Bits p1;
    Bits p2;
    Bits p4;
    Bits p8;
    Bits p16;
    Bits p32;

    explicit LeftClosure(Bits pass)
        : p1(pass), p2(p1 & (p1 >> 1)), p4(p2 & (p2 >> 2)),
          p8(p4 & (p4 >> 4)), p16(p8 & (p8 >> 8)), p32(p16 & (p16 >> 16)) {}

    Bits extend(Bits seeds) const {
        seeds |= (seeds >> 1) & p1;
        seeds |= (seeds >> 2) & p2;
        seeds |= (seeds >> 4) & p4;
        seeds |= (seeds >> 8) & p8;
        seeds |= (seeds >> 16) & p16;
        seeds |= (seeds >> 32) & p32;
        return seeds;
    }
};

Bits coverRuns(Bits starts, int length) {
    // Every left shift adds up to the current number of consecutive cells.
    for (int filled = 1; filled < length;) {
        const int step = std::min(filled, length - filled);
        starts |= starts << step;
        filled += step;
    }
    return starts;
}

bool deduce(const Clue& clue, Cells cells, Cells& result) {
    const Bits unknown = clue.mask & ~cells.known();
    if (!unknown) {
        return clue.matches(cells.black);
    }
    if (!clue.count) {
        result.white = unknown;
        return cells.black == 0;
    }

    const Bits pass = clue.mask & ~cells.black;
    const Bits end = bit(clue.length);
    std::array<Bits, maxSide + 1> fits;
    std::array<Bits, maxRuns> starts;
    std::array<Bits, maxRuns> forward;
    fits[1] = clue.mask & ~cells.white;
    for (int n = 2; n <= clue.maxRun; ++n) {
        fits[n] = fits[n - 1] & (fits[n - 1] >> 1);
    }

    // The bit at a boundary is set if all preceding clues can end by there.
    const Bits firstGap = extendRight(1, pass);
    Bits reach = firstGap;
    for (int i = 0; i < clue.count; ++i) {
        starts[i] = reach & fits[clue.runs[i]] & clue.startBounds[i];
        if (!starts[i]) {
            return false;
        }
        forward[i] = extendRight(starts[i] << clue.runs[i], pass);
        reach = (forward[i] & pass) << 1;
    }
    if (!(forward[clue.count - 1] & end)) {
        return false;
    }

    // Intersect with the reverse path to keep only placements on full paths.
    // A white cell is viable when its incoming and outgoing boundaries meet
    // in the same gap. That single white step also satisfies a required gap.
    const LeftClosure left(pass);
    Bits suffix = left.extend(end);
    Bits ends = suffix;
    Bits possibleBlack = 0;
    Bits possibleWhite = 0;
    for (int i = clue.count - 1; i >= 0; --i) {
        const Bits whiteStep = (suffix >> 1) & pass;
        possibleWhite |= forward[i] & whiteStep;
        const Bits viableStarts = starts[i] & (ends >> clue.runs[i]);
        possibleBlack |= coverRuns(viableStarts, clue.runs[i]);
        if ((possibleBlack & possibleWhite & unknown) == unknown) {
            return true;
        }
        suffix = left.extend(viableStarts);
        ends = (suffix >> 1) & pass;
    }
    possibleWhite |= firstGap & (suffix >> 1) & pass;
    result.black = unknown & ~possibleWhite;
    result.white = unknown & ~possibleBlack;
    return true;
}

struct Effort {
    std::uint64_t calls = 0;
    std::uint64_t misses = 0;
    std::uint64_t uncachedWork = 0;
    std::uint64_t probes = 0;
    std::uint64_t branches = 0;
    int initialUnknown = 0;

    std::uint64_t weight() const {
        return uncachedWork + calls * 2 + probes * 32;
    }
};

struct MemoEntry {
    Bits key = 0;
    Bits white = 0;
    Cells result;
};

struct LineMemo {
    static constexpr int slotBits = 9;
    std::array<MemoEntry, 1 << slotBits> entries;

    bool lookup(const Clue& clue, Cells cells, Bits stamp, Cells& result, Effort& effort) {
        ++effort.calls;
        // Short lines leave 16 bits in the key for identifying the puzzle.
        const Bits key = cells.black | stamp;
        const Bits hash = (cells.black * 0x9e3779b97f4a7c15ULL) ^
                          (cells.white * 0xbf58476d1ce4e5b9ULL);
        auto& entry = entries[hash >> (64 - slotBits)];
        if (entry.key == key && entry.white == cells.white) {
            result = entry.result;
            return result.black != ~Bits{0};
        }
        ++effort.misses;
        effort.uncachedWork += 22 + 5 * clue.count;
        const bool feasible = deduce(clue, cells, result);
        entry = {key, cells.white, feasible ? result : Cells{~Bits{0}, 0}};
        return feasible;
    }
};

struct MemoBank {
    std::array<LineMemo, maxSide> rows;
    std::array<LineMemo, maxSide> cols;
    std::uint16_t generation = 0;

    Bits nextPuzzle() {
        if (++generation == 0) {
            for (auto& line : rows) {
                line.entries.fill({});
            }
            for (auto& line : cols) {
                line.entries.fill({});
            }
            ++generation;
        }
        return Bits{generation} << 48;
    }
};

struct Board {
    std::array<Cells, maxSide> rows{};
    std::array<Cells, maxSide> cols{};
    int unknown = 0;

    void set(int r, int c, bool black) {
        if (black) {
            rows[r].black |= bit(c);
            cols[c].black |= bit(r);
        } else {
            rows[r].white |= bit(c);
            cols[c].white |= bit(r);
        }
        --unknown;
    }
};

struct Lines {
    Bits rows = 0;
    Bits cols = 0;

    void add(Lines other) {
        rows |= other.rows;
        cols |= other.cols;
    }

    bool overlaps(Lines other) const {
        return (rows & other.rows) || (cols & other.cols);
    }
};

struct Candidate {
    int row = 0;
    int col = 0;
    bool preferBlack = true;
};

struct ProbeChoice {
    int cell = -1;
    int gain = -1;
};

enum class ProbeResult { exhausted, advanced, solved, impossible };

struct ProbeMemo {
    Lines dependencies;
    int stage = -1;
    int gain = -1;
    bool preferBlack = true;
};

struct Alternative {
    Board board;
    int row;
    int col;
};

enum class Verdict { unique, multiple, budget };

struct PairKey {
    Bits black;
    Bits white;

    bool operator==(const PairKey&) const = default;
};

struct PairHash {
    std::size_t operator()(PairKey key) const {
        return static_cast<std::size_t>(
            (key.black * 0x9e3779b97f4a7c15ULL) ^ (key.white * 0xd6e8feb86659fd93ULL));
    }
};

using ExactCache = std::array<std::unordered_map<PairKey, MemoEntry, PairHash>, 2 * maxSide>;

class Solver {
public:
    Solver(const Puzzle& puzzle, MemoBank& memo, Effort& effort)
        : puzzle(puzzle), memo(memo), effort(effort), stamp(memo.nextPuzzle()) {}

    Verdict prove(const Grid& answer, std::uint64_t limit, Grid* alternative = nullptr) {
        Board board;
        board.unknown = puzzle.height * puzzle.width;
        if (!propagate(board, {lowBits(puzzle.height), lowBits(puzzle.width)})) {
            throw std::logic_error("The generated grid must satisfy its own clues");
        }
        effort.initialUnknown = board.unknown;
        std::vector<Alternative> pending;
        known = &answer;
        other = alternative;
        bool foundAnswer = false;

        for (;;) {
            if (effort.calls >= limit) {
                return Verdict::budget;
            }
            Candidate branch;
            const auto result = proofProbe(board, branch, limit);
            if (result == ProofState::different) {
                return Verdict::multiple;
            }
            if (result == ProofState::limited) {
                return Verdict::budget;
            }
            if (result == ProofState::stalled) {
                const int r = branch.row;
                const int c = branch.col;
                const bool first = !(answer[r] & bit(c));
                pending.push_back({board, r, c});
                pending.back().board.set(r, c, !first);
                board.set(r, c, first);
                ++effort.branches;
                if (propagate(board, {bit(r), bit(c)})) {
                    continue;
                }
            }
            if (result == ProofState::complete) {
                if (!verify(board)) {
                    throw std::logic_error("An inconsistent complete board survived");
                }
                if (different(board)) {
                    return Verdict::multiple;
                }
                foundAnswer = true;
            }
            for (;;) {
                if (pending.empty()) {
                    if (!foundAnswer) {
                        throw std::logic_error("Uniqueness search discarded the given solution");
                    }
                    return Verdict::unique;
                }
                const Alternative& alt = pending.back();
                board = alt.board;
                const Lines affected{bit(alt.row), bit(alt.col)};
                pending.pop_back();
                if (propagate(board, affected)) {
                    break;
                }
            }
        }
    }

    // A separate workload model uses complete rounds of trial assignments and
    // counts new line states as well as repeat work. It does not time a solver.
    Effort measure(std::uint64_t stopWork, ExactCache& exact) {
        for (auto& line : exact) {
            line.clear();
        }
        meterCache = &exact;
        Board board;
        board.unknown = puzzle.height * puzzle.width;
        propagate(board, {lowBits(puzzle.height), lowBits(puzzle.width)});
        effort.initialUnknown = board.unknown;
        std::vector<Alternative> pending;
        for (;;) {
            if (!board.unknown || effort.weight() >= stopWork) {
                return effort;
            }
            Candidate branch;
            if (measureStage(board, branch, stopWork)) {
                if (!board.unknown || effort.weight() >= stopWork) {
                    return effort;
                }
                const auto [r, c, black] = branch;
                pending.push_back({board, r, c});
                pending.back().board.set(r, c, !black);
                board.set(r, c, black);
                ++effort.branches;
                if (propagate(board, {bit(r), bit(c)})) {
                    continue;
                }
            }
            for (;;) {
                if (pending.empty()) {
                    return effort;
                }
                const auto& alt = pending.back();
                board = alt.board;
                const Lines affected{bit(alt.row), bit(alt.col)};
                pending.pop_back();
                if (propagate(board, affected)) {
                    break;
                }
            }
        }
    }

private:
    const Puzzle& puzzle;
    MemoBank& memo;
    Effort& effort;
    const Bits stamp;
    ExactCache* meterCache = nullptr;
    const Grid* known = nullptr;
    Grid* other = nullptr;

    enum class ProofState { stalled, complete, contradiction, different, limited };

    bool different(const Board& board) {
        for (int r = 0; r < puzzle.height; ++r) {
            if (board.rows[r].black != (*known)[r]) {
                if (other) {
                    for (int i = 0; i < puzzle.height; ++i) {
                        (*other)[i] = board.rows[i].black;
                    }
                }
                return true;
            }
        }
        return false;
    }

    bool line(int index, const Clue& clue, Cells cells, LineMemo& cache, Cells& result) const {
        if (!meterCache) {
            return cache.lookup(clue, cells, stamp, result, effort);
        }
        ++effort.calls;
        auto& entries = (*meterCache)[index];
        const PairKey key{cells.black, cells.white};
        const auto found = entries.find(key);
        if (found != entries.end()) {
            result = found->second.result;
            return result.black != ~Bits{0};
        }
        ++effort.misses;
        effort.uncachedWork += 22 + 5 * clue.count;
        const bool feasible = deduce(clue, cells, result);
        entries.emplace(key, MemoEntry{0, 0, feasible ? result : Cells{~Bits{0}, 0}});
        return feasible;
    }
    static constexpr int historySize = 32;
    static constexpr int focusLimit = 50;
    static constexpr int probeLimit = 55;
    static constexpr int branchThreshold = 150;
    static constexpr int neighborWeight = 40;
    static constexpr int maxProbeBonus = 100;
    static constexpr int priorities = 2 * maxSide + 4 * neighborWeight + maxProbeBonus + 1;
    std::array<ProbeMemo, maxSide * maxSide> probes;
    std::array<Lines, historySize> changed;
    std::array<int, maxSide * maxSide> next;
    std::array<int, priorities> head;

    bool sweep(std::array<Cells, maxSide>& lines, std::array<Cells, maxSide>& cross,
               const std::array<Clue, maxSide>& clues, std::array<LineMemo, maxSide>& cache,
               Bits pending, Bits& next, int& unknown, int axisOffset = 0) const {
        while (pending) {
            const int line = popFirst(pending);
            Cells result;
            if (!this->line(axisOffset + line, clues[line], lines[line], cache[line], result)) {
                return false;
            }
            lines[line].black |= result.black;
            lines[line].white |= result.white;
            next |= result.known();
            const Bits coordinate = bit(line);
            while (result.black) {
                cross[popFirst(result.black)].black |= coordinate;
                --unknown;
            }
            while (result.white) {
                cross[popFirst(result.white)].white |= coordinate;
                --unknown;
            }
        }
        return true;
    }

    bool propagate(Board& board, Lines pending, Lines* dependencies = nullptr) const {
        while (pending.rows || pending.cols) {
            if (dependencies) {
                dependencies->rows |= pending.rows;
            }
            if (!sweep(board.rows, board.cols, puzzle.rows, memo.rows,
                       pending.rows, pending.cols, board.unknown)) {
                return false;
            }
            pending.rows = 0;
            if (dependencies) {
                dependencies->cols |= pending.cols;
            }
            if (!sweep(board.cols, board.rows, puzzle.cols, memo.cols,
                       pending.cols, pending.rows, board.unknown, maxSide)) {
                return false;
            }
            pending.cols = 0;
        }
        return true;
    }

    void rank(const Board& board, int stage, Lines focus, ProbeChoice& best) {
        // A probe stays valid if none of the lines it examined have changed.
        // Rank only the cells whose trials still need to be run.
        head.fill(-1);
        int colKnown[maxSide];
        Bits north[maxSide];
        Bits south[maxSide];
        for (int c = 0; c < puzzle.width; ++c) {
            const Bits known = board.cols[c].known();
            colKnown[c] = std::popcount(known);
            north[c] = (known << 1) | 1;
            south[c] = (known >> 1) | bit(puzzle.height - 1);
        }
        for (int r = 0; r < puzzle.height; ++r) {
            const Bits known = board.rows[r].known();
            const Bits west = (known << 1) | 1;
            const Bits east = (known >> 1) | bit(puzzle.width - 1);
            const int rowKnown = std::popcount(known);
            Bits unknown = puzzle.rows[r].mask & ~known;
            if (!(focus.rows & bit(r))) {
                unknown &= focus.cols;
            }
            while (unknown) {
                const int c = popFirst(unknown);
                const int cell = r * maxSide + c;
                const ProbeMemo& memo = probes[cell];
                if (memo.stage >= 0 && stage - memo.stage < historySize &&
                    !memo.dependencies.overlaps(changed[memo.stage % historySize])) {
                    if (memo.gain > best.gain) {
                        best = {cell, memo.gain};
                    }
                    continue;
                }
                const int neighbors = ((west >> c) & 1) + ((east >> c) & 1) +
                                      ((north[c] >> r) & 1) + ((south[c] >> r) & 1);
                const int extra = std::min(maxProbeBonus, std::max(0, memo.gain - 11) / 4);
                const int priority = neighborWeight * neighbors + rowKnown + colKnown[c] + extra;
                next[cell] = head[priority];
                head[priority] = cell;
            }
        }
    }

    Lines merge(Board& board, const Board& black, const Board& white,
                Bits touchedRows) const {
        Lines changed;
        while (touchedRows) {
            const int r = popFirst(touchedRows);
            const Bits extraBlack = (black.rows[r].black & white.rows[r].black) & ~board.rows[r].black;
            const Bits extraWhite = (black.rows[r].white & white.rows[r].white) & ~board.rows[r].white;
            if (!(extraBlack | extraWhite)) {
                continue;
            }
            changed.rows |= bit(r);
            changed.cols |= extraBlack | extraWhite;
            for (Bits bits = extraBlack; bits;) {
                board.set(r, popFirst(bits), true);
            }
            for (Bits bits = extraWhite; bits;) {
                board.set(r, popFirst(bits), false);
            }
        }
        return changed;
    }

    static void restore(Board& trial, const Board& base, Lines touched) {
        trial.unknown = base.unknown;
        while (touched.rows) {
            const int r = popFirst(touched.rows);
            trial.rows[r] = base.rows[r];
        }
        while (touched.cols) {
            const int c = popFirst(touched.cols);
            trial.cols[c] = base.cols[c];
        }
    }

    void recordProgress(const Board& before, const Board& after, int& stage) {
        Lines dirty;
        for (int r = 0; r < puzzle.height; ++r) {
            const Bits delta = after.rows[r].known() ^ before.rows[r].known();
            if (delta) {
                dirty.rows |= bit(r);
                dirty.cols |= delta;
            }
        }
        const int first = std::max(0, stage - historySize + 1);
        for (int i = first; i <= stage; ++i) {
            changed[i % historySize].add(dirty);
        }
        ++stage;
        changed[stage % historySize] = {};
    }

    ProbeResult scanCandidates(Board& board, int& stage, int limit,
                               int& checked, ProbeChoice& best) {
        Board black = board;
        Board white = board;
        for (int p = priorities - 1; p >= 0; --p) {
            for (int cell = head[p]; cell >= 0; cell = next[cell]) {
                if (checked >= limit || (checked >= probeLimit && best.gain >= branchThreshold)) {
                    return ProbeResult::exhausted;
                }
                ++checked;
                ++effort.probes;
                const int r = cell / maxSide;
                const int c = cell % maxSide;
                black.set(r, c, true);
                white.set(r, c, false);
                Lines blackSeen;
                const bool blackOK = propagate(black, {bit(r), bit(c)}, &blackSeen);
                if (blackOK && !black.unknown && different(black)) {
                    return ProbeResult::solved;
                }
                Lines whiteSeen;
                const bool whiteOK = propagate(white, {bit(r), bit(c)}, &whiteSeen);
                if (whiteOK && !white.unknown && different(white)) {
                    return ProbeResult::solved;
                }
                if (!blackOK && !whiteOK) {
                    return ProbeResult::impossible;
                }
                if (!whiteOK || !blackOK) {
                    const Board& survivor = whiteOK ? white : black;
                    recordProgress(board, survivor, stage);
                    board = survivor;
                    return ProbeResult::advanced;
                }

                if (std::max(black.unknown, white.unknown) < board.unknown - 1) {
                    Board joined = board;
                    const Lines common = merge(joined, black, white, blackSeen.rows & whiteSeen.rows);
                    if (common.rows) {
                        if (!propagate(joined, common)) {
                            return ProbeResult::impossible;
                        }
                        recordProgress(board, joined, stage);
                        board = joined;
                        return ProbeResult::advanced;
                    }
                }
                const int minGain = board.unknown - std::max(black.unknown, white.unknown);
                const int maxGain = board.unknown - std::min(black.unknown, white.unknown);
                // Favor branches that make progress for either color.
                const int gain = minGain * 10 + maxGain;
                const bool preferBlack = black.unknown <= white.unknown;
                restore(black, board, blackSeen);
                restore(white, board, whiteSeen);
                blackSeen.add(whiteSeen);
                probes[cell] = {blackSeen, stage, gain, preferBlack};
                if (gain > best.gain) {
                    best = {cell, gain};
                }
            }
        }
        return ProbeResult::exhausted;
    }

    ProbeResult probeStage(Board& board, int& stage, ProbeChoice& best) {
        const Lines all{lowBits(puzzle.height), lowBits(puzzle.width)};
        int checked = 0;
        if (stage) {
            const Lines recent = changed[(stage - 1) % historySize];
            // Try the lines changed by the previous deduction first. If the
            // local scan stalls, the cached trials carry into the full scan.
            if (recent.rows != all.rows && recent.cols != all.cols) {
                rank(board, stage, recent, best);
                const ProbeResult result = scanCandidates(board, stage, focusLimit, checked, best);
                if (result != ProbeResult::exhausted) {
                    return result;
                }
            }
        }
        rank(board, stage, all, best);
        return scanCandidates(board, stage, maxSide * maxSide, checked, best);
    }

    ProofState proofProbe(Board& board, Candidate& branch, std::uint64_t limit) {
        for (ProbeMemo& memo : probes) {
            memo.stage = -1;
        }
        changed[0] = {};
        int stage = 0;
        while (board.unknown) {
            if (effort.calls >= limit) {
                return ProofState::limited;
            }
            ProbeChoice best;
            switch (probeStage(board, stage, best)) {
            case ProbeResult::exhausted:
                branch = {best.cell / maxSide, best.cell % maxSide, probes[best.cell].preferBlack};
                return ProofState::stalled;
            case ProbeResult::advanced:
                break;
            case ProbeResult::solved:
                return ProofState::different;
            case ProbeResult::impossible:
                return ProofState::contradiction;
            }
        }
        return ProofState::complete;
    }

    struct Measurement {
        Lines dependencies;
        int stage = -1;
        int minimum = 0;
        int maximum = 0;
    };

    bool measureStage(Board& board, Candidate& branch, std::uint64_t stopWork) {
        std::array<Measurement, maxSide * maxSide> tried;
        changed[0] = {};
        int stage = 0;
        for (;;) {
            const int start = stage;
            std::array<std::pair<int, int>, maxSide> order;
            for (int r = 0; r < puzzle.height; ++r) {
                order[r] = {puzzle.width - std::popcount(board.rows[r].known()), r};
            }
            std::sort(order.begin(), order.begin() + puzzle.height);
            std::pair<int, int> best{-1, -1};
            for (int i = 0; i < puzzle.height; ++i) {
                const int r = order[i].second;
                for (Bits cells = puzzle.rows[r].mask & ~board.rows[r].known(); cells;) {
                    if (!board.unknown || effort.weight() >= stopWork) {
                        return true;
                    }
                    const int c = popFirst(cells);
                    if (board.rows[r].known() & bit(c)) {
                        continue;
                    }
                    auto& rec = tried[r * maxSide + c];
                    if (rec.stage < 0 || stage - rec.stage >= historySize ||
                        rec.dependencies.overlaps(changed[rec.stage % historySize])) {
                        ++effort.probes;
                        Board black = board;
                        Board white = board;
                        Lines seen;
                        black.set(r, c, true);
                        white.set(r, c, false);
                        const bool b = propagate(black, {bit(r), bit(c)}, &seen);
                        const bool w = propagate(white, {bit(r), bit(c)}, &seen);
                        if (!b && !w) {
                            return false;
                        }
                        if ((b && black.unknown == 0) || (w && white.unknown == 0)) {
                            board = b && black.unknown == 0 ? black : white;
                            return true;
                        }
                        if (!b || !w) {
                            const Board& survivor = b ? black : white;
                            recordProgress(board, survivor, stage);
                            board = survivor;
                            continue;
                        }
                        Board combined = board;
                        const Lines common = merge(combined, black, white, seen.rows);
                        if (common.rows) {
                            if (!propagate(combined, common)) {
                                return false;
                            }
                            recordProgress(board, combined, stage);
                            board = combined;
                            continue;
                        }
                        const int g1 = board.unknown - black.unknown;
                        const int g2 = board.unknown - white.unknown;
                        rec = {seen, stage, std::min(g1, g2), std::max(g1, g2)};
                    }
                    const std::pair score{rec.minimum, rec.maximum};
                    if (score > best) {
                        best = score;
                        branch = {r, c, true};
                    }
                }
            }
            if (stage == start) {
                if (board.unknown && best.first >= 0) {
                    Board black = board;
                    Board white = board;
                    black.set(branch.row, branch.col, true);
                    white.set(branch.row, branch.col, false);
                    const Lines changed{bit(branch.row), bit(branch.col)};
                    const bool b = propagate(black, changed);
                    const bool w = propagate(white, changed);
                    branch.preferBlack = b && (!w || black.unknown <= white.unknown);
                }
                return true;
            }
        }
    }

    bool verify(const Board& board) const {
        for (int r = 0; r < puzzle.height; ++r) {
            if (!puzzle.rows[r].matches(board.rows[r].black)) {
                return false;
            }
        }
        for (int c = 0; c < puzzle.width; ++c) {
            if (!puzzle.cols[c].matches(board.cols[c].black)) {
                return false;
            }
        }
        return true;
    }
};
struct Entry {
    std::uint64_t seed = 0;
    int variant = 0;
    int height = 45;
    int width = 45;
    Grid grid{};
    Effort proof;
    Effort estimated;
};

void writeEntry(std::ostream& out, const Entry& entry) {
    out << entry.seed << ' ' << entry.variant << ' ' << entry.height << ' ' << entry.width
        << ' ' << entry.proof.calls << ' ' << entry.proof.misses << ' ' << entry.proof.probes
        << ' ' << entry.proof.branches << ' ' << entry.proof.initialUnknown;
    for (int r = 0; r < entry.height; ++r) {
        out << ' ' << std::hex << entry.grid[r] << std::dec;
    }
    out << '\n';
}

bool readEntry(std::istream& in, Entry& entry) {
    if (!(in >> entry.seed >> entry.variant >> entry.height >> entry.width
          >> entry.proof.calls >> entry.proof.misses >> entry.proof.probes
          >> entry.proof.branches >> entry.proof.initialUnknown)) {
        return false;
    }
    if (entry.height < 1 || entry.width < 1 || entry.height > maxSide || entry.width > maxSide) {
        throw std::runtime_error("bad candidate dimensions");
    }
    for (int r = 0; r < entry.height; ++r) {
        if (!(in >> std::hex >> entry.grid[r] >> std::dec) || (entry.grid[r] & ~lowBits(entry.width))) {
            throw std::runtime_error("bad candidate row");
        }
    }
    return true;
}

bool sameClue(Bits lhs, Bits rhs) {
    while (lhs && rhs) {
        lhs >>= std::countr_zero(lhs);
        rhs >>= std::countr_zero(rhs);
        const int run = std::countr_one(lhs);
        if (run != std::countr_one(rhs)) {
            return false;
        }
        lhs >>= run;
        rhs >>= run;
    }
    return !(lhs | rhs);
}

void breakAdjacentSwitches(Grid& grid, int h, int w, std::mt19937_64& rng) {
    Grid columns{};
    for (int r = 0; r < h; ++r) {
        for (Bits v = grid[r]; v;) {
            columns[popFirst(v)] |= bit(r);
        }
    }
    for (int r = 0; r + 1 < h; ++r) {
        for (int c = 0; c + 1 < w; ++c) {
            const Bits rPair = Bits{3} << r;
            const Bits cPair = Bits{3} << c;
            const Bits top = (grid[r] >> c) & 3;
            const Bits bottom = (grid[r + 1] >> c) & 3;
            if ((top != 1 && top != 2) || bottom != (top ^ 3)) {
                continue;
            }
            if (sameClue(grid[r], grid[r] ^ cPair) &&
                sameClue(grid[r + 1], grid[r + 1] ^ cPair) &&
                sameClue(columns[c], columns[c] ^ rPair) &&
                sameClue(columns[c + 1], columns[c + 1] ^ rPair)) {
                const int i = r + (rng() & 1);
                const int j = c + (rng() & 1);
                grid[i] ^= bit(j);
                columns[j] ^= bit(i);
            }
        }
    }
}

Entry generate(std::uint64_t seed, int family, std::mt19937_64& rng) {
    Entry entry;
    entry.seed = seed;
    const int cycle = static_cast<int>(seed % 20);
    const int density = family == 1 ? 493 + cycle * 3 : 470 + cycle * 4;
    std::array<int, maxSide> colBias{};
    if (family == 2) {
        for (int c = 0; c < entry.width; ++c) {
            colBias[c] = static_cast<int>(rng() % 89) - 44;
        }
    }
    for (int r = 0; r < entry.height; ++r) {
        const int bias = family == 2 ? static_cast<int>(rng() % 77) - 38 : 0;
        for (int c = 0; c < entry.width; ++c) {
            if (static_cast<int>(rng() % 1000) < density + bias + colBias[c]) {
                entry.grid[r] |= bit(c);
            }
        }
    }
    breakAdjacentSwitches(entry.grid, entry.height, entry.width, rng);
    return entry;
}

bool repair(Entry& entry, const Grid& alternate, std::mt19937_64& rng) {
    std::array<std::pair<int, int>, maxSide * maxSide> different;
    int count = 0;
    for (int r = 0; r < entry.height; ++r) {
        for (Bits diff = entry.grid[r] ^ alternate[r]; diff;) {
            different[count++] = {r, popFirst(diff)};
        }
    }
    if (!count) {
        return false;
    }
    const auto [r, c] = different[rng() % count];
    entry.grid[r] ^= bit(c);
    return true;
}

template <typename Function>
void parallelFor(std::uint64_t count, int workers, Function&& function) {
    if (workers < 1 || workers > 64) {
        throw std::invalid_argument("worker count must be between 1 and 64");
    }
    std::atomic<std::uint64_t> position{0};
    std::mutex latch;
    std::exception_ptr error;
    std::vector<std::thread> threads;
    for (int i = 0; i < workers; ++i) {
        threads.emplace_back([&] {
            try {
                auto memo = std::make_unique<MemoBank>();
                auto exact = std::make_unique<ExactCache>();
                for (;;) {
                    const auto index = position.fetch_add(1, std::memory_order_relaxed);
                    if (index >= count) {
                        break;
                    }
                    function(index, *memo, *exact);
                }
            } catch (...) {
                position.store(count, std::memory_order_relaxed);
                const std::lock_guard lock(latch);
                error = std::current_exception();
            }
        });
    }
    for (auto& thread : threads) {
        thread.join();
    }
    if (error) {
        std::rethrow_exception(error);
    }
}

void survey(std::uint64_t first, std::uint64_t count, int family, std::uint64_t limit, int workers) {
    if (family != 1 && family != 2) {
        throw std::invalid_argument("survey family must be 1 or 2");
    }
    std::mutex output;
    std::atomic<int> unique{0};
    std::atomic<int> hard{0};
    std::atomic<int> abandoned{0};
    std::atomic<int> processed{0};
    parallelFor(count, workers, [&](std::uint64_t index, MemoBank& memo, ExactCache&) {
        const auto seed = first + index;
        std::mt19937_64 rng(seed);
        Entry entry = generate(seed, family, rng);
        for (int round = 0; round < 7; ++round) {
            const Puzzle puzzle(entry.grid, entry.height, entry.width);
            Effort effort;
            Grid alternate{};
            const auto verdict = Solver(puzzle, memo, effort).prove(entry.grid, limit, &alternate);
            if (verdict == Verdict::unique) {
                entry.variant = family * 100 + round;
                entry.proof = effort;
                ++unique;
                if (effort.initialUnknown >= 320) {
                    ++hard;
                }
                const std::lock_guard lock(output);
                writeEntry(std::cout, entry);
                std::cout.flush();
                break;
            }
            if (verdict == Verdict::budget) {
                ++abandoned;
                break;
            }
            if (!repair(entry, alternate, rng)) {
                break;
            }
        }
        if (++processed % 100 == 0) {
            const std::lock_guard lock(output);
            std::cerr << processed << " examined, " << unique << " unique, " << hard
                      << " stalled with >=320 free cells, " << abandoned << " budget stops\n";
        }
    });
}

std::string clueText(const Clue& clue) {
    if (!clue.count) {
        return "0";
    }
    std::string out;
    for (int i = 0; i < clue.count; ++i) {
        if (i) {
            out += ' ';
        }
        out += std::to_string(clue.runs[i]);
    }
    return out;
}

void writeBatch(const std::vector<Entry>& entries, const std::string& puzzleFile, const std::string& answerFile) {
    std::ofstream puzzles(puzzleFile);
    std::ofstream answers(answerFile);
    if (!puzzles || !answers) {
        throw std::runtime_error("could not open output files");
    }
    for (std::size_t i = 0; i < entries.size(); ++i) {
        const auto& entry = entries[i];
        const Puzzle puzzle(entry.grid, entry.height, entry.width);
        const std::string id = "gpt6-r2-" + std::to_string(i + 101);
        puzzles << "PUZZLE " << id << ' ' << entry.height << ' ' << entry.width << '\n';
        for (int j = 0; j < entry.height; ++j) {
            puzzles << clueText(puzzle.rows[j]) << '\n';
        }
        for (int j = 0; j < entry.width; ++j) {
            puzzles << clueText(puzzle.cols[j]) << '\n';
        }
        answers << "SOLUTION " << id << '\n';
        for (int r = 0; r < entry.height; ++r) {
            for (int c = 0; c < entry.width; ++c) {
                answers << (entry.grid[r] & bit(c) ? '#' : '.');
            }
            answers << '\n';
        }
    }
    if (!puzzles || !answers) {
        throw std::runtime_error("could not write all output");
    }
}

void score(const std::string& pool, std::uint64_t stopWork, int workers) {
    std::ifstream in(pool);
    if (!in) {
        throw std::runtime_error("could not open candidate pool");
    }
    std::vector<Entry> entries;
    for (Entry entry; readEntry(in, entry); entry = {}) {
        if (entry.proof.initialUnknown >= 190) {
            entries.push_back(entry);
        }
    }
    std::mutex output;
    parallelFor(entries.size(), workers, [&](std::uint64_t index, MemoBank& memo, ExactCache& exact) {
        auto& entry = entries[index];
        const Puzzle puzzle(entry.grid, entry.height, entry.width);
        Effort effort;
        entry.estimated = Solver(puzzle, memo, effort).measure(stopWork, exact);
        const std::lock_guard lock(output);
        std::cout << entry.estimated.weight() << ' ' << entry.estimated.misses << ' '
                  << entry.estimated.probes << ' ' << entry.estimated.branches << ' ';
        writeEntry(std::cout, entry);
        std::cout.flush();
    });
}

std::uint64_t finalScore(const Entry& entry) {
    return entry.estimated.uncachedWork;
}

std::vector<Entry> readScores(const std::string& path) {
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("could not open the score file");
    }
    std::vector<Entry> entries;
    for (Entry entry; input >> entry.estimated.uncachedWork >> entry.estimated.misses
                            >> entry.estimated.probes >> entry.estimated.branches; entry = {}) {
        if (!readEntry(input, entry)) {
            throw std::runtime_error("incomplete scored candidate");
        }
        entries.push_back(entry);
    }
    return entries;
}

Grid oriented(const Grid& grid, int n, int orientation) {
    Grid result{};
    for (int r = 0; r < n; ++r) {
        for (Bits occupied = grid[r]; occupied;) {
            int a = r;
            int b = popFirst(occupied);
            if (orientation & 1) {
                std::swap(a, b);
            }
            if (orientation & 2) {
                a = n - 1 - a;
            }
            if (orientation & 4) {
                b = n - 1 - b;
            }
            result[a] |= bit(b);
        }
    }
    return result;
}

Grid canonical(const Entry& entry) {
    Grid result = entry.grid;
    if (entry.height == entry.width) {
        for (int i = 1; i < 8; ++i) {
            result = std::min(result, oriented(entry.grid, entry.height, i));
        }
    }
    return result;
}

std::vector<Entry> ranked(const std::string& path) {
    auto entries = readScores(path);
    std::sort(entries.begin(), entries.end(), [](const Entry& a, const Entry& b) {
        if (finalScore(a) != finalScore(b)) {
            return finalScore(a) > finalScore(b);
        }
        return std::pair{a.seed, a.variant} < std::pair{b.seed, b.variant};
    });
    return entries;
}

void expandOrientations(const std::string& scores, int top) {
    const auto entries = ranked(scores);
    int emitted = 0;
    std::unordered_set<std::uint64_t> seen;
    for (const Entry& parent : entries) {
        if (parent.height != parent.width || !seen.insert(parent.seed).second) {
            continue;
        }
        for (int i = 1; i < 8; ++i) {
            Entry child = parent;
            child.variant = parent.variant * 8 + i + 200000000;
            child.grid = oriented(parent.grid, parent.height, i);
            writeEntry(std::cout, child);
        }
        if (++emitted == top) {
            break;
        }
    }
}

void breed(const std::string& scores, int top, int trials, std::uint64_t salt,
           std::uint64_t limit, int workers) {
    const auto sorted = ranked(scores);
    std::vector<Entry> parents;
    std::unordered_set<std::uint64_t> seen;
    for (const auto& entry : sorted) {
        if (seen.insert(entry.seed).second) {
            parents.push_back(entry);
            if (static_cast<int>(parents.size()) == top) {
                break;
            }
        }
    }
    std::atomic<int> examined{0};
    std::atomic<int> accepted{0};
    std::atomic<int> limited{0};
    std::mutex output;
    parallelFor(parents.size() * trials, workers, [&](std::uint64_t index, MemoBank& memo, ExactCache&) {
        const auto& parent = parents[index % parents.size()];
        const auto token = index / parents.size();
        std::mt19937_64 rng(parent.seed ^ (salt + token * 0x9e3779b97f4a7c15ULL));
        Entry child = parent;
        child.variant = 1000000 + static_cast<int>(salt % 10000) * 10000 + static_cast<int>(token);
        const int changes = token % 7 < 5 ? 1 : (token % 7 == 5 ? 2 : 3);
        for (int i = 0; i < changes; ++i) {
            const int r = static_cast<int>(rng() % child.height);
            const int c = static_cast<int>(rng() % child.width);
            child.grid[r] ^= bit(c);
        }
        for (int round = 0; round < 3 && child.grid != parent.grid; ++round) {
            const Puzzle puzzle(child.grid, child.height, child.width);
            Effort effort;
            Grid alternate{};
            const auto result = Solver(puzzle, memo, effort).prove(child.grid, limit, &alternate);
            if (result == Verdict::unique) {
                if (effort.initialUnknown >= 1300) {
                    child.proof = effort;
                    ++accepted;
                    const std::lock_guard lock(output);
                    writeEntry(std::cout, child);
                    std::cout.flush();
                }
                break;
            }
            if (result == Verdict::budget) {
                ++limited;
                break;
            }
            if (!repair(child, alternate, rng)) {
                break;
            }
        }
        if (++examined % 150 == 0) {
            const std::lock_guard lock(output);
            std::cerr << examined << " neighbors checked, " << accepted << " accepted, "
                      << limited << " budget stops\n";
        }
    });
}

void choose(const std::string& path, const std::string& puzzles, const std::string& answers, int workers) {
    const auto entries = ranked(path);
    std::vector<Entry> selected;
    std::vector<Grid> fingerprints;
    std::unordered_map<std::uint64_t, int> familyCounts;
    for (const Entry& entry : entries) {
        int& familyCount = familyCounts[entry.seed];
        if (familyCount >= 4) {
            continue;
        }
        const Grid fingerprint = canonical(entry);
        if (std::find(fingerprints.begin(), fingerprints.end(), fingerprint) == fingerprints.end()) {
            fingerprints.push_back(fingerprint);
            selected.push_back(entry);
            ++familyCount;
        }
        if (selected.size() == 120) {
            break;
        }
    }
    if (selected.size() != 120) {
        throw std::runtime_error("candidate pool does not contain 120 distinct scored grids");
    }
    parallelFor(selected.size(), workers, [&](std::uint64_t index, MemoBank& memo, ExactCache&) {
        const auto& entry = selected[index];
        const Puzzle puzzle(entry.grid, entry.height, entry.width);
        Effort effort;
        if (Solver(puzzle, memo, effort).prove(entry.grid, std::numeric_limits<std::uint64_t>::max()) != Verdict::unique) {
            throw std::logic_error("Final candidate failed the independent full search");
        }
    });
    writeBatch(selected, puzzles, answers);
    std::cerr << "120 unique grids, estimated workload range " << finalScore(selected.back())
              << " to " << finalScore(selected.front()) << '\n';
}

} // namespace

int main(int argc, char** argv) {
    try {
        if (argc == 7 && std::string(argv[1]) == "survey") {
            survey(std::stoull(argv[2]), std::stoull(argv[3]), std::stoi(argv[4]),
                   std::stoull(argv[5]), std::stoi(argv[6]));
        } else if (argc == 5 && std::string(argv[1]) == "score") {
            score(argv[2], std::stoull(argv[3]), std::stoi(argv[4]));
        } else if (argc == 4 && std::string(argv[1]) == "orient") {
            expandOrientations(argv[2], std::stoi(argv[3]));
        } else if (argc == 8 && std::string(argv[1]) == "breed") {
            breed(argv[2], std::stoi(argv[3]), std::stoi(argv[4]),
                  std::stoull(argv[5]), std::stoull(argv[6]), std::stoi(argv[7]));
        } else if (argc == 6 && std::string(argv[1]) == "choose") {
            choose(argv[2], argv[3], argv[4], std::stoi(argv[5]));
        } else {
            std::cerr << "survey FIRST COUNT FAMILY PROOF_BUDGET WORKERS\n"
                         "score POOL ESTIMATE_BUDGET WORKERS\n"
                         "orient SCORES TOP\n"
                         "breed SCORES TOP TRIALS SALT PROOF_BUDGET WORKERS\n"
                         "choose SCORES PUZZLES ANSWERS WORKERS\n";
            return 1;
        }
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
    return 0;
}
