#!/usr/bin/env python3
"""出题赛判分：多核并行，逐题单独跑乌龟，记每道题的用时和工作量。

    python3 turtle_bench.py 题目.txt [--cap 10] [--jobs 8] [--json 结果.jsonl]

每道题单独起一个乌龟进程（turtle/solver.py --stats --time-limit CAP），多道题并行，
互不影响：乌龟单线程、每道题的缓存都是新建的。用时取乌龟自己报的 ms（不含解释器启动）；
超过 CAP 秒的按 CAP 算。另外记乌龟的单行推理次数、试填次数、猜测次数：这些和机器、
并行度无关，只要没被 CAP 截断，同一道题每次都一样，可以当用时之外的旁证。

云端测速时很多选手的题卡到 10 秒上限，区分不开，所以放到另一台多核机器上
并行跑、放宽上限。只用 Python 标准库。
"""
import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 乌龟放在本文件旁边的 turtle/
TURTLE = os.path.join(HERE, "turtle", "solver.py")
STATS_RE = re.compile(r"STATS lines=(\d+) probes=(\d+) guesses=(\d+) backtracks=(\d+) ms=(\d+)")


def split_puzzles(text):
    lines, out, i = text.splitlines(), [], 0
    while i < len(lines):
        parts = lines[i].split()
        if not parts or parts[0] != "PUZZLE":
            i += 1
            continue
        h, w = int(parts[2]), int(parts[3])
        out.append((parts[1], "\n".join(lines[i:i + 1 + h + w]) + "\n"))
        i += 1 + h + w
    return out


def run_one(pid, text, cap):
    r = subprocess.run([sys.executable, TURTLE, "--stats", "--time-limit", str(cap)], input=text, text=True,
                       capture_output=True, timeout=cap + 60)
    m = STATS_RE.search(r.stdout)
    if not m:
        return {"id": pid, "status": "error", "ms": cap * 1000, "error": r.stderr.strip()[-300:]}
    lines, probes, guesses, backtracks, ms = map(int, m.groups())
    solved = f"SOLUTION {pid}" in r.stdout
    return {"id": pid, "status": "solved" if solved else "capped", "ms": min(ms, cap * 1000),
            "lines": lines, "probes": probes, "guesses": guesses, "backtracks": backtracks}


def main():
    ap = argparse.ArgumentParser(description="多核并行逐题跑乌龟")
    ap.add_argument("puzzles")
    ap.add_argument("--cap", type=float, default=10, help="每道题的用时上限（秒）")
    ap.add_argument("--jobs", type=int, default=os.cpu_count(), help="同时跑几道题")
    ap.add_argument("--json", help="逐题结果写到这个 JSONL 文件")
    a = ap.parse_args()
    with open(a.puzzles, encoding="utf-8") as f:
        puzzles = split_puzzles(f.read())
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
        results = list(ex.map(lambda p: run_one(p[0], p[1], a.cap), puzzles))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    total = sum(r["ms"] for r in results)
    capped = [r for r in results if r["status"] != "solved"]
    print(f"{len(results)} 道，每道上限 {a.cap:g} 秒，并行 {a.jobs}：总用时 {total / 1000:.1f} 秒；"
          f"卡到上限 {len(capped)} 道；单行推理共 {sum(r.get('lines', 0) for r in results)} 次")
    for r in sorted(results, key=lambda r: -r["ms"])[:5]:
        print(f"  {r['id']:<20} {r['ms'] / 1000:.1f} s  {r['status']}  lines={r.get('lines')}")


if __name__ == "__main__":
    main()
