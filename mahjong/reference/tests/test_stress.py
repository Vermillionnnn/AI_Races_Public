"""随机整场压力测试：四个座位随机选合法操作打完整场，每一步查不变量。

不变量：点数守恒（点数合计 + 供托 = 100000）、牌数守恒（手牌 + 摸到的 + 副露 + 河 = 122 − 余牌）、
看得见的牌每种不超过 4 张、视角隐私、wall_left 不增、合法操作一定被接受、非法操作返回 400 且状态不变、
结算的番数加总、delta 和点数变化一致、每个状态过 checkState。

规模用环境变量调：STRESS_GAMES（进程内局数，默认 24）、STRESS_HTTP（走 HTTP 的局数，默认 2）。
"""

import os
import random
import time
import unittest

from util import REF, InProcClient, check_states, harness
from rules import DEFAULTS, parse_rules
from score import base_points, hand_value
from tiles import counts, kind, sort_tiles
from agari import shanten

N_INPROC = int(os.environ.get('STRESS_GAMES', '24'))
N_HTTP = int(os.environ.get('STRESS_HTTP', '2'))


def random_rules(rng):
    r = {}
    for k, (default, allowed) in DEFAULTS.items():
        if rng.random() < 0.3:
            r[k] = rng.choice(allowed) if allowed else (not default)
    return r


class Driver:
    def __init__(self, test, client, seed, players=None, length=None):
        self.t = test
        self.c = client
        self.rng = random.Random(seed)
        self.seed = seed
        self.players = players or ['human'] * 4
        self.length = length or self.rng.choice(['tonpuu', 'hanchan'])
        self.rules_in = random_rules(self.rng)
        self.states = []
        self.requests = 0
        self.max_ms = 0

    def call(self, fn, *a, **kw):
        t0 = time.time()
        res = fn(*a, **kw)
        self.max_ms = max(self.max_ms, (time.time() - t0) * 1000)
        self.requests += 1
        return res

    def keep(self, name, st):
        if len(self.states) < 400 or st['phase'] != 'playing' or self.rng.random() < 0.05:
            self.states.append(('%s seed=%d' % (name, self.seed), st))

    # ------------------------------------------------------------ 一整场

    def run(self):
        st = self.call(self.c.new_game, players=self.players, length=self.length, seed=self.seed,
                       rules=self.rules_in)
        self.gid = st['game_id']
        self.rules = parse_rules(self.rules_in)
        self.t.assertEqual(st['rules'], self.rules)
        rounds = 0
        while True:
            self.round_start = self.view(0)
            self.play_round()
            end = self.view(0)
            rounds += 1
            self.check_round_end(end)
            if end['phase'] == 'game_end':
                self.check_game_end(end)
                return rounds
            self.t.assertLess(rounds, 60)
            st = self.call(self.c.next, self.gid, self.rng.randrange(4))
            self.keep('next', st)

    def view(self, seat):
        st = self.call(self.c.state, self.gid, seat)
        self.check_state(st, seat)
        self.keep('view', st)
        return st

    def play_round(self):
        last_left = 999
        for _ in range(3000):
            st0 = self.view(0)
            if st0['phase'] != 'playing':
                return
            self.t.assertLessEqual(st0['wall_left'], last_left)
            last_left = st0['wall_left']
            self.check_conservation(self.view(st0['turn']))
            waiting = st0['waiting_for']
            self.t.assertTrue(waiting, 'playing 但 waiting_for 为空')
            for s in range(4):
                if self.players[s] == 'bot':
                    self.t.assertNotIn(s, waiting)
            seat = self.rng.choice(waiting)
            st = self.view(seat)
            if self.rng.random() < 0.03:
                self.try_illegal(seat, st)
            typ, kw = self.choose(st)
            res = self.call(self.c.action, self.gid, seat, typ, **kw)
            self.check_state(res, seat)
            self.keep('action', res)
        self.t.fail('一局走不完')

    def choose(self, st):
        legal = {a['type']: a for a in st['legal_actions']}
        rng = self.rng
        self.t.assertTrue(legal, '在 waiting_for 里但没有合法操作')
        for typ, p in (('tsumo', 0.8), ('ron', 0.8), ('kyuushu', 0.3), ('riichi', 0.5), ('ankan', 0.4),
                       ('kakan', 0.4), ('minkan', 0.3), ('pon', 0.2), ('chi', 0.15)):
            if typ in legal and rng.random() < p:
                a = legal[typ]
                if typ == 'riichi':
                    t = rng.choice(a['tiles'])
                    hand = st['players'][st['viewer']]['hand']
                    return typ, {'tile': t, 'tsumogiri': t == st['drawn'] and (t not in hand or rng.random() < 0.5)}
                if typ in ('ankan', 'kakan'):
                    return typ, {'tile': rng.choice(a['tiles'])}
                if typ in ('chi', 'pon'):
                    return typ, {'tiles': rng.choice(a['options'])}
                return typ, {}
        if 'discard' in legal:
            t = self.pick_discard(st, legal['discard']['tiles'])
            hand = st['players'][st['viewer']]['hand']
            tg = (t == st['drawn']) and (t not in hand or rng.random() < 0.5)
            return 'discard', {'tile': t, 'tsumogiri': tg}
        self.t.assertIn('pass', legal)
        return 'pass', {}

    def pick_discard(self, st, tiles):
        """大多数时候打向听数最小的牌（让牌局能和、能立直），有时随便打。"""
        if self.rng.random() < 0.25:
            return self.rng.choice(tiles)
        p = st['players'][st['viewer']]
        own = p['hand'] + ([st['drawn']] if st['drawn'] else [])
        best, best_sh = [], 99
        for t in tiles:
            rest = list(own)
            rest.remove(t)
            sh = shanten(counts(rest), len(p['melds']))
            if sh < best_sh:
                best, best_sh = [t], sh
            elif sh == best_sh:
                best.append(t)
        return self.rng.choice(best)

    def try_illegal(self, seat, st):
        before = len(st['events'])
        hand = set(st['players'][seat]['hand']) | {st['drawn']}
        bad = [t for t in ('1m', '9p', '5s', '7z', '0m') if t not in hand][0]
        other = (st['waiting_for'][0] + 1) % 4 if len(st['waiting_for']) == 1 else None
        tries = [lambda: self.c.action(self.gid, seat, 'discard', tile=bad, tsumogiri=False),
                 lambda: self.c.action(self.gid, seat, 'bogus')]
        if other is not None and other not in st['waiting_for']:
            tries.append(lambda: self.c.action(self.gid, other, 'pass'))
        for fn in tries:
            with self.t.assertRaises(harness.ApiError) as cm:
                fn()
            self.t.assertEqual(cm.exception.status, 400)
        self.t.assertEqual(len(self.c.state(self.gid, seat)['events']), before)

    # ------------------------------------------------------------ 检查

    def check_state(self, st, seat):
        t = self.t
        t.assertEqual(st['viewer'], seat)
        t.assertEqual(sum(p['score'] for p in st['players']) + 1000 * st['round']['riichi_sticks'], 100000)
        for i, p in enumerate(st['players']):
            t.assertEqual('hand' in p, i == seat)
            n = p['hand_count'] + 3 * len(p['melds'])
            if i == seat:
                t.assertEqual(len(p['hand']), p['hand_count'])
                t.assertEqual(p['hand'], sort_tiles(p['hand']))
                if st['drawn'] is not None:
                    t.assertEqual(n, 13)
            # 只有轮到的人在吃碰之后（没有 drawn）才是 14 张形
            t.assertIn(n, (13, 14) if i == st['turn'] else (13,))
        for e in st['events']:
            if e['type'] == 'draw' and e['seat'] != seat:
                t.assertIsNone(e['tile'])
        if st['phase'] == 'playing':
            if seat not in st['waiting_for']:
                t.assertEqual(st['legal_actions'], [])
            disc = [a for a in st['legal_actions'] if a['type'] == 'discard']
            if disc:
                own = set(st['players'][seat]['hand']) | ({st['drawn']} if st['drawn'] else set())
                t.assertTrue(set(disc[0]['tiles']) <= own)
            h = st['hints']
            for w in h['waits']:
                t.assertTrue(0 <= w['left'] <= 4)
        # 看得见的牌每种最多 4 张、红五最多 1 张
        vis = list(st['players'][seat]['hand']) + ([st['drawn']] if st['drawn'] else []) + st['dora_indicators']
        for p in st['players']:
            vis += [d['tile'] for d in p['discards'] if not d['called']]
            for m in p['melds']:
                vis += m['tiles']
        c = [0] * 34
        for x in vis:
            c[kind(x)] += 1
        t.assertLessEqual(max(c), 4, vis)
        for s in 'mps':
            t.assertLessEqual(vis.count('0' + s), 1 if self.rules['aka_dora'] else 0)

    def check_conservation(self, st):
        """从轮到的人的视角数牌：手牌 + 摸到的 + 副露 + 河（不算被鸣走的） = 52 + 摸过的张数。"""
        total = sum(p['hand_count'] for p in st['players']) + (1 if st['drawn'] else 0)
        for p in st['players']:
            total += sum(len(m['tiles']) for m in p['melds'])
            total += sum(1 for d in p['discards'] if not d['called'])
        self.t.assertEqual(total, 122 - st['wall_left'], st)
        kans = sum(1 for p in st['players'] for m in p['melds'] if m['type'] in ('minkan', 'ankan', 'kakan'))
        self.t.assertLessEqual(len(st['dora_indicators']), 1 + kans)

    def check_round_end(self, end):
        t = self.t
        t.assertIn(end['phase'], ('round_end', 'game_end'))
        r = end['result']
        start = self.round_start
        riichi = [1 if p['riichi'] else 0 for p in end['players']]
        delta = r['delta']
        left = r.get('leftover_sticks', {}).get('count', 0)
        sticks_taken = start['round']['riichi_sticks'] + sum(riichi) - end['round']['riichi_sticks']
        t.assertEqual(sum(delta), 1000 * sticks_taken)
        for i in range(4):
            t.assertEqual(end['players'][i]['score'],
                          start['players'][i]['score'] - 1000 * riichi[i] + delta[i])
        if r['type'] == 'agari':
            t.assertTrue(1 <= len(r['wins']) <= 3)
            for w in r['wins']:
                t.assertEqual(w['han'], sum(y['han'] for y in w['yaku']))
                kans = sum(1 for m in w['melds'] if len(m['tiles']) == 4)
                t.assertEqual(len(w['hand']) + 1 + sum(len(m['tiles']) for m in w['melds']), 14 + kans)
                tsumo = w['from'] is None
                dealer = w['seat'] == end['round']['dealer']
                if w['yakuman']:
                    t.assertTrue(all(y['han'] % 13 == 0 for y in w['yaku']))
                    t.assertEqual(w['points'], hand_value(8000 * w['yakuman'], dealer, tsumo))
                else:
                    t.assertTrue(w['han'] >= 1 and w['fu'] in (20, 25) + tuple(range(30, 120, 10)), w)
                    t.assertEqual(w['points'], hand_value(base_points(w['han'], w['fu'], self.rules), dealer, tsumo))
            if not left:
                t.assertGreater(delta[r['wins'][0]['seat']], 0)
        else:
            t.assertIn(r['reason'], ('exhaustive', 'kyuushu', 'four_kans', 'four_riichi', 'four_winds', 'triple_ron'))
            if r['reason'] == 'exhaustive' and not r.get('nagashi'):
                n = sum(r['tenpai'])
                base = [d - (1000 * left if i == r.get('leftover_sticks', {}).get('to') else 0)
                        for i, d in enumerate(delta)]
                exp = [0] * 4 if n in (0, 4) else [3000 // n if tp else -3000 // (4 - n) for tp in r['tenpai']]
                t.assertEqual(base, exp)
        self.keep('end', end)

    def check_game_end(self, end):
        ranks = end['result']['final']['ranks']
        self.t.assertEqual(sorted(ranks), [1, 2, 3, 4])
        order = sorted(range(4), key=lambda s: (-end['players'][s]['score'], s))
        self.t.assertEqual([ranks[s] for s in order], [1, 2, 3, 4])


class Stress(unittest.TestCase):
    def run_games(self, client, n, seed0, players=None, length=None):
        all_states = []
        stats = []
        for i in range(n):
            d = Driver(self, client, seed0 + i, players, length)
            rounds = d.run()
            stats.append((rounds, d.requests, d.max_ms))
            all_states += d.states
        ok, out = check_states(all_states)
        if ok is not None:
            self.assertTrue(ok, out)
        return stats

    def test_inproc_random(self):
        stats = self.run_games(InProcClient(), N_INPROC, 1000)
        print('\n进程内 %d 场：共 %d 局，%d 次请求，最慢 %.0f ms' %
              (len(stats), sum(s[0] for s in stats), sum(s[1] for s in stats), max(s[2] for s in stats)))

    def test_inproc_with_bots(self):
        stats = self.run_games(InProcClient(), max(2, N_INPROC // 6), 5000, ['human', 'bot', 'bot', 'bot'], 'hanchan')
        print('\n人机混合 %d 场：最慢 %.0f ms' % (len(stats), max(s[2] for s in stats)))

    def test_http(self):
        with harness.Server(REF) as srv:
            c = harness.Client(srv)
            stats = self.run_games(c, N_HTTP, 9000)
            stats += self.run_games(c, 1, 9500, ['bot', 'human', 'bot', 'bot'], 'tonpuu')
            # 四个电脑：new_game 一次就打完第一局，每局一个请求
            t0 = time.time()
            st = c.new_game(players=['bot'] * 4, length='hanchan', seed=7)
            n = 1
            while st['phase'] != 'game_end':
                self.assertEqual(st['phase'], 'round_end')
                st = c.next(st['game_id'], 0)
                n += 1
            per = (time.time() - t0) / n
            self.assertLess(per, 5)
        print('\nHTTP %d 场，最慢 %.0f ms；全电脑半庄 %d 局，平均每局 %.2f s' %
              (len(stats), max(s[2] for s in stats), n, per))


if __name__ == '__main__':
    unittest.main()
