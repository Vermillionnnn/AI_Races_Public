#include <algorithm>
#include <array>
#include <bit>
#include <charconv>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace {

using Bits = std::uint64_t;
constexpr int maxSide = 63;
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
    bool valid = true;

    void read(const std::string& input, int lineLength) {
        length = lineLength;
        mask = lowBits(length);
        const char* cursor = input.data();
        const char* end = cursor + input.size();
        int span = 0;
        while (cursor != end) {
            if (*cursor == ' ' || *cursor == '\t' || *cursor == '\r') {
                ++cursor;
                continue;
            }
            int run;
            const auto parsed = std::from_chars(cursor, end, run);
            if (parsed.ec != std::errc{}) {
                valid = false;
                break;
            }
            cursor = parsed.ptr;
            if (run == 0) {
                continue;
            }
            if (count == maxRuns || run < 0 || run > length) {
                valid = false;
                break;
            }
            runs[count++] = run;
            span += run + 1;
            maxRun = std::max(maxRun, run);
        }
        if (count == 0) {
            return;
        }
        const int slack = length - (span - 1);
        if (slack < 0) {
            valid = false;
            return;
        }
        int first = 0;
        for (int i = 0; i < count; ++i) {
            startBounds[i] = lowBits(slack + 1) << first;
            first += runs[i] + 1;
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

struct Puzzle {
    std::string id;
    int height = 0;
    int width = 0;
    bool valid = false;
    std::array<Clue, maxSide> rows;
    std::array<Clue, maxSide> cols;

    bool read() {
        std::string line;
        if (!std::getline(std::cin, line)) {
            return false;
        }
        std::istringstream header(line);
        std::string tag;
        if (!(header >> tag >> id >> height >> width) || tag != "PUZZLE") {
            return false;
        }
        valid = height > 0 && height <= maxSide && width > 0 && width <= maxSide;
        for (int r = 0; r < height; ++r) {
            if (!std::getline(std::cin, line)) {
                return false;
            }
            if (valid) {
                rows[r].read(line, width);
            }
        }
        for (int c = 0; c < width; ++c) {
            if (!std::getline(std::cin, line)) {
                return false;
            }
            if (valid) {
                cols[c].read(line, height);
            }
        }
        return true;
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
    if (!clue.valid) {
        return false;
    }
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

struct MemoEntry {
    Bits key = 0;
    Bits white = 0;
    Cells result;
};

struct LineMemo {
    static constexpr int slotBits = 9;
    std::array<MemoEntry, 1 << slotBits> entries;

    bool lookup(const Clue& clue, Cells cells, Bits stamp, Cells& result) {
        // Short lines leave 16 bits in the key for identifying the puzzle.
        if (clue.length > 48) {
            return deduce(clue, cells, result);
        }
        const Bits key = cells.black | stamp;
        const Bits hash = (cells.black * 0x9e3779b97f4a7c15ULL) ^
                          (cells.white * 0xbf58476d1ce4e5b9ULL);
        auto& entry = entries[hash >> (64 - slotBits)];
        if (entry.key == key && entry.white == cells.white) {
            result = entry.result;
            return result.black != ~Bits{0};
        }
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

struct Task {
    Puzzle puzzle;
    Board board;
    std::vector<Alternative> alternatives;
    bool started = false;
};

enum class Status { solved, impossible, paused };

class Solver {
public:
    Solver(const Puzzle& puzzle, MemoBank& memo)
        : puzzle(puzzle), memo(memo), stamp(memo.nextPuzzle()) {}

    Status solve(Task& task) {
        if (!puzzle.valid) {
            return Status::impossible;
        }
        Board& board = task.board;
        if (!task.started) {
            task.started = true;
            board.unknown = puzzle.height * puzzle.width;
            if (!propagate(board, {lowBits(puzzle.height), lowBits(puzzle.width)})) {
                return Status::impossible;
            }
        }

        // Rotate hard puzzles through the input queue so that a deep search
        // still leaves time to answer other puzzles.
        constexpr int branchBudget = 48;
        for (int attempt = 0; attempt < branchBudget; ++attempt) {
            Candidate branch;
            if (probe(board, branch)) {
                if (!board.unknown) {
                    return verify(board) ? Status::solved : Status::impossible;
                }
                const auto [r, c, preferBlack] = branch;
                task.alternatives.push_back({board, r, c});
                task.alternatives.back().board.set(r, c, !preferBlack);
                board.set(r, c, preferBlack);
                if (propagate(board, {bit(r), bit(c)})) {
                    continue;
                }
            }
            for (;;) {
                if (task.alternatives.empty()) {
                    return Status::impossible;
                }
                const Alternative& alt = task.alternatives.back();
                board = alt.board;
                const Lines affected{bit(alt.row), bit(alt.col)};
                task.alternatives.pop_back();
                if (propagate(board, affected)) {
                    break;
                }
            }
        }
        return Status::paused;
    }

private:
    const Puzzle& puzzle;
    MemoBank& memo;
    const Bits stamp;
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
               Bits pending, Bits& next, int& unknown) const {
        while (pending) {
            const int line = popFirst(pending);
            Cells result;
            if (!cache[line].lookup(clues[line], lines[line], stamp, result)) {
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
                       pending.cols, pending.rows, board.unknown)) {
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
                const int r = cell / maxSide;
                const int c = cell % maxSide;
                black.set(r, c, true);
                white.set(r, c, false);
                Lines blackSeen;
                const bool blackOK = propagate(black, {bit(r), bit(c)}, &blackSeen);
                if (blackOK && !black.unknown) {
                    board = black;
                    return ProbeResult::solved;
                }
                Lines whiteSeen;
                const bool whiteOK = propagate(white, {bit(r), bit(c)}, &whiteSeen);
                if (!blackOK && !whiteOK) {
                    return ProbeResult::impossible;
                }
                if (!whiteOK || !blackOK || !white.unknown) {
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

    bool probe(Board& board, Candidate& branch) {
        for (ProbeMemo& memo : probes) {
            memo.stage = -1;
        }
        changed[0] = {};
        int stage = 0;
        while (board.unknown) {
            ProbeChoice best;
            switch (probeStage(board, stage, best)) {
            case ProbeResult::exhausted:
                branch = {best.cell / maxSide, best.cell % maxSide, probes[best.cell].preferBlack};
                return true;
            case ProbeResult::advanced:
                break;
            case ProbeResult::solved:
                return true;
            case ProbeResult::impossible:
                return false;
            }
        }
        return true;
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

std::string answer(const Task& task, Status status) {
    const Puzzle& puzzle = task.puzzle;
    if (status != Status::solved) {
        return "UNSOLVED " + puzzle.id + '\n';
    }
    const Board& board = task.board;
    std::string out = "SOLUTION " + puzzle.id + '\n';
    out.reserve(out.size() + puzzle.height * (puzzle.width + 1));
    for (int r = 0; r < puzzle.height; ++r) {
        const Bits black = board.rows[r].black;
        for (int c = 0; c < puzzle.width; ++c) {
            out += (black & bit(c)) ? '#' : '.';
        }
        out += '\n';
    }
    return out;
}

class Batch {
public:
    void submit(std::unique_ptr<Task> task) {
        {
            const std::lock_guard lock(mutex);
            queue.push_back(std::move(task));
        }
        ready.notify_one();
    }

    void finish() {
        {
            const std::lock_guard lock(mutex);
            closed = true;
        }
        ready.notify_all();
    }

    void work() {
        const auto memo = std::make_unique<MemoBank>();
        for (;;) {
            std::unique_ptr<Task> task;
            {
                std::unique_lock lock(mutex);
                ready.wait(lock, [this] { return closed || !queue.empty(); });
                if (queue.empty()) {
                    return;
                }
                task = std::move(queue.front());
                queue.pop_front();
            }
            const Status status = Solver(task->puzzle, *memo).solve(*task);
            if (status == Status::paused) {
                submit(std::move(task));
                continue;
            }
            const std::string out = answer(*task, status);
            const std::lock_guard lock(output);
            std::cout << out << std::flush;
        }
    }

private:
    std::mutex mutex;
    std::mutex output;
    std::condition_variable ready;
    std::deque<std::unique_ptr<Task>> queue;
    bool closed = false;
};

} // namespace

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    Batch batch;
    std::thread worker1(&Batch::work, &batch);
    std::thread worker2(&Batch::work, &batch);
    for (;;) {
        auto task = std::make_unique<Task>();
        if (!task->puzzle.read()) {
            break;
        }
        batch.submit(std::move(task));
    }
    batch.finish();
    worker1.join();
    worker2.join();
    return 0;
}
