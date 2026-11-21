"""Generate the round-two puzzle pack and verify each endpoint certificate."""

import argparse
from functools import lru_cache
from itertools import groupby
from pathlib import Path
from random import Random


# Instance parameters selected with an independent native nonogram solver.
INSTANCES = [
    (30, -1), (32, 0), (64, 0), (105, 0), (167, 0),
    (176, 0), (244, -1), (255, 0), (273, 2), (279, 0),
    (332, 0), (427, 0), (448, 33), (469, 0), (471, 0),
    (532, 0), (555, 0), (587, 0), (591, 1), (598, 2),
    (615, 0), (640, 0), (672, 32), (691, -1), (747, 0),
    (756, 1), (768, 0), (868, -1), (909, 2), (995, 0),
    (1003, 1), (1039, 0), (1164, 0), (1259, 1), (1329, 0),
    (1415, 2), (1481, 32), (1564, 0), (1639, 0), (1656, -1),
    (1689, 2), (1792, 1), (1867, 4), (1941, 0), (1991, 0),
    (2035, 31), (2098, 1), (2208, -1), (2260, 35), (2352, 0),
    (2367, 1), (2464, 1), (2595, 0), (2661, 2), (2669, -1),
    (2707, -1), (2755, 0), (2764, 4), (2887, 0), (2904, 0),
    (2964, -1), (3019, 0), (3024, 2), (3059, 31), (3079, -1),
    (3143, 1), (3159, 3), (3268, 1), (3347, -1), (3359, 0),
    (3397, 0), (3423, 1), (3436, 0), (3541, 3), (3612, 1),
    (3659, 0), (3688, -1), (3799, -1), (3808, 0), (3813, -1),
    (3840, 0), (3849, 0), (3997, 1), (4035, -1), (4064, 1),
    (4187, 32), (4320, -1), (4371, 1), (4420, -1), (4425, -1),
    (4472, 2), (4651, 0), (4763, 1), (4795, -1), (4815, 2),
    (4835, 2), (4869, 0), (4925, -1), (4932, -1), (4967, 31),
    (5003, 0), (5048, 4), (5051, 0), (5104, 0), (5131, 1),
    (5265, -1), (5311, -1), (5450, 1), (5547, -1), (5655, 2),
    (5853, 0), (6083, 0), (6280, 0), (6349, 0), (6361, 0),
    (6380, 0), (6448, 0), (6471, 31), (6592, 31), (6653, 31),
]


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


def build(seed):
    rng = Random(seed)
    width = rng.randrange(38, 46)
    cuts = list(range(1, width))
    rng.shuffle(cuts)
    size = rng.randint(5, 10)
    starts = [0] + cuts[:size]
    ends = [width] + cuts[size:2 * size]
    pairs = [(a, b) for a in sorted(starts) for b in sorted(ends) if a < b]
    place = legal_placements(starts, ends)
    pool = set()
    for _ in range(230):
        available = pairs
        selected = []
        for _ in range(rng.choice((1, 2, 2, 3, 3, 4, 5))):
            if not available:
                break
            a, b = rng.choice(available)
            selected.append((a, b))
            available = [(x, y) for x, y in available if y < a or x > b]
        lengths = tuple(b - a for a, b in sorted(selected))
        if not 3 <= sum(lengths) <= width - 5:
            continue
        count, mask = place(lengths)
        if count == 1:
            pool.add(mask)
    if not pool:
        raise ValueError("no eligible rows")
    pool = sorted(pool)
    mode = seed % 4
    if mode == 1:
        pool.sort(key=lambda v: (v & ~(v << 1)).bit_count())
        pool = pool[:max(6, len(pool) // 2)]
    if mode == 2:
        pool = rng.sample(pool, min(len(pool), rng.randrange(7, 15)))
    active = rng.randint(13, 23)
    counts = [0] * width
    rows = []
    for _ in range(active):
        if mode in (0, 3):
            target = rng.uniform(.30, .55) * (len(rows) + .5)
            def balance(v):
                cost = sum(counts[c] - target for c in range(width) if v & (1 << c))
                return cost + rng.uniform(-3, 3)
            choices = rng.sample(pool, min(len(pool), rng.randint(5, 22)))
            mask = min(choices, key=balance)
        else:
            mask = rng.choice(pool)
        rows.append(mask)
        for c in range(width):
            counts[c] += (mask >> c) & 1
    grid = []
    for mask in rows:
        if grid:
            grid.append([0] * width)
        grid.append([(mask >> c) & 1 for c in range(width)])
    return grid, bool(rng.getrandbits(1))


def layout(grid, transpose, seed, variant):
    if variant == -1:
        original = list(zip(*grid)) if transpose else grid
        return [row[::-1] for row in zip(*original)]
    if variant:
        rng = Random((seed + 1) * 1009 + variant * 419)
        active = grid[::2]
        rng.shuffle(active)
        if rng.randrange(2):
            active = [row[::-1] for row in active]
        grid = []
        for row in active:
            if grid:
                grid.append([0] * len(row))
            grid.append(row)
        transpose = bool(rng.getrandbits(1))
    return list(zip(*grid)) if transpose else grid


def verify_certificate(grid):
    """Reconstruct every row from the public clues of the untransposed grid."""
    width = len(grid[0])
    column_mass = [sum(runs(col)) for col in zip(*grid)]
    deltas = [y - x for x, y in zip([0] + column_mass, column_mass + [0])]
    clues = [runs(row) for row in grid]
    if sum(len(c) for c in clues) != sum(max(d, 0) for d in deltas):
        raise ValueError("unsaturated endpoint count")
    place = legal_placements(
        [i for i, d in enumerate(deltas) if d > 0],
        [i for i, d in enumerate(deltas) if d < 0],
    )
    for row, clue in zip(grid, clues):
        mask = sum(bit << i for i, bit in enumerate(row))
        if place(clue) != (1, mask):
            raise ValueError("row certificate failed")
    if any(len(row) != width for row in grid):
        raise ValueError("nonrectangular grid")


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
    parser.add_argument("--output", type=Path, default=Path.cwd())
    parser.add_argument("--verify-only", action="store_true", help="prove the existing puzzle and answer files")
    args = parser.parse_args()
    if args.verify_only:
        verify_files(args.output)
        return
    if len(INSTANCES) != 120 or len({seed for seed, _ in INSTANCES}) != 120:
        raise ValueError("expected 120 different seeds")
    puzzles, solutions, boards = [], [], set()
    for i, (seed, variant) in enumerate(INSTANCES, 1):
        grid, transpose = build(seed)
        verify_certificate(grid)
        grid = layout(grid, transpose, seed, variant)
        puzzle, solution = encode(f"edge-{i:03}", grid)
        body = puzzle.split("\n", 1)[1]
        if body in boards:
            raise ValueError("repeated clue set")
        boards.add(body)
        puzzles.append(puzzle)
        solutions.append(solution)
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, parts in (("题目.txt", puzzles), ("答案.txt", solutions)):
        (args.output / filename).write_bytes("".join(parts).encode("ascii"))
    verify_files(args.output)


if __name__ == "__main__":
    main()
