# GPT-6 第二轮数织题集

共 120 道 45×45 题。每道题都从已知黑白盘面提取线索，并附满足这些线索的答案。

## 出题与选题

从固定随机种子生成接近一半黑格的盘面，并打破会保留全部线索的相邻 2×2 交换。找到多解时，尝试改变其中一个分歧格，再重新证明。也对较难的候选尝试少量格子扰动、转置和反射。定稿排除转置或反射等价的盘面，每个原始种子最多保留四道。最终题集来自 31 个原始种子。

乌龟在单行推理停滞后会遍历未知格做两色试填。定稿题在单行传播后仍有 1,933 到 2,025 个未定格，不同假设会触发多种行列状态。独立的 C++ 难度模型按完整试填轮次统计新出现的单行状态、传播次数和试填数，用工作量筛选。官方测速只用于检查已定稿的整套题。

## 唯一性

出题器用位集动态规划计算每条线的所有可行块起点，再迭代传播必然格。试填时排除矛盾的颜色，并合并两色共同推出的格子。传播停滞时，对一个未定格的两种颜色分别搜索。只有在核对已知答案并穷尽其余分支后才接受。最终选题阶段对 120 道题逐一取消搜索预算，重新证明唯一。另外以标量前向、后向动态规划替换单行推理，重跑穷举，120 道均通过。官方格式检查确认了全部答案和线索相符。

## 编译和复现

在仓库根目录的 PowerShell 中执行。中间候选池和评分文件仅供复现。

```powershell
Push-Location .\nonogram\submission\round-2\gpt-6
g++ -O2 -std=c++20 .\generator.cpp -o .\generator.exe
cmd /c ".\generator.exe survey 8291300 1900 1 850000 4 > a.pool"
cmd /c ".\generator.exe survey 9302700 1900 2 850000 4 > b.pool"
cmd /c "copy /y /b a.pool+b.pool ab.pool"
cmd /c ".\generator.exe score ab.pool 50000000 4 > ab.scores"
cmd /c ".\generator.exe survey 15538100 1400 1 6500000 4 > c.pool"
cmd /c ".\generator.exe score c.pool 55000000 4 > c.scores"
cmd /c ".\generator.exe breed ab.scores 40 40 325829129 2600000 4 > d.pool"
cmd /c ".\generator.exe score d.pool 55000000 4 > d.scores"
cmd /c ".\generator.exe orient ab.scores 100 > o.pool"
cmd /c ".\generator.exe score o.pool 55000000 4 > o.scores"
cmd /c "copy /y /b ab.scores+c.scores+d.scores+o.scores first.scores"
cmd /c ".\generator.exe breed first.scores 32 15 7861957 4200000 4 > f.pool"
cmd /c ".\generator.exe score f.pool 55000000 4 > f.scores"
cmd /c "copy /y /b first.scores+f.scores final.scores"
.\generator.exe choose final.scores puzzles.txt answers.txt 4
Move-Item -Force puzzles.txt 题目.txt
Move-Item -Force answers.txt 答案.txt
Pop-Location
```

在 Linux 上以单线程完整复跑上述种子流程，重建的题目和答案与提交文件逐字节一致。

## 官方测速

在当前 Linux 云环境用选手包的 `测速.py` 对冻结题集运行一次。总用时 **1,124,414.9 ms**。乌龟解出 **23 道**，**97 道**达到上限或未答完。
