# 学号: 250226（接口适配与修复）
"""立直麻将 HTTP + JSON 后端。

启动：python3 server.py --port 8000
只依赖 Python 标准库，页面由同目录 frontend/index.html 提供。
"""

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import game
import tenpai

INDEX = os.path.join(BASE_DIR, "frontend", "index.html")
RYUUKYOKU_KEY = {
    "荒牌流局": "exhaustive",
    "九种九牌": "kyuushu",
    "四杠散了": "four_kans",
    "四家立直": "four_riichi",
    "四风连打": "four_winds",
    "三家和": "triple_ron",
}

current_game = None
current_game_id = None
current_players = ["human", "bot", "bot", "bot"]
_game_serial = 0


def _tile_left(items):
    return [{"tile": tile, "left": left} for tile, left in items.items()]


def _build_hints(g, seat):
    empty = {"waits": [], "discards": {}, "furiten": False}
    if g.phase == "end":
        return None
    try:
        hand = list(g.hands[seat])
        melds = g.melds_plain(seat)
        visible = g.get_visible(seat)
        total = len(hand) + 3 * len(melds)
        if total == 14:
            # 立直后没有择牌空间，只提示其他可打牌会诱导玩家点击非法操作。
            raw = {} if g.riichi[seat] else tenpai.discard_hints(hand, melds, visible)
            return {
                "waits": [],
                "discards": {tile: _tile_left(waits) for tile, waits in raw.items()},
                "furiten": False,
            }
        if total == 13:
            waits = tenpai.get_waits(hand, melds, visible)
            return {
                "waits": _tile_left(waits),
                "discards": {},
                "furiten": bool(waits and g._is_furiten(seat)),
            }
    except Exception as exc:
        # 提示不是规则判定，提示异常不应让整局无法继续；错误仍写服务器日志。
        print("hints error: %s" % exc, file=sys.stderr)
    return empty


def _legal(g, seat):
    result = []
    chi_options, pon_options, ankan, kakan = [], [], [], []
    for action in g.get_legal_actions(seat):
        kind = action["type"]
        if kind == "chi":
            chi_options.append(list(action["tiles"]))
        elif kind == "pon":
            pon_options.append(list(action["tiles"]))
        elif kind == "kan":
            kan_kind = action.get("kind")
            if kan_kind == "ankan":
                ankan.append(game.norm(action["tiles"][0]))
            elif kan_kind == "kakan":
                kakan.append(game.norm(action["tiles"][0]))
            else:
                result.append({"type": "minkan"})
        elif kind in ("discard", "riichi"):
            result.append({"type": kind, "tiles": list(action["tiles"])})
        else:
            result.append({"type": kind})
    if chi_options:
        result.append({"type": "chi", "options": chi_options})
    if pon_options:
        result.append({"type": "pon", "options": pon_options})
    if ankan:
        result.append({"type": "ankan", "tiles": ankan})
    if kakan:
        result.append({"type": "kakan", "tiles": kakan})
    return result


def _waiting_for(g):
    if g.phase == "discard":
        return [g.current] if g.current in g.human_seats else []
    if g.phase == "call":
        return sorted(s for s in g.call_options
                      if s in g.human_seats and s not in g.responses)
    return []


def _format_meld(m):
    return {
        "type": m["type"],
        "tiles": list(m["tiles"]),
        "from": m.get("from"),
        "called_tile": m.get("called_tile"),
    }


def _result(g):
    r = g.result
    if not r:
        return None
    if r["type"] in ("tsumo", "ron"):
        wins = []
        for w in r["wins"]:
            hand = list(w["hand"])
            if w["tile"] in hand:
                hand.remove(w["tile"])
            hand.sort(key=game.tile_key)
            wins.append({
                "seat": w["seat"],
                "from": w["from"],
                "hand": hand,
                "melds": [_format_meld(m) for m in g.melds[w["seat"]]],
                "win_tile": w["tile"],
                "yaku": [dict(y) for y in w["yaku"]],
                "han": w["han"],
                "fu": w["fu"],
                "yakuman": w["yakuman"],
                "points": w["points"],
            })
        return {
            "type": "agari",
            "wins": wins,
            "dora_indicators": list(r["dora_indicators"]),
            "uradora_indicators": list(r.get("ura_indicators") or []),
            "delta": list(r["delta"]),
        }
    out = {
        "type": "ryuukyoku",
        "reason": RYUUKYOKU_KEY.get(r.get("reason"), "exhaustive"),
        "delta": list(r["delta"]),
    }
    if "tenpai" in r:
        out["tenpai"] = list(r["tenpai"])
    return out


def build_state(g, seat):
    if seat not in range(4):
        raise ValueError("seat 必须在 0~3")
    st = g.get_state(seat)
    r = st["round"]
    phase = "playing"
    if g.phase == "end":
        phase = "game_end" if g.game_over else "round_end"

    separate_draw = g.drawn if g.phase == "discard" else None
    if g.phase == "end" and g.result and g.result.get("type") == "tsumo":
        separate_draw = g.drawn
    players = []
    for s in range(4):
        hand = list(g.hands[s])
        if s == g.current and separate_draw is not None and separate_draw in hand:
            hand.remove(separate_draw)
        # remove() 会删掉旧副本，若 drawn 与旧牌相同，末尾的新副本仍需重新归位。
        hand.sort(key=game.tile_key)
        if s in g.human_seats:
            name = "你" if s == 0 else "座位 %d" % s
        else:
            name = "电脑 %d" % s
        p = {
            "seat": s,
            "name": name,
            "score": g.scores[s],
            "seat_wind": g.jikaze(s),
            "riichi": g.riichi[s],
            "discards": [{
                "tile": d["tile"],
                "tsumogiri": d.get("tsumogiri", False),
                "riichi": d.get("riichi", False),
                "called": d.get("called", False),
            } for d in g.rivers[s]],
            "melds": [_format_meld(m) for m in g.melds[s]],
            "hand_count": len(hand),
        }
        if s == seat:
            p["hand"] = hand
        players.append(p)

    events = []
    for event in g.events:
        e = dict(event)
        if e.get("type") == "draw" and e.get("seat") != seat:
            e["tile"] = None
        events.append(e)

    return {
        "version": 1,
        "game_id": current_game_id,
        "phase": phase,
        "round": {
            "wind": r["bakaze"],
            "number": g.kyoku % 4 + 1,
            "honba": r["honba"],
            "riichi_sticks": r["kyotaku"],
            "dealer": r["oya"],
        },
        "dora_indicators": list(st["dora_indicators"]),
        "wall_left": st["remaining"],
        "viewer": seat,
        "turn": st["current"],
        "waiting_for": _waiting_for(g) if phase == "playing" else [],
        "rules": dict(g.rules),
        "players": players,
        "drawn": g.drawn if g.phase == "discard" and seat == g.current else None,
        "legal_actions": _legal(g, seat) if phase == "playing" else [],
        "hints": _build_hints(g, seat) if phase == "playing" else None,
        "events": events,
        "result": _result(g),
    }


def _seat(value):
    try:
        seat = int(value)
    except (TypeError, ValueError):
        raise ValueError("seat 必须是 0~3")
    if seat not in range(4):
        raise ValueError("seat 必须在 0~3")
    return seat


def _require_game(game_id):
    if current_game is None:
        raise ValueError("还没开局，请先调用 /api/new_game")
    if game_id != current_game_id:
        raise ValueError("game_id 不正确或该局已被新游戏替换")
    return current_game


class MahjongHandler(BaseHTTPRequestHandler):
    server_version = "Mahjong/1.0"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            raise ValueError("Content-Length 不正确")
        if length <= 0:
            return {}
        if length > 2_000_000:
            raise ValueError("请求体过大")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _html(self):
        with open(INDEX, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path in ("/", "/index.html"):
                self._html()
                return
            if parsed.path == "/api/state":
                qs = parse_qs(parsed.query)
                g = _require_game(qs.get("game_id", [None])[0])
                seat = _seat(qs.get("seat", [0])[0])
                self._send_json(build_state(g, seat))
                return
            self._send_json({"error": "not found"}, 404)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": "服务器错误: %s" % exc}, 500)

    def do_POST(self):
        global current_game, current_game_id, current_players, _game_serial
        parsed = urlparse(self.path)
        try:
            data = self._read_json()
            if not isinstance(data, dict):
                raise ValueError("JSON 请求体必须是对象")
            if parsed.path == "/api/new_game":
                players = data.get("players", ["human", "bot", "bot", "bot"])
                if (not isinstance(players, list) or len(players) != 4
                        or any(p not in ("human", "bot") for p in players)):
                    raise ValueError("players 必须是四个 human/bot")
                human_seats = [i for i, p in enumerate(players) if p == "human"]
                _game_serial += 1
                new_id = "g%d" % _game_serial
                new_game = game.Game(
                    human_seats=human_seats,
                    wall=data.get("wall"),
                    seed=data.get("seed"),
                    rules=data.get("rules"),
                    length=data.get("length", "tonpuu"),
                )
                current_game = new_game
                current_game_id = new_id
                current_players = list(players)
                self._send_json(build_state(new_game, 0))
                return

            g = _require_game(data.get("game_id"))
            seat = _seat(data.get("seat", 0))
            if parsed.path == "/api/action":
                action = str(data.get("type") or data.get("action") or "").lower()
                if action in ("ankan", "kakan", "minkan"):
                    action = "kan"
                elif action in ("skip", "cancel"):
                    action = "pass"
                elif action in ("hu", "win", "agari"):
                    action = "tsumo" if g.phase == "discard" else "ron"
                if not action:
                    raise ValueError("缺少 type 参数")
                g.do_action(seat, action, tile=data.get("tile"), tiles=data.get("tiles"),
                            tsumogiri=data.get("tsumogiri"))
                self._send_json(build_state(g, seat))
                return
            if parsed.path == "/api/next":
                g.next_round(wall=data.get("wall"))
                self._send_json(build_state(g, seat))
                return
            self._send_json({"error": "not found"}, 404)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": "服务器错误: %s" % exc}, 500)


def run_server(host="127.0.0.1", port=8000):
    httpd = HTTPServer((host, port), MahjongHandler)
    # 服务器控制台可能使用 ASCII 代码页，启动日志不能因此让进程退出。
    print("Mahjong backend: http://%s:%d/" % (host, port), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


# 兼容旧补丁脚本的函数名。
run = run_server


def main():
    parser = argparse.ArgumentParser(description="立直麻将后端")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run_server(port=args.port)


if __name__ == "__main__":
    main()
