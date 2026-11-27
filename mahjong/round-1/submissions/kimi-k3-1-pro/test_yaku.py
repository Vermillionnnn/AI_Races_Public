# 学号 250118

import unittest
from collections import Counter

import yaku


def tiles(text):
    return text.split()


class YakuTest(unittest.TestCase):
    def calc(self, hand, win_tile, *, melds=None, is_tsumo=False,
             bakaze="1z", jikaze="1z", dora=None, state=None, rules=None):
        return yaku.calc_yaku(
            tiles(hand), melds or [], win_tile, is_tsumo, bakaze, jikaze,
            dora or [], state or {}, rules
        )

    def test_detailed_dora_ura_and_red(self):
        hand = tiles(
            "2m 2m 2m 3m 4m 5m 4p 5p 6p 6s 7s 8s 0s 5s"
        )
        args = (hand, [], "0s", False, "1z", "1z", ["5s"],
                {"riichi": True, "ura_dora": ["2m"]})
        detailed, han = yaku.calc_yaku_detailed(*args)
        self.assertEqual(detailed, [
            {"name": "立直", "han": 1},
            {"name": "断幺九", "han": 1},
            {"name": "宝牌2", "han": 2},
            {"name": "赤宝牌1", "han": 1},
            {"name": "里宝牌3", "han": 3},
        ])
        self.assertEqual(han, 8)
        self.assertEqual(yaku.calc_yaku(*args),
                         ([item["name"] for item in detailed], han))

    def test_aka_dora_rule(self):
        hand = "2m 2m 2m 3m 4m 5m 4p 5p 6p 6s 7s 8s 0s 5s"
        self.assertEqual(
            self.calc(hand, "0s", rules={"aka_dora": False}),
            (["断幺九"], 1)
        )
        self.assertEqual(
            self.calc(hand, "0s"), (["断幺九", "赤宝牌1"], 2)
        )

    def test_open_tanyao_kuitan_rule_and_no_yaku_dora(self):
        hand = "2m 3m 4m 5m 6m 7m 2p 3p 4p 5s 5s"
        melds = [tiles("6s 7s 8s")]
        self.assertEqual(
            self.calc(hand, "5s", melds=melds, dora=["5s"]),
            (["断幺九", "宝牌2"], 3)
        )
        self.assertEqual(
            self.calc(hand, "5s", melds=melds, dora=["5s"],
                      rules={"kuitan": False}),
            ([], 0)
        )

    def test_dora_alone_is_not_a_win(self):
        self.assertEqual(
            self.calc(
                "1m 2m 3m 4m 5m 6m 2p 3p 4p 2s 2s 2s 7z 7z",
                "2s", dora=["2s"]
            ),
            ([], 0)
        )

    def test_chihou_and_legacy_chiihou(self):
        hand = "2m 2m 2m 3m 4m 5m 4p 5p 6p 6s 7s 8s 5s 5s"
        for key in ("chihou", "chiihou"):
            with self.subTest(key=key):
                self.assertEqual(
                    self.calc(hand, "5s", is_tsumo=True, jikaze="2z",
                              state={key: True}),
                    (["地和"], 13)
                )

    def test_double_and_compound_yakuman(self):
        detailed, han = yaku.calc_yaku_detailed(
            tiles("1z 1z 1z 2z 2z 2z 3z 3z 3z 4z 4z 4z 5z 5z"),
            [], "5z", True, "1z", "1z", [], {}
        )
        self.assertEqual(detailed, [
            {"name": "字一色", "han": 13},
            {"name": "大四喜", "han": 26},
            {"name": "四暗刻单骑", "han": 26},
        ])
        self.assertEqual(han, 65)

    def test_ankan_indices_marks_concealed_kan(self):
        detailed, han = yaku.calc_yaku_detailed(
            tiles("2m 2m 2m 3p 3p 3p 4s 4s 4s 5z 5z"),
            [tiles("1m 1m 1m 1m")], "5z", True, "1z", "1z", [],
            {"ankan_indices": [0]}
        )
        self.assertEqual(detailed, [{"name": "四暗刻单骑", "han": 26}])
        self.assertEqual(han, 26)

    def test_best_shape_is_not_overwritten_by_chiitoitsu(self):
        names, han = self.calc(
            "1m 1m 2m 2m 3m 3m 4m 4m 5m 5m 6m 6m 7m 7m",
            "6m"
        )
        self.assertIn("二杯口", names)
        self.assertIn("平和", names)
        self.assertNotIn("七对子", names)
        self.assertEqual(han, 10)

    def test_split_groups_rejects_inconsistent_counts(self):
        self.assertEqual(list(yaku.split_groups(Counter(), 1)), [])
        self.assertEqual(list(yaku.split_groups(Counter({"1m": 2}), 1)), [])
        self.assertEqual(list(yaku.split_groups(Counter({"1m": 3}), 0)), [])
        self.assertEqual(list(yaku.split_groups(Counter({"1m": -1}), 0)), [])
        self.assertEqual(
            list(yaku.split_groups(Counter({"1m": 3}), 1)),
            [[("triplet", "1m", False)]]
        )

    def test_invalid_tiles_return_empty(self):
        self.assertEqual(self.calc("1m " * 14, "1m"), ([], 0))
        self.assertEqual(
            self.calc("1m 2m 3m 4m 5m 6m 7m 8m 9m 1p 2p 3p 4p 5p",
                      "5p"),
            ([], 0)
        )


if __name__ == "__main__":
    unittest.main()
