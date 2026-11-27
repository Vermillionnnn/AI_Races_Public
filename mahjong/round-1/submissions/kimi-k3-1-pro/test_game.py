import unittest

import game
import server


class GameTest(unittest.TestCase):
    def test_wall_layout_and_physical_seat_dealing(self):
        wall = game.make_wall()
        g = game.Game(human_seats=[0, 1, 2, 3], wall=wall)
        for seat in range(4):
            self.assertEqual(g.hands[seat][:13], sorted(wall[seat * 13:(seat + 1) * 13], key=game.tile_key))
        self.assertEqual(g.drawn, wall[52])
        self.assertEqual(g.dora_indicators(), [wall[122]])
        self.assertEqual(g.ura_indicators(), [wall[127]])

        second = game.make_wall()
        second.reverse()
        g.kyoku = 1
        g.start_round(second)
        self.assertEqual(g.oya, 1)
        self.assertEqual(g.current, 1)
        self.assertEqual(g.drawn, second[52])
        for seat in range(4):
            self.assertEqual(g.hands[seat][:13], sorted(second[seat * 13:(seat + 1) * 13], key=game.tile_key))

    def test_rinshan_and_kang_dora_positions(self):
        wall = game.make_wall()
        g = game.Game(human_seats=[0, 1, 2, 3], wall=wall)
        before = g.remaining()
        g._draw(0, rinshan=True)
        self.assertEqual(g.drawn, wall[132])
        self.assertEqual(g.remaining(), before - 1)

    def test_rules_validation_and_no_aka_wall(self):
        g = game.Game(human_seats=[0], rules={"aka_dora": False}, seed=2)
        self.assertFalse(any(t[0] == "0" for t in g.wall))
        self.assertEqual(g.rules["renpu_fu"], 4)
        with self.assertRaises(ValueError):
            game.Game(rules={"renpu_fu": 3})
        with self.assertRaises(ValueError):
            game.Game(rules={"aka_dora": "yes"})

    def test_tenhou_result_has_detailed_yaku_and_base_points(self):
        wall = game.make_wall()
        hand = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s", "1z", "1z", "1z", "2z"]
        rest = list(wall)
        for tile in hand + ["2z"]:
            rest.remove(tile)
        wall = hand + rest[:39] + ["2z"] + rest[39:]
        g = game.Game(human_seats=[0], wall=wall)
        g.do_action(0, "tsumo")
        win = g.result["wins"][0]
        self.assertEqual(win["points"], 48000)
        self.assertEqual(win["yakuman"], 1)
        self.assertEqual(win["han"], sum(y["han"] for y in win["yaku"]))
        self.assertEqual(g.result["delta"], [48000, -16000, -16000, -16000])
        self.assertEqual(g.events[-1], {"type": "tsumo", "seat": 0})

    def test_chankan_is_offered_and_robbed_kang_does_not_flip_dora(self):
        g = game.Game(human_seats=[0, 1, 2, 3], wall=game.make_wall())
        g.hands[0] = ["1m", "2m", "3m", "4m", "6m", "7m", "8m", "1p", "2p", "3p", "5m"]
        g.melds[0] = [{"type": "pon", "tiles": ["5m", "5m", "5m"], "from": 3, "called_tile": "5m"}]
        g.hands[1] = ["1p", "2p", "3p", "4p", "5p", "6p", "7s", "8s", "9s", "2z", "2z", "5m", "5m"]
        g.current = 0
        g.drawn = "5m"
        g.phase = "discard"
        g.call_options = {}
        g.responses = {}
        legal = g.get_legal_actions(0)
        self.assertTrue(any(a["type"] == "kan" and a.get("kind") == "kakan" for a in legal))
        g.do_action(0, "kan", tile="5m")
        self.assertIn(1, g.call_options)
        g.do_action(1, "ron")
        self.assertEqual(g.result["type"], "ron")
        self.assertEqual(g.result["wins"][0]["seat"], 1)
        self.assertIn("抢杠", [y["name"] for y in g.result["wins"][0]["yaku"]])
        self.assertEqual(g.dora_count, 1)
        self.assertEqual(g.kan_seats, [])

    def test_four_kans_abort_before_chi_or_pon(self):
        g = game.Game(human_seats=[0, 1, 2, 3], wall=game.make_wall())
        g.kan_seats = [0, 1, 2, 3]
        g.last_discard = (0, "3m")
        g.rivers[0] = [{"tile": "3m", "called": False}]
        g.hands[1] = ["3m", "3m", "7p"]
        g.call_options = {1: [{"type": "pon", "tiles": ["3m", "3m"]}]}
        g.responses = {1: {"type": "pon", "tiles": ["3m", "3m"]}}
        g._resolve_calls()
        self.assertEqual(g.result["reason"], "四杠散了")
        self.assertEqual(g.melds[1], [])

    def test_visible_tiles_do_not_double_count_called_or_own_melds(self):
        g = game.Game(human_seats=[0, 1, 2, 3], wall=game.make_wall())
        g.rivers[1] = [{"tile": "5m", "called": True}, {"tile": "3p", "called": False}]
        g.melds[0] = [{"type": "pon", "tiles": ["5m", "5m", "5m"], "from": 1}]
        visible = g.get_visible(0)
        self.assertNotIn("5m", visible)
        self.assertIn("3p", visible)
        self.assertEqual(visible.count(g.dora_indicators()[0]), 1)

    def test_state_contract_and_hidden_information(self):
        old_id = server.current_game_id
        try:
            server.current_game_id = "test-game"
            g = game.Game(human_seats=[0], seed=4)
            state = server.build_state(g, 0)
        finally:
            server.current_game_id = old_id
        for key in ("version", "game_id", "phase", "round", "dora_indicators", "wall_left",
                    "viewer", "turn", "waiting_for", "rules", "players", "drawn",
                    "legal_actions", "hints", "events", "result"):
            self.assertIn(key, state)
        self.assertEqual(len(state["players"]), 4)
        self.assertIn("hand", state["players"][0])
        for seat in (1, 2, 3):
            self.assertNotIn("hand", state["players"][seat])
        self.assertEqual(state["players"][0]["hand_count"], 13)
        self.assertEqual(state["rules"], game.DEFAULT_RULES)
        self.assertEqual(state["events"][0]["tile"], g.drawn)


if __name__ == "__main__":
    unittest.main()
