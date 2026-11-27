"""流程：用指定牌山按剧本打一局（judge/harness.py 的 Script），检查结算、振听、立直、抢杠、流局、换庄、结束条件、开关。

同一套场景跑两遍：FlowInProc 直接调 server.py 的处理函数（可以改点数、本场来搭局面），
FlowHTTP 起一个真的服务、走 HTTP（只跑不需要改内部状态的场景）。所有经过的状态最后交给 checkState。
"""

import os
import unittest

from util import REF, InProcClient, T, check_states, harness

STATES = []   # 测试中看到的状态，最后统一跑 checkState


def W(hands=None, draws=(), dora=('5z',), ura=('5z',), rinshan=(), avoid=(), seed=0, aka=True):
    return harness.build_wall(hands={k: T(v) for k, v in (hands or {}).items()}, draws=T(''.join(draws)),
                              dora=T(''.join(dora)), ura=T(''.join(ura)), rinshan=T(''.join(rinshan)),
                              avoid=T(''.join(avoid)), seed=seed, aka=aka)


class Scenarios:
    """场景本身；子类给出 self.c（客户端）和 INPROC。"""

    INPROC = False

    def start(self, wall, rules=None, length='tonpuu'):
        st = harness.start(self.c, wall, rules, length)
        STATES.append(('start', st))
        return st['game_id'], harness.Script(self.c, st['game_id'])

    def view(self, gid, seat):
        st = self.c.state(gid, seat)
        STATES.append(('view', st))
        return st

    def finish(self, gid, script, steps=()):
        """执行剧本，再打到这一局结束（默认决定：摸切、不鸣不和）。"""
        script.run(steps)
        st = script.run([], until=lambda s: False)
        for s in range(4):
            self.view(gid, s)
        return st

    # ------------------------------------------------------------ 立直

    def test_riichi_tile_ronned(self):
        """立直宣言牌被荣和：立直不成立，不扣 1000。"""
        wall = W({0: '123m456m789m234p5p', 1: '234s456s678p22p78s'}, ['9s'], avoid=['9s'])
        gid, sc = self.start(wall)
        st = self.finish(gid, sc, [(0, 'riichi', {'tile': '9s', 'tsumogiri': True}), (1, 'ron')])
        r = st['result']
        self.assertEqual(st['phase'], 'round_end')
        self.assertEqual([(w['seat'], w['from'], w['points']) for w in r['wins']], [(1, 0, 1000)])
        self.assertEqual(r['delta'], [-1000, 1000, 0, 0])
        self.assertEqual(st['players'][0]['score'], 24000)
        self.assertEqual(st['round']['riichi_sticks'], 0)
        self.assertFalse(st['players'][0]['riichi'])
        self.assertTrue(st['players'][0]['discards'][0]['riichi'])

    def test_riichi_ippatsu_tsumo_and_renchan(self):
        """立直成立扣 1000；一发自摸；庄家和了连庄、本场 +1。庄家第一巡先默听打一张，第二巡才立直。"""
        wall = W({0: '123m456m789m234p5p'}, ['1z', '2z', '3z', '4z', '9s', '6z', '6z', '7z', '5p'],
                 avoid=['5p', '9s'])
        gid, sc = self.start(wall)
        sc.run([(0, 'discard', {'tile': '1z', 'tsumogiri': True}), (0, 'riichi', {'tile': '9s', 'tsumogiri': True})])
        st = self.view(gid, 1)
        self.assertTrue(st['players'][0]['riichi'])
        self.assertEqual(st['players'][0]['score'], 24000)
        self.assertEqual(st['round']['riichi_sticks'], 1)
        st = self.finish(gid, sc, [(0, 'tsumo')])
        w = st['result']['wins'][0]
        names = [y['name'] for y in w['yaku']]
        for n in ('立直', '一发', '门前清自摸和', '一气通贯'):
            self.assertIn(n, names)
        self.assertEqual((w['han'], w['points']), (5, 12000))
        self.assertEqual(st['result']['delta'], [13000, -4000, -4000, -4000])
        self.assertEqual([p['score'] for p in st['players']], [37000, 21000, 21000, 21000])
        self.assertEqual(len(st['result']['uradora_indicators']), 1)
        nx = self.c.next(gid, 0)
        STATES.append(('next', nx))
        self.assertEqual((nx['round']['number'], nx['round']['honba'], nx['round']['dealer']), (1, 1, 0))

    def test_double_riichi(self):
        """第一次打牌就立直、之前没人鸣牌：两立直（2 番，不和立直复合）。"""
        wall = W({0: '123m456m789m234p5p'}, ['9s', '1z', '2z', '3z', '5p'], avoid=['5p', '9s'])
        gid, sc = self.start(wall)
        st = self.finish(gid, sc, [(0, 'riichi', {'tile': '9s', 'tsumogiri': True}), (0, 'tsumo')])
        w = st['result']['wins'][0]
        names = [y['name'] for y in w['yaku']]
        self.assertIn('两立直', names)
        self.assertNotIn('立直', names)
        self.assertEqual((w['han'], w['points']), (6, 18000))
        self.assertEqual(st['result']['delta'], [19000, -6000, -6000, -6000])

    # ------------------------------------------------------------ 一炮双响、三家和了

    DOUBLE = {0: '123m456m789m56p9s4z', 1: '234s456s678p22p78s', 2: '111z456m789p234p9s'}

    def test_double_ron(self):
        wall = W(self.DOUBLE, ['7z'], dora=['8m'], ura=['8m'], avoid=['9s'])
        gid, sc = self.start(wall)
        honba = 0
        if self.INPROC:   # 搭 2 本场、1 根供托（座位 3 出的 1000）
            g = self.c.game(gid)
            g.honba, g.riichi_sticks = 2, 1
            g.scores[3] -= 1000
            honba = 2
        st = self.finish(gid, sc, [(0, 'discard', {'tile': '9s', 'tsumogiri': False}), (1, 'ron'), (2, 'ron')])
        r = st['result']
        self.assertEqual([(w['seat'], w['points']) for w in r['wins']], [(1, 1000), (2, 1300)])
        if honba:
            self.assertEqual(r['delta'], [-2900, 2600, 1300, 0])
            self.assertEqual(st['round']['riichi_sticks'], 0)
        else:
            self.assertEqual(r['delta'], [-2300, 1000, 1300, 0])
        nx = self.c.next(gid, 0)
        self.assertEqual((nx['round']['dealer'], nx['round']['honba']), (1, 0))

    def test_atamahane(self):
        wall = W(self.DOUBLE, ['7z'], dora=['8m'], ura=['8m'], avoid=['9s'])
        gid, sc = self.start(wall, {'double_ron': False})
        st = self.finish(gid, sc, [(0, 'discard', {'tile': '9s', 'tsumogiri': False}), (1, 'ron'), (2, 'ron')])
        self.assertEqual([w['seat'] for w in st['result']['wins']], [1])
        self.assertEqual(st['result']['delta'], [-1000, 1000, 0, 0])

    TRIPLE = {**DOUBLE, 3: '555z789p456s789s9s'}

    def test_triple_ron(self):
        wall = W(self.TRIPLE, ['7z'], dora=['8m'], ura=['8m'])
        steps = [(0, 'discard', {'tile': '9s', 'tsumogiri': False}), (1, 'ron'), (2, 'ron'), (3, 'ron')]
        gid, sc = self.start(wall)
        st = self.finish(gid, sc, steps)
        self.assertEqual((st['result']['type'], st['result']['reason']), ('ryuukyoku', 'triple_ron'))
        self.assertEqual(st['result']['delta'], [0, 0, 0, 0])
        nx = self.c.next(gid, 0)
        self.assertEqual((nx['round']['dealer'], nx['round']['honba']), (0, 1))
        gid, sc = self.start(wall, {'triple_ron_abort': False})
        st = self.finish(gid, sc, steps)
        self.assertEqual([w['seat'] for w in st['result']['wins']], [1, 2, 3])

    # ------------------------------------------------------------ 抢杠

    def chankan_wall(self):
        return W({0: '3p147m258p369s124z', 2: '33p258m147p258s56z', 3: '123m789m123s99s24p'},
                 ['7z', '7z', '7z', '6z', '3p'])

    def test_chankan(self):
        """加杠被抢：座位 3 本来没役（不能荣和打出的 3p，算同巡振听），摸打一次后抢杠有役。"""
        for rules in ({}, {'furiten_no_yaku': False}):
            gid, sc = self.start(self.chankan_wall(), rules)
            st = self.finish(gid, sc, [(0, 'discard', {'tile': '3p', 'tsumogiri': False}),
                                       (2, 'pon', {'tiles': ['3p', '3p']}), (2, 'kakan', {'tile': '3p'}), (3, 'ron')])
            w = st['result']['wins'][0]
            self.assertEqual((w['seat'], w['from'], w['win_tile'], w['han'], w['fu'], w['points']),
                             (3, 2, '3p', 1, 40, 1300))
            self.assertIn('抢杠', [y['name'] for y in w['yaku']])
            self.assertEqual(st['result']['delta'], [0, 0, -1300, 1300])

    def test_kokushi_robs_ankan(self):
        wall = W({2: '777z258m258p258s3z', 3: '19m19p19s123456z1m'}, ['8m', '8p', '7z'])
        gid, sc = self.start(wall)
        st = self.finish(gid, sc, [(2, 'ankan', {'tile': '7z'}), (3, 'ron')])
        w = st['result']['wins'][0]
        self.assertEqual((w['seat'], w['from'], w['yakuman'], w['points']), (3, 2, 1, 32000))
        gid, sc = self.start(wall, {'kokushi_ankan_rob': False})
        sc.run([(2, 'ankan', {'tile': '7z'})])
        st = self.view(gid, 2)
        self.assertEqual(st['players'][2]['melds'][0]['type'], 'ankan')
        self.assertEqual(len(st['dora_indicators']), 2)      # 暗杠立即翻

    # ------------------------------------------------------------ 振听

    TENPAI1 = '234s456s678p22p78s'   # 听 3s 6s 9s，平和

    def test_furiten_discard(self):
        wall = W({1: self.TENPAI1}, ['1z', '9s', '6s', '2z', '3z', '6s'], avoid=['3s', '6s', '9s'])
        gid, sc = self.start(wall)
        st = sc.run([], until=lambda s: any(e['type'] == 'discard' and e['seat'] == 2 for e in s['events']))
        self.assertEqual(st['waiting_for'], [3])            # 座位 1 舍张振听，6s 不能荣和
        v1 = self.view(gid, 1)
        self.assertTrue(v1['hints']['furiten'])
        self.assertEqual([w['tile'] for w in v1['hints']['waits']], ['3s', '6s', '9s'])
        st = self.finish(gid, sc, [(1, 'tsumo')])          # 自摸可以
        self.assertEqual(st['result']['wins'][0]['seat'], 1)

    def test_furiten_same_turn(self):
        wall = W({1: self.TENPAI1}, ['1z', '2z', '9s', '6s', '9s', '3z', '6s'], avoid=['3s', '6s', '9s'])
        gid, sc = self.start(wall)
        st = self.finish(gid, sc, [(1, 'pass'), (1, 'ron')])
        w = st['result']['wins'][0]
        self.assertEqual((w['seat'], w['from'], w['win_tile']), (1, 2, '6s'))
        self.assertEqual(len(st['players'][2]['discards']), 2)   # 第二次才荣和：中间的 6s、9s 都同巡振听

    def test_furiten_riichi(self):
        wall = W({1: self.TENPAI1}, ['1z', '2z', '9s', '3z', '4z', '7z', '6s', '1z', '2z', '6s'], avoid=['3s', '6s', '9s'])
        gid, sc = self.start(wall)
        sc.run([(1, 'riichi', {'tile': '2z', 'tsumogiri': True}), (1, 'pass')])
        st = sc.run([], until=lambda s: sum(1 for e in s['events'] if e['type'] == 'discard' and e['seat'] == 2) == 2)
        self.assertEqual(st['waiting_for'], [3])            # 打过一张后仍然不能荣和
        self.assertTrue(self.view(gid, 1)['hints']['furiten'])
        st = self.finish(gid, sc, [(1, 'tsumo')])
        names = [y['name'] for y in st['result']['wins'][0]['yaku']]
        self.assertIn('两立直', names)       # 第一次打牌就立直
        self.assertNotIn('一发', names)

    def test_furiten_no_yaku_switch(self):
        """没役时漏掉听的牌：默认算同巡振听，开关关掉不算。"""
        wall = W({1: '123m789m123s99s24p'}, ['1z', '2z', '3p'], avoid=['3p'])
        for rules, expect in (({}, True), ({'furiten_no_yaku': False}, False)):
            gid, sc = self.start(wall, rules)
            sc.run([], until=lambda s: any(e['type'] == 'discard' and e['seat'] == 2 for e in s['events']))
            self.assertEqual(self.view(gid, 1)['hints']['furiten'], expect)

    # ------------------------------------------------------------ 流局、换庄、指定牌山

    NOTEN0 = '13579m2468p1357s'
    NOTEN2 = '13579p2468s2468m'
    TENPAI3 = '123m456m789p111z9s'

    def test_exhaustive_and_next_wall(self):
        wall = W({0: self.NOTEN0, 1: self.TENPAI1, 2: self.NOTEN2, 3: self.TENPAI3}, ['5z', '6z', '7z', '6z'])
        gid, sc = self.start(wall)
        st = self.finish(gid, sc)
        r = st['result']
        self.assertEqual((r['type'], r['reason']), ('ryuukyoku', 'exhaustive'))
        self.assertEqual(r['tenpai'], [False, True, False, True])
        self.assertEqual(r['delta'], [-1500, 1500, -1500, 1500])
        self.assertEqual(st['wall_left'], 0)
        wall2 = W({}, seed=7)
        nx = self.c.next(gid, 1, wall=wall2)
        STATES.append(('next', nx))
        self.assertEqual((nx['round']['number'], nx['round']['dealer'], nx['round']['honba']), (2, 1, 1))
        self.assertEqual(nx['viewer'], 1)
        self.assertEqual(nx['drawn'], wall2[52])          # 庄家（座位 1）先摸 wall[52]
        self.assertEqual(sorted(nx['players'][1]['hand'] + [nx['drawn']]), sorted(wall2[13:26] + [wall2[52]]))
        self.assertEqual([p['seat_wind'] for p in nx['players']], ['4z', '1z', '2z', '3z'])
        v0 = self.view(gid, 0)
        self.assertEqual(sorted(v0['players'][0]['hand']), sorted(wall2[0:13]))
        self.assertEqual(v0['wall_left'], 69)

    def test_exhaustive_dealer_tenpai_renchan(self):
        wall = W({0: self.TENPAI3, 1: self.NOTEN0, 2: self.NOTEN2, 3: self.TENPAI1}, ['5z', '6z', '7z', '6z'])
        gid, sc = self.start(wall)
        st = self.finish(gid, sc)
        self.assertEqual(st['result']['delta'], [1500, -1500, -1500, 1500])
        nx = self.c.next(gid, 0)
        self.assertEqual((nx['round']['number'], nx['round']['dealer'], nx['round']['honba']), (1, 0, 1))

    # ------------------------------------------------------------ 途中流局

    def test_kyuushu(self):
        wall = W({0: '19m19p19s123z2345m'}, ['4z'])
        gid, sc = self.start(wall)
        st = self.finish(gid, sc, [(0, 'kyuushu')])
        self.assertEqual((st['result']['reason'], st['result']['delta']), ('kyuushu', [0, 0, 0, 0]))
        nx = self.c.next(gid, 0)
        self.assertEqual((nx['round']['dealer'], nx['round']['honba']), (0, 1))

    def test_four_winds(self):
        wall = W({}, ['1z', '1z', '1z', '1z'])
        gid, sc = self.start(wall)
        st = self.finish(gid, sc)
        self.assertEqual(st['result']['reason'], 'four_winds')

    def test_four_riichi(self):
        hands = {0: '123m456m789m234p5p', 1: self.TENPAI1, 2: '111z456m789p234p9s', 3: '555z789p456s789s9s'}
        wall = W(hands, ['9s', '2z', '3z', '4z'], dora=['7z'], ura=['7z'])
        gid, sc = self.start(wall)
        st = self.finish(gid, sc, [(0, 'riichi', {'tile': '9s', 'tsumogiri': True}),
                                   (1, 'riichi', {'tile': '2z', 'tsumogiri': True}),
                                   (2, 'riichi', {'tile': '3z', 'tsumogiri': True}),
                                   (3, 'riichi', {'tile': '4z', 'tsumogiri': True})])
        self.assertEqual(st['result']['reason'], 'four_riichi')
        self.assertEqual([p['score'] for p in st['players']], [24000] * 4)
        nx = self.c.next(gid, 0)
        self.assertEqual((nx['round']['honba'], nx['round']['riichi_sticks']), (1, 4))

    def test_four_kans(self):
        wall = W({0: '1111m2222m159p37z', 1: '3333m4444m159s24z'}, ['6z', '6z'], rinshan=['5z', '5z', '7z', '7z'])
        gid, sc = self.start(wall)
        st = self.finish(gid, sc, [(0, 'ankan', {'tile': '1m'}), (0, 'ankan', {'tile': '2m'}),
                                   (1, 'ankan', {'tile': '3m'}), (1, 'ankan', {'tile': '4m'})])
        self.assertEqual(st['result']['reason'], 'four_kans')
        self.assertEqual(len(st['dora_indicators']), 5)

    def test_kan_dora_timing(self):
        wall = W({0: '7p147m258s369m124z', 1: '777p258m147s369p1z'}, ['6z'], rinshan=['5z'])
        for rules, before in (({}, 1), ({'kan_dora_delay': False}, 2)):
            gid, sc = self.start(wall, rules)
            sc.run([(0, 'discard', {'tile': '7p', 'tsumogiri': False}), (1, 'minkan')])
            st = self.view(gid, 1)
            self.assertEqual(st['drawn'], '5z')               # 岭上牌
            self.assertEqual(len(st['dora_indicators']), before)
            self.assertEqual(st['wall_left'], 68)             # 摸了 1 张、开了 1 杠
            st = self.c.action(gid, 1, 'discard', tile='5z', tsumogiri=True)
            self.assertEqual(len(st['dora_indicators']), 2)

    # ------------------------------------------------------------ 同时表态、红五暗杠、提示

    PRIO = {0: '4m147p258s369p123z', 1: '23m258p147s569m45z', 2: '44m369s178m67z28p9s'}

    def test_pon_beats_chi_and_partial_reply(self):
        wall = W(self.PRIO, ['7z'])
        for second, winner in (('pon', 2), ('pass', 1)):
            gid, sc = self.start(wall)
            sc.run([(0, 'discard', {'tile': '4m', 'tsumogiri': False})])
            st = self.view(gid, 1)
            self.assertEqual(st['waiting_for'], [1, 2])
            chi = [a for a in st['legal_actions'] if a['type'] == 'chi'][0]
            self.assertEqual(chi['options'], [['2m', '3m'], ['3m', '5m'], ['5m', '6m']])
            st = self.c.action(gid, 1, 'chi', tiles=['2m', '3m'])      # 先回复的人：存着，等别人
            STATES.append(('partial', st))
            self.assertEqual((st['phase'], st['waiting_for'], st['legal_actions']), ('playing', [2], []))
            self.assertEqual(st['players'][1]['melds'], [])
            st = self.c.action(gid, 2, second, **({'tiles': ['4m', '4m']} if second == 'pon' else {}))
            STATES.append(('resolved', st))
            self.assertEqual(st['turn'], winner)
            self.assertEqual(st['players'][winner]['melds'][0]['type'], 'chi' if winner == 1 else 'pon')
            self.assertTrue(st['players'][0]['discards'][0]['called'])

    def test_ankan_red_five(self):
        wall = W({0: '0m55m147p258s369p1z'}, ['5m'])
        gid, sc = self.start(wall)
        st = self.view(gid, 0)
        self.assertEqual([a['tiles'] for a in st['legal_actions'] if a['type'] == 'ankan'], [['5m']])
        st = self.c.action(gid, 0, 'ankan', tile='5m')
        STATES.append(('ankan', st))
        m = st['players'][0]['melds'][0]
        self.assertEqual((m['type'], sorted(m['tiles']), m['from'], m['called_tile']), ('ankan', ['0m', '5m', '5m', '5m'], None, None))
        self.assertEqual(st['events'][-3:-1], [{'type': 'ankan', 'seat': 0, 'tile': '5m'}, {'type': 'dora', 'tile': wall[123]}])
        self.assertNotIn('0m', st['players'][0]['hand'])

    def test_hints_exact(self):
        wall = W({0: '123m456m789m234p5p', 1: self.TENPAI1}, ['9s'], avoid=['3s', '5p', '6s', '9s'])
        gid, sc = self.start(wall)
        st = self.view(gid, 0)
        self.assertEqual(st['drawn'], '9s')
        # 打 9s 剩 2345p 是延张，听 2p 5p
        self.assertEqual(st['hints']['discards'], {'2p': [{'tile': '9s', 'left': 3}], '5p': [{'tile': '9s', 'left': 3}],
                                                   '9s': [{'tile': '2p', 'left': 3}, {'tile': '5p', 'left': 3}]})
        self.assertEqual([a['tiles'] for a in st['legal_actions'] if a['type'] == 'riichi'], [['2p', '5p', '9s']])
        v1 = self.view(gid, 1)
        self.assertEqual(v1['hints']['waits'], [{'tile': '3s', 'left': 3}, {'tile': '6s', 'left': 3}, {'tile': '9s', 'left': 4}])
        self.assertFalse(v1['hints']['furiten'])
        self.assertEqual(v1['legal_actions'], [])
        self.assertIsNone(v1['drawn'])
        self.assertEqual(v1['events'][-1], {'type': 'draw', 'seat': 0, 'tile': None})
        self.c.action(gid, 0, 'discard', tile='9s', tsumogiri=True)
        v1 = self.view(gid, 1)
        self.assertEqual(v1['hints']['waits'][2], {'tile': '9s', 'left': 3})   # 河里那张扣掉
        self.assertIn({'type': 'ron'}, v1['legal_actions'])

    # ------------------------------------------------------------ 包、流局满贯

    PAO_HANDS = {0: '5z258m369p147s123z', 1: '55z66z77z123m9s147p', 2: '67z369m258p258s34z'}
    PAO_STEPS = [(0, 'discard', {'tile': '5z', 'tsumogiri': False}), (1, 'pon', {'tiles': ['5z', '5z']}),
                 (1, 'discard', {'tile': '1p', 'tsumogiri': False}), (2, 'discard', {'tile': '6z', 'tsumogiri': False}),
                 (1, 'pon', {'tiles': ['6z', '6z']}), (1, 'discard', {'tile': '4p', 'tsumogiri': False}),
                 (2, 'discard', {'tile': '7z', 'tsumogiri': False}), (1, 'pon', {'tiles': ['7z', '7z']}),
                 (1, 'discard', {'tile': '7p', 'tsumogiri': False})]

    def test_pao_daisangen(self):
        """座位 2 打出第三组三元牌被碰：大三元自摸由座位 2 全付；别人放铳时两人各付一半。"""
        tsumo = W(self.PAO_HANDS, ['1m', '8p', '8s', '9p', '9m', '4m', '9s'], dora=['8m'], ura=['8m'], avoid=['9s'])
        for rules, delta in (({}, [0, 32000, -32000, 0]), ({'pao': False}, [-16000, 32000, -8000, -8000])):
            gid, sc = self.start(tsumo, rules)
            st = self.finish(gid, sc, self.PAO_STEPS + [(1, 'tsumo')])
            w = st['result']['wins'][0]
            self.assertEqual((w['seat'], w['yakuman'], w.get('pao')), (1, 1, 2 if not rules else None))
            self.assertEqual(st['result']['delta'], delta)
        ron = W(self.PAO_HANDS, ['1m', '8p', '8s', '9p', '9s'], dora=['8m'], ura=['8m'])
        gid, sc = self.start(ron)
        st = self.finish(gid, sc, self.PAO_STEPS + [(1, 'ron')])
        self.assertEqual(st['result']['wins'][0]['from'], 3)
        self.assertEqual(st['result']['delta'], [0, 32000, -16000, -16000])

    def test_nagashi_mangan(self):
        """开关：座位 2 打出的牌全是幺九、没被鸣走，荒牌时按满贯自摸收点（不付听牌料）。"""
        yao = harness.full_set()
        mine = [t for t in yao if t[1] == 'z'][:14:] + ['1m', '9m', '1p']
        mine = sorted(mine)[:17]
        pool = list(yao)
        for t in mine:
            pool.remove(t)
        import random
        random.Random(11).shuffle(pool)
        wall = [None] * 136
        for k, t in enumerate(mine):
            wall[54 + 4 * k] = t
        for i in range(136):
            if wall[i] is None:
                wall[i] = pool.pop()
        for rules, nag in (({'nagashi_mangan': True}, True), ({}, False)):
            gid, sc = self.start(wall, rules)
            st = self.finish(gid, sc)
            r = st['result']
            self.assertEqual(r['reason'], 'exhaustive')
            if nag:
                self.assertEqual(r['nagashi'], [2])
                self.assertEqual(r['delta'], [-4000, -2000, 8000, -2000])
            else:
                self.assertNotIn('nagashi', r)

    # ------------------------------------------------------------ 食替、接口开关

    def test_kuikae(self):
        wall = W({0: '3m147p258s369p123z', 1: '3456m147p258s123z'}, ['7z'])
        for rules, banned in (({}, True), ({'kuikae_ban': False}, False)):
            gid, sc = self.start(wall, rules)
            sc.run([(0, 'discard', {'tile': '3m', 'tsumogiri': False}), (1, 'chi', {'tiles': ['4m', '5m']})])
            st = self.view(gid, 1)
            tiles = [a for a in st['legal_actions'] if a['type'] == 'discard'][0]['tiles']
            self.assertEqual('3m' not in tiles and '6m' not in tiles, banned)
            if banned:
                with self.assertRaises(harness.ApiError) as cm:
                    self.c.action(gid, 1, 'discard', tile='6m', tsumogiri=False)
                self.assertEqual(cm.exception.status, 400)

    def test_kuitan_switch(self):
        wall = W({0: '4m147p258s369m123z', 1: '23m456p678s34s55p6z'}, ['7z', '5s'], avoid=['5s', '2s'])
        steps = [(0, 'discard', {'tile': '4m', 'tsumogiri': False}), (1, 'chi', {'tiles': ['2m', '3m']}),
                 (1, 'discard', {'tile': '6z', 'tsumogiri': False})]
        gid, sc = self.start(wall)
        st = self.finish(gid, sc, steps + [(1, 'ron')])
        w = st['result']['wins'][0]
        self.assertEqual(([y['name'] for y in w['yaku']], w['fu'], w['points']), (['断幺九'], 30, 1000))
        gid, sc = self.start(wall, {'kuitan': False})
        sc.run(steps)
        st = sc.run([], until=lambda s: any(e['type'] == 'discard' and e['seat'] == 2 for e in s['events']))
        self.assertNotIn(1, st['waiting_for'])
        self.assertFalse(st['rules']['kuitan'])

    def test_aka_switch_and_rules_echo(self):
        wall = W({}, seed=3)                                   # 牌山里有红五
        gid, sc = self.start(wall, {'aka_dora': False, 'renpu_fu': 2, 'kiriage_mangan': True})
        for s in range(4):
            st = self.view(gid, s)
            self.assertFalse(any(t[0] == '0' for t in st['players'][s]['hand'] + [st['drawn'] or '1z']))
            self.assertEqual({k: st['rules'][k] for k in ('aka_dora', 'kuitan', 'kiriage_mangan', 'renpu_fu')},
                             {'aka_dora': False, 'kuitan': True, 'kiriage_mangan': True, 'renpu_fu': 2})
        st = self.c.new_game(players=['human'] * 4)
        self.assertEqual(st['rules']['renpu_fu'], 4)
        self.assertTrue(st['rules']['aka_dora'])

    def test_errors(self):
        gid, sc = self.start(W({}, seed=1))
        for bad in (lambda: self.c.action(gid, 1, 'discard', tile='1m', tsumogiri=False),   # 不该他
                    lambda: self.c.action(gid, 0, 'discard', tile='9z', tsumogiri=False),   # 不是牌
                    lambda: self.c.action(gid, 0, 'ron'),
                    lambda: self.c.next(gid, 0),                                           # 一局没完
                    lambda: self.c.new_game(rules={'renpu_fu': 3}),
                    lambda: self.c.new_game(wall=['1m'] * 136)):
            with self.assertRaises(harness.ApiError) as cm:
                bad()
            self.assertEqual(cm.exception.status, 400)
        with self.assertRaises(harness.ApiError) as cm:
            self.c.state('nope', 0)
        self.assertEqual(cm.exception.status, 404)


class FlowInProc(Scenarios, unittest.TestCase):
    INPROC = True

    def setUp(self):
        self.c = InProcClient()

    # ---- 只在进程内跑：要改点数、局数来搭局面

    def win_at(self, gid, scores=None, number=None, sticks=0, wall=None):
        g = self.c.game(gid)
        if number:
            g.number = number
        if scores:
            g.scores = list(scores)
        g.riichi_sticks = sticks
        if number:
            g._start_round(wall)
        return g

    def test_tobi(self):
        for rules, phase in (({}, 'game_end'), ({'tobi': False}, 'round_end')):
            wall = W(TestData.DOUBLE_ONE, ['7z'], dora=['8m'], ura=['8m'], avoid=['9s'])
            gid, sc = self.start(wall, rules)
            self.win_at(gid, scores=[500, 25000, 25000, 49500])
            st = self.finish(gid, sc, [(0, 'discard', {'tile': '9s', 'tsumogiri': False}), (1, 'ron')])
            self.assertEqual(st['phase'], phase)
            self.assertEqual(st['players'][0]['score'], -500)
            if phase == 'game_end':
                self.assertEqual(st['result']['final']['ranks'], [4, 2, 3, 1])
                with self.assertRaises(harness.ApiError):
                    self.c.next(gid, 0)
            else:
                self.c.next(gid, 0)

    def test_last_round_dealer(self):
        """东 4 局庄家（座位 3）和了：是第一就结束，不是第一就连庄；开关关掉不结束。"""
        wall = W({3: self.TENPAI3, 0: '123m456s789p55p9s4z'}, ['7z', '7z'], dora=['8m'], ura=['8m'], avoid=['9s'])
        steps = [(0, 'discard', {'tile': '9s', 'tsumogiri': False}), (3, 'ron')]
        cases = [({}, [25000] * 4, 'game_end'), ({}, [40000, 20000, 20000, 20000], 'round_end'),
                 ({'agari_yame': False}, [25000] * 4, 'round_end')]
        for rules, scores, phase in cases:
            gid, sc = self.start(W({}, seed=5), rules)
            self.win_at(gid, scores=scores, number=4, wall=wall)
            st = self.finish(gid, sc, steps)
            self.assertEqual(st['result']['wins'][0]['seat'], 3)
            self.assertEqual(st['phase'], phase, (rules, scores))
            if phase == 'round_end':
                nx = self.c.next(gid, 0)
                self.assertEqual((nx['round']['number'], nx['round']['dealer'], nx['round']['honba']), (4, 3, 1))

    def test_last_round_non_dealer_win_ends(self):
        wall = W({1: self.TENPAI1, 0: '123m456s789p55p9s4z'}, ['7z', '7z'], dora=['8m'], ura=['8m'], avoid=['9s'])
        gid, sc = self.start(W({}, seed=5))
        self.win_at(gid, number=4, wall=wall)
        st = self.finish(gid, sc, [(0, 'discard', {'tile': '9s', 'tsumogiri': False}), (1, 'ron')])
        self.assertEqual(st['phase'], 'game_end')

    def test_leftover_sticks(self):
        hands = {3: self.NOTEN0, 1: self.TENPAI1, 2: self.NOTEN2, 0: self.TENPAI3}
        wall = W(hands, ['5z', '6z', '7z', '6z'])
        for rules, top_score, sticks in (({}, 32500, 0), ({'leftover_sticks_to_top': False}, 31500, 1)):
            gid, sc = self.start(W({}, seed=5), rules)
            self.win_at(gid, scores=[30000, 24000, 25000, 20000], number=4, sticks=1, wall=wall)
            st = self.finish(gid, sc)
            self.assertEqual(st['phase'], 'game_end')
            self.assertEqual([p['score'] for p in st['players']], [top_score, 25500, 23500, 18500])
            self.assertEqual(st['round']['riichi_sticks'], sticks)
            self.assertEqual(sum(st['result']['delta']), 1000 * (1 - sticks))

    def test_hanchan_goes_to_south(self):
        gid, sc = self.start(W({}, seed=5), length='hanchan')
        wall = W({1: self.TENPAI1, 0: '123m456s789p55p9s4z'}, ['7z', '7z'], dora=['8m'], ura=['8m'], avoid=['9s'])
        self.win_at(gid, number=4, wall=wall)
        st = self.finish(gid, sc, [(0, 'discard', {'tile': '9s', 'tsumogiri': False}), (1, 'ron')])
        self.assertEqual(st['phase'], 'round_end')
        nx = self.c.next(gid, 0)
        self.assertEqual((nx['round']['wind'], nx['round']['number'], nx['round']['dealer']), ('2z', 1, 0))

    def test_tonpuu_extension(self):
        """南入：东 4 局结束没人到 30000 进入南场；南场有人到 30000 就结束。"""
        wall = W({1: self.TENPAI1, 0: '123m456s789p55p9s4z'}, ['7z', '7z'], dora=['8m'], ura=['8m'], avoid=['9s'])
        gid, sc = self.start(W({}, seed=5), {'tonpuu_extension': True})
        self.win_at(gid, number=4, wall=wall)
        st = self.finish(gid, sc, [(0, 'discard', {'tile': '9s', 'tsumogiri': False}), (1, 'ron')])
        self.assertEqual(st['phase'], 'round_end')
        nx = self.c.next(gid, 0, wall=W({1: self.TENPAI1, 0: '123m456s789p55p9s4z'}, ['7z', '7z'], dora=['8m'],
                                        ura=['8m'], avoid=['9s']))
        self.assertEqual(nx['round']['wind'], '2z')
        self.c.game(gid).scores = [25000, 29000, 23000, 23000]
        st = self.finish(gid, harness.Script(self.c, gid),
                         [(0, 'discard', {'tile': '9s', 'tsumogiri': False}), (1, 'ron')])
        self.assertEqual(st['phase'], 'game_end')


class TestData:
    DOUBLE_ONE = {0: '123m456m789m56p9s4z', 1: '234s456s678p22p78s'}


class FlowHTTP(Scenarios, unittest.TestCase):
    server = None

    @classmethod
    def setUpClass(cls):
        cls.server = harness.Server(REF).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def setUp(self):
        self.c = harness.Client(self.server)


class ZZCheckState(unittest.TestCase):
    """最后跑：前面所有测试看到的状态都要过页面的 checkState。"""

    def test_check_state(self):
        ok, out = check_states(STATES)
        if ok is None:
            self.skipTest(out)
        self.assertTrue(ok, out)
        self.assertGreater(len(STATES), 50)


if __name__ == '__main__':
    unittest.main()
