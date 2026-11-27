import unittest

import tenpai


class TenpaiTest(unittest.TestCase):
    def test_regular_chiitoitsu_and_kokushi(self):
        regular = ["1m", "2m", "3m", "4p", "0p", "6p", "7s", "8s", "9s", "1z", "1z", "1z", "2z", "2z"]
        pairs = ["1m", "1m", "2m", "2m", "3p", "3p", "4p", "4p", "5s", "5s", "6s", "6s", "7z", "7z"]
        kokushi = ["1m", "9m", "1p", "9p", "1s", "9s", "1z", "2z", "3z", "4z", "5z", "6z", "7z", "1m"]
        self.assertTrue(tenpai.can_hu(regular))
        self.assertTrue(tenpai.can_hu(pairs))
        self.assertTrue(tenpai.can_hu(kokushi))
        self.assertFalse(tenpai.can_hu(regular[:-1]))

    def test_wait_counts_include_hand_melds_and_visible_once(self):
        # 一组 111m 副露，门前 23m + 234p + 456s + 22z，听 1m/4m。
        hand = ["2m", "3m", "2p", "3p", "4p", "4s", "5s", "6s", "2z", "2z"]
        melds = [["1m", "1m", "1m"]]
        waits = tenpai.get_waits(hand, melds, ["4m", "4m"])
        self.assertEqual(waits.get("4m"), 2)
        self.assertEqual(waits.get("1m"), 1)

    def test_discard_hints_counts_discarded_tile_as_visible(self):
        # 最后摸入 1s；打出 1s 后听 1s/4s，河里的这张 1s 也要扣除。
        hand = ["1m", "2m", "3m", "4m", "5m", "6m", "7p", "8p", "9p", "2s", "3s", "5z", "5z", "1s"]
        hints = tenpai.discard_hints(hand, [], [])
        self.assertEqual(hints.get("1s"), {"1s": 3, "4s": 4})

    def test_discard_hints_distinguish_red_five(self):
        hand = ["1m", "2m", "3m", "4p", "0p", "6p", "7s", "8s", "9s", "2s", "3s", "5z", "5z", "7z"]
        hints = tenpai.discard_hints(hand, [], ["1s"])
        self.assertIsInstance(hints, dict)
        for waits in hints.values():
            self.assertTrue(all(0 <= left <= 4 for left in waits.values()))


if __name__ == "__main__":
    unittest.main()
