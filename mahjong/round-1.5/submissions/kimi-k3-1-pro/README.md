# 网页立直麻将（round-1 修复版）

## 启动

在本目录执行：

```bash
python3 server.py --port 8000
```

Windows 开发机也可执行 `py -3.13 server.py --port 8000`。不带 `--port` 时默认 8000，只监听 `127.0.0.1`。浏览器打开 `http://127.0.0.1:8000/`。

只使用 Python 标准库；前端仍是原来的 `frontend/index.html`。`server_patch.py` 仅保留为旧命令的兼容入口，不再维护第二套转换逻辑。

## 规则选择

页面目前会显示实际规则，但原页面没有规则选择控件。调用 `POST /api/new_game` 时可传：

```json
{
  "players": ["human", "bot", "bot", "bot"],
  "length": "tonpuu",
  "rules": {
    "aka_dora": true,
    "kuitan": true,
    "kiriage_mangan": false,
    "renpu_fu": 4
  }
}
```

四个键均可省略，省略时使用上述默认值。规则会在状态中原样返回，并在整场保持不变。详见 `docs/新手规则.md`。

## 测试

```bash
python3 -m unittest -v test_tenpai.py test_fu_score.py test_yaku.py test_game.py test_server.py
```

API 实测见 `TESTING.md`。指定牌山时严格采用 `frontend/接口说明.md` 的物理座位与王牌布局。

## 目录

- `game.py`：对局状态机、电脑、流局与换庄。
- `tenpai.py`：和牌形、听牌与打牌提示。
- `yaku.py`：役、宝牌、役满及逐项番数。
- `fu.py`：符数。
- `score.py`：基本点、本场、供托与多倍役满。
- `server.py`：HTTP 接口、视角隐藏及前端格式。
- `feedback/`：按学号分开的修复反馈。
- `docs/新手规则.md`：规则与新手教学。
