# 后端回归测试：python3 tests/test_backend.py   （不用起服务器，直接调 server.py 里的函数）
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import game    # noqa: E402
import server  # noqa: E402
from yaku import calc_yaku  # noqa: E402
from score import calc_score  # noqa: E402


def build_wall(hands, draws, aka=False):
    """hands：座位 0~3 的配牌；draws：从 wall[52] 开始依次摸的牌；剩下的随便填"""
    w = game.make_wall(aka)
    out = []
    for t in [t for h in hands for t in h] + list(draws):
        w.remove(t)
        out.append(t)
    return out + w


def test_wall_order():
    w = game.make_wall()
    random.Random(3).shuffle(w)
    g = game.Game(human_seats=[0, 1, 2, 3], wall=w)
    for s in (1, 2, 3):   # 配牌按物理座位，不管谁是庄家
        assert sorted(w[13 * s:13 * s + 13], key=game.tile_key) == g.hands[s]
    assert g.drawn == w[52] and g.dora_indicators() == [w[122]]


def test_riichi_ankan_tsumo():
    h0 = ['9m', '9m', '9m', '2m', '3m', '4m', '4p', '6p', '6s', '7s', '8s', '5m', '5m']
    others = [['1m', '1m', '9p', '9p', '3z', '3z', '4z', '4z', '2p', '8p', '1s', '9s', '2z'],
              ['7m', '7m', '1p', '1p', '6z', '6z', '5z', '5z', '3p', '3p', '2s', '2s', '7z'],
              ['8m', '8m', '7p', '7p', '1p', '6m', '9s', '9s', '4s', '4s', '6m', '1z', '7z']]
    draws = ['3p', '1z', '8m', '5s', '9m', '2z', '4m', '4s', '5p']
    g = game.Game(human_seats=[0], wall=build_wall([h0] + others, draws))
    g.do_action(0, 'riichi', tile='3p', tsumogiri=True)
    assert g.riichi[0] and g.phase == 'discard' and g.drawn == '9m'
    g.do_action(0, 'ankan', tile='9m')
    g.do_action(0, 'discard', tile=g.drawn, tsumogiri=True)
    assert g.drawn == '5p'
    st = server.build_state('x', g, 0)
    assert any(a['type'] == 'tsumo' for a in st['legal_actions']), st['legal_actions']
    g.do_action(0, 'tsumo')
    names = [y['name'] for y in server.build_state('x', g, 0)['result']['wins'][0]['yaku']]
    assert '两立直' in names and '门前清自摸和' in names, names


def test_chankan():
    h0 = ['1m', '1m', '1m', '9m', '9m', '9m', '1s', '1s', '1s', '9s', '9s', '2z', '3z']
    h1 = ['7p', '7p', '2m', '2m', '4z', '4z', '4z', '6z', '6z', '8s', '8s', '5z', '5z']
    h2 = ['2s', '3s', '4s', '5p', '6p', '3m', '4m', '5m', '6m', '7m', '8m', '9p', '9p']
    h3 = ['1p', '1p', '2p', '2p', '3p', '3p', '4p', '4p', '8p', '8p', '6s', '7s', '8s']
    g = game.Game(human_seats=[0, 1, 2, 3], wall=build_wall([h0, h1, h2, h3], ['7p', '3z', '1z', '1z', '7p']))
    g.do_action(0, 'discard', tile='7p')
    g.do_action(1, 'pon', tiles=['7p', '7p'])
    g.do_action(2, 'pass')
    g.do_action(1, 'discard', tile='5z')

    def pass_all():
        while g.phase == 'call':
            for s in list(g.call_options):
                if s not in g.responses:
                    g.do_action(s, 'pass')
    pass_all()
    while g.current != 1:
        g.do_action(g.current, 'discard', tile=g.drawn)
        pass_all()
    g.do_action(1, 'kakan', tile='7p')
    g.do_action(2, 'ron')
    w = g.result['wins'][0]
    assert ('抢杠', 1) in w['yaku'] and w['seat'] == 2


def test_score_rules():
    assert calc_score(30, 4, False, False, kiriage=True)['get'] == 8000
    assert calc_score(30, 4, False, False, kiriage=False)['get'] == 7700
    assert calc_score(40, 4, False, False, kiriage=False)['get'] == 8000
    assert calc_score(0, 26, False, False, yakuman=2)['get'] == 64000
    st = dict(riichi=True)
    hand = ['1s', '2s', '2s', '3p', '3p', '3s', '3s', '4s', '6p', '7p', '7s', '8p', '8s', '9s']
    assert '平和' in calc_yaku(hand, [], '2s', False, '1z', '2z', [], st)[0]
    # 食断开关
    open_tanyao = (['2m', '3m', '4m', '5p', '6p', '7p', '3s', '4s', '5s', '8s', '8s'], [['6m', '6m', '6m']])
    assert calc_yaku(*open_tanyao, '8s', False, '1z', '2z', [], {'kuitan': True})[1] == 1
    assert calc_yaku(*open_tanyao, '8s', False, '1z', '2z', [], {'kuitan': False})[1] == 0


def test_random_games():
    for seed in range(6):
        rng = random.Random(seed)
        st = server.api_new_game({'players': ['human'] * 4, 'seed': seed,
                                  'rules': {'aka_dora': seed % 2 == 0, 'renpu_fu': 2}})
        gid = st['game_id']
        for _ in range(4000):
            if st['phase'] == 'game_end':
                break
            if st['phase'] == 'round_end':
                st = server.api_next({'game_id': gid, 'seat': 0})
                continue
            seat = st['waiting_for'][0]
            st = server.api_state({'game_id': [gid], 'seat': [str(seat)]})
            la = {a['type']: a for a in st['legal_actions']}
            if 'tsumo' in la or 'ron' in la:
                body = {'type': 'tsumo' if 'tsumo' in la else 'ron'}
            elif 'pon' in la and rng.random() < 0.5:
                body = {'type': 'pon', 'tiles': la['pon']['options'][0]}
            elif 'chi' in la and rng.random() < 0.5:
                body = {'type': 'chi', 'tiles': la['chi']['options'][0]}
            elif 'riichi' in la:
                t = la['riichi']['tiles'][0]
                body = {'type': 'riichi', 'tile': t, 'tsumogiri': t == st['drawn']}
            elif 'discard' in la:
                t = rng.choice(la['discard']['tiles'])
                body = {'type': 'discard', 'tile': t, 'tsumogiri': t == st['drawn'] and t not in st['players'][seat]['hand']}
            else:
                body = {'type': 'pass'}
            body.update(game_id=gid, seat=seat)
            st = server.api_action(body)
            if st['result'] and st['result']['type'] == 'agari':
                for w in st['result']['wins']:
                    assert w['han'] == sum(y['han'] for y in w['yaku'])
        total = sum(p['score'] for p in st['players']) + st['round']['riichi_sticks'] * 1000
        assert total == 100000, total


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
