# 回归测试：python3 tests/test_mahjong.py （在 claude-opus-5-5 目录下运行）
# 覆盖拼代码时找到的 bug，以及整场自动对局的点数守恒、接口格式。

import json
import os
import random
import sys
import threading
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import fu      # noqa: E402
import game    # noqa: E402
import score   # noqa: E402
import server  # noqa: E402
import yaku    # noqa: E402

FAILS = []


def check(name, cond, detail=''):
    if cond:
        print('  ok  ', name)
    else:
        print('  FAIL', name, detail)
        FAILS.append(name)


def build_wall(hands, draws, dora_ind=None):
    """hands: 4 个座位的 13 张；draws: 从 wall[52] 开始依次摸的牌；其余随机补齐"""
    rest = game.make_wall()
    for t in sum(hands, []) + draws + ([dora_ind] if dora_ind else []):
        rest.remove(t)
    random.Random(7).shuffle(rest)
    wall = sum(hands, []) + draws
    need = 122 - len(wall)
    wall += rest[:need]
    rest = rest[need:]
    if dora_ind:
        wall += [dora_ind] + rest
    else:
        wall += rest
    assert len(wall) == 136
    return wall


def test_units():
    print('单元测试')
    # 260331：同一手牌算番按平和，算符也要按平和 30 符（原来取符最大给了 40 符）
    hand = ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '3s', '4s', '5s', '5s', '5s']
    names, han = yaku.calc_yaku(hand, [], '5s', False, '1z', '2z', [], {'riichi': True})
    check('34555s 和 5s 有平和', '平和' in names, names)
    check('原来的取最大符是 40', fu.calc_fu(hand, [], '5s', False, '1z', '2z') == 40)
    check('平和时符数 30', fu.calc_fu(hand, [], '5s', False, '1z', '2z', is_pinfu=True) == 30)
    # 连风牌开关
    h = ['2m', '2m', '2m', '4p', '5p', '6p', '6s', '7s', '8s', '2s', '3s', '4s', '1z', '1z']
    check('连风 4 符 -> 40', fu.calc_fu(h, [], '1z', False, '1z', '1z', renpu_fu=4) == 40)
    check('连风 2 符 -> 40(38)', fu.calc_fu(h, [], '1z', False, '1z', '1z', renpu_fu=2) == 40)
    h2 = ['2m', '3m', '4m', '4p', '5p', '6p', '6s', '7s', '8s', '2s', '3s', '4s', '1z', '1z']
    check('连风单骑 4 符：20+10+2+4=36->40', fu.calc_fu(h2, [], '1z', False, '1z', '1z', renpu_fu=4) == 40)
    check('连风单骑 2 符：20+10+2+2=34->40', fu.calc_fu(h2, [], '1z', False, '1z', '1z', renpu_fu=2) == 40)
    h3 = ['2m', '3m', '4m', '4p', '5p', '6p', '6s', '7s', '8s', '2s', '3s', '1z', '1z', '4s']
    check('连风雀头两面自摸 4 符：20+2+4=26->30', fu.calc_fu(h3, [], '4s', True, '1z', '1z', renpu_fu=4) == 30)

    # 260409：切上满贯开关、多倍役满
    check('无切上 子 4番30符 7700', score.calc_score(30, 4, False, False)['get'] == 7700)
    check('有切上 子 4番30符 8000', score.calc_score(30, 4, False, False, kiriage=True)['get'] == 8000)
    check('无切上 庄 3番60符 11600', score.calc_score(60, 3, True, False)['get'] == 11600)
    check('4番40符 满贯 8000', score.calc_score(40, 4, False, False)['get'] == 8000)
    check('双倍役满 子荣和 64000', score.calc_score(0, 26, False, False, yakuman=2)['get'] == 64000)
    check('累计役满 13番 子荣和 32000', score.calc_score(40, 13, False, False)['get'] == 32000)
    r = score.calc_score(30, 1, False, True, 2, 1)
    check('本场供托 子自摸 1番30符 2本场1供托', (r['ko_pay'], r['oya_pay'], r['get']) == (500, 700, 2700), r)

    # 250118：逐项番数、食断开关、役满倍数
    open_hand = ['2m', '3m', '4m', '5p', '5p', '6s', '7s', '8s', '3p', '4p', '5p']
    pairs, ym = yaku.calc_yaku_detail(open_hand, [['2s', '3s', '4s']], '5p', False, '1z', '2z', [], {'kuitan': True})
    check('食断有：副露断幺 1 番', pairs == [('断幺九', 1)], pairs)
    pairs, ym = yaku.calc_yaku_detail(open_hand, [['2s', '3s', '4s']], '5p', False, '1z', '2z', [], {'kuitan': False})
    check('食断没有：0 番', pairs == [], pairs)
    big4 = ['1z', '1z', '1z', '2z', '2z', '2z', '3z', '3z', '3z', '4z', '4z', '4z', '5m', '5m']
    pairs, ym = yaku.calc_yaku_detail(big4, [], '5m', True, '1z', '1z', [], {})
    check('大四喜(+字一色?) 役满倍数', ym >= 2 and sum(h for _, h in pairs) == 13 * ym, (pairs, ym))
    st = {'riichi': True, 'ura_dora': ['5z']}
    rh = ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '2s', '3s', '4s', '5z', '5z']
    pairs, _ = yaku.calc_yaku_detail(rh, [], '4s', False, '1z', '2z', [], st)
    check('里宝牌单独列出', ('里宝牌', 2) in pairs, pairs)


def test_wall_layout():
    print('牌山顺序（接口说明）')
    w = game.make_wall()
    random.Random(3).shuffle(w)
    g = game.Game(human_seats=[0, 1, 2, 3], wall=w)
    for k in range(4):
        exp = sorted(w[13 * k:13 * k + 13], key=game.tile_key)
        got = sorted(g.hands[k], key=game.tile_key)
        if k == 0:
            got.remove(g.drawn)
        check('座位 %d 配牌 = wall[%d:%d]' % (k, 13 * k, 13 * k + 13), got == exp)
    check('庄家先摸 wall[52]', g.drawn == w[52])
    check('宝牌指示牌 = wall[122]', g.dora_indicators() == [w[122]])
    check('里宝指示牌 = wall[127]', g.ura_indicators() == [w[127]])
    check('余 70 张', g.remaining() == 69)   # 庄家已经摸了 1 张


def test_ankan_riichi_and_chiihou():
    print('暗杠 + 立直、地和')
    # 座位 0（庄）：立直后暗杠 1z 再自摸
    h0 = ['1z', '1z', '1z', '2m', '3m', '4m', '6p', '7p', '8p', '3s', '4s', '5s', '9p']
    other = [['1m', '1m', '9m', '9m', '1p', '1p', '9s', '9s', '2z', '3z', '4z', '5z', '6z'],
             ['2m', '2m', '8m', '8m', '2p', '2p', '8s', '8s', '3z', '4z', '5z', '6z', '7z'],
             ['3m', '3m', '7m', '7m', '3p', '3p', '7s', '7s', '2z', '4z', '6z', '7z', '1s']]
    draws = ['7z', '1m', '2m', '3m',     # 座位 0 摸 7z（打 7z 立直）, 1、2、3 摸了打
             '1z',                        # 座位 0 摸第 4 张东 -> 暗杠
             ]
    wall = build_wall([h0] + other, draws)
    # 岭上牌放 9p（单骑和）
    i = wall.index('9p', 122) if '9p' in wall[122:] else None
    rin = 132
    j = wall.index('9p', 52 + len(draws))
    wall[rin], wall[j] = wall[j], wall[rin]
    g = game.Game(human_seats=[0], wall=wall)
    acts = {a['type']: a for a in g.get_legal_actions(0)}
    check('能立直', 'riichi' in acts, acts.keys())
    g.do_action(0, 'riichi', tile='7z', tsumogiri=True)
    acts = {a['type']: a for a in g.get_legal_actions(0)}
    check('立直后摸到第 4 张东能暗杠', 'kan' in acts, list(acts))
    g.do_action(0, 'kan', tile='1z')
    acts = {a['type']: a for a in g.get_legal_actions(0)}
    check('岭上自摸能和（原来暗杠被当明杠会丢掉立直）', 'tsumo' in acts, list(acts))
    if 'tsumo' in acts:
        g.do_action(0, 'tsumo')
        names = [y['name'] for y in g.result['wins'][0]['yaku']]
        # 第一巡立直 -> 两立直
        check('有两立直、门清自摸、岭上开花', {'两立直', '门前清自摸和', '岭上开花'} <= set(names), names)
        w = g.result['wins'][0]
        # 20 + 32(东暗杠) + 2(单骑) + 2(自摸) + 4(连风雀头? 不是) -> 56 -> 60
        check('暗杠算 32 符 -> 60 符', w['fu'] == 60, w['fu'])
        check('han 等于各项之和', w['han'] == sum(y['han'] for y in w['yaku']))


def test_simulation():
    print('全电脑自动对局（点数守恒、不崩）')
    for length in ('tonpuu', 'hanchan'):
        for rules in ({}, {'aka_dora': False, 'kuitan': False, 'kiriage_mangan': True, 'renpu_fu': 2}):
            ok = True
            for seed in range(6):
                g = game.Game(human_seats=[], seed=seed, length=length, rules=rules)
                n = 1
                while not g.game_over:
                    if sum(g.scores) + g.kyotaku * 1000 != 100000:
                        ok = False
                    if not rules.get('aka_dora', True) and any(t[0] == '0' for t in g.wall):
                        ok = False
                    g.next_round()
                    n += 1
                if sum(g.scores) != 100000:
                    ok = False
            check('%s %s' % (length, rules or '默认规则'), ok)


def check_api_state(s):
    """照着 index.html 的 checkState 粗略检查一遍"""
    p = []
    for k in ('version', 'game_id', 'phase', 'round', 'dora_indicators', 'wall_left', 'viewer',
              'turn', 'waiting_for', 'rules', 'players', 'legal_actions', 'events'):
        if k not in s:
            p.append('缺 ' + k)
    for k in ('aka_dora', 'kuitan', 'kiriage_mangan', 'renpu_fu'):
        if k not in s.get('rules', {}):
            p.append('rules 缺 ' + k)
    for i, pl in enumerate(s['players']):
        for k in ('seat', 'name', 'score', 'seat_wind', 'riichi', 'discards', 'melds', 'hand_count'):
            if k not in pl:
                p.append('players[%d] 缺 %s' % (i, k))
        if (i == s['viewer']) != ('hand' in pl):
            p.append('players[%d] hand 不该给/该给' % i)
    if s['phase'] != 'playing':
        r = s['result']
        if not r or 'delta' not in r or len(r['delta']) != 4:
            p.append('result 不对')
        if r and r['type'] == 'agari':
            for w in r['wins']:
                if w['han'] != sum(y['han'] for y in w['yaku']):
                    p.append('han 不等于各役之和')
                if w['win_tile'] is None or len(w['hand']) + 3 * len(w['melds']) != 13:
                    p.append('结算手牌张数不对')
        elif r and r['type'] != 'ryuukyoku':
            p.append('result.type 不对')
    return p


def test_api_random_play():
    print('接口：人类随机操作（格式、合法性）')
    rng = random.Random(1)
    problems = []
    for seed in range(8):
        players = ['human', 'bot', 'bot', 'bot'] if seed % 2 == 0 else ['human'] * 4
        s = server.api_new_game({'players': players, 'seed': seed, 'length': 'tonpuu'})
        gid = s['game_id']
        steps = 0
        while s['phase'] != 'game_end' and steps < 3000:
            steps += 1
            problems += check_api_state(s)
            if s['phase'] == 'round_end':
                s = server.api_next({'game_id': gid, 'seat': 0})
                continue
            seat = s['waiting_for'][0]
            s = server.api_state({'game_id': [gid], 'seat': [str(seat)]})
            acts = {a['type']: a for a in s['legal_actions']}
            if not acts:
                problems.append('waiting_for 里的人没有操作')
                break
            body = {'game_id': gid, 'seat': seat}
            if 'tsumo' in acts:
                body['type'] = 'tsumo'
            elif 'ron' in acts:
                body['type'] = 'ron'
            elif 'riichi' in acts and rng.random() < 0.5:
                body.update(type='riichi', tile=acts['riichi']['tiles'][0], tsumogiri=False)
            elif 'ankan' in acts:
                body.update(type='ankan', tile=acts['ankan']['tiles'][0])
            elif 'pon' in acts and rng.random() < 0.5:
                body.update(type='pon', tiles=acts['pon']['options'][-1])
            elif 'chi' in acts and rng.random() < 0.3:
                body.update(type='chi', tiles=acts['chi']['options'][0])
            elif 'minkan' in acts and rng.random() < 0.5:
                body['type'] = 'minkan'
            elif 'discard' in acts:
                t = rng.choice(acts['discard']['tiles'])
                body.update(type='discard', tile=t, tsumogiri=(t == s['drawn']))
            else:
                body['type'] = 'pass'
            s = server.api_action(body)
        problems += check_api_state(s)
    check('随机对局 %d 场没有格式问题' % 8, not problems, problems[:5])
    # 错误情况要 400
    s = server.api_new_game({})
    try:
        server.api_action({'game_id': s['game_id'], 'seat': 1, 'type': 'discard', 'tile': '1m'})
        check('替电脑操作要报错', False)
    except server.ApiError:
        check('替电脑操作要报错', True)
    try:
        server.api_action({'game_id': s['game_id'], 'seat': 0, 'type': 'discard', 'tile': '9z'})
        check('打手里没有的牌要报错', False)
    except (ValueError, server.ApiError):
        check('打手里没有的牌要报错', True)
    try:
        server.api_new_game({'rules': {'renpu_fu': 3}})
        check('rules 值不对要报错', False)
    except ValueError:
        check('rules 值不对要报错', True)
    s = server.api_new_game({'rules': {'kuitan': False}})
    check('rules 回填默认值', s['rules'] == {'aka_dora': True, 'kuitan': False, 'kiriage_mangan': False, 'renpu_fu': 4},
          s['rules'])


def raw_http(request_bytes):
    """不监听端口，用 socketpair 直接把一个 HTTP 请求喂给 MahjongHandler"""
    import socket
    a, b = socket.socketpair()
    a.sendall(request_bytes)
    a.shutdown(socket.SHUT_WR)

    class FakeServer:
        pass

    def serve():
        try:
            server.MahjongHandler(b, ('127.0.0.1', 0), FakeServer())
        finally:
            try:
                b.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            b.close()
    th = threading.Thread(target=serve, daemon=True)
    th.start()
    a.settimeout(10)
    chunks = []
    while True:
        c = a.recv(65536)
        if not c:
            break
        chunks.append(c)
    th.join(5)
    a.close()
    data = b''.join(chunks)
    head, _, body = data.partition(b'\r\n\r\n')
    return int(head.split()[1]), body


def test_http_handler():
    print('HTTP 处理（socketpair，不占端口）')
    st, body = raw_http(b'GET / HTTP/1.0\r\n\r\n')
    check('GET / 200 返回页面', st == 200 and b'<html' in body)
    payload = json.dumps({'seed': 5, 'rules': {'aka_dora': False}}).encode()
    st, body = raw_http(b'POST /api/new_game HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: '
                        + str(len(payload)).encode() + b'\r\n\r\n' + payload)
    s = json.loads(body)
    check('POST /api/new_game', st == 200 and s['version'] == 1 and s['rules']['aka_dora'] is False)
    payload = json.dumps({'game_id': s['game_id'], 'seat': 0, 'type': 'pon'}).encode()
    st, body = raw_http(b'POST /api/action HTTP/1.0\r\nContent-Length: ' + str(len(payload)).encode()
                        + b'\r\n\r\n' + payload)
    check('不合法操作返回 400 + error', st == 400 and 'error' in json.loads(body))
    st, body = raw_http(b'OPTIONS /api/action HTTP/1.0\r\n\r\n')
    check('OPTIONS 预检 204', st == 204)
    st, body = raw_http(b'GET /api/state?game_id=nope&seat=0 HTTP/1.0\r\n\r\n')
    check('不存在的 game_id 返回 404', st == 404)


def test_http():
    print('HTTP 启动（--port，GET / 返回页面）')
    try:
        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.MahjongHandler)
    except OSError as e:
        print('  skip 本机不能监听端口：', e)
        return
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    base = 'http://127.0.0.1:%d' % port
    try:
        with urllib.request.urlopen(base + '/', timeout=5) as r:
            body = r.read()
            check('GET / 200 返回页面', r.status == 200 and b'<html' in body)
        req = urllib.request.Request(base + '/api/new_game', data=json.dumps({'seed': 1}).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=5) as r:
            s = json.loads(r.read())
            check('POST /api/new_game', s['version'] == 1 and s['phase'] == 'playing')
        req = urllib.request.Request(base + '/api/action', data=json.dumps(
            {'game_id': s['game_id'], 'seat': 0, 'type': 'pon'}).encode(), method='POST')
        try:
            urllib.request.urlopen(req, timeout=5)
            check('不合法操作返回 400', False)
        except urllib.error.HTTPError as e:
            check('不合法操作返回 400 + error', e.code == 400 and 'error' in json.loads(e.read()))
    finally:
        httpd.shutdown()


# ---------- 第二轮：同学们整理的 10 个问题，每个一条回归测试 ----------

JUNK = ['1m', '4m', '7m', '1p', '4p', '7p', '1s', '4s', '7s', '1z', '2z', '3z', '4z']   # 不听牌的 13 张


def fresh():
    """白盒测试用：四个人类座位，手牌全换成不听牌的 JUNK，宝牌指示牌换成白（宝牌是发，测试手牌里没有）"""
    g = game.Game(human_seats=[0, 1, 2, 3], seed=1)
    for s in range(4):
        g.hands[s] = list(JUNK)
    g.wall[122] = '5z'
    g.first_turn = [False] * 4
    g.no_call_yet = False
    return g


def turn(g, seat, hand, drawn):
    """直接摆成“轮到 seat 打牌，刚摸了 drawn”"""
    g.hands[seat] = list(hand) + [drawn]
    g.drawn = drawn
    g.current = seat
    g.phase = 'discard'
    g.after_call = False
    g.kuikae = []
    g.call_options = {}
    g.responses = {}


def chankan_table():
    g = fresh()
    g.melds[0] = [{'type': 'pon', 'tiles': ['5m', '5m', '5m'], 'from': 2, 'called_tile': '5m'}]
    turn(g, 0, ['1p', '2p', '3p', '7s', '8s', '9s', '1z', '1z', '2s', '3s'], '5m')
    g.hands[1] = ['4m', '6m', '2p', '3p', '4p', '6p', '7p', '8p', '3s', '4s', '5s', '6s', '6s']   # 嵌张听 5m，断幺
    return g


def test_round2():
    print('第二轮问题')
    # 1. 抢杠
    g = chankan_table()
    check('1 能加杠 5m', any(a.get('kind') == 'kakan' for a in g.get_legal_actions(0)))
    g.do_action(0, 'kan', tile='5m')
    check('1 加杠时听 5m 的人能抢杠', g.phase == 'call' and 1 in g.call_options, (g.phase, g.call_options))
    g.do_action(1, 'ron')
    names = [y['name'] for y in g.result['wins'][0]['yaku']] if g.result and g.result.get('wins') else []
    check('1 抢杠和了，役里有“抢杠”', '抢杠' in names, names)
    g = chankan_table()
    g.do_action(0, 'kan', tile='5m')
    g.do_action(1, 'pass')
    check('1 没人抢：加杠成立、摸岭上牌', g.melds[0][0]['type'] == 'kakan' and g.current == 0 and g.is_rinshan_draw)
    check('1 不抢杠的人同巡振听', g.temp_furiten[1])

    # 2. 摸到一样的牌，手牌顺序
    hands = [['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p'],
             ['1s', '2s', '3s', '4s', '5s', '6s', '7s', '8s', '9s', '1z', '2z', '3z', '4z'],
             ['5p', '6p', '7p', '8p', '9p', '5z', '6z', '7z', '1z', '2z', '3z', '4z', '9m'],
             ['1s', '2s', '3s', '4s', '5s', '6s', '7s', '8s', '9s', '5z', '6z', '7z', '9p']]
    s = server.api_new_game({'wall': build_wall(hands, ['2m'])})
    h = s['players'][0]['hand']
    check('2 摸到一样的牌，手牌还是排好序的', h == sorted(h, key=game.tile_key) and s['drawn'] == '2m', (h, s['drawn']))

    # 3. 一杯口 + 混全：番和符要用同一种拆法
    g = fresh()
    turn(g, 0, JUNK, '3m')
    g.hands[1] = ['1m', '1m', '1m', '2m', '2m', '2m', '3m', '3m', '7p', '8p', '9p', '4z', '4z']
    g.do_action(0, 'discard', tile='3m', tsumogiri=True)
    g.do_action(1, 'ron')
    w = g.result['wins'][0]
    check('3 111222333m 789p 44z 荣和 3m：一杯口+混全 3 番 40 符 5200',
          (w['han'], w['fu'], w['points']) == (3, 40, 5200),
          (w['han'], w['fu'], w['points'], [y['name'] for y in w['yaku']]))

    # 4. 食替：吃完手里只剩不能打的牌，这种吃法不给
    g = fresh()
    g.melds[1] = [{'type': 'chi', 'tiles': ['1p', '2p', '3p'], 'from': 0, 'called_tile': '1p'},
                  {'type': 'chi', 'tiles': ['7s', '8s', '9s'], 'from': 0, 'called_tile': '7s'},
                  {'type': 'pon', 'tiles': ['9p', '9p', '9p'], 'from': 2, 'called_tile': '9p'}]
    g.hands[1] = ['3m', '4m', '5m', '6m']
    turn(g, 0, JUNK, '3m')
    g.do_action(0, 'discard', tile='3m', tsumogiri=True)
    opts = g.call_options.get(1, [])
    check('4 45m 吃 3m 后只剩 3m、6m（都不能打）-> 不给吃', not any(o['type'] == 'chi' for o in opts), opts)
    g = fresh()
    g.melds[1] = [{'type': 'chi', 'tiles': ['1p', '2p', '3p'], 'from': 0, 'called_tile': '1p'},
                  {'type': 'chi', 'tiles': ['7s', '8s', '9s'], 'from': 0, 'called_tile': '7s'},
                  {'type': 'pon', 'tiles': ['9p', '9p', '9p'], 'from': 2, 'called_tile': '9p'}]
    g.hands[1] = ['4m', '5m', '7m', '7m']
    turn(g, 0, JUNK, '3m')
    g.do_action(0, 'discard', tile='3m', tsumogiri=True)
    opts = g.call_options.get(1, [])
    check('4 剩下有能打的牌时照常能吃', any(o['type'] == 'chi' for o in opts), opts)

    # 5. 立直宣言牌被荣和
    g = fresh()
    turn(g, 0, ['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '1p', '4p', '5p'], '2z')
    g.hands[1] = ['5z', '5z', '5z', '2p', '3p', '4p', '5s', '6s', '7s', '2s', '3s', '4s', '2z']
    g.do_action(0, 'riichi', tile='2z', tsumogiri=True)
    g.do_action(1, 'ron')
    check('5 宣言牌被荣和：不再算立直', g.phase == 'end' and g.riichi[0] is False)
    check('5 宣言牌被荣和：不交立直棒、点数守恒', g.kyotaku == 0 and sum(g.scores) == 100000, (g.kyotaku, g.scores))

    # 6. 四杠散了：第 4 个杠之后的那张不能碰
    g = fresh()
    g.kan_seats = [0, 1, 0, 1]
    g.rinshan_used = 4
    g.dora_count = 5
    g.wall_end = 118
    g.hands[1] = ['3m', '3m'] + JUNK[2:]
    turn(g, 0, JUNK, '3m')
    g.do_action(0, 'discard', tile='3m', tsumogiri=True)
    check('6 两人合计 4 杠后打出的牌不能碰，没人和就四杠散了',
          g.phase == 'end' and g.result['reason'] == 'four_kans', (g.phase, g.call_options))

    # 7. all last 庄家和了，跟起家同分 -> 起家第一，接着打
    g = fresh()
    g.kyoku = 3
    g.scores = [35000, 15000, 15000, 35000]
    check('7 庄家和了但跟起家同分：不结束', g._check_game_over(True, True) is False)
    g.scores = [34000, 16000, 15000, 35000]
    check('7 庄家和了而且单独第一：结束', g._check_game_over(True, True) is True)

    # 8. 终局时剩下的立直棒要算进点数变化
    g = fresh()
    g.kyoku = 3
    g.kyotaku = 2
    g.scores = [40000, 20000, 20000, 18000]
    g._end_round({'type': 'ryuukyoku', 'reason': 'exhaustive', 'tenpai': [False] * 4}, [0, 0, 0, 0],
                 False, False, draw=True)
    d = g.result['delta']
    check('8 剩下 2 根立直棒给第一名，点数变化里也有 +2000',
          g.game_over and d == [2000, 0, 0, 0] and g.scores[0] == 42000, (d, g.scores))

    # 9. 打牌提示：打出去的那张也要从“剩几张”里扣掉
    import tenpai
    hints = tenpai.discard_hints(['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '5z', '5z', '5z', '2z', '2z'],
                                 [], [])
    check('9 打 2z 单骑听 2z：剩 2 张（不是 3 张）', hints.get('2z', {}).get('2z') == 2, hints.get('2z'))

    # 10. 真人不在座位 0：new_game 返回座位 0 的视角
    s = server.api_new_game({'players': ['bot', 'human', 'bot', 'bot'], 'seed': 3})
    check('10 new_game 返回座位 0 的视角', s['viewer'] == 0 and 'hand' in s['players'][0]
          and 'hand' not in s['players'][1], s['viewer'])


if __name__ == '__main__':
    test_units()
    test_wall_layout()
    test_ankan_riichi_and_chiihou()
    test_simulation()
    test_api_random_play()
    test_http_handler()
    test_round2()
    test_http()
    print()
    print('失败 %d 项' % len(FAILS) if FAILS else '全部通过')
    sys.exit(1 if FAILS else 0)
