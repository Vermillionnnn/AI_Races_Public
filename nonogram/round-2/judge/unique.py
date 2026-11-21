#!/usr/bin/env python3
"""证明选手交的题只有一个解（出题赛判分用）。

    python3 unique.py 题目.txt 答案.txt [--seconds 0] [--work 0] [--jobs 2]

每道题先核对答案满足线索，再交给唯一解证明器 `prover/prove check-one`：从全未知开始推理、
试填、搜索，找和答案不同的第二个解；所有分支都排除才算唯一。证明器只收正方形，h×w 的题补全白的
行或列（线索 0）垫成 n×n，n = max(h, w)：补出的格子只能是白的、原线索不变，所以垫完后唯一当且仅当
原题唯一。

结果：unique（证出唯一）、multiple（找到第二个解）、timeout（预算内证不出来）；和前面某道完全相同
（尺寸和线索一样）的记 duplicate（旋转、镜像后线索不同的不算重复）。round-2 发出的规则没有禁止重复，
这一轮只作记录、不扣分。出题赛规则是证明不设时限，
所以默认不限时间和推理次数；要试跑时可以用 --seconds 加上限。

--count-rule：传播里加上跨列计数规则（两侧补白后，相邻两列黑格数之差 = 这条边界上黑块起点数 - 终点数；
全盘起点总数 = 黑块总数），边界上的上下界收紧时强制或排除起点、终点，行列两个方向都用。规则是必要条件，
不会改变结论（5–10 格随机盘 3000 道和不加规则结果全部一致），对 astra 那种按这条规则构造的题能从卡住变成毫秒级。
"""
import argparse
import concurrent.futures
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 证明器：prover/ 里的独立证明器 prove（编译：g++ -O3 -std=c++17 prover/prove.cpp -o prover/prove）。
# 也可以用环境变量 NONOGRAM_PROVER 指定。
PROVER = os.environ.get("NONOGRAM_PROVER") or os.path.join(HERE, "prover", "prove")


def parse_puzzles(text):
    lines, out, i = text.splitlines(), [], 0
    while i < len(lines):
        parts = lines[i].split()
        if not parts or parts[0] != "PUZZLE":
            i += 1
            continue
        pid, h, w = parts[1], int(parts[2]), int(parts[3])
        body = lines[i + 1:i + 1 + h + w]
        clues = [[int(x) for x in l.split() if int(x) > 0] for l in body]
        out.append((pid, h, w, clues[:h], clues[h:]))
        i += 1 + h + w
    return out


def parse_answers(text):
    lines, out, i = text.splitlines(), {}, 0
    while i < len(lines):
        parts = lines[i].split()
        if len(parts) == 2 and parts[0] == "SOLUTION":
            grid, i = [], i + 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith("SOLUTION"):
                grid.append(lines[i].strip())
                i += 1
            out[parts[1]] = grid
        else:
            i += 1
    return out


def runs(cells):
    r, run = [], 0
    for c in cells:
        if c == "#":
            run += 1
        elif run:
            r.append(run)
            run = 0
    return r + [run] if run else r


def canonical(puzzle):
    """8 种旋转、镜像里取最小的线索表示：同一道题转出来的朝向得到同一个键。"""
    _, h, w, rows, cols = puzzle
    forms = []
    for k in range(8):
        r, c = rows, cols
        if k & 1:
            r, c = [x[::-1] for x in r], c[::-1]
        if k & 2:
            r, c = r[::-1], [x[::-1] for x in c]
        if k & 4:
            r, c = c, r
        forms.append((len(r), len(c), tuple(map(tuple, r)), tuple(map(tuple, c))))
    return min(forms)


def prove(puzzle, grid, work, seconds, count_rule=False):
    pid, h, w, rows, cols = puzzle
    if grid is None:
        return {"id": pid, "status": "no-answer"}
    if len(grid) != h or any(len(r) != w for r in grid) or any(set(r) - {"#", "."} for r in grid) \
            or [runs(r) for r in grid] != rows or [runs("".join(g[c] for g in grid)) for c in range(w)] != cols:
        return {"id": pid, "status": "bad-answer"}
    n = max(h, w)
    rows_n = rows + [[]] * (n - h)
    cols_n = cols + [[]] * (n - w)
    grid_n = [r + "." * (n - w) for r in grid] + ["." * n] * (n - h)
    lines = [str(n)] + [" ".join(map(str, [len(a)] + a)) for a in rows_n + cols_n] + grid_n
    work = work or 2 ** 63  # 0 表示不限
    cmd = [PROVER, "check-one", "--proof-work", str(work), "--max-seconds", str(seconds), "--no-cache"]
    if count_rule:
        cmd.append("--count-rule")
    r = subprocess.run(cmd,
                       input="\n".join(lines) + "\n", text=True, capture_output=True)
    if r.returncode not in (0, 2):
        return {"id": pid, "status": "error", "error": r.stderr.strip()}
    res = json.loads(r.stdout)
    return {"id": pid, "status": res["status"], "ms": round(res["ms"]), "lines": res["lines"], "size": f"{h}x{w}"}


def main():
    ap = argparse.ArgumentParser(description="证明选手题目的唯一解")
    ap.add_argument("puzzles")
    ap.add_argument("answers")
    ap.add_argument("--seconds", type=float, default=0, help="每道题的证明时限（秒），0 表示不限")
    ap.add_argument("--work", type=int, default=0, help="每道题的单行推理次数预算，0 表示不限")
    ap.add_argument("--jobs", type=int, default=2, help="同时证明几道题")
    ap.add_argument("--json", help="逐题结果写到这个 JSONL 文件")
    ap.add_argument("--count-rule", action="store_true",
                    help="证明器的传播里加上跨列计数规则（相邻两列黑格数之差 = 这条边界上黑块起点数 - 终点数）")
    a = ap.parse_args()
    if not os.path.exists(PROVER):
        sys.exit(f"先编译证明器：cd {os.path.dirname(PROVER)} && g++ -O3 -std=c++17 {os.path.basename(PROVER)}.cpp -o {os.path.basename(PROVER)}")
    with open(a.puzzles, encoding="utf-8") as f:
        puzzles = parse_puzzles(f.read())
    with open(a.answers, encoding="utf-8") as f:
        answers = parse_answers(f.read())
    first, todo = {}, []
    for p in puzzles:
        key = (p[1], p[2], tuple(map(tuple, p[3])), tuple(map(tuple, p[4])))
        todo.append(first.setdefault(key, p[0]) == p[0])
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
        results = list(ex.map(lambda pt: prove(pt[0], answers.get(pt[0][0]), a.work, a.seconds, a.count_rule) if pt[1]
                              else {"id": pt[0][0], "status": "duplicate"}, zip(puzzles, todo)))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if r["status"] != "unique":
            print(f"{r['id']:<20} {r['status']}" + (f"  {r.get('error', '')}" if r["status"] == "error" else ""))
    print(f"共 {len(results)} 道：" + "，".join(f"{k} {v}" for k, v in sorted(counts.items())))
    groups = {}
    for p in puzzles:
        groups.setdefault(canonical(p), []).append(p[0])
    turned = [g for g in groups.values() if len(g) > 1]
    if turned:
        print(f"同一道题旋转、镜像出的组（含完全相同）：{len(turned)} 组，共 {sum(map(len, turned))} 道；"
              f"不同的题 {len(groups)} 道")
        for g in sorted(turned, key=len, reverse=True)[:5]:
            print("  " + "、".join(g))
    slow = sorted((r for r in results if "ms" in r), key=lambda r: -r["ms"])[:3]
    if slow:
        print("证明最慢：" + "，".join(f"{r['id']} {r['ms']} ms" for r in slow))


if __name__ == "__main__":
    main()
