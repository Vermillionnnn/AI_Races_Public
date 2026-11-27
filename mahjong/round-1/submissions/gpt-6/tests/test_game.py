import unittest

from fu import calc_fu
from game import Game, dora_from_indicator
from score import calc_score
from server import build_state
from tenpai import can_hu, discard_hints, get_waits
from yaku import calc_yaku, scoring_options

from fixtures import pass_calls, wall_with


class ScoringTests(unittest.TestCase):
    def test_fu_and_yaku_use_the_same_interpretation(self):
        hand = '1m 2m 3m 3m 4m 5m 2p 3p 4p 6s 7s 8s 8p 8p'.split()
        g = Game(range(4), wall=wall_with({0: hand[:2] + hand[3:]}, ['3m'], {122: '7z'}))
        g.first_turn[0] = False
        g.do_action(0, 'tsumo')
        win = g.result['wins'][0]
        self.assertEqual((win['han'], win['fu'], win['points']), (2, 20, 2100))
        self.assertEqual(win['yaku'], [{'name': '门前清自摸和', 'han': 1}, {'name': '平和', 'han': 1}])
        self.assertEqual(g.result['delta'], [2100, -700, -700, -700])

    def test_double_wind_pair_crosses_rounding_boundary(self):
        hand = '7z 7z 7z 6p 7p 8p 3s 4s 5s 1z 1z'.split()
        meld = ['1p', '2p', '3p']
        self.assertEqual(calc_fu(hand, [meld], '5s', False, '1z', '1z', renpu_fu=2), 30)
        self.assertEqual(calc_fu(hand, [meld], '5s', False, '1z', '1z', renpu_fu=4), 40)
        for setting, points in ((2, 1500), (4, 2000)):
            with self.subTest(renpu_fu=setting):
                g = Game(range(4), wall=wall_with(dead={122: '4m'}), rules={'renpu_fu': setting})
                g.melds[0] = [{'type': 'chi', 'tiles': meld, 'from': 3, 'called_tile': '1p'}]
                win, _ = g._score_one(0, hand, '5s', False, 1, 0, 0)
                self.assertEqual(win['points'], points)

    def test_open_tanyao_and_bonus_only(self):
        hand = '2p 3p 4p 4s 5s 6s 6p 7p 8p 5m 0m'.split()
        melds = [['2m', '3m', '4m']]
        self.assertEqual(calc_yaku(hand, melds, '8p', False, '1z', '2z', ['5m'],
                                   {'kuitan': False}), ([], 0))
        options = list(scoring_options(hand, melds, '8p', False, '1z', '2z', ['5m'], {}))
        self.assertEqual(options[0].entries, (('断幺九', 1), ('宝牌', 2), ('赤宝牌', 1)))

    def test_score_caps_kiriage_and_counted_yakuman(self):
        for fu, han in ((30, 4), (60, 3)):
            self.assertEqual(calc_score(fu, han, False, False)['get'], 7700)
            self.assertEqual(calc_score(fu, han, False, False, kiriage_mangan=True)['get'], 8000)
        self.assertEqual(calc_score(120, 2, False, False, kiriage_mangan=True)['get'], 7700)
        self.assertEqual(calc_score(130, 2, False, False)['get'], 8000)
        self.assertEqual(calc_score(30, 26, False, False)['get'], 32000)
        self.assertEqual(calc_score(0, 26, False, False, yakuman=2)['get'], 64000)

    def test_concealed_kan_is_closed_and_has_higher_fu(self):
        hand = '2m 3m 4m 4p 5p 6p 6s 7s 8s 5m 5m'.split()
        kan = [['1z'] * 4]
        self.assertEqual(calc_fu(hand, kan, '4m', True, '2z', '3z', kan), 60)
        self.assertEqual(calc_fu(hand, kan, '4m', True, '2z', '3z'), 40)
        self.assertEqual(calc_yaku(hand, kan, '4m', True, '2z', '3z', [], {'ankan_indices': [0]}),
                         (['门前清自摸和'], 1))
        self.assertEqual(calc_yaku(hand, kan, '4m', True, '2z', '3z', [], {}), ([], 0))

    def test_compound_yakuman_and_chiihou(self):
        hand = '1z 1z 1z 2z 2z 2z 3z 3z 3z 4z 4z 4z 6z 6z'.split()
        option, = scoring_options(hand, [], '6z', True, '1z', '2z', [], {'chiihou': True})
        self.assertEqual(option.yakuman, 6)
        self.assertEqual(dict(option.entries), {'地和': 13, '字一色': 13, '大四喜': 26, '四暗刻单骑': 26})
        self.assertEqual(calc_score(0, option.han, False, True, yakuman=option.yakuman)['get'], 192000)


class GameTests(unittest.TestCase):
    def test_fixed_wall_red_ankan_and_indicator_cycles(self):
        wall = wall_with({0: ['5m'] * 3}, ['0m'], {122: '7z', 123: '3p', 127: '4m', 128: '2z', 132: '6p'})
        g = Game(range(4), wall=wall)
        self.assertEqual((g.drawn, g.dora_indicators(), g.remaining()), ('0m', ['7z'], 69))
        with self.assertRaises(ValueError):
            g.do_action(0, 'kakan', tile='5m')
        g.do_action(0, 'ankan', tile='5m')
        self.assertEqual((g.drawn, g.dora_indicators(), g.ura_indicators(), g.remaining()),
                         ('6p', ['7z', '3p'], ['4m', '2z'], 68))
        self.assertEqual(g.dora_list(), ['5z', '4p'])
        self.assertEqual([dora_from_indicator(t) for t in ('9s', '4z', '0p')], ['1s', '1z', '6p'])
        self.assertEqual(g.melds[0], [
            {'type': 'ankan', 'tiles': ['5m', '5m', '5m', '0m'], 'from': None, 'called_tile': None}])
        self.assertEqual([event['type'] for event in g.events], ['draw', 'ankan', 'dora', 'draw'])

    def test_kakan_can_be_robbed_without_consuming_a_rinshan(self):
        waiting = '4m 6m 1p 2p 3p 7s 8s 9s 2p 3p 4p 5z 5z'.split()
        wall = wall_with({0: ['5m', '5m', '0m'], 2: waiting},
                         ['9s', '5m', '9m', '8m', '7m', '3m'], {122: '6z'})
        g = Game(range(4), wall=wall)
        g.do_action(0, 'discard', '9s')
        pass_calls(g)
        g.do_action(1, 'discard', '5m')
        self.assertEqual([action for action in g.get_legal_actions(2) if action['type'] == 'ron'], [])
        g.do_action(0, 'pon', tiles=['5m', '5m'])
        pass_calls(g)
        discard = next(a for a in g.get_legal_actions(0) if a['type'] == 'discard')
        g.do_action(0, 'discard', discard['tiles'][0])
        pass_calls(g)
        for seat in (1, 2, 3):
            g.do_action(seat, 'discard', g.drawn)
            pass_calls(g)
        left = g.remaining()
        g.do_action(0, 'kakan', '5m')
        self.assertEqual(build_state(g, 'test', 2)['waiting_for'], [2])
        g.do_action(2, 'ron')
        result = build_state(g, 'test', 2)['result']
        win, = result['wins']
        self.assertEqual((win['seat'], win['from'], win['win_tile'], win['points']), (2, 0, '0m', 2600))
        self.assertEqual(win['yaku'], [{'name': '抢杠', 'han': 1}, {'name': '赤宝牌', 'han': 1}])
        self.assertEqual(g.melds[0][0]['type'], 'pon')
        self.assertEqual((g.rinshan_used, g.remaining(), g.dora_indicators()), (0, left, ['6z']))

    def test_ankan_can_be_robbed_by_thirteen_orphans(self):
        waiting = '9m 9m 1p 9p 1s 9s 1z 2z 3z 4z 5z 6z 7z'.split()
        g = Game(range(4), wall=wall_with({0: ['1m'] * 4, 1: waiting}, ['4m']))
        g.do_action(0, 'ankan', '1m')
        self.assertEqual(build_state(g, 'test', 0)['waiting_for'], [1])
        g.do_action(1, 'ron')
        win, = g.result['wins']
        self.assertEqual((win['seat'], win['yakuman'], win['points']), (1, 1, 32000))
        self.assertEqual(g.rinshan_used, 0)

    def test_riichi_ankan_preserves_waits_and_hand_structure(self):
        can_kan = '1m 1m 1m 2p 3p 4p 3s 4s 5s 6s 7s 8s 7z'.split()
        changes_shape = '1m 1m 1m 2m 2m 2m 3m 3m 3m 6p 7p 8p 7z'.split()
        for hand, allowed in ((can_kan, True), (changes_shape, False)):
            with self.subTest(allowed=allowed):
                g = Game(range(4), wall=wall_with({0: hand}, ['1m']))
                g.riichi[0] = True
                self.assertEqual(g._waits(hand, []), {'7z'})
                self.assertEqual(any(a.get('kind') == 'ankan' for a in g.get_legal_actions(0)), allowed)

    def test_multiple_ron_and_round_extras(self):
        hand1 = '1m 2m 4p 5p 6p 7s 8s 9s 5z 5z 5z 3z 3z'.split()
        hand2 = '1m 2m 2p 3p 4p 6s 7s 8s 6z 6z 6z 4z 4z'.split()
        g = Game(range(4), wall=wall_with({1: hand1, 2: hand2}, ['3m'], {122: '8m'}))
        g.honba, g.kyotaku = 2, 1
        g.scores[2] -= 1000
        g.do_action(0, 'discard', '3m')
        self.assertEqual(build_state(g, 'test', 0)['waiting_for'], [1, 2])
        g.do_action(2, 'ron')
        self.assertEqual(build_state(g, 'test', 0)['waiting_for'], [1])
        self.assertIsNone(g.result)
        g.do_action(1, 'ron')
        self.assertEqual([win['seat'] for win in g.result['wins']], [1, 2])
        self.assertEqual([win['points'] for win in g.result['wins']], [1300, 1300])
        self.assertEqual(g.result['delta'], [-3200, 2900, 1300, 0])
        self.assertEqual(sum(g.scores), 100000)

    def test_triple_ron_is_an_abortive_draw(self):
        hands = {
            1: '1m 2m 4p 5p 6p 7s 8s 9s 5z 5z 5z 3z 3z'.split(),
            2: '1m 2m 2p 3p 4p 6s 7s 8s 6z 6z 6z 4z 4z'.split(),
            3: '1m 2m 5p 6p 7p 2s 3s 4s 7z 7z 7z 2z 2z'.split(),
        }
        g = Game(range(4), wall=wall_with(hands, ['3m']))
        g.do_action(0, 'discard', '3m')
        self.assertEqual(build_state(g, 'test', 0)['waiting_for'], [1, 2, 3])
        for seat in (3, 2, 1):
            g.do_action(seat, 'ron')
        self.assertEqual(build_state(g, 'test', 0)['result'],
                         {'type': 'ryuukyoku', 'reason': 'triple_ron', 'delta': [0] * 4})
        g.next_round()
        self.assertEqual((g.oya, g.honba), (0, 1))

    def test_riichi_declaration_refunded_if_ron(self):
        hand0 = '4m 5m 6m 2p 3p 4p 2s 3s 4s 7z 7z 3p 4p'.split()
        hand1 = '1m 2m 4p 5p 6p 7s 8s 9s 5z 5z 5z 3z 3z'.split()
        g = Game(range(4), wall=wall_with({0: hand0, 1: hand1}, ['3m'], {122: '8m'}))
        g.do_action(0, 'riichi', '3m', tsumogiri=True)
        self.assertEqual((g.scores[0], g.kyotaku), (24000, 1))
        g.do_action(1, 'ron')
        pass_calls(g)
        self.assertEqual((g.scores[0], g.kyotaku), (23700, 0))
        self.assertFalse(g.riichi[0])
        self.assertEqual(g.result['delta'], [-1300, 1300, 0, 0])

    def test_separate_dora_ura_and_red_dora(self):
        hand = '1m 2m 3m 4p 0p 6p 7p 8p 9p 2s 3s 5z 5z'.split()
        wall = wall_with({0: hand}, ['8m', '9m', '3m', '1z', '4s'], {122: '4p', 127: '7z'})
        g = Game([0], wall=wall)
        g.do_action(0, 'riichi', '8m', tsumogiri=True)
        self.assertEqual((g.current, g.drawn, g.scores[0]), (0, '4s', 24000))
        g.do_action(0, 'tsumo')
        r = build_state(g, 'test', 0)['result']
        win, = r['wins']
        self.assertEqual(r['uradora_indicators'], ['7z'])
        self.assertEqual(dict((y['name'], y['han']) for y in win['yaku']),
                         {'两立直': 2, '一发': 1, '门前清自摸和': 1, '宝牌': 1, '赤宝牌': 1, '里宝牌': 2})
        self.assertEqual((win['han'], win['fu'], win['yakuman'], win['points']), (8, 30, 0, 24000))
        self.assertEqual(r['delta'], [25000, -8000, -8000, -8000])

    def test_temporary_furiten_ends_on_draw_riichi_furiten_persists(self):
        hand = '1m 2m 3m 4p 5p 6p 2s 3s 7z 7z 7z 5z 5z'.split()
        for riichi in (False, True):
            with self.subTest(riichi=riichi):
                g = Game(range(4), wall=wall_with({2: hand}, ['1s', '9m', '9p']))
                g.riichi[2] = riichi
                g.do_action(0, 'discard', '1s')
                g.do_action(2, 'pass')
                pass_calls(g)
                self.assertTrue(g._is_furiten(2))
                g.do_action(1, 'discard', '9m')
                pass_calls(g)
                self.assertFalse(g.temp_furiten[2])
                self.assertEqual(g._is_furiten(2), riichi)
        g.rivers[2].append({'tile': '1s', 'called': True})
        g.riichi_furiten[2] = False
        self.assertTrue(g._is_furiten(2))

    def test_four_kans_abort_after_the_rinshan_discard(self):
        wall = wall_with({0: ['2m'] * 4 + ['3m'] * 4, 1: ['4p'] * 4 + ['6p'] * 4})
        g = Game(range(4), wall=wall)
        for kind in ('2m', '3m'):
            g.do_action(0, 'ankan', kind)
        g.do_action(0, 'discard', g.drawn, tsumogiri=True)
        pass_calls(g)
        for kind in ('4p', '6p'):
            g.do_action(1, 'ankan', kind)
        self.assertEqual((g.rinshan_used, len(g.dora_indicators())), (4, 5))
        self.assertIsNone(g.result)
        g.do_action(1, 'discard', g.drawn, tsumogiri=True)
        pass_calls(g)
        r = build_state(g, 'test', 0)
        self.assertEqual(r['result'], {'type': 'ryuukyoku', 'reason': 'four_kans', 'delta': [0] * 4})
        self.assertEqual(r['events'][-1], {'type': 'ryuukyoku', 'reason': 'four_kans'})

    def test_last_live_draw_and_discard_yaku(self):
        hand = '4m 6m 1p 2p 3p 7s 8s 9s 2p 3p 4p 5z 5z'.split()
        for is_tsumo in (True, False):
            with self.subTest(is_tsumo=is_tsumo):
                seat = 1 if is_tsumo else 2
                g = Game(range(4), wall=wall_with({seat: hand}, ['2z'], {121: '5m', 122: '6z'}))
                g.wall_pos = 121
                g.first_turn = [False] * 4
                g.do_action(0, 'discard', '2z')
                pass_calls(g)
                self.assertEqual(g.remaining(), 0)
                if is_tsumo:
                    g.do_action(1, 'tsumo')
                else:
                    g.do_action(1, 'discard', '5m')
                    self.assertEqual(g.get_legal_actions(2), [{'type': 'ron', 'tile': '5m'}, {'type': 'pass'}])
                    g.do_action(2, 'ron')
                    pass_calls(g)
                names = {item['name'] for item in g.result['wins'][0]['yaku']}
                self.assertIn('海底摸月' if is_tsumo else '河底捞鱼', names)

    def test_final_rinshan_is_neither_haitei_nor_houtei(self):
        hand = '2m 2m 2m 2m 4p 5p 6p 6s 7s 8s 2s 3s 5z'.split()
        g = Game(range(4), wall=wall_with({0: hand}, ['5z'], {122: '6z', 123: '6z', 132: '4s'}))
        g.wall_pos = 121
        g.do_action(0, 'ankan', '2m')
        self.assertEqual(g.remaining(), 0)
        self.assertFalse(g._make_yaku_state(0, True, False)['haitei'])
        g.do_action(0, 'tsumo')
        self.assertEqual(g.result['wins'][0]['yaku'],
                         [{'name': '门前清自摸和', 'han': 1}, {'name': '岭上开花', 'han': 1}])

    def test_kyuushu_and_four_winds_abort_before_advancing(self):
        hand = '1m 9m 1p 9p 1s 9s 1z 2z 3z 4z 5z 6z 7z'.split()
        g = Game(range(4), wall=wall_with({0: hand}, ['4m']))
        g.do_action(0, 'kyuushu')
        self.assertEqual(build_state(g, 'test', 0)['result']['reason'], 'kyuushu')
        g.next_round(wall_with(draws=['1z'] * 4))
        for seat in range(4):
            g.do_action(seat, 'discard', '1z')
        state = build_state(g, 'test', 0)
        self.assertEqual(state['result']['reason'], 'four_winds')
        self.assertEqual((state['round']['number'], state['round']['honba']), (1, 1))

    def test_wind_length_and_invalid_next_wall(self):
        east = Game([], seed=10, length='tonpuu')
        south = Game([], seed=10, length='hanchan')
        for game in (east, south):
            while game.kyoku < 3:
                game.next_round()
            self.assertEqual(game.bakaze, '1z')
            self.assertFalse(game.game_over)
        # 同在东四，达到返还点时东风战可结束，而半庄进南一。
        for game in (east, south):
            game.scores = [30000, 20000, 25000, 25000]
        self.assertTrue(east._check_game_over(False, False))
        self.assertFalse(south._check_game_over(False, False))
        for _ in range(4):
            south.next_round()
        self.assertEqual((south.kyoku, south.bakaze, south.game_over), (7, '2z', True))
        state = (east.kyoku, east.honba, east.result)
        with self.assertRaises(ValueError):
            east.next_round(['1m'] * 136)
        self.assertEqual((east.kyoku, east.honba, east.result), state)


class TenpaiTests(unittest.TestCase):
    def test_discard_counts_discarded_tile_and_keeps_red_keys(self):
        hand = '1m 2m 3m 4p 5p 6p 7p 8p 9p 2s 3s 5m 0m 1s'.split()
        hints = discard_hints(hand)
        self.assertEqual(hints['1s']['1s'], 3)
        self.assertEqual(hints['5m'], {'5m': 2})
        self.assertEqual(hints['0m'], {'5m': 2})

    def test_meld_and_called_discard_are_only_counted_once(self):
        hand = '3m 4m 1p 2p 3p 6s 7s 8s 7z 7z'.split()
        g = Game(range(4), wall=wall_with(dead={122: '6z'}))
        g.melds[2] = [{'type': 'pon', 'tiles': ['5m', '5m', '0m'], 'from': 0, 'called_tile': '5m'}]
        g.rivers[0] = [{'tile': '5m', 'called': True}]
        self.assertEqual(get_waits(hand, g.melds_plain(2), g.get_visible(2)), {'2m': 4, '5m': 1})
        self.assertEqual(g.get_visible(3).count('5m'), 3)
        self.assertFalse(can_hu(hand + ['5m'], [['1z', '2z', '3z']]))


if __name__ == '__main__':
    unittest.main()
