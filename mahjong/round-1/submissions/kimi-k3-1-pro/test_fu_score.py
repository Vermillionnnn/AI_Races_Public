import unittest

from fu import calc_fu
from score import calc_score


class FuTest(unittest.TestCase):
    def test_pinfu_ron_and_tsumo_and_13_tile_input(self):
        hand = [
            '1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s',
            '2s', '3s', '4s', '5m', '5m',
        ]
        self.assertEqual(calc_fu(hand, [], '4s', False, '1z', '2z'), 30)
        self.assertEqual(calc_fu(hand, [], '4s', True, '1z', '2z'), 20)
        hand13 = hand.copy()
        hand13.remove('4s')
        self.assertEqual(calc_fu(hand13, [], '4s', False, '1z', '2z'), 30)

    def test_chiitoitsu_is_fixed_25_and_supports_13_tile_input(self):
        hand = [
            '1m', '1m', '3m', '3m', '5p', '5p', '7p', '7p',
            '2s', '2s', '9s', '9s', '7z', '7z',
        ]
        self.assertEqual(calc_fu(hand, [], '7z', False, '1z', '2z'), 25)
        self.assertEqual(calc_fu(hand[:-1], [], '7z', True, '1z', '2z'), 25)

    def test_open_hand_with_no_extra_fu_is_30(self):
        hand = ['4p', '5p', '6p', '6s', '7s', '8s',
                '2s', '3s', '4s', '5m', '5m']
        melds = [['1m', '2m', '3m']]
        self.assertEqual(calc_fu(hand, melds, '4s', False, '1z', '2z'), 30)
        self.assertEqual(calc_fu(hand, melds, '4s', True, '1z', '2z'), 30)

    def test_double_wind_pair_respects_renpu_fu(self):
        hand = [
            '1m', '2m', '3m', '4p', '5p', '6p', '2s', '3s', '4s',
            '5z', '5z', '5z', '1z', '1z',
        ]
        self.assertEqual(calc_fu(hand, [], '4s', False, '1z', '1z'), 50)
        self.assertEqual(
            calc_fu(hand, [], '4s', False, '1z', '1z', renpu_fu=2), 40
        )
        self.assertEqual(
            calc_fu(hand, [], '4s', False, '1z', '1z', None, 4), 50
        )
        with self.assertRaises(ValueError):
            calc_fu(hand, [], '4s', False, '1z', '1z', renpu_fu=3)

    def test_concealed_and_open_kongs(self):
        hand = ['2m', '3m', '4m', '4p', '5p', '6p',
                '6s', '7s', '8s', '5m', '5m']
        kong = [['1z', '1z', '1z', '1z']]
        self.assertEqual(calc_fu(hand, kong, '4m', True, '2z', '3z', kong), 60)
        self.assertEqual(calc_fu(hand, kong, '4m', True, '2z', '3z'), 40)

    def test_sequence_wait_fu(self):
        base = ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s']
        cases = [
            # 234s 和 4s：两面，门前平和荣和 30 符。
            ('4s', ['2s', '3s', '4s'], 30),
            # 234s 和 3s：嵌张，加 2 符后切上为 40 符。
            ('3s', ['2s', '3s', '4s'], 40),
            # 123s 和 3s：边张，加 2 符后切上为 40 符。
            ('3s', ['1s', '2s', '3s'], 40),
        ]
        for win_tile, sequence, expected in cases:
            with self.subTest(win_tile=win_tile, sequence=sequence):
                hand = base + sequence + ['5m', '5m']
                self.assertEqual(
                    calc_fu(hand, [], win_tile, False, '1z', '2z'), expected
                )

    def test_pair_wait_adds_two_fu(self):
        hand = [
            '1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s',
            '2s', '3s', '4s', '5m', '5m',
        ]
        self.assertEqual(calc_fu(hand, [], '5m', False, '1z', '2z'), 40)


class ScoreTest(unittest.TestCase):
    def test_table_driven_ron_and_tsumo(self):
        self.assertEqual(calc_score(30, 2, False, False), {
            'get': 2000, 'ron_pay': 2000, 'oya_pay': 0, 'ko_pay': 0, 'rank': '',
        })
        self.assertEqual(calc_score(40, 3, True, True), {
            'get': 7800, 'ron_pay': 0, 'oya_pay': 0, 'ko_pay': 2600, 'rank': '',
        })
        self.assertEqual(calc_score(25, 3, False, True), {
            'get': 3200, 'ron_pay': 0, 'oya_pay': 1600, 'ko_pay': 800, 'rank': '',
        })

    def test_formula_fallback_for_missing_table_entry(self):
        # 20符1番不在表内：基本点 20*2^(1+2)=160，闲家荣和 ceil100(160*4)=700。
        self.assertEqual(calc_score(20, 1, False, False)['ron_pay'], 700)
        self.assertEqual(calc_score(20, 1, True, False)['ron_pay'], 1000)

    def test_kiriage_mangan_is_opt_in(self):
        self.assertEqual(calc_score(30, 4, False, False)['ron_pay'], 7700)
        self.assertEqual(calc_score(30, 4, True, False)['ron_pay'], 11600)
        self.assertEqual(calc_score(60, 3, False, False)['ron_pay'], 7700)
        for fu, han in [(30, 4), (60, 3)]:
            with self.subTest(fu=fu, han=han):
                result = calc_score(
                    fu, han, False, False, kiriage_mangan=True
                )
                self.assertEqual(result['ron_pay'], 8000)
                self.assertEqual(result['rank'], '満貫')

    def test_natural_mangan_thresholds_unchanged(self):
        for fu, han in [(40, 4), (70, 3), (20, 5)]:
            with self.subTest(fu=fu, han=han):
                self.assertEqual(calc_score(fu, han, False, False)['ron_pay'], 8000)

    def test_honba_and_kyotaku_ron(self):
        self.assertEqual(calc_score(30, 2, False, False, 2, 3), {
            'get': 5600, 'ron_pay': 2600, 'oya_pay': 0, 'ko_pay': 0, 'rank': '',
        })

    def test_honba_and_kyotaku_dealer_tsumo(self):
        self.assertEqual(calc_score(40, 3, True, True, 2, 1), {
            'get': 9400, 'ron_pay': 0, 'oya_pay': 0, 'ko_pay': 2800, 'rank': '',
        })

    def test_honba_and_kyotaku_nondealer_tsumo(self):
        self.assertEqual(calc_score(40, 3, False, True, 2, 1), {
            'get': 6800, 'ron_pay': 0, 'oya_pay': 2800, 'ko_pay': 1500, 'rank': '',
        })

    def test_counted_yakuman_is_single_even_above_13_han(self):
        for yakuman in [None, 0]:
            with self.subTest(yakuman=yakuman):
                result = calc_score(30, 26, False, False, yakuman=yakuman)
                self.assertEqual(result['ron_pay'], 32000)
                self.assertEqual(result['rank'], '役満')
        self.assertEqual(
            calc_score(30, 12, False, False, yakuman=0)['ron_pay'], 24000
        )

    def test_true_multiple_yakuman_ron_and_tsumo(self):
        ron = calc_score(30, 0, False, False, 1, 1, yakuman=2)
        self.assertEqual(ron, {
            'get': 65300, 'ron_pay': 64300, 'oya_pay': 0, 'ko_pay': 0, 'rank': '役満',
        })
        tsumo = calc_score(30, 0, False, True, 1, 1, yakuman=2)
        self.assertEqual(tsumo, {
            'get': 65300, 'ron_pay': 0, 'oya_pay': 32100, 'ko_pay': 16100, 'rank': '役満',
        })
        dealer = calc_score(30, 1, True, True, yakuman=3)
        self.assertEqual(dealer['ko_pay'], 48000)
        self.assertEqual(dealer['get'], 144000)

    def test_old_positional_arguments_remain_compatible(self):
        self.assertEqual(
            calc_score(30, 2, False, False, 0, 0),
            calc_score(30, 2, False, False),
        )


if __name__ == '__main__':
    unittest.main()
