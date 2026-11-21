#!/usr/bin/env python3
"""数织裁判：按正式比赛的方式运行一个求解程序，判对、计时，可选和基准程序对比。

用法：
    python3 judge.py --cmd "<运行你的程序的命令>" [--puzzles 题目.txt] [--with-baseline]

比赛流程（和正式判分相同）：
1. 启动程序一次，先发热身题，等热身题的答案全部收到；
2. 再发全部正式题并关闭输入；从这一刻开始计时，到最后一道答案到达为止；
3. 程序限定在 --cpus 个逻辑处理器上（Linux、Windows；macOS 不支持，会提示）；
4. 超过 --timeout 秒还没答完就终止程序，已经输出的答案照常判分。

只用 Python 标准库。
"""
import argparse
import os
import shlex
import statistics
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# 默认热身题：10×10，只靠单行推理就能解完
WARMUP = """PUZZLE warmup-1 10 10
1 1 1
2 3 2
1 2 2 1
9
9
2 3 2
10
10
1 5 2
5 1
9
1 5
3 4
9
2 7
9
3 4
1 5
9
4
"""


def parse_puzzles(text):
    """返回 [(id, h, w, rows, cols, 原文)]。"""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        parts = lines[i].split()
        if not parts or parts[0] != "PUZZLE":
            i += 1
            continue
        pid, h, w = parts[1], int(parts[2]), int(parts[3])
        body = lines[i + 1:i + 1 + h + w]
        if len(body) != h + w:
            sys.exit(f"题目 {pid} 不完整")
        clues = [[int(x) for x in l.split() if int(x) > 0] for l in body]
        out.append((pid, h, w, clues[:h], clues[h:], "\n".join(lines[i:i + 1 + h + w]) + "\n"))
        i += 1 + h + w
    return out


def runs(cells):
    r, run = [], 0
    for v in cells:
        if v:
            run += 1
        elif run:
            r.append(run)
            run = 0
    if run:
        r.append(run)
    return r


def correct(p, grid):
    _, h, w, rows, cols, _ = p
    if len(grid) != h or any(len(g) != w or set(g) - set("#.") for g in grid):
        return False
    g = [[c == "#" for c in row] for row in grid]
    return all(runs(g[r]) == rows[r] for r in range(h)) and \
        all(runs([g[r][c] for r in range(h)]) == cols[c] for c in range(w))


def cpu_mask(n):
    """取当前进程可用的前 n 个逻辑处理器。"""
    if hasattr(os, "sched_getaffinity"):
        cpus = sorted(os.sched_getaffinity(0))[:n]
    else:
        cpus = list(range(min(n, os.cpu_count() or n)))
    return cpus


def start(cmd, cpus):
    note = ""
    if os.name == "nt":
        if not cpus:
            return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE), note
        # 子进程从创建起就继承父进程的亲和性：先把裁判自己限定住再启动程序，启动后恢复，
        # 这样程序和它再启动的子进程（比如 py 启动器拉起的 python）从第一条指令起就只用这几个处理器。
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        k32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        me = k32.GetCurrentProcess()
        old, system = ctypes.c_size_t(), ctypes.c_size_t()
        mask = sum(1 << c for c in cpus)
        ok = k32.GetProcessAffinityMask(me, ctypes.byref(old), ctypes.byref(system)) and k32.SetProcessAffinityMask(me, mask)
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        finally:
            if ok:
                k32.SetProcessAffinityMask(me, old.value)
        if not ok or not k32.SetProcessAffinityMask(wintypes.HANDLE(int(proc._handle)), mask):
            note = "（没能限定处理器）"
    else:
        pre = None
        if cpus and hasattr(os, "sched_setaffinity"):
            pre = lambda: os.sched_setaffinity(0, cpus)  # noqa: E731
        elif cpus:
            note = "（这个系统不支持限定处理器，按全部处理器运行）"
        proc = subprocess.Popen(shlex.split(cmd), stdin=subprocess.PIPE, stdout=subprocess.PIPE, preexec_fn=pre)
    return proc, note


def run_once(cmd, warmup, puzzles, cpus, timeout, progress=0, stall=0):
    """跑一遍，返回 {id: (到达时刻, 答案行)}、开始计时的时刻、说明。

    progress：每答完这么多道正式题，在标准错误打印一次进度；stall：这么多秒没有新答案就判卡住、提前终止
    （0 表示不用）。提前终止和超时一样，没答完的题都算没回答。"""
    sizes = {p[0]: p[1] for p in warmup + puzzles}
    proc, note = start(cmd, cpus)
    answers, lock = {}, threading.Lock()
    warm_ids = {p[0] for p in warmup}
    warm_done = threading.Event()
    all_done = threading.Event()
    main_ids = {p[0] for p in puzzles}

    def reader():
        pending = None  # (id, 还要读几行, 已读行)
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            now = time.perf_counter()
            if pending:
                pid, left, grid = pending
                grid.append(line)
                if left == 1:
                    record(pid, now, grid)
                    pending = None
                else:
                    pending = (pid, left - 1, grid)
                continue
            parts = line.split()
            if len(parts) == 2 and parts[0] == "SOLUTION" and parts[1] in sizes:
                pending = (parts[1], sizes[parts[1]], [])
            elif len(parts) == 2 and parts[0] == "UNSOLVED" and parts[1] in sizes:
                record(parts[1], now, None)
        warm_done.set()
        all_done.set()

    def record(pid, now, grid):
        with lock:
            if pid in answers:
                return  # 同一道题回答两次，以第一次为准
            answers[pid] = (now, grid)
            if warm_ids <= answers.keys():
                warm_done.set()
            if main_ids <= answers.keys():
                all_done.set()

    threading.Thread(target=reader, daemon=True).start()
    t0 = None
    try:
        proc.stdin.write("".join(p[5] for p in warmup).encode())
        proc.stdin.flush()
        if not warm_done.wait(timeout):
            note += "（热身题超时）"
        else:
            t0 = time.perf_counter()
            # 另开线程写正式题：程序不及时读输入时管道会写满、write 阻塞，不能让它拖住总时限。
            data = "".join(p[5] for p in puzzles).encode()

            def writer():
                try:
                    proc.stdin.write(data)
                    proc.stdin.close()
                except (BrokenPipeError, OSError, ValueError):
                    pass

            threading.Thread(target=writer, daemon=True).start()
            deadline, reported, stalled = t0 + timeout, 0, False
            while not all_done.is_set():
                left = deadline - time.perf_counter()
                if left <= 0:
                    break
                all_done.wait(min(1.0, left))
                with lock:
                    got = [answers[p][0] for p in main_ids & answers.keys()]
                now = time.perf_counter()
                if progress and len(got) // progress > reported:
                    reported = len(got) // progress
                    print(f"  进度：{len(got)}/{len(main_ids)} 道，{now - t0:.1f} s", file=sys.stderr, flush=True)
                if stall and not all_done.is_set() and now - max(got, default=t0) > stall:
                    note += f"（{stall:g} 秒没有新答案，判卡住，提前终止）"
                    stalled = True
                    break
            if not all_done.is_set() and not stalled:
                note += "（超时，已终止）"
    except (BrokenPipeError, OSError):
        note += "（程序提前退出）"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    with lock:
        return dict(answers), t0, note


def score(puzzles, answers, t0):
    ok = wrong = unsolved = missing = 0
    per = {}
    for p in puzzles:
        a = answers.get(p[0])
        if a is None:
            missing += 1
            continue
        when, grid = a
        if grid is None:
            unsolved += 1
        elif correct(p, grid):
            ok += 1
            per[p[0]] = when
        else:
            wrong += 1
    ids = {p[0] for p in puzzles}
    arrived = sorted((a[0], pid) for pid, a in answers.items() if pid in ids)
    total = (arrived[-1][0] - t0) * 1000 if arrived and t0 else None
    # 单题用时：按答案到达的先后，和前一道答案（或计时起点）的间隔；只列解对的题
    gaps, last = {}, t0
    for when, pid in arrived:
        if pid in per:
            gaps[pid] = (when - last) * 1000
        last = when
    return {"ok": ok, "wrong": wrong, "unsolved": unsolved, "missing": missing,
            "total_ms": total, "gaps": gaps}


def judge(name, cmd, warmup, puzzles, args, cpus):
    results = []
    for i in range(args.repeat):
        answers, t0, note = run_once(cmd, warmup, puzzles, cpus, args.timeout, args.progress, args.stall)
        r = score(puzzles, answers, t0)
        r["note"] = note
        results.append(r)
        tot = f"{r['total_ms']:.1f} ms" if r["total_ms"] is not None else "—"
        print(f"[{name}] 第 {i + 1} 遍：解对 {r['ok']}，答错 {r['wrong']}，未解 {r['unsolved']}，"
              f"没回答 {r['missing']}；总用时 {tot}{note}", flush=True)
    totals = [r["total_ms"] for r in results if r["total_ms"] is not None]
    best = results[0]
    if totals:
        med = statistics.median(totals)
        best = min(results, key=lambda r: abs((r["total_ms"] or 0) - med))
    return best, (statistics.median(totals) if totals else None)


def main():
    # Windows 上输出被管道接走时默认用本地编码（如 cp1252），中文会报 UnicodeEncodeError；统一用 UTF-8
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="数织裁判")
    ap.add_argument("--cmd", help="运行你的程序的命令，例如 \"solver.exe\" 或 \"py -3.13 main.py\"")
    ap.add_argument("--puzzles", default=os.path.join(HERE, "..", "练习题.txt"), help="题目文件，默认是选手包里的练习题")
    ap.add_argument("--warmup", help="热身题文件；默认用一道内置的 10×10")
    ap.add_argument("--with-baseline", action="store_true", help="同时在这台机器上运行基准程序作对比（需要 node）")
    ap.add_argument("--baseline-only", action="store_true", help="只运行基准程序")
    ap.add_argument("--repeat", type=int, default=1, help="跑几遍，总用时取中位数（正式判分 3 遍）")
    ap.add_argument("--cpus", type=int, default=2, help="限定的逻辑处理器数，0 表示不限定（正式判分 2）")
    ap.add_argument("--timeout", type=float, default=600, help="每遍的总时限（秒）")
    ap.add_argument("--progress", type=int, default=0, help="每答完这么多道题打印一次进度（0 不打印）")
    ap.add_argument("--stall", type=float, default=0, help="这么多秒没有新答案就判卡住、提前终止（0 不用）")
    args = ap.parse_args()
    if not args.cmd and not args.baseline_only:
        ap.error("需要 --cmd，或者用 --baseline-only")

    with open(args.puzzles, encoding="utf-8") as f:
        puzzles = parse_puzzles(f.read())
    warm_text = WARMUP
    if args.warmup:
        with open(args.warmup, encoding="utf-8") as f:
            warm_text = f.read()
    warmup = parse_puzzles(warm_text)
    cpus = cpu_mask(args.cpus) if args.cpus > 0 else []
    print(f"题目 {len(puzzles)} 道，热身 {len(warmup)} 道，限定处理器 {cpus if cpus else '不限'}", flush=True)

    rows = []
    if args.cmd and not args.baseline_only:
        rows.append(("你的程序",) + judge("你的程序", args.cmd, warmup, puzzles, args, cpus))
    if args.with_baseline or args.baseline_only:
        script = os.path.join(HERE, "baseline", "main.js")
        if not os.path.exists(script):
            script = os.path.join(HERE, "..", "solvers", "baseline", "main.js")
        cmd = subprocess.list2cmdline(["node", script]) if os.name == "nt" else shlex.join(["node", script])
        rows.append(("基准程序",) + judge("基准程序", cmd, warmup, puzzles, args, cpus))

    print()
    for name, r, med in rows:
        tot = f"{med:.1f} ms" if med is not None else "—"
        print(f"{name}：解对 {r['ok']}/{len(puzzles)}，答错 {r['wrong']}，总用时（中位）{tot}")
    if len(rows) == 2 and rows[0][2] and rows[1][2] and rows[0][1]["ok"] == rows[1][1]["ok"] == len(puzzles):
        ratio = rows[1][2] / rows[0][2]
        print(f"你的程序是基准程序的 {ratio:.2f} 倍速度" if ratio >= 1 else f"你的程序比基准程序慢 {1 / ratio:.2f} 倍")
    if rows and any(r["gaps"] for _, r, _ in rows):
        print("\n单题用时（ms，按答案到达的间隔）：")
        print("题号".ljust(16) + "".join(name.rjust(12) for name, _, _ in rows))
        for p in puzzles:
            cells = []
            for _, r, _ in rows:
                g = r["gaps"].get(p[0])
                cells.append(f"{g:.1f}" if g is not None else "—")
            print(p[0].ljust(16) + "".join(c.rjust(12) for c in cells))


if __name__ == "__main__":
    main()
