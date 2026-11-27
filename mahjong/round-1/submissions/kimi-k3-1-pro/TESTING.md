# 验证记录

环境：Windows 11，Python 3.13；未使用第三方库，未联网。

## 自动测试

```powershell
py -3.13 -B -m unittest -v test_tenpai.py test_fu_score.py test_yaku.py test_game.py test_server.py
py -3.13 -m py_compile game.py yaku.py fu.py score.py tenpai.py server.py server_patch.py test_game.py test_server.py
```

最终结果：39 项 unittest 全部通过，编译检查通过。

覆盖范围：

- 和牌形、七对子、国士、副露听牌、红五提示与剩余枚数。
- 平和、七对子 25 符、连风 2/4 符、明暗杠、边嵌单骑、副露无加符。
- 点数表与公式、本场供托、切上开关、庄闲自摸、累计及多倍役满。
- 食断/赤牌开关、暗杠、地和拼写兼容、逐项番数、非法输入不崩溃。
- 物理座位发牌、王牌布局、岭上补牌、天和、抢杠、四杠优先级、视角隐藏。
- 自动启动真实 HTTP 进程，检查 HTML、规则回显、状态视角、打牌、错误响应和 5 秒时限。

算番模块另做 5000 组随机合法/非法输入崩溃检查，全部正常返回。

## 整局压力测试

用四个由测试驱动的人类座位，随机选择合法打牌、立直、吃碰杠、和与跳过，连续完成 12 场东风战（共 96 局）；每局检查：

- 没有无合法响应的死锁；
- 没有越权操作和异常；
- `sum(scores) + 1000 * kyotaku == 100000`；
- 整场结束后的分数总和为 100000。

电脑使用题目允许的“摸什么打什么”最简策略，因此不会主动做牌，摸切局大量荒牌属于预期，不作为和牌率指标。

## 页面与启动

`test_server.py` 会动态选择本地端口并启动、结束服务器。也人工用 `py -3.13 -B server.py --port 8765` 实测过：

- `GET /` 返回 200 和原 HTML；
- 新游戏传四个非默认规则均正确返回；
- 错误 game_id、未结束就 next、非法 wall 均返回 400 与 error；
- 请求耗时约 0.02 秒，低于 5 秒限制。

`frontend/index.html` 与 `mahjong/prompt/frontend/index.html` 的 SHA-256 完全一致，没有修改页面。原 `mahjong/prompt/` 无 diff。
