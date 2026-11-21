"""Reproduce the overtime pack, or certify already generated files from clues alone."""
import argparse
from functools import lru_cache
from itertools import groupby
from pathlib import Path
from random import Random

SEEDS = (
    159, 275, 307, 326, 344, 361, 386, 416, 516, 603,
    658, 714, 810, 854, 870, 944, 958, 1078, 1097, 1111,
    1193, 1216, 1218, 1294, 1395, 1421, 1428, 1447, 1477, 1478,
    1490, 1538, 1615, 1771, 1783, 1849, 1893, 1902, 1920, 2041,
    2154, 2159, 2192, 2214, 2234, 2301, 2306, 2480, 2636, 2637,
    2683, 2704, 2770, 2936, 3004, 3109, 3115, 3139, 3241, 3252,
    3290, 3304, 3348, 3353, 3398, 3400, 3511, 3580, 3593, 3611,
    3628, 3645, 3866, 3869, 3924, 3989, 4072, 4133, 4186, 4187,
    4199, 4200, 4246, 4293, 4311, 4391, 4404, 4487, 4522, 4548,
    4558, 4592, 4601, 4660, 4694, 4727, 4930, 5029, 5083, 5217,
    5223, 5225, 5242, 5294, 5450, 5478, 5506, 5511, 5539, 5615,
    5622, 5713, 5733, 5748, 5784, 5822, 5849, 5902, 5984, 5993,
)

def runs(line):
    return tuple(sum(group) for black, group in groupby(line) if black)


def legal_placements(starts, ends):
    """Count up to two placements and retain a witness mask when unique."""
    by_length = {}
    for a in sorted(starts):
        for b in sorted(ends):
            if b > a:
                by_length.setdefault(b - a, []).append((a, b))

    @lru_cache(maxsize=None)
    def place(lengths, lower=0):
        if not lengths:
            return 1, 0
        count = witness = 0
        k = lengths[0]
        for a, b in by_length.get(k, ()):
            if a < lower:
                continue
            n, mask = place(lengths[1:], b + 1)
            if n:
                count += n
                if count > 1:
                    return 2, 0
                witness = mask | (((1 << k) - 1) << a)
        return count, witness

    return place


def make(seed):
    rng = Random(seed + 713752)
    width = rng.randint(41, 45)
    height = rng.randint(19, 23)
    cuts = list(range(1, width))
    rng.shuffle(cuts)
    count = rng.randint(5, 11)
    starts = sorted([0] + cuts[:count])
    ends = sorted([width] + cuts[count:2 * count])
    pairs = [(a, b) for a in starts for b in ends if 2 <= b - a <= 22]
    placements = legal_placements(starts, ends)
    pool = set()

    for _ in range(420):
        available, selected = pairs, []
        for _ in range(rng.choice((1, 1, 2, 2, 3, 3, 4))):
            if not available:
                break
            a, b = rng.choice(available)
            selected.append((a, b))
            available = [(x, y) for x, y in available if y < a or x > b]
        lengths = tuple(b - a for a, b in sorted(selected))
        if not 5 <= sum(lengths) <= width * .68 or max(lengths) > 20:
            continue
        ways, mask = placements(lengths)
        if ways == 1:
            pool.add(mask)

    if len(pool) < 8:
        return None
    pool = sorted(pool)
    rows = rng.choices(pool, k=height)
    counts = [sum((row >> c) & 1 for row in rows) for c in range(width)]
    target = rng.uniform(.32, .48) * height
    penalty = [(v - target)**2 + 2.5 * max(0, height * .23 - v)**3
               + 1.5 * max(0, v - .75 * height)**3 for v in range(height + 1)]

    # Remove one active row, then try several replacements against the column totals.
    for _ in range(200):
        i = rng.randrange(height)
        previous = rows[i]
        options = rng.sample(pool, min(8, len(pool))) + [previous]
        base = [v - ((previous >> c) & 1) for c, v in enumerate(counts)]
        marginal = [penalty[v + 1] - penalty[v] for v in base]

        def energy(row):
            return sum(cost for c, cost in enumerate(marginal) if row & (1 << c)) + rng.uniform(-6, 6)

        replacement = min(options, key=energy)
        if replacement != previous:
            rows[i] = replacement
            counts = [v + ((replacement >> c) & 1) for c, v in enumerate(base)]

    if min(counts) < 2 or max(counts) > height - 2 or len(set(rows)) < 5:
        return None
    grid = []
    for row in rows:
        if grid:
            grid.append([0] * width)
        grid.append([(row >> c) & 1 for c in range(width)])
    return grid


def encode(name, grid):
    h, w = len(grid), len(grid[0])
    if not (1 <= h <= 45 and 1 <= w <= 45):
        raise ValueError("invalid board size")
    clues = [runs(line) for line in [*grid, *zip(*grid)]]
    puzzle = f"PUZZLE {name} {h} {w}\n"
    puzzle += "".join((" ".join(map(str, clue)) or "0") + "\n" for clue in clues)
    solution = f"SOLUTION {name}\n"
    solution += "".join("".join("#" if v else "." for v in row) + "\n" for row in grid)
    return puzzle, solution


def reconstruct(row_clues, column_clues):
    """Independent proof from clues alone, using earliest and latest placements."""
    mass = [sum(c) for c in column_clues]
    delta = [b - a for a, b in zip([0] + mass, mass + [0])]
    if sum(map(len, row_clues)) != sum(max(v, 0) for v in delta):
        return None
    width = len(column_clues)
    starts = [i for i in range(width) if delta[i] > 0]
    result = []
    for clue in row_clues:
        candidates = [[s for s in starts if s+k <= width and delta[s+k] < 0] for k in clue]
        earliest = []
        lower = 0
        for k, choices in zip(clue, candidates):
            pos = next((v for v in choices if v >= lower), None)
            if pos is None:
                return None
            earliest.append(pos)
            lower = pos+k+1
        upper = width
        for k, choices, witness in zip(reversed(clue), reversed(candidates), reversed(earliest)):
            pos = next((v for v in reversed(choices) if v+k <= upper), None)
            if pos != witness:
                return None
            upper = pos-1
        row = [0] * width
        for start, length in zip(earliest, clue):
            row[start:start+length] = [1] * length
        result.append(row)
    if [runs(col) for col in zip(*result)] != column_clues:
        return None
    return result


def verify_files(directory):
    """Verify the published text files without consulting seeds or the generator."""
    with (directory / "题目.txt").open(encoding="ascii") as puzzles, \
         (directory / "答案.txt").open(encoding="ascii") as answers:
        seen = set()
        for header in puzzles:
            tag, name, h, w = header.split()
            h, w = int(h), int(w)
            if tag != "PUZZLE" or name in seen or not (1 <= h <= 45 and 1 <= w <= 45):
                raise ValueError(f"invalid header for {name}")
            seen.add(name)
            clues = []
            for _ in range(h + w):
                numbers = tuple(map(int, next(puzzles).split()))
                if numbers == (0,):
                    numbers = ()
                elif not numbers or min(numbers) < 1:
                    raise ValueError(f"invalid clue in {name}")
                clues.append(numbers)
            rows, cols = clues[:h], clues[h:]
            grid = reconstruct(rows, cols)
            if grid is None:
                columns = reconstruct(cols, rows)
                if columns is None:
                    raise ValueError(f"no endpoint certificate for {name}")
                grid = list(zip(*columns))
            if next(answers).split() != ["SOLUTION", name]:
                raise ValueError(f"answer header mismatch for {name}")
            for row in grid:
                if next(answers).rstrip("\r\n") != "".join("#" if cell else "." for cell in row):
                    raise ValueError(f"published answer differs from proof for {name}")
        if len(seen) != 120 or answers.read().strip():
            raise ValueError("unexpected puzzle or answer count")
    print("120 unique solutions reconstructed from the public clues")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify_files(args.output)
        return
    puzzles, answers = [], []
    for i, seed in enumerate(SEEDS, 1):
        grid = make(seed)
        if grid is None:
            raise RuntimeError(f"seed {seed} did not yield a candidate")
        if i % 2 == 0:
            grid = list(zip(*grid))
        puzzle, answer = encode(f"ot-{i:03}", grid)
        puzzles.append(puzzle)
        answers.append(answer)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, parts in (("题目.txt", puzzles), ("答案.txt", answers)):
        (args.output / name).write_bytes("".join(parts).encode("ascii"))
    verify_files(args.output)


if __name__ == "__main__":
    main()
