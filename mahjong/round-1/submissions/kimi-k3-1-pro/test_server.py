import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base = "http://127.0.0.1:%d" % cls.port
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        cls.process = subprocess.Popen(
            [sys.executable, "server.py", "--port", str(cls.port)],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 5
        while True:
            try:
                with urllib.request.urlopen(cls.base + "/", timeout=.2) as response:
                    if response.status == 200:
                        break
            except Exception:
                if cls.process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("server did not start")
                time.sleep(.05)

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=3)

    def request(self, path, method="GET", data=None, expected=200):
        body = None if data is None else json.dumps(data).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=body, method=method,
            headers={"Content-Type": "application/json"},
        )
        start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                raw = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
            content_type = exc.headers.get("Content-Type", "")
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(status, expected, raw[:500])
        return raw, content_type

    def test_html_rules_state_action_and_errors(self):
        raw, content_type = self.request("/")
        self.assertIn(b"<html", raw.lower())
        self.assertIn("text/html", content_type)

        rules = {"aka_dora": False, "kuitan": False,
                 "kiriage_mangan": True, "renpu_fu": 2}
        raw, _ = self.request("/api/new_game", "POST", {
            "players": ["human", "bot", "bot", "bot"],
            "length": "hanchan", "seed": 123, "rules": rules,
        })
        state = json.loads(raw)
        self.assertEqual(state["rules"], rules)
        self.assertEqual(state["version"], 1)
        self.assertEqual(len(state["players"]), 4)
        self.assertIn("hand", state["players"][0])
        self.assertTrue(all("hand" not in state["players"][i] for i in (1, 2, 3)))
        self.assertFalse(any(t[0] == "0" for t in state["players"][0]["hand"]))
        game_id = state["game_id"]

        self.request("/api/state?game_id=wrong&seat=0", expected=400)
        raw, _ = self.request("/api/state?game_id=%s&seat=1" % game_id)
        other = json.loads(raw)
        self.assertEqual(other["viewer"], 1)
        self.assertIn("hand", other["players"][1])
        self.assertNotIn("hand", other["players"][0])

        discard = next(a for a in state["legal_actions"] if a["type"] == "discard")
        tile = discard["tiles"][0]
        raw, _ = self.request("/api/action", "POST", {
            "game_id": game_id, "seat": 0, "type": "discard", "tile": tile,
            "tsumogiri": tile == state["drawn"],
        })
        after = json.loads(raw)
        self.assertIn(after["phase"], ("playing", "round_end", "game_end"))
        self.assertTrue(after["events"])
        self.request("/api/next", "POST", {"game_id": game_id, "seat": 0}, expected=400)
        self.request("/api/new_game", "POST", {"wall": ["1m"]}, expected=400)


if __name__ == "__main__":
    unittest.main()
