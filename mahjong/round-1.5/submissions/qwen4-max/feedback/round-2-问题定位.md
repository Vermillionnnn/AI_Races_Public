# Round-2 · 社团反馈的 10 个问题：定位 + 改法

> 整理：qwen4-max。每条都已在 `submission/round-1/qwen4-max/` 里改好并加了回归测试
> （`tests/test_round2.py`，10 条全过；原有 core/stress/edges/http/格式测试也全过）。
> 下面按"现象 → 根因 → 改在哪 → 怎么改"写，方便转给对应同学。原件 `mahjong/prompt/` 未动。

---

## 1. 四番和了一万多点（4番40符该满贯封顶 8000）— 260409 `score.py`
- **根因**：`_get_limit_rank` 只按**番数**判满贯（`han>=5`），漏了"基本点 ≥2000 即满贯"这条。
  4番40符 基本点 = 40×2⁶ = 2560 ≥2000，本该满贯，却走了查表/公式算出 10300；3番70符=2240 同理算出 9000。
  关不关切上满贯都受影响（切上只是额外把 4番30符/3番60符 抬进满贯）。
- **改法**：在 `_get_limit_rank` 里算 `base = fu × 2^(han+2)`，`han>=5 or base>=2000` 都返回满贯。
  这样 4番40符、3番70符、2番130符等基本点够 2000 的都正确封顶。

## 2. 只有抢杠一个役不让和 — 250207 `game.py`
- **根因**：`_kakan` 检查别人能不能抢杠时调 `_win_ok`，但那时 `self.chankan_mode` 还是 False，
  `_make_state` 给出的 `chankan=False`，于是"抢杠"这 1 番没算进去，没别的役就判 0 番拒绝。
- **改法**：`_kakan` 一开始就把 `chankan_mode=True` 再做判断；没人抢杠就置回 False 再 `_do_kakan`。
  `_resolve_calls` 抢杠分支没人荣和时也置回 False。抢杠本身是 1 番，现在能单独成立。

## 3. 两人四杠，第 4 杠打出的牌还能被碰 — 250207 `game.py`
- **根因**：原来四杠散了只在 `_after_discard_pass`（没人鸣牌时）检查；一旦有人碰/吃就走鸣牌分支，永远查不到。
- **改法**：加 `four_kans_pending` 标志。`_after_kan` 里两人以上合计第 4 杠时置位；
  `_discard` 里这张牌**只允许荣和、禁止鸣牌**；`_resolve_calls` 里没人荣和就 `_abort('four_kans')`。
  荣和仍优先于流局。删掉 `_after_discard_pass` 里旧的那段检查。

## 4. 手牌没排好，摸到一样的牌新摸的跑最右 — 250207 `game.py`
- **根因**：吃/碰后 `_call_meld` 从手里拿走牌却**没重新排序**，手牌就乱了。
  （摸到的牌单独显示在右边是前端刻意把 `drawn` 隔开，属正常。）
- **改法**：`_call_meld` 拿完牌 `hand.sort(key=tile_key)`；`get_state` 展示前再统一排一次序兜底。

## 5. 剩牌提示偏少，碰过的牌被扣两次 — 250207 `game.py`
- **根因**：被鸣走的舍张在河里标了 `called=True` 但**仍留在河里**，同时又进了副露。
  `get_visible` 把河和副露都算进去，这张牌就被扣了两次。
- **改法**：`get_visible` 收河时跳过 `called` 的舍张（`if not r['called']`），它已在副露里算过。

## 6. 副露多吃完一张，手里全是食替不能打，卡住 — 250207 `game.py`
- **根因**：提供吃/碰选项时没检查"鸣完手里还有没有能打的牌"。极端副露下吃完只剩食替禁张，无牌可打。
- **改法**：新增 `_discardable_after_call`，模拟鸣牌后去掉食替禁张是否还有可打张；
  `_chi_combos` 和碰的选项都据此过滤，这种吃/碰干脆不提供。

## 7. 立直宣言牌被和了，结算还挂着立直标 — 250207 `game.py`
- **根因**：宣言时就把 `riichi[seat]=True`；宣言牌被荣和时立直其实不成立（也没交棒），但标记没撤。
- **改法**：`_resolve_calls` 荣和分支里，若 `riichi_pending==放铳者`，撤掉其 `riichi/double_riichi/ippatsu`、
  河里那张的横放标记，并清 `riichi_pending`。供托本来就没交，保持不变。

## 8. 立直后只能摸切，提示还提示别的牌 — 250207 `game.py`
- **根因**：`_build_hints` 对 14 张一律算全部打牌提示，没考虑立直后只能打摸到的那张。
- **改法**：立直时把 `discard_hints` 结果过滤到只剩 `drawn` 那一项。

## 9. 打牌前听牌提示剩几张偶尔多 1 — 260522 `tenpai.py`
- **根因**：`discard_hints` 算"打某张后听什么"时，打出的那张会进河，但没把它算进 `visible`，
  当听的牌恰好包含这张时就少扣一张、剩牌多 1。
- **改法**：`get_waits(rest, melds, visible + [tile])`，把打出的张计入河。

## 10. 全电脑开局卡住 / 真人在非 0 座位视角不对 — 250226 `server.py` + 前端
- **根因 a（卡住）**：`_new_game` 在没人选 human 时硬塞 `human_seats=[0]`，于是停在座位 0 等人操作。
- **根因 b（视角）**：后端返回的 `viewer` 其实是对的（第一个真人座位）；是**前端** `newGame` 把 `viewer` 写死 0，
  没跟随后端返回的 `state.viewer`，导致真人在别的座位时页面仍按座位 0 渲染、看不到自己手牌。
- **改法**：
  - server：去掉硬塞 `[0]`，`human_seats` 可为空（`Game` 会自动打完，观战模式）；视角取第一个真人座位，没有则 0。
  - 前端：`newGame` 拿到状态后 `viewer = state.viewer` 并同步下拉框、重渲染（仅这一处小改）。

---

### 验证
`python3 tests/test_round2.py` 逐条覆盖上面 10 个问题；
`test_core / test_stress(30 半庄随机操作) / test_edges / test_http / check_format.js` 全部通过，点数守恒。