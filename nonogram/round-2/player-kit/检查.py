#!/usr/bin/env python3
"""检查题集的格式和答案（不检查唯一解）。

    python3 检查.py 题目.txt 答案.txt

检查：题目数正好 120；题号不重复、只用字母数字和连字符；行数、列数在 1–45 之间；
每条线索都放得下；每道题都有答案，答案的尺寸对、只用 # 和 .、满足全部线索。
唯一解要你自己保证，这个脚本不查。只用 Python 标准库。
"""
import re
import sys

COUNT = 120
MAX_SIZE = 45
ID_RE = re.compile(r"^[A-Za-z0-9-]+$")


def parse_puzzles(text, errors):
    """返回 [(id, h, w, rows, cols)]；格式问题记进 errors。"""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        parts = lines[i].split()
        if not parts:
            i += 1
            continue
        if parts[0] != "PUZZLE" or len(parts) != 4:
            errors.append(f"第 {i + 1} 行：应该是 PUZZLE <id> <h> <w>，实际是 {lines[i]!r}")
            i += 1
            continue
        pid = parts[1]
        try:
            h, w = int(parts[2]), int(parts[3])
        except ValueError:
            errors.append(f"第 {i + 1} 行：{pid} 的行数、列数不是整数")
            i += 1
            continue
        if not ID_RE.match(pid):
            errors.append(f"{pid}：题号只能用字母、数字和连字符")
        if not (1 <= h <= MAX_SIZE and 1 <= w <= MAX_SIZE):
            errors.append(f"{pid}：尺寸 {h}×{w} 超出 1–{MAX_SIZE}")
            i += 1
            continue
        body = lines[i + 1:i + 1 + h + w]
        if len(body) != h + w:
            errors.append(f"{pid}：线索不够 {h + w} 行")
            break
        clues = []
        for k, line in enumerate(body):
            n = w if k < h else h
            name = f"第 {k + 1} 行线索" if k < h else f"第 {k - h + 1} 列线索"
            try:
                nums = [int(x) for x in line.split()]
            except ValueError:
                errors.append(f"{pid} {name}：不是空格分隔的整数：{line!r}")
                nums = []
            if not nums:
                errors.append(f"{pid} {name}：是空的，全白要写 0")
            elif nums == [0]:
                nums = []
            elif any(x <= 0 for x in nums):
                errors.append(f"{pid} {name}：只有全白的线可以写 0，其余数字必须是正整数")
                nums = [x for x in nums if x > 0]
            if nums and sum(nums) + len(nums) - 1 > n:
                errors.append(f"{pid} {name}：{' '.join(map(str, nums))} 放不进 {n} 格")
            clues.append(nums)
        out.append((pid, h, w, clues[:h], clues[h:]))
        i += 1 + h + w
    return out


def parse_answers(text, errors):
    """返回 {id: [行字符串]}。"""
    lines = text.splitlines()
    out, i = {}, 0
    while i < len(lines):
        parts = lines[i].split()
        if not parts:
            i += 1
            continue
        if parts[0] != "SOLUTION" or len(parts) != 2:
            errors.append(f"答案第 {i + 1} 行：应该是 SOLUTION <id>，实际是 {lines[i]!r}")
            i += 1
            continue
        pid = parts[1]
        i += 1
        grid = []
        while i < len(lines) and lines[i].strip() and not lines[i].startswith("SOLUTION"):
            grid.append(lines[i].strip())
            i += 1
        if pid in out:
            errors.append(f"答案 {pid} 出现了不止一次")
        out[pid] = grid
    return out


def runs(cells):
    r, run = [], 0
    for c in cells:
        if c == "#":
            run += 1
        elif run:
            r.append(run)
            run = 0
    if run:
        r.append(run)
    return r


def check(puzzle_text, answer_text):
    errors = []
    puzzles = parse_puzzles(puzzle_text, errors)
    answers = parse_answers(answer_text, errors) if answer_text is not None else None
    if len(puzzles) != COUNT:
        errors.append(f"题目有 {len(puzzles)} 道，要正好 {COUNT} 道")
    seen = set()
    for pid, h, w, rows, cols in puzzles:
        if pid in seen:
            errors.append(f"题号 {pid} 重复")
        seen.add(pid)
        if answers is None:
            continue
        grid = answers.get(pid)
        if grid is None:
            errors.append(f"{pid}：没有答案")
            continue
        if len(grid) != h or any(len(r) != w for r in grid) or any(set(r) - {"#", "."} for r in grid):
            errors.append(f"{pid}：答案应该是 {h} 行、每行 {w} 个 # 或 .")
            continue
        bad = [f"第 {r + 1} 行" for r in range(h) if runs(grid[r]) != rows[r]]
        bad += [f"第 {c + 1} 列" for c in range(w) if runs("".join(grid[r][c] for r in range(h))) != cols[c]]
        if bad:
            errors.append(f"{pid}：答案不满足 {'、'.join(bad[:5])}{' 等' if len(bad) > 5 else ''}")
    if answers is not None:
        for pid in answers:
            if pid not in seen:
                errors.append(f"答案 {pid} 没有对应的题目")
    return puzzles, errors


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if len(sys.argv) != 3:
        sys.exit("用法：python3 检查.py 题目.txt 答案.txt")
    with open(sys.argv[1], encoding="utf-8") as f:
        puzzle_text = f.read()
    with open(sys.argv[2], encoding="utf-8") as f:
        answer_text = f.read()
    puzzles, errors = check(puzzle_text, answer_text)
    if errors:
        print(f"发现 {len(errors)} 处问题：")
        for e in errors[:50]:
            print("  " + e)
        if len(errors) > 50:
            print(f"  ……另外还有 {len(errors) - 50} 处")
        sys.exit(1)
    sizes = sorted({(h, w) for _, h, w, _, _ in puzzles})
    print(f"通过：{len(puzzles)} 道题，答案都满足线索；尺寸 {len(sizes)} 种。唯一解没有检查。")


if __name__ == "__main__":
    main()
