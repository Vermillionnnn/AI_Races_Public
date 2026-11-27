"""立直麻将综合自动化测试：覆盖全部模块、规则开关、边界牌型、高点法、接口协议与随机对局。"""

import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import unittest
from urllib import error as urlerror
from urllib import request as urlrequest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import fu
import game
import score
import server
import tenpai
import yaku

TILE_RE = re.compile(r'^([0-9][mps]|[1-7]z)$')


def check_state_schema(s):
    """等价于 frontend/index.html 的 checkState()，外加更严格的字段检查。"""
    problems = []
    assert isinstance(s, dict), 'state must be dict'
    if s.get('version') != 1:
        problems.append('version != 1')
    for k, tp in [
        ('game_id', str), ('phase', str), ('round', dict),
        ('dora_indicators', list), ('wall_left', int),
        ('viewer', int), ('turn', int), ('waiting_for', list),
        ('rules', dict), ('players', list), ('legal_actions', list),
        ('events', list),
    ]:
        if k not in s or not isinstance(s[k], tp) or isinstance(s[k], bool):
            problems.append(f'bad field {k}: {s.get(k)!r}')

    if s.get('phase') not in ('playing', 'round_end', 'game_end'):
        problems.append(f'bad phase: {s.get("phase")}')

    r = s['round']
    if r.get('wind') not in ('1z', '2z', '3z', '4z'):
        problems.append(f'bad round.wind: {r.get("wind")}')
    for rk in ('number', 'honba', 'riichi_sticks', 'dealer'):
        if not isinstance(r.get(rk), int) or isinstance(r.get(rk), bool):
            problems.append(f'bad round.{rk}')
    if not (1 <= r['number'] <= 4):
        problems.append(f'round.number out of range: {r["number"]}')

    rules = s['rules']
    for bk in ('aka_dora', 'kuitan', 'kiriage_mangan'):
        if not isinstance(rules.get(bk), bool):
            problems.append(f'rules.{bk} not bool')
    if rules.get('renpu_fu') not in (2, 4) or isinstance(rules.get('renpu_fu'), bool):
        problems.append(f'rules.renpu_fu invalid: {rules.get("renpu_fu")}')

    for t in s['dora_indicators']:
        if not TILE_RE.match(t):
            problems.append(f'bad dora_indicator: {t}')

    if len(s['players']) != 4:
        problems.append('players len != 4')
    viewer = s['viewer']
    for i, p in enumerate(s['players']):
        if p.get('seat') != i:
            problems.append(f'players[{i}].seat != {i}')
        if not isinstance(p.get('score'), int):
            problems.append(f'players[{i}].score not int')
        if not isinstance(p.get('hand_count'), int):
            problems.append(f'players[{i}].hand_count not int')
        if p.get('seat_wind') not in ('1z', '2z', '3z', '4z'):
            problems.append(f'players[{i}].seat_wind invalid')
        if not isinstance(p.get('riichi'), bool):
            problems.append(f'players[{i}].riichi not bool')
        for d in p.get('discards', []):
            if not TILE_RE.match(d.get('tile', '')):
                problems.append(f'bad discard tile: {d}')
            for fk in ('tsumogiri', 'riichi', 'called'):
                if not isinstance(d.get(fk), bool):
                    problems.append(f'discard.{fk} not bool')
        for m in p.get('melds', []):
            if m.get('type') not in ('chi', 'pon', 'minkan', 'ankan', 'kakan'):
                problems.append(f'bad meld type: {m}')
            for t in m.get('tiles', []):
                if not TILE_RE.match(t):
                    problems.append(f'bad meld tile: {t}')
            if m['type'] == 'ankan':
                if m.get('from') is not None or m.get('called_tile') is not None:
                    problems.append(f'ankan from/called_tile must be None: {m}')
            else:
                if m.get('from') not in (0, 1, 2, 3) or not TILE_RE.match(m.get('called_tile', '')):
                    problems.append(f'open meld from/called_tile invalid: {m}')
        if i == viewer:
            if 'hand' not in p or not isinstance(p['hand'], list):
                problems.append('viewer missing hand')
            else:
                if len(p['hand']) != p['hand_count']:
                    problems.append(f'viewer hand len {len(p["hand"])} != hand_count {p["hand_count"]}')
                for t in p['hand']:
                    if not TILE_RE.match(t):
                        problems.append(f'bad hand tile: {t}')
        else:
            if 'hand' in p:
                problems.append(f'leaked hand of seat {i} to viewer {viewer}')

    if s['drawn'] is not None and not TILE_RE.match(s['drawn']):
        problems.append(f'bad drawn: {s["drawn"]}')

    # 无赤宝牌时，牌桌状态中绝不应出现红五
    if not rules['aka_dora']:
        for t in s['dora_indicators']:
            if t[0] == '0':
                problems.append(f'red five in dora_indicators with aka_dora=False: {t}')
        if s['drawn'] and s['drawn'][0] == '0':
            problems.append('red five in drawn with aka_dora=False')
        for p in s['players']:
            for t in p.get('hand', []):
                if t[0] == '0':
                    problems.append('red five in hand with aka_dora=False')

    # events 中不能泄露别人摸的牌
    for e in s['events']:
        if e.get('type') == 'draw' and e.get('seat') != viewer:
            if e.get('tile') is not None:
                problems.append(f'leaked draw tile of seat {e["seat"]} to viewer {viewer}')

    if s['phase'] != 'playing':
        if not s['result']:
            problems.append('missing result when round/game ended')
        else:
            res = s['result']
            if res.get('type') == 'agari':
                for w in res['wins']:
                    for nk in ('seat', 'han', 'fu', 'yakuman', 'points'):
                        if not isinstance(w.get(nk), int) or isinstance(w.get(nk), bool):
                            problems.append(f'win.{nk} not int')
                    if sum(y['han'] for y in w['yaku']) != w['han']:
                        problems.append(f'win yaku han sum != han: {w}')
                    if not TILE_RE.match(w.get('win_tile', '')):
                        problems.append(f'bad win_tile: {w}')
            elif res.get('type') != 'ryuukyoku':
                problems.append(f'bad result.type: {res.get("type")}')
            if len(res.get('delta', [])) != 4:
                problems.append('result.delta len != 4')
    return problems


def build_wall(seat_hands, draws=None, dora_inds=None, ura_inds=None, rinshans=None, aka_dora=True):
    """按 接口说明.md 构造合法的 136 张牌山（剩余位置自动用未用牌补齐）。"""
    pool = game.make_wall(aka_dora=aka_dora)

    def take(t):
        if t in pool:
            pool.remove(t)
            return t
        raise ValueError(f'牌山中剩余的 {t} 不足')

    hands_out = []
    for s in range(4):
        h = list(seat_hands.get(s, []))
        taken = [take(t) for t in h]
        hands_out.append(taken)

    draws_taken = [take(t) for t in (draws or [])]
    dora_taken = [take(t) for t in (dora_inds or [])]
    ura_taken = [take(t) for t in (ura_inds or [])]
    rinshan_taken = [take(t) for t in (rinshans or [])]

    for s in range(4):
        while len(hands_out[s]) < 13:
            hands_out[s].append(pool.pop(0))

    while len(dora_taken) < 5:
        dora_taken.append(pool.pop(0))
    while len(ura_taken) < 5:
        ura_taken.append(pool.pop(0))
    while len(rinshan_taken) < 4:
        rinshan_taken.append(pool.pop(0))
    while len(draws_taken) < 70:
        draws_taken.append(pool.pop(0))

    assert len(pool) == 0, f'pool left: {len(pool)}'
    wall = (
        hands_out[0] + hands_out[1] + hands_out[2] + hands_out[3]
        + draws_taken + dora_taken + ura_taken + rinshan_taken
    )
    assert len(wall) == 136
    return wall


class TestTenpai(unittest.TestCase):
    def test_discard_hints_counts_discarded_tile(self):
        # 4 张 3m 在手里，打掉一张 3m 后听 3m/6m，此时 3m 剩余张数必须是 0（不是 1！）
        hand = ['3m', '3m', '3m', '3m', '4m', '5m', '1p', '2p', '3p', '7s', '8s', '9s', '5p', '5p']
        hints = tenpai.discard_hints(hand, [], [])
        self.assertIn('3m', hints)
        self.assertEqual(hints['3m']['3m'], 0)
        self.assertEqual(hints['3m']['6m'], 4)

    def test_discard_hints_chiitoitsu(self):
        hand = ['1m', '1m', '2m', '2m', '3p', '3p', '4p', '4p', '5s', '5s', '6s', '6s', '7z', '7z']
        hints = tenpai.discard_hints(hand, [], [])
        # 打掉一张 7z 后：手里 1 张 + 河里 1 张 = 用掉 2 张，剩 2 张（不是 3 张）
        self.assertEqual(hints['7z']['7z'], 2)

    def test_invalid_tile_rejected(self):
        hand = ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '1z', '1z', '1z', '9z', '9z']
        self.assertFalse(tenpai.can_hu(hand, []))


class TestFuScoreYaku(unittest.TestCase):
    def test_renpu_fu_switch(self):
        # 东场东家，11z 雀头 + 222m 暗刻 + 345p + 678s + 46s 嵌张自摸 5s
        # 20 + 2(自摸) + 2(嵌张) + 4(2m暗刻) = 28；连风 2 符 -> 30 符，连风 4 符 -> 32 -> 40 符
        hand = ['1z', '1z', '2m', '2m', '2m', '3p', '4p', '5p', '6s', '7s', '8s', '4s', '6s']
        self.assertEqual(fu.calc_fu(hand, [], '5s', True, '1z', '1z', renpu_fu=2), 30)
        self.assertEqual(fu.calc_fu(hand, [], '5s', True, '1z', '1z', renpu_fu=4), 40)

    def test_koutenhō_no_illegal_pinfu_30fu(self):
        # 23455m 234p 678p 234s 自摸 5m：
        # 拆成 22m? 不，13张=2345m 234p 678p 234s，自摸 5m -> 23455m：
        # 拆法A（雀头 2m 不成立；换成 22345m? 换 234567m 234p 678s 55p + 自摸 5m 不行；
        # 正确例子：13张 = 234m 345m 45m 234p 88s，自摸 4m -> 234m 345m 456m?
        # 13张 = 2m 3m 4m 3m 4m 5m 4m 5m 6m 2p 3p 4p 8s 8s（14张），自摸 4m：
        # 拆法A：4m 属于 234m（两面）-> 门清自摸+平和+断幺九 = 3 番 20 符（700/1300）
        # 拆法B：4m 属于 345m（嵌张）-> 门清自摸+断幺九 = 2 番 30 符（500/1000）
        # 绝不能出现 平和 + 30 符（3 番 30 符）！
        hand14 = ['2m', '3m', '4m', '3m', '4m', '5m', '4m', '5m', '6m', '2p', '3p', '4p', '8s', '8s']
        ev = yaku.evaluate_hand(hand14, [], '4m', True, '1z', '2z', [], {}, is_oya=False)
        self.assertTrue(ev['valid'])
        yaku_names = [y['name'] for y in ev['yaku']]
        self.assertIn('平和', yaku_names)
        self.assertEqual(ev['han'], 3)
        self.assertEqual(ev['fu'], 20)

    def test_koutenhō_same_han_picks_higher_fu(self):
        # 同番数不同符：234m 345m 456m 999s 55p，自摸 4m（有 999s 暗刻所以无论怎么拆都不是平和）
        # 两面拆法：20+2+8 = 30 符；嵌张拆法（4m 在 345m）：20+2+8+2 = 32 -> 40 符！应选 40 符
        hand14 = ['2m', '3m', '4m', '3m', '4m', '5m', '4m', '5m', '6m', '9s', '9s', '9s', '5p', '5p']
        ev = yaku.evaluate_hand(hand14, [], '4m', True, '1z', '2z', [], {}, is_oya=False)
        self.assertEqual(ev['han'], 1)
        self.assertEqual(ev['fu'], 40)

    def test_kuitan_switch(self):
        # 副露断幺九
        hand = ['2m', '3m', '4m', '5p', '6p', '7p', '3s', '4s', '8p', '8p']
        melds = [['6s', '7s', '8s']]
        ev_on = yaku.evaluate_hand(hand, melds, '5s', False, '1z', '2z', [], {}, rules={'kuitan': True})
        ev_off = yaku.evaluate_hand(hand, melds, '5s', False, '1z', '2z', [], {}, rules={'kuitan': False})
        self.assertTrue(ev_on['valid'])
        self.assertEqual(ev_on['han'], 1)
        self.assertFalse(ev_off['valid'])

    def test_score_2han_140fu_capped_at_mangan(self):
        # 2 番 140 符基本点 2240 >= 2000，应封顶满贯 8000 / 12000，绝不能超过满贯
        sc_ko = score.calc_score(140, 2, False, False)
        sc_oya = score.calc_score(140, 2, True, False)
        self.assertEqual(sc_ko['base_points'], 8000)
        self.assertEqual(sc_ko['rank'], '満貫')
        self.assertEqual(sc_oya['base_points'], 12000)

    def test_score_kiriage_mangan_switch(self):
        # 4 番 30 符、3 番 60 符：开切上满贯 = 8000/12000，关 = 7700/11600
        self.assertEqual(score.calc_score(30, 4, False, False, kiriage_mangan=False)['base_points'], 7700)
        self.assertEqual(score.calc_score(30, 4, False, False, kiriage_mangan=True)['base_points'], 8000)
        self.assertEqual(score.calc_score(60, 3, True, False, kiriage_mangan=False)['base_points'], 11600)
        self.assertEqual(score.calc_score(60, 3, True, False, kiriage_mangan=True)['base_points'], 12000)
        # 自摸
        s_off = score.calc_score(30, 4, False, True, kiriage_mangan=False)
        s_on = score.calc_score(30, 4, False, True, kiriage_mangan=True)
        self.assertEqual((s_off['ko_pay'], s_off['oya_pay'], s_off['base_points']), (2000, 3900, 7900))
        self.assertEqual((s_on['ko_pay'], s_on['oya_pay'], s_on['base_points']), (2000, 4000, 8000))

    def test_double_yakuman_vs_kazoe_yakuman(self):
        # 真双倍役满（四暗刻单骑）-> 64000 / 96000，yakuman = 2
        hand = ['1m', '1m', '1m', '2p', '2p', '2p', '3s', '3s', '3s', '5z', '5z', '5z', '9m']
        ev = yaku.evaluate_hand(hand, [], '9m', False, '1z', '2z', [], {}, is_oya=False)
        self.assertEqual(ev['yakuman'], 2)
        self.assertEqual(ev['han'], 26)
        self.assertEqual(ev['fu'], 0)
        sc = score.calc_score(ev['fu'], ev['han'], False, False, yakuman=ev['yakuman'])
        self.assertEqual(sc['base_points'], 64000)

        # 累计役满（14 番普通役）-> yakuman = 0，但点数按 1 倍役满 32000 算
        sc_kazoe = score.calc_score(30, 14, False, False, yakuman=0)
        self.assertEqual(sc_kazoe['base_points'], 32000)
        # 哪怕普通役凑到 26 番，累计役满也只有 1 倍
        sc_kazoe26 = score.calc_score(30, 26, False, False, yakuman=0)
        self.assertEqual(sc_kazoe26['base_points'], 32000)

    def test_chiihou_and_ankan_menzen(self):
        # 地和（同时兼容 chiihou 与 chihou）
        hand = ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '2s', '3s', '4s', '5m']
        ev1 = yaku.evaluate_hand(hand, [], '5m', True, '1z', '2z', [], {'chiihou': True})
        ev2 = yaku.evaluate_hand(hand, [], '5m', True, '1z', '2z', [], {'chihou': True})
        self.assertEqual(ev1['yakuman'], 1)
        self.assertEqual(ev2['yakuman'], 1)
        self.assertEqual(ev1['yaku'][0]['name'], '地和')

        # 暗杠保持门清：立直 + 暗杠 + 门清自摸 + 里宝牌 全部生效，且暗杠计 32 符
        h = ['2m', '3m', '4m', '4p', '5p', '6p', '6s', '7s', '8s', '5m']
        melds = [['1z', '1z', '1z', '1z']]
        st = {'riichi': True, 'ankan_indices': [0], 'ura_dora': ['5m']}
        ev = yaku.evaluate_hand(h, melds, '5m', True, '2z', '3z', [], st)
        names = [y['name'] for y in ev['yaku']]
        self.assertIn('立直', names)
        self.assertIn('门前清自摸和', names)
        self.assertIn('里宝牌', names)
        # 20 + 32(1z暗杠) + 2(单骑) + 2(自摸) = 56 -> 60 符
        self.assertEqual(ev['fu'], 60)


class TestGameScenarios(unittest.TestCase):
    def test_custom_wall_layout_and_dealer_rotation(self):
        # 验证 接口说明.md 的牌山布局：物理座位 0..3 配牌，wall[122] 宝牌指示牌，wall[127] 里宝，wall[132] 岭上
        s0 = ['1m', '2m', '3m', '4p', '0p', '6p', '7s', '8s', '9s', '2s', '3s', '4s', '5m']
        wall = build_wall(
            {0: s0},
            draws=['5m'],          # wall[52]: 庄家摸 5m -> 天和
            dora_inds=['3p'],      # wall[122]
            ura_inds=['9s'],       # wall[127]
            rinshans=['1z'],       # wall[132]
        )
        g = game.Game(human_seats=[0], wall=wall)
        st = g.to_api_state(viewer=0)
        self.assertEqual(check_state_schema(st), [])
        self.assertEqual(st['dora_indicators'], ['3p'])
        self.assertEqual(st['drawn'], '5m')
        self.assertEqual(st['wall_left'], 69)
        self.assertIn('tsumo', [a['type'] for a in st['legal_actions']])
        g.do_action(0, 'tsumo')
        st2 = g.to_api_state(viewer=0)
        self.assertEqual(check_state_schema(st2), [])
        self.assertEqual(st2['result']['wins'][0]['yakuman'], 1)
        self.assertEqual(st2['result']['wins'][0]['yaku'], [{'name': '天和', 'han': 13}])
        self.assertEqual(st2['result']['wins'][0]['points'], 48000)

        # 东 1 局让闲家（座位 1）地和：验证下一局轮到庄家=1 时，wall[0:13] 仍发给物理座位 0！
        s1_win = ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '2s', '3s', '4s', '7m']
        wall2 = build_wall(
            {0: ['1p', '2p', '3p', '4m', '5m', '6m', '1s', '2s', '3s', '5z', '5z', '6z', '6z'],
             1: s1_win},
            draws=['7z', '7m'],    # wall[52]=7z(东1庄家0摸并打), wall[53]=7m(座位1摸 -> 地和)
        )
        g2 = game.Game(human_seats=[0, 1, 2, 3], wall=wall2)
        g2.do_action(0, 'discard', tile='7z', tsumogiri=True)
        st_s1 = g2.to_api_state(viewer=1)
        self.assertIn('tsumo', [a['type'] for a in st_s1['legal_actions']])
        g2.do_action(1, 'tsumo')
        st_end = g2.to_api_state(viewer=1)
        self.assertEqual(st_end['result']['wins'][0]['yaku'], [{'name': '地和', 'han': 13}])
        self.assertEqual(st_end['result']['wins'][0]['points'], 32000)

        # 进入东 2 局（dealer=1）：wall[0:13] 必须给物理座位 0，wall[52] 由当前庄家（座位 1）先摸！
        s0_r2 = ['1m', '1m', '2m', '2m', '3m', '3m', '4m', '4m', '5m', '5m', '6m', '6m', '7m']
        s1_r2 = ['1p', '2p', '3p', '4p', '5p', '6p', '7p', '8p', '9p', '1s', '2s', '3s', '9s']
        wall3 = build_wall({0: s0_r2, 1: s1_r2}, draws=['9s'])
        g2.next_round(wall=wall3)
        st_r2_0 = g2.to_api_state(viewer=0)
        st_r2_1 = g2.to_api_state(viewer=1)
        self.assertEqual(st_r2_0['round']['dealer'], 1)
        self.assertEqual(st_r2_0['round']['number'], 2)
        self.assertEqual(st_r2_0['players'][0]['hand'], sorted(s0_r2, key=game.tile_key))
        self.assertEqual(st_r2_1['turn'], 1)
        self.assertEqual(st_r2_1['drawn'], '9s')

    def test_chankan_and_ippatsu(self):
        # 座位 0 立直听 2m/5m（手里 3m 4m，不含 5m）；座位 1 之前碰了 5m，立直后下一巡摸第 4 张 5m 加杠 -> 座位 0 抢杠 + 一发！
        s0 = ['3m', '4m', '4p', '5p', '6p', '7s', '8s', '9s', '2s', '3s', '4s', '7z', '7z']
        s1 = ['5m', '5m', '1p', '2p', '3p', '7p', '8p', '9p', '1s', '2s', '3s', '9m', '9m']
        s2 = ['1m', '6m', '8m', '9m', '1p', '3p', '6p', '8p', '9p', '1s', '5s', '6s', '7s']
        s3 = ['1m', '9m', '1p', '9p', '1s', '9s', '1z', '2z', '3z', '4z', '5z', '6z', '8s']
        wall = build_wall(
            {0: s0, 1: s1, 2: s2, 3: s3},
            draws=['9p', '8p', '5m', '1z', '2z', '3z', '0m'],
            dora_inds=['4z'],
        )
        g = game.Game(human_seats=[0, 1, 2, 3], wall=wall)

        def pass_all():
            while g.phase == 'call':
                for w in list(g.waiting_for()):
                    g.do_action(w, 'pass')

        g.do_action(0, 'discard', tile='9p', tsumogiri=True)
        pass_all()
        g.do_action(1, 'discard', tile='8p', tsumogiri=True)
        pass_all()
        g.do_action(2, 'discard', tile='5m', tsumogiri=True)
        # 座位 1 碰 5m（若有其他人有鸣牌选项一并跳过）
        for w in list(g.waiting_for()):
            if w == 1:
                g.do_action(1, 'pon', tiles=['5m', '5m'])
            else:
                g.do_action(w, 'pass')
        g.do_action(1, 'discard', tile='9m', tsumogiri=False)
        pass_all()
        g.do_action(2, 'discard', tile='1z', tsumogiri=True)
        pass_all()
        g.do_action(3, 'discard', tile='2z', tsumogiri=True)
        pass_all()
        # 座位 0 摸 3z，立直打 3z（清除此前若有的同巡振听，此时立直+一发有效）
        g.do_action(0, 'riichi', tile='3z', tsumogiri=True)
        pass_all()
        # 座位 1 摸第 4 张 5m（红五 0m），加杠 5m
        st1 = g.to_api_state(viewer=1)
        self.assertIn('kakan', [a['type'] for a in st1['legal_actions']])
        g.do_action(1, 'kakan', tile='5m')
        # 此时应暂停等待座位 0 抢杠荣和！
        st0 = g.to_api_state(viewer=0)
        self.assertEqual(st0['phase'], 'playing')
        self.assertEqual(st0['waiting_for'], [0])
        self.assertIn('ron', [a['type'] for a in st0['legal_actions']])
        g.do_action(0, 'ron')
        st_end = g.to_api_state(viewer=0)
        self.assertEqual(check_state_schema(st_end), [])
        yaku_names = [y['name'] for y in st_end['result']['wins'][0]['yaku']]
        self.assertIn('立直', yaku_names)
        self.assertIn('一发', yaku_names)
        self.assertIn('抢杠', yaku_names)
        self.assertIn('赤宝牌', yaku_names)

    def test_four_kans_abortive_draw(self):
        # 座位 0 暗杠 2 次，座位 1 暗杠 2 次 -> 第 4 次杠摸岭上牌并打牌且无人荣和 -> 四杠散了！
        s0 = ['1m', '1m', '1m', '1m', '2m', '2m', '2m', '2m', '5p', '6p', '7p', '8s', '9s']
        s1 = ['1p', '1p', '1p', '1p', '2p', '2p', '2p', '2p', '5s', '6s', '7s', '8m', '9m']
        wall = build_wall(
            {0: s0, 1: s1},
            draws=['1z', '2z'],
            rinshans=['3z', '4z', '5z', '6z'],
            dora_inds=['7z', '9p', '9s', '8p', '8s'],
        )
        g = game.Game(human_seats=[0, 1, 2, 3], wall=wall)
        g.do_action(0, 'ankan', tile='1m')
        g.do_action(0, 'ankan', tile='2m')
        g.do_action(0, 'discard', tile='4z', tsumogiri=True)
        g.do_action(1, 'ankan', tile='1p')
        g.do_action(1, 'ankan', tile='2p')
        # 杠满 4 次时还没流局，座位 1 仍可打牌（也可岭上开花）
        self.assertEqual(g.phase, 'discard')
        g.do_action(1, 'discard', tile='6z', tsumogiri=True)
        st = g.to_api_state(viewer=0)
        self.assertEqual(check_state_schema(st), [])
        self.assertEqual(st['phase'], 'round_end')
        self.assertEqual(st['result']['type'], 'ryuukyoku')
        self.assertEqual(st['result']['reason'], 'four_kans')

    def test_visible_not_double_counted_and_red_five_pon_options(self):
        # 座位 1 手里有 0m, 5m, 5m，座位 0 打 5m -> 碰应给两个选项 ['0m','5m'] 与 ['5m','5m']
        # 碰完后，get_visible 不得重复统计被鸣走的 5m 和自己的副露
        s0 = ['5m', '1p', '2p', '3p', '4p', '5p', '6p', '7p', '8p', '9p', '1s', '2s', '3s']
        s1 = ['0m', '5m', '5m', '2s', '3s', '4s', '5s', '6s', '7s', '8s', '9s', '7z', '7z']
        wall = build_wall({0: s0, 1: s1}, draws=['1z'], dora_inds=['2z'])
        g = game.Game(human_seats=[0, 1, 2, 3], wall=wall)
        g.do_action(0, 'discard', tile='5m', tsumogiri=False)
        st1 = g.to_api_state(viewer=1)
        pon_act = [a for a in st1['legal_actions'] if a['type'] == 'pon'][0]
        self.assertEqual(len(pon_act['options']), 2)
        self.assertIn(['0m', '5m'], pon_act['options'])
        self.assertIn(['5m', '5m'], pon_act['options'])
        g.do_action(1, 'pon', tiles=['0m', '5m'])
        for w in list(g.waiting_for()):
            if g.phase == 'call':
                g.do_action(w, 'pass')
        # 此时所有 5m（0m, 5m, 5m 在副露；5m 在座位 1 手里）共 4 张
        # 座位 0 看来：河里 5m 已 called，副露里 3 张 5m -> visible 含 3 张 5m（绝不是 4 张！）
        self.assertEqual(g.get_visible(0).count('5m'), 3)
        # 座位 1 看来：自己副露不放进 visible，河里 5m 已 called -> visible 含 0 张 5m
        self.assertEqual(g.get_visible(1).count('5m'), 0)

    def test_temp_furiten_on_no_yaku_wait(self):
        # 座位 1 门清 23m 444p 234s 567s 88p，听 1m（无役：有刻子不算平和、含 1m 不算断幺）和 4m（断幺九 1 番）！
        # 座位 2 打 1m（座位 1 无役不能荣和，但触发同巡振听！）-> 同巡座位 3 打 4m，座位 1 不能荣和！
        # 下一巡座位 1 自己摸打后，同巡振听解除 -> 再打 4m 可以荣和！
        s1 = ['2m', '3m', '4p', '4p', '4p', '2s', '3s', '4s', '5s', '6s', '7s', '8p', '8p']
        s0 = ['9m', '9m', '1z', '1z', '2z', '2z', '3z', '3z', '4z', '4z', '5z', '5z', '6z']
        s2 = ['1m', '9p', '9p', '1z', '2z', '3z', '4z', '5z', '6z', '7z', '7z', '9s', '9s']
        s3 = ['4m', '4m', '9p', '9p', '1p', '1p', '1s', '1s', '9m', '9m', '7z', '7z', '6z']
        wall = build_wall(
            {0: s0, 1: s1, 2: s2, 3: s3},
            draws=['6z', '9s', '1p', '1s', '1z', '2z', '3z', '4m'],
        )
        g = game.Game(human_seats=[0, 1, 2, 3], wall=wall)

        def pass_all():
            while g.phase == 'call':
                for w in list(g.waiting_for()):
                    g.do_action(w, 'pass')

        # 0 打 6z，1 摸 9s 打 9s，2 打 1m（座位 1 听 1m/4m，1m 没役但触发同巡振听！）
        g.do_action(0, 'discard', tile='6z', tsumogiri=True)
        pass_all()
        g.do_action(1, 'discard', tile='9s', tsumogiri=True)
        pass_all()
        g.do_action(2, 'discard', tile='1m', tsumogiri=False)
        pass_all()
        self.assertTrue(g.temp_furiten[1])
        # 同巡座位 3 打 4m：尽管 4m 有断幺九役，但因同巡振听，座位 1 不可荣和！
        g.do_action(3, 'discard', tile='4m', tsumogiri=False)
        self.assertNotIn('ron', [a['type'] for a in g.to_api_state(viewer=1)['legal_actions']])
        pass_all()
        # 0 打 1z，1 摸 2z 打 2z -> 解除同巡振听！
        g.do_action(0, 'discard', tile='1z', tsumogiri=True)
        pass_all()
        g.do_action(1, 'discard', tile='2z', tsumogiri=True)
        pass_all()
        self.assertFalse(g.temp_furiten[1])
        # 2 打 3z，3 摸 4m 打 4m -> 座位 1 现在可以荣和 4m！
        g.do_action(2, 'discard', tile='3z', tsumogiri=True)
        pass_all()
        g.do_action(3, 'discard', tile='4m', tsumogiri=True)
        self.assertIn('ron', [a['type'] for a in g.to_api_state(viewer=1)['legal_actions']])

    def test_kokushi_chankan_on_ankan(self):
        # 座位 1 听国士无双单听 7z；座位 0 暗杠 7z -> 座位 1 可以抢暗杠荣和！
        s0 = ['7z', '7z', '7z', '1m', '2m', '3m', '4p', '5p', '6p', '2s', '3s', '4s', '5s']
        s1 = ['1m', '1m', '9m', '1p', '9p', '1s', '9s', '1z', '2z', '3z', '4z', '5z', '6z']
        wall = build_wall({0: s0, 1: s1}, draws=['7z'])
        g = game.Game(human_seats=[0, 1, 2, 3], wall=wall)
        g.do_action(0, 'ankan', tile='7z')
        st1 = g.to_api_state(viewer=1)
        self.assertEqual(st1['waiting_for'], [1])
        self.assertIn('ron', [a['type'] for a in st1['legal_actions']])
        g.do_action(1, 'ron')
        st_end = g.to_api_state(viewer=1)
        self.assertEqual(st_end['result']['wins'][0]['yakuman'], 1)
        self.assertEqual(st_end['result']['wins'][0]['yaku'], [{'name': '国士无双', 'han': 13}])

    def test_minkan_dora_flips_on_discard(self):
        # 座位 1 大明杠 7z：摸岭上牌时尚未翻开第 2 张宝牌指示牌；打牌后才翻开！
        s0 = ['7z', '1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p']
        s1 = ['7z', '7z', '7z', '4p', '5p', '6p', '7p', '8p', '9p', '1s', '2s', '3s', '9s']
        wall = build_wall(
            {0: s0, 1: s1},
            draws=['1z'],
            dora_inds=['2z', '3z'],
            rinshans=['4z'],
        )
        g = game.Game(human_seats=[0, 1, 2, 3], wall=wall)
        g.do_action(0, 'discard', tile='7z', tsumogiri=False)
        g.do_action(1, 'minkan')
        # 岭上摸牌后：大明杠宝牌指示牌尚未翻开（仍只有 1 张）
        self.assertEqual(g.dora_indicators(), ['2z'])
        self.assertEqual(g.drawn, '4z')
        # 打出岭上牌后：新宝牌指示牌 3z 翻开！
        g.do_action(1, 'discard', tile='4z', tsumogiri=True)
        self.assertEqual(g.dora_indicators(), ['2z', '3z'])
        self.assertTrue(any(e['type'] == 'dora' and e['tile'] == '3z' for e in g.events))

    def test_four_human_simultaneous_call_priority(self):
        # 座位 0 打 5s：座位 1 可吃，座位 2 可碰 -> 两人都需回复，waiting_for 逐步减少，最终碰优先于吃！
        s0 = ['5s', '1m', '1m', '2m', '2m', '3m', '3m', '4m', '4m', '6m', '6m', '7m', '7m']
        s1 = ['4s', '6s', '1p', '1p', '2p', '2p', '3p', '3p', '8m', '8m', '9m', '9m', '1z']
        s2 = ['5s', '5s', '4p', '4p', '5p', '5p', '6p', '6p', '7p', '7p', '8p', '8p', '2z']
        s3 = ['9p', '9p', '1s', '1s', '2s', '2s', '8s', '8s', '9s', '9s', '3z', '3z', '4z']
        wall = build_wall({0: s0, 1: s1, 2: s2, 3: s3}, draws=['7z'])
        g = game.Game(human_seats=[0, 1, 2, 3], wall=wall)
        g.do_action(0, 'discard', tile='5s', tsumogiri=False)
        self.assertEqual(g.waiting_for(), [1, 2])
        # 座位 1 先选吃 -> 尚未结算，waiting_for 只剩 [2]
        g.do_action(1, 'chi', tiles=['4s', '6s'])
        self.assertEqual(g.phase, 'call')
        self.assertEqual(g.waiting_for(), [2])
        # 座位 2 选碰 -> 碰优先于吃！轮到座位 2 出牌
        g.do_action(2, 'pon', tiles=['5s', '5s'])
        self.assertEqual(g.phase, 'discard')
        self.assertEqual(g.current, 2)
        self.assertEqual(g.melds[2][0]['type'], 'pon')
        self.assertEqual(g.melds[2][0]['called_tile'], '5s')

    def test_kuikae_blocks_all_kuikae_call(self):
        # 座位 1 吃 3m 后手里只剩 3m 和 6m（全在食替范围内），因此不允许用 4m 5m 吃 3m！
        s0 = ['3m', '1p', '1p', '2p', '2p', '3p', '3p', '4p', '4p', '5p', '5p', '6p', '6p']
        s1 = ['3m', '4m', '5m', '6m', '1z', '1z', '1z', '2z', '2z', '2z', '3z', '3z', '3z']
        wall = build_wall({0: s0, 1: s1}, draws=['7z'])
        g = game.Game(human_seats=[0, 1, 2, 3], wall=wall)
        # 人为让座位 1 已经有 3 组副露，手里只剩 ['3m', '4m', '5m', '6m']
        g.hands[1] = ['3m', '4m', '5m', '6m']
        g.melds[1] = [
            {'type': 'pon', 'tiles': ['1z', '1z', '1z'], 'from': 0, 'called_tile': '1z'},
            {'type': 'pon', 'tiles': ['2z', '2z', '2z'], 'from': 2, 'called_tile': '2z'},
            {'type': 'pon', 'tiles': ['3z', '3z', '3z'], 'from': 3, 'called_tile': '3z'},
        ]
        g.do_action(0, 'discard', tile='3m', tsumogiri=False)
        acts1 = g.to_api_state(viewer=1)['legal_actions']
        self.assertNotIn('chi', [a['type'] for a in acts1])

    def test_riichi_declaration_ron_and_all_last_tie(self):
        # 验证 All Last 同分：座位 0 和座位 3 同为 32000 分时，座位 0 为起家 1 位，座位 3 连庄和了不触发和了止め
        g = game.Game(human_seats=[0], seed=1, length='tonpuu')
        g.kyoku = 3  # 东 4 局，dealer = 3
        g.scores = [32000, 18000, 18000, 32000]
        self.assertFalse(g._check_game_over(renchan=True, is_win=True))
        # 若座位 3 严格领先（32100），则触发和了止め
        g.scores = [31900, 18000, 18000, 32100]
        self.assertTrue(g._check_game_over(renchan=True, is_win=True))

    def test_legacy_module_apis(self):
        # 确认各模块原函数签名仍然兼容可用
        h14 = ['1m', '2m', '3m', '4p', '0p', '6p', '7s', '8s', '9s', '2s', '3s', '4s', '5m', '5m']
        self.assertTrue(tenpai.can_hu(h14, []))
        self.assertEqual(fu.calc_fu(h14, [], '4s', True, '1z', '2z'), 20)
        names, han = yaku.calc_yaku(h14, [], '4s', True, '1z', '2z', ['5m'], {})
        self.assertIn('平和', names)
        self.assertIn('门前清自摸和', names)
        self.assertEqual(han, 5)  # 门清自摸1 + 平和1 + 宝牌2(5m*2) + 赤宝牌1(0p)
        sc = score.calc_score(30, 2, False, False, 0, 0)
        self.assertEqual(sc['ron_pay'], 2000)
        self.assertEqual(sc['base_points'], 2000)

    def test_riichi_ankan_structure_check(self):
        # 立直后 111222333m 56p 99s 摸第 4 张 2m：虽然听牌仍是 4p/7p，但杠 2m 会破坏 123m x 3 面子构成，禁止暗杠！
        s0 = ['1m', '1m', '1m', '2m', '2m', '2m', '3m', '3m', '3m', '5p', '6p', '9s', '9s']
        wall = build_wall({0: s0}, draws=['1z', '2z', '3z', '4z', '2m'])
        g = game.Game(human_seats=[0, 1, 2, 3], wall=wall)
        g.do_action(0, 'riichi', tile='1z', tsumogiri=True)
        g.do_action(1, 'discard', tile='2z', tsumogiri=True)
        g.do_action(2, 'discard', tile='3z', tsumogiri=True)
        g.do_action(3, 'discard', tile='4z', tsumogiri=True)
        st0 = g.to_api_state(viewer=0)
        self.assertEqual(st0['drawn'], '2m')
        self.assertNotIn('ankan', [a['type'] for a in st0['legal_actions']])

    def test_aka_dora_false_no_red_fives(self):
        g = game.Game(human_seats=[0], seed=42, rules={'aka_dora': False})
        st = g.to_api_state(viewer=0)
        self.assertEqual(check_state_schema(st), [])
        self.assertEqual(st['rules']['aka_dora'], False)
        self.assertFalse(any(t[0] == '0' for t in g.wall))

    def test_hanchan_length_and_random_simulations(self):
        # 跑 30 局全电脑（东风+半庄+不同规则）+ 20 局含人类随机合法操作，校验点数守恒和接口格式
        configs = [
            ('tonpuu', {'aka_dora': True, 'kuitan': True, 'kiriage_mangan': False, 'renpu_fu': 4}),
            ('hanchan', {'aka_dora': False, 'kuitan': False, 'kiriage_mangan': True, 'renpu_fu': 2}),
        ]
        for idx, (length, rules) in enumerate(configs):
            for seed in range(15):
                g = game.Game(human_seats=[], seed=seed + idx * 100, length=length, rules=rules)
                while not g.game_over:
                    st = g.to_api_state(viewer=0)
                    self.assertEqual(check_state_schema(st), [])
                    self.assertEqual(sum(g.scores) + g.kyotaku * 1000, 100000)
                    g.next_round()
                st_fin = g.to_api_state(viewer=0)
                self.assertEqual(check_state_schema(st_fin), [])
                self.assertEqual(st_fin['phase'], 'game_end')
                self.assertEqual(sum(g.scores), 100000)

        # 人类随机操作（覆盖吃碰杠立直自摸荣和）
        for seed in range(15):
            rng = random.Random(seed)
            g = game.Game(human_seats=[0], seed=500 + seed, length='tonpuu')
            while not g.game_over:
                st = g.to_api_state(viewer=0)
                self.assertEqual(check_state_schema(st), [])
                if st['phase'] == 'round_end':
                    g.next_round()
                    continue
                acts = st['legal_actions']
                self.assertTrue(acts)
                by_type = {a['type']: a for a in acts}
                if 'tsumo' in by_type:
                    g.do_action(0, 'tsumo')
                elif 'ron' in by_type:
                    g.do_action(0, 'ron')
                elif 'riichi' in by_type:
                    g.do_action(0, 'riichi', tile=by_type['riichi']['tiles'][0])
                elif 'ankan' in by_type and rng.random() < 0.5:
                    g.do_action(0, 'ankan', tile=by_type['ankan']['tiles'][0])
                elif 'kakan' in by_type and rng.random() < 0.5:
                    g.do_action(0, 'kakan', tile=by_type['kakan']['tiles'][0])
                elif 'minkan' in by_type and rng.random() < 0.3:
                    g.do_action(0, 'minkan')
                elif 'pon' in by_type and rng.random() < 0.4:
                    g.do_action(0, 'pon', tiles=rng.choice(by_type['pon']['options']))
                elif 'chi' in by_type and rng.random() < 0.3:
                    g.do_action(0, 'chi', tiles=rng.choice(by_type['chi']['options']))
                elif 'discard' in by_type:
                    g.do_action(0, 'discard', tile=rng.choice(by_type['discard']['tiles']))
                else:
                    g.do_action(0, 'pass')
            self.assertEqual(sum(g.scores), 100000)


class TestHTTPServer(unittest.TestCase):
    """通过真实 HTTP 报文测试 MahjongHandler 全部接口，并验证 CLI --port 启动。"""

    def _raw_http(self, method, path, body=None):
        import http.client
        import socket

        c_sock, s_sock = socket.socketpair()
        payload = json.dumps(body).encode('utf-8') if body is not None else b''
        req_lines = [
            f'{method} {path} HTTP/1.1',
            'Host: 127.0.0.1:8000',
            f'Content-Length: {len(payload)}',
        ]
        if body is not None:
            req_lines.append('Content-Type: application/json')
        req_bytes = ('\r\n'.join(req_lines) + '\r\n\r\n').encode('utf-8') + payload

        class _DummyServer:
            server_name = '127.0.0.1'
            server_port = 8000

        def _serve():
            try:
                server.MahjongHandler(s_sock, ('127.0.0.1', 0), _DummyServer())
            finally:
                s_sock.close()

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        try:
            c_sock.sendall(req_bytes)
            c_sock.shutdown(socket.SHUT_WR)
            resp = http.client.HTTPResponse(c_sock)
            resp.begin()
            data = resp.read().decode('utf-8')
            status = resp.status
            headers = dict(resp.getheaders())
            resp.close()
        finally:
            c_sock.close()
            t.join(timeout=5)
        return status, data, headers

    def test_cli_startup_with_port(self):
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, 'server.py'), '--port', '18766'],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            line = proc.stdout.readline()
            self.assertIn('127.0.0.1:18766', line)
            self.assertIsNone(proc.poll())
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            proc.stdout.close()
            proc.stderr.close()

    def test_index_and_cors(self):
        status, body, headers = self._raw_http('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('麻将牌桌', body)
        self.assertIn('opt-aka-dora', body)
        self.assertEqual(headers.get('Access-Control-Allow-Origin'), '*')

        status, _, headers = self._raw_http('OPTIONS', '/api/new_game')
        self.assertEqual(status, 204)
        self.assertEqual(headers.get('Access-Control-Allow-Origin'), '*')

    def test_full_api_lifecycle_and_errors(self):
        # 1. 新游戏（指定规则开关与种子）
        st_code, text, _ = self._raw_http('POST', '/api/new_game', {
            'players': ['human', 'bot', 'bot', 'bot'],
            'length': 'hanchan',
            'seed': 123,
            'rules': {'aka_dora': False, 'kuitan': False, 'kiriage_mangan': True, 'renpu_fu': 2},
        })
        self.assertEqual(st_code, 200)
        st = json.loads(text)
        self.assertEqual(check_state_schema(st), [])
        self.assertEqual(st['rules'], {
            'aka_dora': False, 'kuitan': False, 'kiriage_mangan': True, 'renpu_fu': 2,
        })
        gid = st['game_id']

        # 2. GET /api/state
        st_code, text, _ = self._raw_http('GET', f'/api/state?game_id={gid}&seat=0')
        self.assertEqual(st_code, 200)
        self.assertEqual(check_state_schema(json.loads(text)), [])

        # 3. 非法操作应返回 400 + {"error": ...}
        st_code, text, _ = self._raw_http('POST', '/api/action', {
            'game_id': gid, 'seat': 1, 'type': 'discard', 'tile': '1m',
        })
        self.assertEqual(st_code, 400)
        self.assertIn('error', json.loads(text))

        st_code, text, _ = self._raw_http('POST', '/api/action', {
            'game_id': 'no_such_game', 'seat': 0, 'type': 'pass',
        })
        self.assertEqual(st_code, 400)
        self.assertIn('error', json.loads(text))

        # 4. 合法出牌（摸切）
        drawn = st['drawn']
        st_code, text, _ = self._raw_http('POST', '/api/action', {
            'game_id': gid, 'seat': 0, 'type': 'discard', 'tile': drawn, 'tsumogiri': True,
        })
        self.assertEqual(st_code, 200)
        st2 = json.loads(text)
        self.assertEqual(check_state_schema(st2), [])
        self.assertTrue(st2['players'][0]['discards'][0]['tsumogiri'])

        # 5. 连续开新局拿到不同 game_id，且支持 4 bot 自动打完一局并 /api/next
        st_code, text, _ = self._raw_http('POST', '/api/new_game', {
            'players': ['bot', 'bot', 'bot', 'bot'],
            'length': 'tonpuu',
            'seed': 7,
        })
        self.assertEqual(st_code, 200)
        st3 = json.loads(text)
        self.assertNotEqual(st3['game_id'], gid)
        self.assertEqual(check_state_schema(st3), [])
        self.assertIn(st3['phase'], ('round_end', 'game_end'))
        if st3['phase'] == 'round_end':
            st_code, text, _ = self._raw_http('POST', '/api/next', {
                'game_id': st3['game_id'], 'seat': 0,
            })
            self.assertEqual(st_code, 200)
            self.assertEqual(check_state_schema(json.loads(text)), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
