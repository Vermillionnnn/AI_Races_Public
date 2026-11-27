# 网页麻将 · round-1 整理（qwen4-max）

社团同学分头写的后端，拼起来后"打起来手感怪"。这份是**修好、对齐前端接口、加了规则开关**的版本。
学生交上来的原件在 `mahjong/prompt/`，**一个字没动**；本目录是复制后修改的工作副本。

## 怎么跑
```
python3 server.py --port 8000
```
- 浏览器开 `http://127.0.0.1:8000/`（`GET /` 直接返回 `frontend/index.html`）。
- 只用 Python 标准库，无需 Flask。默认端口 8000，`--port` 可改，只监听 127.0.0.1。
- 兼容旧入口：`python3 server_patch.py` 也行（转调 server）。
- 前端单独跑时：`index.html?api=http://localhost:8000`，已开 CORS。`?seed=123` 可复现。

## 目录
```
game.py / fu.py / yaku.py / score.py / tenpai.py / server.py   修好的后端
server_patch.py        旧补丁的兼容入口（逻辑已并入 server.py）
frontend/index.html    前端（仅加了规则开关下拉框，其余未动）
frontend/接口说明.md    前端接口契约（照它实现）
docs/规则.md            采用的规则 + 四个开关 + 未采用/简化项
docs/新手教学.md        零基础教学
docs/麻将项目分工和约定.md  原任务书（保留）
feedback/<学号>.md      给每位同学的反馈（可直接转发）
tests/                 单元 / 压力 / 边界 / HTTP / 前端格式校验
```

## 这次主要修了什么（详见 feedback/）
1. **一和牌就崩**：score 返回 dict，game 按元组拆 → KeyError。已按 dict 接。
2. **牌山顺序**与前端《接口说明》不符（配牌按物理座位、王牌宝牌/里宝/岭上位置）。已重排。
3. **暗杠没标**（ankan_indices / an_gang）→ 被当明杠、破门清、符算错。已传。
4. **里宝混进宝牌**、**地和键名不一致**（chihou/chiihou）。已对齐。
5. **符/番各取各的拆法** → 现联合取点数最高（fu_candidates + yaku_candidates）。
6. **双倍/复合役满被少算**、**切上满贯写死**、**连风雀头写死**、**食断写死** → 做成开关/倍数。
7. **听牌剩牌数重复扣副露** → 修正。
8. **接口字段/启动方式/多局 game_id** 与前端不符 → 完全按《接口说明》实现。
9. 补齐 **tsumogiri、events、rules 回显、length、四杠散了、抢杠、碰多选项、终局供托**。

## 规则开关（新游戏 rules，默认值）
`aka_dora=true`（赤宝牌）、`kuitan=true`（食断）、`kiriage_mangan=false`（切上满贯）、`renpu_fu=4`（连风雀头）。
页面顶部已有下拉框可选，整场生效并在状态里回显。

## 测试怎么跑
```
python3 tests/test_core.py     # 符/番/点/听牌 单元 +  forced 天和/荣和
python3 tests/test_stress.py   # 30 个半庄随机人类操作，点数守恒、无崩溃
python3 tests/test_edges.py    # 抢杠 / 四杠散了 / 换庄 / 立直棒
python3 tests/test_round2.py   # 社团反馈的 10 个问题逐条回归
python3 tests/test_http.py     # 起真实 server，走完整接口契约
python3 tests/gen_states.py && node tests/check_format.js   # 用前端自带 checkState 校验格式
```
全部通过。`test_http.py` / `test_round2.py` 会自动起停服务并占用一个空闲端口。

## Round-2（社团反馈的 10 个问题）
已逐条定位并修复，详见 `feedback/round-2-问题定位.md`（现象→根因→改法，可转给对应同学）：
满贯基本点封顶、抢杠单独成役、四杠散了禁止鸣牌、鸣牌后手牌排序、被碰舍张不重复扣、
食替无牌可打的吃碰不提供、立直宣言被荣和撤标、立直后提示只留摸切、打牌提示剩牌计数、
全电脑自动打完 + 非 0 座位真人视角同步。

## 已知简化（后续可加，见 docs/规则.md §12）
流局满贯、包牌未实现；杠宝牌统一"杠完立刻翻"；仅加杠可抢杠；电脑按任务书摸切（较被动）。