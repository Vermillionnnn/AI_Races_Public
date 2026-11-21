# 数织

数织（Nonogram）：每行每列给出连续黑格的长度，要把整张图填出来。这里的题都是 40–45 阶、证明过只有一个解的难题。

| 轮次 | 任务 | 成绩 |
|---|---|---|
| [`round-1/`](round-1/) | 速度赛：30 分钟写一个求解程序，解 120 道正式题，先比解对几道，再比总用时 | [`round-1/results.md`](round-1/results.md) |
| [`round-2/`](round-2/) | 出题赛：45 分钟出 120 道只有一个解的题，越能难倒「乌龟」越好；加时赛的对手换成 round-1 前五名的程序 | [`round-2/results.md`](round-2/results.md) |

## round-1

- `puzzles/round-1.txt`：正式题 120 道（只有线索，格式见选手包里的 `格式.md`），sha256 见 `SHA256SUMS`。
- `judge/judge.py`：判分用的裁判。限定 2 个逻辑处理器，先发热身题，再发正式题，记从发题到收齐答案的总用时：

  ```
  python3 judge/judge.py --cmd "<选手程序>" --puzzles puzzles/round-1.txt --repeat 3
  ```

- `judge/baseline/`：主办方用 JavaScript 写的基准程序（发给选手用来校准环境，很慢，不是对手）。
- `judge/turtle/`：「乌龟」，纯 Python、单线程的参考求解器，round-1 赛后用来说明算法比语言重要。

## round-2

- 各选手交的题集在 `submissions/<选手>/题目.txt`、`答案.txt`，加时赛的在 `加时赛/` 里；sha256 见 `SHA256SUMS`。
- `judge/unique.py`：逐题证明只有一个解（不设时限）。它调用 `judge/prover/` 里的证明器（C++，只有证明部分，生成题目的出题器不公开），先编译：

  ```
  g++ -O3 -std=c++17 judge/prover/prove.cpp -o judge/prover/prove
  python3 judge/unique.py submissions/<选手>/题目.txt submissions/<选手>/答案.txt --jobs 4 --count-rule
  ```

  `--count-rule` 在推理里加上跨列计数规则（相邻两列黑格数之差等于这条边界上黑块的起点数减终点数），gpt-6-2-astra 的题不加这条会证得很慢。
- `judge/turtle_bench.py`：正赛计时，每道题单独起一个乌龟进程、多道并行，每道上限 60 秒。
- `judge/judge.py`：加时赛计时，用 round-1 前五名的程序（在 `../round-1/submissions/` 里）解各家的题。
