#!/usr/bin/env python3
"""用计分时同样的方式跑乌龟，只报一套 120 道题的总用时。

    python3 测速.py 题目.txt

先按 检查.py 的规则查格式（不查答案、不查唯一解），题数不是 120 道就拒绝。然后用裁判
（先发一道热身题、不计时，再发全部题，限 2 个逻辑处理器）跑 乌龟/solver.py，每道题最多
算 PER_PUZZLE 秒，到时乌龟输出 UNSOLVED。只打印整套的总用时和卡到上限的题数，不报单题。

规则：整场最多用 3 次，只用来检查题集，不能拿它挑题、改题。只用 Python 标准库。
"""
import os
import re
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from 检查 import check  # noqa: E402

PER_PUZZLE = 10  # 每道题的用时上限（秒），和正式计分相同


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        sys.exit("用法：python3 测速.py 题目.txt")
    path = os.path.abspath(sys.argv[1])
    with open(path, encoding="utf-8") as f:
        puzzles, errors = check(f.read(), None)
    if errors:
        print("题集格式不对，没有测速：")
        for e in errors[:20]:
            print("  " + e)
        sys.exit(1)

    turtle = [sys.executable, os.path.join(HERE, "乌龟", "solver.py"), "--time-limit", str(PER_PUZZLE)]
    turtle_cmd = subprocess.list2cmdline(turtle) if os.name == "nt" else shlex.join(turtle)
    judge = [sys.executable, os.path.join(HERE, "裁判", "judge.py"), "--cmd", turtle_cmd, "--puzzles", path,
             "--repeat", "1", "--timeout", str(PER_PUZZLE * len(puzzles) + 120)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    print(f"测速中：{len(puzzles)} 道题，每道最多 {PER_PUZZLE} 秒，最长约 {PER_PUZZLE * len(puzzles) // 60} 分钟……", flush=True)
    out = subprocess.run(judge, capture_output=True, text=True, encoding="utf-8", env=env).stdout
    m = re.search(r"第 1 遍：解对 (\d+)，答错 (\d+)，未解 (\d+)，没回答 (\d+)；总用时 ([^\n（]+)(（[^）]*）)?", out)
    if not m:
        sys.exit("测速失败：裁判没有给出结果。")
    ok, wrong, unsolved, missing, total, note = m.groups()
    capped = int(unsolved) + int(missing)
    print(f"总用时：{total.strip()}{note or ''}")
    print(f"乌龟解出 {ok} 道；卡到上限或没答完 {capped} 道。")
    if int(wrong):
        print(f"乌龟答出了 {wrong} 道不满足线索的答案，题目可能有问题。")
    print("提醒：整场最多用 3 次。")


if __name__ == "__main__":
    main()
