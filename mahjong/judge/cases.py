"""已知 bug 的复现用例（编号对应 bug清单.md）。

每个用例是一个函数 f(c) -> Result，c 是 harness.Client。
- PASS：表现正确；FAIL：表现错误（detail 写看到了什么）；
- VAR：规则变体，记下选手选的是哪一种（detail），不算对错，之后和选手的规则文档对照。
牌例都按参考规则手算过，算式写在注释里。
"""

from harness import ApiError, Script, build_wall, start

CASES = []


def case(cid, title):
    def deco(f):
        f.cid, f.title = cid, title
        CASES.append(f)
        return f
    return deco


class Result:
    def __init__(self, status, detail=''):
        self.status, self.detail = status, detail


def PASS(d=''):
    return Result('PASS', d)


def FAIL(d):
    return Result('FAIL', d)


def VAR(d):
    return Result('VAR', d)


class Check:
    """收集多个断言，全对才 PASS。"""

    def __init__(self):
        self.bad = []

    def eq(self, what, got, want):
        if got != want:
            self.bad.append('%s：%r（应为 %r）' % (what, got, want))

    def true(self, what, cond, got=None):
        if not cond:
            self.bad.append(what + ('：%r' % (got,) if got is not None else ''))

    def result(self, ok_detail=''):
        return FAIL('；'.join(self.bad)) if self.bad else PASS(ok_detail)


# ---------------------------------------------------------------- 小工具

ORDER = {s: i for i, s in enumerate('mpsz')}


def tile_key(t):
    n = 5 if t[0] == '0' else int(t[0])
    return (ORDER[t[1]], n)


def norm(t):
    return '5' + t[1] if t[0] == '0' else t


def h(s):
    return s.split()


def has_yaku(win, *keys):
    return any(any(k in y['name'] for k in keys) for y in win['yaku'])


def yaku_han(win, *keys):
    return sum(y['han'] for y in win['yaku'] if any(k in y['name'] for k in keys))


def legal(st, typ):
    for a in st.get('legal_actions') or []:
        if a['type'] == typ:
            return a
    return None


def D(tile, tsumogiri=True):
    return {'tile': tile, 'tsumogiri': tsumogiri}


def win_of(end, seat=None):
    r = end.get('result') or {}
    if r.get('type') != 'agari':
        raise AssertionError('没有和牌，结算是 %s' % (r.get('type'),))
    for w in r['wins']:
        if seat is None or w['seat'] == seat:
            return w
    raise AssertionError('座位 %s 没有和牌' % seat)


def play(c, wall, steps, rules=None, length='tonpuu', until=None, max_requests=400):
    st = start(c, wall, rules=rules, length=length)
    sc = Script(c, st['game_id'], max_requests=max_requests)
    return st, sc, sc.run(steps, until=until)


def expect_status(fn):
    try:
        fn()
    except ApiError as e:
        return e.status, e.body
    return 200, ''


# ---------------------------------------------------------------- I 接口和启动

@case('I2', 'GET / 返回页面')
def i2(c):
    import urllib.request
    with urllib.request.urlopen(c.server.url('/'), timeout=5) as r:
        body = r.read().decode('utf-8', 'replace')
    return PASS() if '<html' in body.lower() else FAIL('GET / 返回的不是页面：%r' % body[:80])


@case('I4', '四个 human：别人打牌后能碰的座位由人决定')
def i4(c):
    # 座位 0（庄）摸 9p 摸切，座位 2 手里两张 9p 可以碰；pass 之后轮到座位 1，也要停下来等人
    wall = build_wall(hands={2: h('9p 9p 1m 4m 7m 2p 5p 3s 6s 1z 2z 3z 4z')}, draws=['9p'], avoid=['9p'])
    st = start(c, wall)
    gid = st['game_id']
    c.action(gid, 0, 'discard', **D('9p'))
    s0 = c.state(gid, 0)
    ck = Check()
    ck.true('座位 0 打出 9p 后 waiting_for 应包含座位 2', 2 in (s0.get('waiting_for') or []), s0.get('waiting_for'))
    s2 = c.state(gid, 2)
    ck.true('座位 2 的 legal_actions 应有 pon', legal(s2, 'pon') is not None, [a['type'] for a in s2.get('legal_actions') or []])
    if not ck.bad:
        c.action(gid, 2, 'pass')
        s1 = c.state(gid, 1)
        ck.eq('pass 后 waiting_for', s1.get('waiting_for'), [1])
        ck.eq('座位 1 还没打牌', len(s1['players'][1]['discards']), 0)
        ck.true('座位 1 应摸到牌', s1.get('drawn') is not None)
    return ck.result()


@case('I5', '每次 new_game 给新的 game_id，对旧局的操作不影响新局')
def i5(c):
    a = start(c, build_wall(seed=1))
    b = start(c, build_wall(seed=2))
    ck = Check()
    ck.true('两局 game_id 应不同', a['game_id'] != b['game_id'], (a['game_id'], b['game_id']))
    if not ck.bad:
        # 接口说明允许旧局不留：对旧局操作回 4xx 也行，但不能动到新局
        expect_status(lambda: c.action(a['game_id'], 0, 'discard', **D(a.get('drawn'))))
        sb = c.state(b['game_id'], 0)
        ck.eq('第二局座位 0 的河', len(sb['players'][0]['discards']), 0)
        ck.eq('第二局座位 0 仍是刚摸的牌', sb.get('drawn'), b.get('drawn'))
    return ck.result()


@case('I6', '非法请求返回 4xx 和 error，状态不变')
def i6(c):
    wall = build_wall(hands={0: h('1m 2m 3m 4p 5p 6p 7s 8s 9s 1z 1z 2z 3z')}, draws=['4z'])
    st = start(c, wall)
    gid = st['game_id']
    ck = Check()
    for what, fn in [
        ('不该座位 1 打牌', lambda: c.action(gid, 1, 'discard', tile='1m', tsumogiri=False)),
        ('座位 0 打手里没有的牌', lambda: c.action(gid, 0, 'discard', tile='9m', tsumogiri=False)),
        ('不认识的 game_id', lambda: c.state('no-such-game', 0)),
        ('不认识的操作', lambda: c.action(gid, 0, 'fly')),
    ]:
        code, body = expect_status(fn)
        ck.true('%s 应返回 4xx' % what, 400 <= code < 500, code)
        if 400 <= code < 500:
            ck.true('%s 的返回应带 error' % what, '"error"' in body, body[:80])
    after = c.state(gid, 0)
    ck.eq('非法请求后 wall_left 不变', after['wall_left'], st['wall_left'])
    ck.eq('非法请求后座位 0 的河', len(after['players'][0]['discards']), 0)
    ck.eq('非法请求后 drawn', after.get('drawn'), '4z')
    return ck.result()


@case('I7', '摸切和手切分开记')
def i7(c):
    # 座位 0 手里有 3m，第一巡摸 3m 手切（打手里那张），第二巡又摸 3m 摸切
    wall = build_wall(hands={0: h('3m 1p 4p 7p 2s 5s 8s 1z 2z 3z 4z 5z 6z')},
                      draws=['3m', '9m', '9m', '9m', '3m'], avoid=['3m', '9m'])
    st, sc, end = play(c, wall, [(0, 'discard', D('3m', False)), (0, 'discard', D('3m', True))])
    p = c.state(st['game_id'], 0)['players'][0]
    riv = p['discards']
    ck = Check()
    ck.eq('河的张数', len(riv), 2)
    if len(riv) == 2:
        ck.eq('第一张（手切）tsumogiri', riv[0].get('tsumogiri'), False)
        ck.eq('第二张（摸切）tsumogiri', riv[1].get('tsumogiri'), True)
    ck.eq('手里还剩一张 3m', p['hand'].count('3m'), 1)
    return ck.result()


@case('I8', '手牌排好序、不含刚摸的那张')
def i8(c):
    wall = build_wall(hands={0: h('1m 2m 3m 4m 6m 7m 8m 9m 1p 2p 3p 4p 7z')}, draws=['2m'])
    st = start(c, wall)
    hand = st['players'][0]['hand']
    ck = Check()
    ck.true('手牌应按牌种排好序', [tile_key(t) for t in hand] == sorted(tile_key(t) for t in hand), ' '.join(hand))
    ck.eq('drawn', st.get('drawn'), '2m')
    ck.eq('手牌里 2m 的张数', hand.count('2m'), 1)
    return ck.result()


@case('I9a', '暗杠：melds 类型 ankan、from 为 null')
def i9a(c):
    wall = build_wall(hands={0: h('1z 1z 1z 2m 3m 4m 5p 6p 7p 3s 4s 9s 9s')}, draws=['1z'], rinshan=['8m'], avoid=['1z'])
    st, sc, _ = play(c, wall, [(0, 'ankan', {'tile': '1z'})], until=None)
    s = c.state(st['game_id'], 0)
    m = s['players'][0]['melds']
    ck = Check()
    ck.eq('副露数', len(m), 1)
    if m:
        ck.eq('类型', m[0].get('type'), 'ankan')
        ck.eq('张数', len(m[0].get('tiles') or []), 4)
        ck.eq('from', m[0].get('from'), None)
    ck.eq('岭上摸到的牌', s.get('drawn'), '8m')
    return ck.result()


@case('I9b', '大明杠：类型 minkan、from、called_tile')
def i9b(c):
    wall = build_wall(hands={1: h('9p 9p 9p 1m 4m 7m 2s 5s 8s 1z 2z 3z 4z')}, draws=['9p'], avoid=['9p'])
    st, sc, _ = play(c, wall, [(0, 'discard', D('9p')), (1, 'minkan')])
    m = c.state(st['game_id'], 1)['players'][1]['melds']
    ck = Check()
    ck.eq('副露数', len(m), 1)
    if m:
        ck.eq('类型', m[0].get('type'), 'minkan')
        ck.eq('张数', len(m[0].get('tiles') or []), 4)
        ck.eq('from', m[0].get('from'), 0)
        ck.eq('called_tile', m[0].get('called_tile'), '9p')
    return ck.result()


# 加杠和抢杠共用的牌山：座位 0 打 7s，座位 2 碰；座位 2 第二次摸到 7s 加杠。
# 座位 3 听 7s 边张（123m 456p 789p 东东 89s），本身没有役，抢杠时有抢杠一役。
def _kakan_wall(seat3_tenpai):
    hands = {0: h('1m 1m 2p 3p 4p 6p 7p 8p 2s 3s 4s 3z 4z'),
             2: h('7s 7s 1m 9m 9m 2z 2z 3z 4z 6z 6z 1p 9p')}
    if seat3_tenpai:
        hands[3] = h('1m 2m 3m 4p 5p 6p 7p 8p 9p 1z 1z 8s 9s')
    # 摸牌顺序：52 座位 0；碰后座位 2 打牌，53 座位 3，54 座位 0，55 座位 1，56 座位 2
    return build_wall(hands=hands, draws=['7s', '5z', '5z', '5z', '7s'], dora=['6z'], rinshan=['5z'])


KAKAN_STEPS = [(0, 'discard', D('7s')), (2, 'pon', {'tiles': ['7s', '7s']}), (2, 'discard', D('1m', False)),
               (2, 'kakan', {'tile': '7s'})]


@case('I9c', '加杠：碰改成 kakan、4 张')
def i9c(c):
    st, sc, _ = play(c, _kakan_wall(False), KAKAN_STEPS)
    m = c.state(st['game_id'], 2)['players'][2]['melds']
    ck = Check()
    ck.eq('副露数', len(m), 1)
    if m:
        ck.eq('类型', m[0].get('type'), 'kakan')
        ck.eq('张数', len(m[0].get('tiles') or []), 4)
    return ck.result()


@case('I10', '碰：from 和 called_tile')
def i10(c):
    st, sc, _ = play(c, _kakan_wall(False), KAKAN_STEPS[:2])
    m = c.state(st['game_id'], 2)['players'][2]['melds']
    ck = Check()
    ck.eq('副露数', len(m), 1)
    if m:
        ck.eq('类型', m[0].get('type'), 'pon')
        ck.eq('from', m[0].get('from'), 0)
        ck.eq('called_tile', m[0].get('called_tile'), '7s')
    riv = c.state(st['game_id'], 0)['players'][0]['discards']
    ck.true('被碰的那张仍留在河里且 called 为 true', riv and riv[0].get('called') is True, riv)
    return ck.result()


@case('I11', 'events 按顺序记录摸打，别人摸的牌不给牌面')
def i11(c):
    wall = build_wall(seed=5)
    st, sc, _ = play(c, wall, [], until=lambda s: len(s['players'][1]['discards']) >= 1)
    ev = c.state(st['game_id'], 0).get('events') or []
    ck = Check()
    kinds = [e.get('type') for e in ev]
    ck.true('应有 draw 和 discard 事件', 'draw' in kinds and 'discard' in kinds, kinds[:10])
    leak = [e for e in ev if e.get('type') == 'draw' and e.get('seat') != 0 and e.get('tile') is not None]
    ck.true('别人摸牌事件的 tile 应为 null', not leak, leak[:2])
    own = [e for e in ev if e.get('type') == 'draw' and e.get('seat') == 0]
    ck.true('自己摸牌事件应给牌面', own and own[0].get('tile') is not None, own[:1])
    return ck.result()


@case('I12', 'points 不含本场和供托')
def i12(c):
    # 第一局：座位 0 拿一手明显没听的牌，大家摸切到荒牌流局，本场 +1
    w1 = build_wall(hands={0: h('1m 4m 7m 2p 5p 8p 3s 6s 9s 1z 2z 3z 4z')}, seed=11)
    st, sc, end = play(c, w1, [], until=lambda s: False, max_requests=1200)
    r = end['result']
    if r.get('type') != 'ryuukyoku':
        return FAIL('第一局应荒牌流局，实际 %s' % r.get('type'))
    dealer = end['round']['dealer']
    tenpai = r.get('tenpai') or [False] * 4
    nd = dealer if tenpai[dealer] else (dealer + 1) % 4
    loser, winner = nd, (nd + 1) % 4
    # 第二局：新庄家打 4s，下家荣和。中暗刻 234m 567p 23s 88s，1 番 40 符 = 1300，加 1 本场 = 1600
    w2 = build_wall(hands={winner: h('7z 7z 7z 2m 3m 4m 5p 6p 7p 2s 3s 8s 8s')}, draws=['4s'], dora=['3z'], avoid=['4s', '1s'])
    s2 = c.next(st['game_id'], 0, wall=w2)
    ck = Check()
    ck.eq('第二局本场数', s2['round']['honba'], 1)
    ck.eq('第二局庄家', s2['round']['dealer'], nd)
    if ck.bad:
        return ck.result()
    sc2 = Script(c, st['game_id'])
    e2 = sc2.run([(loser, 'discard', D('4s')), (winner, 'ron')])
    w = win_of(e2, winner)
    ck.eq('points', w['points'], 1300)
    ck.eq('和牌者 delta', e2['result']['delta'][winner], 1600 + 1000 * s2['round']['riichi_sticks'])
    ck.eq('放铳者 delta', e2['result']['delta'][loser], -1600)
    return ck.result()


@case('I13', '累计役满：yakuman 为 0、照常给番符，点数按役满（或封顶三倍满）')
def i13(c):
    # 庄家门清：11m 234m 234m 567m 78m 听 6-9m，第一巡摸切 1z，第二巡摸 2z 打出立直，一发巡自摸 9m。
    # 立直 1 + 一发 1 + 门前清自摸和 1 + 平和 1 + 一杯口 1 + 清一色 6 + 宝牌 2（指示牌 1m → 2m×2）= 13 番
    wall = build_wall(hands={0: h('1m 1m 2m 3m 4m 2m 3m 4m 5m 6m 7m 7m 8m')},
                      draws=['1z', '5z', '5z', '5z', '2z', '6z', '6z', '6z', '9m'], dora=['1m'], ura=['3z'], avoid=['6m', '9m'])
    st, sc, end = play(c, wall, [(0, 'discard', D('1z')), (0, 'riichi', D('2z')), (0, 'tsumo')])
    w = win_of(end, 0)
    ck = Check()
    ck.eq('yakuman', w['yakuman'], 0)
    ck.true('han 应 ≥ 13', w['han'] >= 13, w['han'])
    ck.eq('各役番数之和等于 han', sum(y['han'] for y in w['yaku']), w['han'])
    if ck.bad:
        return ck.result()
    if w['points'] == 48000:
        return PASS('累计役满 48000')
    if w['points'] == 36000:
        return VAR('累计役满封顶三倍满 36000')
    return FAIL('points %s（累计役满应为 48000，封顶三倍满为 36000）' % w['points'])


# ---------------------------------------------------------------- W 牌山和流程

@case('W1', '宝牌指示牌位置：wall[122]')
def w1(c):
    st = start(c, build_wall(dora=['1z'], seed=3, mirror_original=False))
    return PASS() if st['dora_indicators'] == ['1z'] else FAIL('dora_indicators %r（应为 ["1z"]）' % st['dora_indicators'])


@case('W2', '下一局指定牌山按物理座位发牌、新庄家先摸 wall[52]')
def w2(c):
    # 东 1 局：座位 0 打 4s，座位 1 中暗刻荣和，换庄到座位 1
    w1_ = build_wall(hands={1: h('7z 7z 7z 2m 3m 4m 5p 6p 7p 2s 3s 8s 8s')}, draws=['4s'], dora=['3z'], avoid=['4s', '1s'])
    st, sc, end = play(c, w1_, [(0, 'discard', D('4s')), (1, 'ron')])
    w2_ = build_wall(hands={0: h('1m 1m 2m 2m 3m 3m 4p 4p 5p 5p 6p 6p 7z'),
                            1: h('9s 9s 9s 8s 8s 8s 1z 1z 1z 2z 2z 2z 3z')}, draws=['6z'], seed=8)
    s = c.next(st['game_id'], 0, wall=w2_)
    ck = Check()
    ck.eq('东 2 局庄家', s['round']['dealer'], 1)
    ck.eq('座位 0 的手牌', sorted(s['players'][0]['hand'], key=tile_key), sorted(w2_[0:13], key=tile_key))
    s1 = c.state(st['game_id'], 1)
    ck.eq('座位 1（庄）的手牌', sorted(s1['players'][1]['hand'], key=tile_key), sorted(w2_[13:26], key=tile_key))
    ck.eq('座位 1 先摸的牌', s1.get('drawn'), '6z')
    return ck.result()


@case('W3', '红五和普通五都在手里时，碰给两种选项')
def w3(c):
    wall = build_wall(hands={1: h('5m 5m 0m 1p 4p 7p 2s 5s 8s 1z 2z 3z 4z')}, draws=['5m'])
    st = start(c, wall)
    c.action(st['game_id'], 0, 'discard', **D('5m'))
    a = legal(c.state(st['game_id'], 1), 'pon')
    if not a:
        return FAIL('座位 1 没有碰的选项')
    opts = {tuple(sorted(o)) for o in a.get('options') or []}
    want = {('5m', '5m'), ('0m', '5m')}
    return PASS() if want <= opts else FAIL('pon.options %r（应含 5m5m 和 5m0m）' % a.get('options'))


@case('W5', '立直宣言牌被荣和：立直不成立，不扣 1000')
def w5(c):
    # 座位 1 摸 9p 后打 1z 立直；座位 2 中暗刻单骑 1z 荣和：中 1 番，
    # 20 + 门清荣和 10 + 中暗刻 8 + 单骑 2 + 东（场风）雀头 2 = 42 → 50 符，1 番 50 符闲家 = 1600
    wall = build_wall(hands={1: h('2m 3m 4m 6p 7p 8p 2s 3s 4s 6s 7s 9p 1z'),
                             2: h('7z 7z 7z 3m 4m 5m 4p 5p 6p 6s 7s 8s 1z')},
                      draws=['2z', '9p'], dora=['3z'], avoid=['1z'])
    st, sc, end = play(c, wall, [(1, 'riichi', D('1z', False)), (2, 'ron')])
    w = win_of(end, 2)
    ck = Check()
    ck.eq('点数', w['points'], 1600)
    ck.eq('座位 1 的 delta', end['result']['delta'][1], -1600)
    ck.eq('座位 1 结算后的点数', end['players'][1]['score'], 25000 - 1600)
    ck.eq('供托', end['round']['riichi_sticks'], 0)
    ck.eq('四家 delta 之和', sum(end['result']['delta']), 0)
    return ck.result()


@case('W7', '半庄战东 4 局后进南场')
def w7(c):
    st = start(c, build_wall(hands={0: h('1m 4m 7m 2p 5p 8p 3s 6s 9s 1z 2z 3z 4z')}, seed=21), length='hanchan')
    gid = st['game_id']
    for _ in range(12):
        end = Script(c, gid, max_requests=1200).run([], until=lambda s: False)
        if end['phase'] == 'game_end':
            return FAIL('东 %d 局后整场结束了（半庄应打到南场）' % end['round']['number']) \
                if end['round']['wind'] == '1z' else PASS()
        s = c.next(gid, 0)
        if s['round']['wind'] == '2z':
            return PASS()
    return FAIL('打了 12 局还没进南场')


# ---------------------------------------------------------------- K 杠

@case('K1', '加杠可以抢杠')
def k1(c):
    # 座位 3 边张 7s 抢杠：抢杠 1 番；20 + 门清荣和 10 + 边张 2 + 东（场风）雀头 2 = 34 → 40 符，1 番 40 符闲家 = 1300
    st, sc, end = play(c, _kakan_wall(True), KAKAN_STEPS + [(3, 'ron')])
    w = win_of(end, 3)
    ck = Check()
    ck.true('役里应有抢杠', has_yaku(w, '抢杠', '搶槓', '槍槓', 'chankan'), [y['name'] for y in w['yaku']])
    ck.eq('点数', w['points'], 1300)
    ck.eq('放铳者', w.get('from'), 2)
    m = end['players'][2]['melds']
    ck.true('被抢杠后座位 2 的副露应还是碰', m and m[0].get('type') == 'pon', m)
    return ck.result()


@case('K1b', '加杠抢杠：除抢杠外还有别的役')
def k1b(c):
    # 同 K1，但座位 3 有中暗刻（中中中 123m 456p 东东 89s 边张听 7s）。座位 0 第一次打 7s 时它能和但没和（默认 pass），
    # 自己打过一张后同巡振听解除。抢杠时：中 1 + 抢杠 1 = 2 番；20 + 门清荣和 10 + 中暗刻 8 + 边张 2 + 东雀头 2 = 42 → 50 符，
    # 2 番 50 符闲家 = 3200（宝牌指示牌 2z → 3z，座位 3 没有）
    hands = {0: h('1m 1m 2p 3p 4p 6p 7p 8p 2s 3s 4s 3z 4z'),
             2: h('7s 7s 1m 9m 9m 2z 2z 3z 4z 6z 6z 1p 9p'),
             3: h('7z 7z 7z 1m 2m 3m 4p 5p 6p 1z 1z 8s 9s')}
    wall = build_wall(hands=hands, draws=['7s', '5z', '5z', '5z', '7s'], dora=['2z'], rinshan=['5z'])
    st, sc, end = play(c, wall, KAKAN_STEPS + [(3, 'ron')])
    w = win_of(end, 3)
    ck = Check()
    ck.true('役里应有抢杠', has_yaku(w, '抢杠', '搶槓', '槍槓', 'chankan'), [y['name'] for y in w['yaku']])
    ck.eq('点数', w['points'], 3200)
    return ck.result()


# ---------------------------------------------------------------- S 算番算符

@case('S1', '地和')
def s1(c):
    # 座位 1：123m 456p 789s 东东东 + 9p 单骑，第一张摸到 9p 自摸。闲家役满自摸 32000（庄 16000、闲 8000）
    wall = build_wall(hands={1: h('1m 2m 3m 4p 5p 6p 7s 8s 9s 1z 1z 1z 9p')}, draws=['2z', '9p'], avoid=['9p'])
    st, sc, end = play(c, wall, [(0, 'discard', D('2z')), (1, 'tsumo')])
    w = win_of(end, 1)
    ck = Check()
    ck.true('役里应有地和', has_yaku(w, '地和'), [y['name'] for y in w['yaku']])
    ck.eq('yakuman', w['yakuman'], 1)
    ck.eq('points', w['points'], 32000)
    ck.eq('delta', end['result']['delta'], [-16000, 32000, -8000, -8000])
    return ck.result()


@case('S2', '立直后暗杠再岭上开花')
def s2(c):
    # 庄家 234m 678p 34s 999s 22p，第一巡摸切 1z，第二巡摸 2z 打出立直；第三巡摸切 1z（一发过了）；
    # 第四巡摸第 4 张 9s 暗杠，岭上 2s 自摸。
    # 立直 1 + 门前清自摸和 1 + 岭上开花 1 = 3 番（一发已过）；
    # 20 + 自摸 2 + 9s 暗杠 32 + 两面 0 = 54 → 60 符；庄 3 番 60 符自摸 1920×2 → 3900 all，加回自己的立直棒
    wall = build_wall(hands={0: h('2m 3m 4m 6p 7p 8p 3s 4s 9s 9s 9s 2p 2p')},
                      draws=['1z', '5z', '5z', '5z', '2z', '6z', '6z', '6z', '1z', '7z', '7z', '7z', '9s'],
                      dora=['3z', '4z'], ura=['3z', '3z'], rinshan=['2s'], avoid=['2s', '5s'])
    st, sc, end = play(c, wall, [(0, 'discard', D('1z')), (0, 'riichi', D('2z')), (0, 'discard', D('1z')),
                                 (0, 'ankan', {'tile': '9s'}), (0, 'tsumo')])
    w = win_of(end, 0)
    ck = Check()
    ck.true('役里应有立直、门前清自摸和、岭上开花', has_yaku(w, '立直') and has_yaku(w, '自摸') and has_yaku(w, '岭上', '嶺上'),
            [y['name'] for y in w['yaku']])
    ck.eq('han', w['han'], 3)
    ck.eq('fu', w['fu'], 60)
    ck.eq('points', w['points'], 11700)
    ck.eq('delta', end['result']['delta'], [12700, -3900, -3900, -3900])
    return ck.result()


@case('S3', '里宝牌单独列出')
def s3(c):
    # 庄家 234m 678p 234s 67s 99p，第一巡摸切 1z，第二巡摸 2z 打出立直，座位 1 一发打 8s。
    # 立直 1 + 一发 1 + 平和 1 + 里宝 2（里宝指示牌 8p → 9p×2）= 5 番满贯，庄 12000，加回立直棒
    wall = build_wall(hands={0: h('2m 3m 4m 6p 7p 8p 2s 3s 4s 6s 7s 9p 9p')}, draws=['1z', '5z', '5z', '5z', '2z', '8s'],
                      dora=['3z'], ura=['8p'], avoid=['5s', '8s'])
    st, sc, end = play(c, wall, [(0, 'discard', D('1z')), (0, 'riichi', D('2z')), (1, 'discard', D('8s')), (0, 'ron')])
    w = win_of(end, 0)
    ck = Check()
    ck.eq('里宝牌番数', yaku_han(w, '里'), 2)
    ck.eq('uradora_indicators', end['result'].get('uradora_indicators'), ['8p'])
    ck.eq('han', w['han'], 5)
    ck.eq('points', w['points'], 12000)
    return ck.result()


@case('S4', '拆法一致：平和形和单骑形取点数高的那种')
def s4(c):
    # 座位 1：22m 34m 234p 678s 678p，荣和 2m。拆成 22m+234m 是两面（平和 + 断幺 2 番 30 符 = 2000），
    # 拆成 234m+2m 单骑是断幺 1 番 40 符 = 1300。应取 2000；“平和 40 符”的 2 番 40 符 2600 是拆法混用
    wall = build_wall(hands={1: h('2m 2m 3m 4m 2p 3p 4p 6s 7s 8s 6p 7p 8p')}, draws=['2m'], dora=['3z'], avoid=['5m'], aka=False)
    st, sc, end = play(c, wall, [(0, 'discard', D('2m')), (1, 'ron')], rules={'aka_dora': False})
    w = win_of(end, 1)
    ck = Check()
    ck.eq('(han, fu, points)', (w['han'], w['fu'], w['points']), (2, 30, 2000))
    return ck.result()


@case('S4b', '听牌形有几种解释时取符多的那种')
def s4b(c):
    # 庄家 999p 中中 234m 345s 46s，第一巡摸切 1z，第二巡摸 2z 打出立直，座位 1 一发打 5s。
    # 5s 可以看成 46s 的嵌张（+2），也可以看成 34s 的两面（345s+456s）。规则：取对总点数有利的解释。
    # 立直 1 + 一发 1 = 2 番；20 + 门清荣和 10 + 9p 暗刻 8 + 中雀头 2 = 40，嵌张 +2 → 42 → 50 符（庄 4800），
    # 当成两面是 40 符（3900）
    wall = build_wall(hands={0: h('9p 9p 9p 7z 7z 2m 3m 4m 3s 4s 5s 4s 6s')},
                      draws=['1z', '5z', '5z', '5z', '2z', '5s'], dora=['3z'], ura=['3z'], avoid=['5s'], aka=False)
    st, sc, end = play(c, wall, [(0, 'discard', D('1z')), (0, 'riichi', D('2z')), (1, 'discard', D('5s')), (0, 'ron')],
                       rules={'aka_dora': False})
    w = win_of(end, 0)
    return PASS() if (w['fu'], w['points']) == (50, 4800) else FAIL('(fu, points) %r（应为 (50, 4800)）' % ((w['fu'], w['points']),))


@case('S4c', '拆法一致：一杯口混全形和刻子形（不涉及平和）')
def s4c(c):
    # 对拍第 223 号样本改的。座位 1：789m 123s 123s 13s 东东，庄家打 2s，座位 1 荣和。
    # 拆成 123s×3：混全带幺九 2 + 一杯口 1 = 3 番；20 + 门清荣和 10 + 东雀头（场风）2 + 嵌张 2 = 34 → 40 符，闲 5200。
    # 拆成 111s 222s 333s：没役（荣和的 222s 算明刻，凑不成三暗刻）。符是 20 + 10 + 111s 暗刻 8 + 333s 暗刻 4
    # + 222s 明刻 2 + 东雀头 2 = 46 → 50 符。番取前一种、符取后一种就成了 3 番 50 符 6400，是拆法混用。
    # 只给平和、七对子做了兜底的修法在这里会露出来
    wall = build_wall(hands={1: h('7m 8m 9m 1s 2s 3s 1s 3s 1s 2s 3s 1z 1z')}, draws=['2s'], dora=['3z'], avoid=['2s'], aka=False)
    st, sc, end = play(c, wall, [(0, 'discard', D('2s')), (1, 'ron')], rules={'aka_dora': False})
    w = win_of(end, 1)
    ck = Check()
    ck.eq('(han, fu, points)', (w['han'], w['fu'], w['points']), (3, 40, 5200))
    return ck.result()


@case('S4d', '拆法一致：二杯口和七对子')
def s4d(c):
    # 座位 1：223344m 778899p 东，单骑听东；庄家第一巡摸切东，座位 1 荣和。
    # 拆成 234m×2 789p×2 东东：二杯口 3 番（没有断幺、全带、平和）；20 + 门清荣和 10 + 单骑 2 + 东雀头（场风）2 = 34 → 40 符，闲家 5200。
    # 拆成七对子：2 番 25 符 1600。规则上二杯口优先（也是点数高的那种），两者不复合。
    # 常见的错：七对子和二杯口一起算（5 番满贯 8000）；番取二杯口、符取七对子（3 番 25 符 3200）；只认七对子（1600）
    wall = build_wall(hands={1: h('2m 2m 3m 3m 4m 4m 7p 7p 8p 8p 9p 9p 1z')}, draws=['1z'], dora=['3z'], avoid=['1z'], aka=False)
    st, sc, end = play(c, wall, [(0, 'discard', D('1z')), (1, 'ron')], rules={'aka_dora': False})
    w = win_of(end, 1)
    ck = Check()
    ck.true('役里不应有七对子', not has_yaku(w, '七对', '七對', '七対'), [y['name'] for y in w['yaku']])
    ck.eq('荣和 (han, fu, points)', (w['han'], w['fu'], w['points']), (3, 40, 5200))
    # 自摸版（第二巡，避开地和）：庄家、座位 1 第一巡各摸切，座位 1 第二巡摸东自摸。二杯口 3 + 门前清自摸和 1 = 4 番；20 + 自摸 2 + 单骑 2 + 东雀头 2 = 26 → 30 符，
    # 闲家自摸 2000/3900 = 7900。七对子是 3 番 25 符 6400
    wall = build_wall(hands={1: h('2m 2m 3m 3m 4m 4m 7p 7p 8p 8p 9p 9p 1z')}, draws=['9s', '9m', '9m', '9m', '8s', '1z'], dora=['3z'], avoid=['1z'], aka=False)
    st, sc, end = play(c, wall, [(0, 'discard', D('9s')), (1, 'discard', D('9m')), (1, 'tsumo')], rules={'aka_dora': False})
    w = win_of(end, 1)
    ck.true('自摸：役里不应有七对子', not has_yaku(w, '七对', '七對', '七対'), [y['name'] for y in w['yaku']])
    ck.eq('自摸 (han, fu, points)', (w['han'], w['fu'], w['points']), (4, 30, 7900))
    return ck.result()


@case('S4e', '拆法一致：三暗刻和一杯口（自摸）')
def s4e(c):
    # 座位 1：111m 222m 333m 456p 9s，单骑听 9s，第二巡自摸 9s。
    # 拆成 111m 222m 333m：三暗刻 2 + 门前清自摸和 1 = 3 番；20 + 自摸 2 + 1m 暗刻 8 + 2m 暗刻 4 + 3m 暗刻 4 + 单骑 2 = 40 符；
    # 闲家自摸 1300/2600 = 5200。拆成 123m×3：一杯口 1 + 自摸 1 = 2 番 30 符 2000。应取前者
    wall = build_wall(hands={1: h('1m 1m 1m 2m 2m 2m 3m 3m 3m 4p 5p 6p 9s')}, draws=['1z', '2z', '2z', '2z', '3z', '9s'],
                      dora=['5z'], avoid=['9s'], aka=False)
    st, sc, end = play(c, wall, [(0, 'discard', D('1z')), (1, 'discard', D('2z')), (1, 'tsumo')], rules={'aka_dora': False})
    w = win_of(end, 1)
    ck = Check()
    ck.true('役里应有三暗刻', has_yaku(w, '三暗刻'), [y['name'] for y in w['yaku']])
    ck.eq('(han, fu, points)', (w['han'], w['fu'], w['points']), (3, 40, 5200))
    return ck.result()


@case('S7', '七对子不能有四张同种')
def s7(c):
    # 座位 1：111m 22p 44p 66s 88s 西西，庄家摸切 1m。凑成“1m×4 + 五个对子”不是七对子（对子要七种不同的牌），
    # 也拆不成四组面子一个雀头，所以座位 1 不能荣和；13 张时也不听牌
    wall = build_wall(hands={1: h('1m 1m 1m 2p 2p 4p 4p 6s 6s 8s 8s 3z 3z')}, draws=['1m'], dora=['5z'], aka=False)
    st = start(c, wall, rules={'aka_dora': False})
    gid = st['game_id']
    ck = Check()
    waits = ((c.state(gid, 1).get('hints') or {}).get('waits')) or []
    ck.true('13 张时不应有听牌提示', not waits, waits)
    c.action(gid, 0, 'discard', **D('1m'))
    ck.true('庄家打 1m 后座位 1 不应能荣和', not ron_offered(c, gid, 1))
    return ck.result()


@case('S8', '双碰荣和：荣和的那组算明刻，不是四暗刻')
def s8(c):
    # 座位 1：222m 444p 666s 77s 88s，双碰听 7s 8s，庄家打 8s，座位 1 荣和。
    # 888s 是荣和凑成的，算明刻：三暗刻 2 + 对对和 2 + 断幺九 1 = 5 番满贯 8000，不是四暗刻役满
    wall = build_wall(hands={1: h('2m 2m 2m 4p 4p 4p 6s 6s 6s 7s 7s 8s 8s')}, draws=['8s'], dora=['5z'], avoid=['7s', '8s'], aka=False)
    st, sc, end = play(c, wall, [(0, 'discard', D('8s')), (1, 'ron')], rules={'aka_dora': False})
    w = win_of(end, 1)
    ck = Check()
    ck.eq('yakuman', w['yakuman'], 0)
    ck.eq('(han, points)', (w['han'], w['points']), (5, 8000))
    return ck.result()


@case('S6', '每役番数：副露混一色 2 番、宝牌 3 张')
def s6(c):
    # 庄家 111m 456m 89m 南南 + 中中，第一巡摸切 3s；座位 1 打中，庄家碰，打 3p；座位 1 打 7m，庄家荣和。
    # 中 1 + 混一色（副露）2 + 宝牌 3（指示牌 9m → 1m×3）= 6 番跳满，庄 18000
    wall = build_wall(hands={0: h('1m 1m 1m 4m 5m 6m 8m 9m 2z 2z 7z 7z 3p')}, draws=['3s', '7z', '7m'],
                      dora=['9m'], avoid=['7m'])
    st, sc, end = play(c, wall, [(0, 'discard', D('3s')), (1, 'discard', D('7z')), (0, 'pon', {'tiles': ['7z', '7z']}),
                                 (0, 'discard', D('3p', False)), (1, 'discard', D('7m')), (0, 'ron')])
    w = win_of(end, 0)
    ck = Check()
    ck.eq('混一色番数', yaku_han(w, '混一色'), 2)
    ck.eq('宝牌番数', sum(y['han'] for y in w['yaku'] if '宝' in y['name'] and '里' not in y['name'] and '赤' not in y['name']), 3)
    ck.eq('各役之和等于 han', sum(y['han'] for y in w['yaku']), w['han'])
    ck.eq('han', w['han'], 6)
    ck.eq('points', w['points'], 18000)
    return ck.result()


# ---------------------------------------------------------------- P 点数

@case('P1', '满贯封顶：切上满贯关时闲家 4 番 40 符 = 8000')
def p1(c):
    # 座位 1：234m 666p 234s 46s 88m 嵌张听 5s，荣和。断幺 1 + 宝牌 3（指示牌 5p → 6p×3）= 4 番；
    # 20 + 门清荣和 10 + 嵌张 2 + 6p 暗刻 4 = 36 → 40 符。基本点 2560 > 2000 → 满贯 8000
    wall = build_wall(hands={1: h('2m 3m 4m 6p 6p 6p 2s 3s 4s 4s 6s 8m 8m')}, draws=['5s'], dora=['5p'], avoid=['5s'])
    st, sc, end = play(c, wall, [(0, 'discard', D('5s')), (1, 'ron')], rules={'kiriage_mangan': False})
    w = win_of(end, 1)
    ck = Check()
    ck.eq('(han, fu)', (w['han'], w['fu']), (4, 40))
    ck.eq('points', w['points'], 8000)
    return ck.result()


@case('P2', '四暗刻单骑：显示的倍数和付的钱一致')
def p2(c):
    wall = build_wall(hands={1: h('1m 1m 1m 4p 4p 4p 7s 7s 7s 9m 9m 9m 2z')}, draws=['2z'], avoid=['2z'])
    st, sc, end = play(c, wall, [(0, 'discard', D('2z')), (1, 'ron')])
    w = win_of(end, 1)
    pay = {1: 32000, 2: 64000}
    if w['yakuman'] not in pay:
        return FAIL('yakuman %r' % w['yakuman'])
    if w['points'] != pay[w['yakuman']]:
        return FAIL('yakuman %d 但 points %d（应为 %d）' % (w['yakuman'], w['points'], pay[w['yakuman']]))
    return PASS('2 倍') if w['yakuman'] == 2 else VAR('四暗刻单骑按 1 倍')


# ---------------------------------------------------------------- H 听牌提示

@case('H1', '剩余张数：碰过的牌只扣一次')
def h1(c):
    # 座位 1 碰座位 0 打的 6p，打 1z 后听 3p 6p；从座位 1 看：3p 剩 4 张，6p 剩 1 张
    wall = build_wall(hands={1: h('6p 6p 4p 5p 1m 2m 3m 7s 8s 9s 2m 2m 1z')}, draws=['6p'], dora=['3z'],
                      avoid=['3p', '6p'])
    st, sc, _ = play(c, wall, [(0, 'discard', D('6p')), (1, 'pon', {'tiles': ['6p', '6p']}), (1, 'discard', D('1z', False))])
    hs = (c.state(st['game_id'], 1).get('hints') or {}).get('waits') or []
    got = {norm(x['tile']): x.get('left') for x in hs}
    return PASS() if got == {'3p': 4, '6p': 1} else FAIL('waits %r（应为 3p 剩 4、6p 剩 1）' % got)


@case('H2', '弃牌提示：打出的那张也要扣')
def h2(c):
    # 庄家 123m 789s 22m 中中中 45p + 摸 6p：打 6p 听 3p 6p，6p 剩 3 张（打出去的那张看得见）
    wall = build_wall(hands={0: h('1m 2m 3m 7s 8s 9s 2m 2m 7z 7z 7z 4p 5p')}, draws=['6p'], dora=['1z'])
    st = start(c, wall)
    d = ((st.get('hints') or {}).get('discards') or {}).get('6p') or []
    got = {norm(x['tile']): x.get('left') for x in d}
    return PASS() if got == {'3p': 4, '6p': 3} else FAIL('hints.discards["6p"] %r（应为 3p 剩 4、6p 剩 3）' % got)


@case('H4', '舍张振听：自己河里有听的牌')
def h4(c):
    # 庄家 123m 789s 22m 中中中 45p 听 3p 6p，摸 3p 不和、摸切 → 舍张振听
    wall = build_wall(hands={0: h('1m 2m 3m 7s 8s 9s 2m 2m 7z 7z 7z 4p 5p')},
                      draws=['3p', '1z', '1z', '1z', '2z'], dora=['3z'], avoid=['3p', '6p'])
    st = start(c, wall)
    gid = st['game_id']
    c.action(gid, 0, 'discard', **D('3p'))
    # 只查 13 张时；轮到自己、手里 14 张时 furiten 该怎么显示，接口说明没规定（大多数选手给 false），不测
    f = (c.state(gid, 0).get('hints') or {}).get('furiten')
    return PASS() if f is True else FAIL('打完后 furiten：%r（应为 True）' % f)


# ---------------------------------------------------------------- X 开关

@case('X1', '赤宝牌开关')
def x1(c):
    st = c.new_game(players=['human'] * 4, length='tonpuu', seed=4,
                    rules={'aka_dora': False, 'kuitan': True, 'kiriage_mangan': False, 'renpu_fu': 4})
    ck = Check()
    ck.eq('rules.aka_dora 回显', (st.get('rules') or {}).get('aka_dora'), False)
    seen = set()
    gid = st['game_id']
    sc = Script(c, gid, max_requests=1200)
    end = sc.run([], until=lambda s: False)
    for seat in range(4):
        s = c.state(gid, seat)
        for p in s['players']:
            seen.update(d['tile'] for d in p['discards'])
            for m in p['melds']:
                seen.update(m['tiles'])
        seen.update(s['players'][seat].get('hand') or [])
    red = sorted(t for t in seen if t[0] == '0')
    ck.true('不应出现红五', not red, red)
    ck.true('应看到大部分牌（确认这一局真的打完了）', len(seen) >= 30, len(seen))
    return ck.result()


@case('X2', '食断开关：副露断幺九')
def x2(c):
    # 座位 1 碰 2p，打 9m 后 345m 678s 45p 66m 听 3p 6p，只有断幺九一个役；座位 2 摸 6p 打出
    def run(kuitan):
        wall = build_wall(hands={1: h('2p 2p 3m 4m 5m 6s 7s 8s 4p 5p 6m 6m 9m')}, draws=['2p', '6p'],
                          dora=['3z'], avoid=['3p', '6p'])
        st, sc, _ = play(c, wall, [(0, 'discard', D('2p')), (1, 'pon', {'tiles': ['2p', '2p']}),
                                   (1, 'discard', D('9m', False)), (2, 'discard', D('6p'))], rules={'kuitan': kuitan})
        s1 = c.state(st['game_id'], 1)
        return legal(s1, 'ron') is not None and 1 in (s1.get('waiting_for') or [])
    ck = Check()
    ck.eq('kuitan 开时能荣和', run(True), True)
    ck.eq('kuitan 关时不能荣和', run(False), False)
    return ck.result()


@case('X3', '切上满贯开关：闲家 30 符 4 番')
def x3(c):
    # 座位 1：234m 567p 345s 67s 88p 两面听 5s 8s，荣和 8s：平和 1 + 断幺 1 + 宝牌 2（指示牌 7p → 8p×2）= 4 番 30 符
    def run(kiri):
        wall = build_wall(hands={1: h('2m 3m 4m 5p 6p 7p 3s 4s 5s 6s 7s 8p 8p')}, draws=['8s'], dora=['7p'],
                          avoid=['5s', '8s'], aka=False)
        st, sc, end = play(c, wall, [(0, 'discard', D('8s')), (1, 'ron')],
                           rules={'kiriage_mangan': kiri, 'aka_dora': False})
        return win_of(end, 1)['points']
    ck = Check()
    ck.eq('切上满贯关', run(False), 7700)
    ck.eq('切上满贯开', run(True), 8000)
    return ck.result()


@case('X4', '连风雀头开关：东场东家东雀头 4 符 / 2 符')
def x4(c):
    # 庄家 东东 999p 234m 789m 45s 两面听 3s 6s，第一巡摸切 1p，第二巡摸 2z 打出立直，座位 1 一发打 6s。
    # 立直 1 + 一发 1 = 2 番；20 + 门清荣和 10 + 9p 暗刻 8 = 38，
    # 连风雀头 4 符 → 42 → 50 符（庄 4800）；2 符 → 40 → 40 符（3900）
    def run(renpu):
        wall = build_wall(hands={0: h('1z 1z 9p 9p 9p 2m 3m 4m 7m 8m 9m 4s 5s')},
                          draws=['1p', '5z', '5z', '5z', '2z', '6s'], dora=['3z'], ura=['3z'], avoid=['3s', '6s'], aka=False)
        st, sc, end = play(c, wall, [(0, 'discard', D('1p')), (0, 'riichi', D('2z')), (1, 'discard', D('6s')), (0, 'ron')],
                           rules={'renpu_fu': renpu, 'aka_dora': False})
        w = win_of(end, 0)
        return (w['fu'], w['points'])
    ck = Check()
    ck.eq('renpu_fu 4', run(4), (50, 4800))
    ck.eq('renpu_fu 2', run(2), (40, 3900))
    return ck.result()


# ---------------------------------------------------------------- N 选手修出来的新问题（原件是对的）

@case('N1', '两立直后有人鸣牌，两立直不取消（只破一发）')
def n1(c):
    # 庄家第一巡打 1z 两立直（234m 678p 234s 67s 99p 听 5s8s）；座位 1 打 7z，座位 2 碰、打 9m；庄家下一巡自摸 8s。
    # 两立直 2 + 门前清自摸和 1 + 平和 1 = 4 番 20 符，庄家自摸 2600 all = 7800（一发被碰取消）。
    # GLM 把“宣言后被鸣牌”当成两立直要退成普通立直，算成 3 番 3900。
    wall = build_wall(hands={0: h('2m 3m 4m 6p 7p 8p 2s 3s 4s 6s 7s 9p 9p'),
                             2: h('7z 7z 1m 1p 9m 2z 3z 4z 1s 9s 3m 5p 6z')},
                      draws=['1z', '7z', '2z', '8s'], dora=['3z'], ura=['3z'], avoid=['5s', '8s'])
    st, sc, end = play(c, wall, [(0, 'riichi', D('1z')), (1, 'discard', D('7z')), (2, 'pon', {'tiles': ['7z', '7z']}),
                                 (2, 'discard', D('9m', False)), (0, 'tsumo')])
    w = win_of(end, 0)
    ck = Check()
    ck.eq('两立直番数', yaku_han(w, '两立直', '双立直', 'W立直', 'ダブル'), 2)
    ck.eq('points', w['points'], 7800)
    return ck.result()


@case('N2', '明杠后打出的牌被碰，之后有人和牌：杠宝要算进去')
def n2(c):
    # 座位 1 大明杠 9p，打 1z；座位 2 碰 1z，打 2m；座位 3（34m 白白白 456p 789s 99m）荣和 2m。
    # 明杠的杠宝最晚在杠的人打牌后翻（一律立即翻也行），结算时应有 2 张宝牌指示牌。
    # Hydrogen 只在“打出的牌没人鸣”时才翻，这张被碰了就一直压着，到和牌都没翻，杠宝丢了
    wall = build_wall(hands={1: h('9p 9p 9p 1m 4m 7m 2s 5s 8s 1z 2z 3z 4z'),
                             2: h('1z 1z 2m 5m 8m 3p 6p 3s 6s 9s 6z 7z 2p'),
                             3: h('3m 4m 5z 5z 5z 4p 5p 6p 7s 8s 9s 9m 9m')},
                      draws=['9p'], dora=['4z', '6z'], rinshan=['7z'], avoid=['1z', '2m', '5m'], aka=False)
    st = start(c, wall, rules={'aka_dora': False})
    gid = st['game_id']
    c.action(gid, 0, 'discard', **D('9p'))
    _pass_others(c, gid, skip=(1,))
    c.action(gid, 1, 'minkan')
    c.action(gid, 1, 'discard', tile='1z', tsumogiri=False)
    _pass_others(c, gid, skip=(2,))
    c.action(gid, 2, 'pon', tiles=['1z', '1z'])
    c.action(gid, 2, 'discard', tile='2m', tsumogiri=False)
    _pass_others(c, gid, skip=(3,))
    c.action(gid, 3, 'ron')
    _pass_others(c, gid)
    r = c.state(gid, 0).get('result') or {}
    if r.get('type') != 'agari':
        return FAIL('没和牌：%s' % (r.get('type'),))
    n = len(r.get('dora_indicators') or [])
    return PASS() if n == 2 else FAIL('结算里宝牌指示牌 %d 张（应为 2 张）' % n)


# ---------------------------------------------------------------- R 稀有规则（随机牌局和对拍里很少碰到；没有规则争议的）
#
# 这一节不是学生原件的已知 bug，是第二批补的规则覆盖：振听真的拦住荣和、流局听牌料、海底河底。
# 有规则变体的（流局满贯、包、头跳、九种九牌、四风连打、四家立直等）另外按选手自己的规则文档比，不在这里。

WAIT_3P6P = h('1m 2m 3m 7s 8s 9s 2m 2m 7z 7z 7z 4p 5p')   # 庄家：123m 789s 22m 中中中 45p，听 3p 6p，有中一番


def ron_offered(c, gid, seat):
    """座位 seat 现在能不能荣和：在等它，而且 legal_actions 里有 ron。"""
    if seat not in (c.state(gid, 0).get('waiting_for') or []):
        return False
    return legal(c.state(gid, seat), 'ron') is not None


def put_last(wall, tile):
    """把牌山里一张 tile 换到 wall[121]（最后一张正常摸的牌，座位 1 摸到它就是海底）。"""
    j = max(i for i, t in enumerate(wall) if t == tile and i != 121)
    wall[121], wall[j] = wall[j], wall[121]
    return wall


@case('R1', '舍张振听：自己打过听的牌，别人打另一张听的牌也不能荣和')
def r1(c):
    # 庄家听 3p 6p，第一巡摸 3p 摸切（舍张振听）；座位 1 摸 6p 摸切：庄家不能荣和
    wall = build_wall(hands={0: WAIT_3P6P}, draws=['3p', '6p'], dora=['3z'], avoid=['3p', '6p'], aka=False)
    st, sc, end = play(c, wall, [(0, 'discard', D('3p')), (1, 'discard', D('6p'))], rules={'aka_dora': False})
    return FAIL('座位 1 打 6p 后庄家还能荣和') if ron_offered(c, st['game_id'], 0) else PASS()


@case('R2', '同巡振听：放过一次荣和，同一巡内别人再打听的牌也不能荣和')
def r2(c):
    # 庄家第一巡摸切 1z；座位 1 摸切 6p，庄家能荣和但 pass；座位 2 摸切 3p：庄家还没轮到自己，不能荣和。
    # “到下次摸牌解除”和“到下次打牌解除”两种说法在这里结论一样
    wall = build_wall(hands={0: WAIT_3P6P}, draws=['1z', '6p', '3p'], dora=['3z'], avoid=['3p', '6p'], aka=False)
    st, sc, end = play(c, wall, [(0, 'discard', D('1z')), (1, 'discard', D('6p'))], rules={'aka_dora': False})
    gid = st['game_id']
    ck = Check()
    ck.true('座位 1 打 6p 后庄家应能荣和', ron_offered(c, gid, 0))
    if ck.bad:
        return ck.result()
    sc.run([(0, 'pass'), (2, 'discard', D('3p'))])
    ck.true('同巡内座位 2 打 3p，庄家不应能荣和', not ron_offered(c, gid, 0))
    return ck.result()


@case('R3', '立直振听：立直后放过荣和，过了一巡也不能荣和（自摸可以）')
def r3(c):
    # 庄家第一巡摸 1z 打出立直（两立直，无所谓）；座位 1 摸切 6p，庄家 pass；座位 2、3 摸切；
    # 庄家摸 9m 摸切（已经过了一巡）；座位 1 摸切 3p：立直后见逃，一直振听，不能荣和
    wall = build_wall(hands={0: WAIT_3P6P}, draws=['1z', '6p', '9m', '9m', '9m', '3p'], dora=['3z'], ura=['3z'],
                      avoid=['3p', '6p'], aka=False)
    st, sc, end = play(c, wall, [(0, 'riichi', D('1z')), (1, 'discard', D('6p'))], rules={'aka_dora': False})
    gid = st['game_id']
    ck = Check()
    ck.true('座位 1 打 6p 后庄家应能荣和', ron_offered(c, gid, 0))
    if ck.bad:
        return ck.result()
    sc.run([(0, 'pass'), (2, 'discard', D('9m')), (3, 'discard', D('9m')), (0, 'discard', D('9m')),
            (1, 'discard', D('3p'))])
    ck.true('立直见逃后下一巡座位 1 打 3p，庄家不应能荣和', not ron_offered(c, gid, 0))
    return ck.result()


@case('R4', '荒牌流局：听牌的两家各收 1500，不听的两家各付 1500')
def r4(c):
    # 庄家听 3p 6p，座位 2 听 7s 9s（234m 567p 345s 888s 9s），座位 1、3 散牌不听。大家一直摸切到荒牌。
    # 3p 6p 7s 9s 放到牌山最深处（都进王牌，不会被摸到）；前四张摸牌不是风牌，避开四风连打
    wall = build_wall(hands={0: WAIT_3P6P,
                             1: h('1m 4m 7m 2p 5p 8p 3s 6s 1z 2z 3z 4z 9m'),
                             2: h('2m 3m 4m 5p 6p 7p 3s 4s 5s 8s 8s 8s 9s'),
                             3: h('3m 6m 9m 1p 4p 7p 1s 4s 6s 9p 5z 6z 2z')},
                      draws=['9p', '9p', '1s', '1s'], dora=['3z'], avoid=['3p', '6p', '7s', '9s'], aka=False)
    st, sc, end = play(c, wall, [], rules={'aka_dora': False}, until=lambda s: False, max_requests=1500)
    r = end.get('result') or {}
    ck = Check()
    ck.eq('结算类型', r.get('type'), 'ryuukyoku')
    ck.eq('delta', r.get('delta'), [1500, -1500, 1500, -1500])
    return ck.result()


@case('R5', '海底摸月：最后一张牌自摸')
def r5(c):
    # 座位 1：123m 456p 789s 南南 45m，听 3m 6m。3m 6m 都放进王牌，再把一张 3m 换到 wall[121]（第 70 张，座位 1 摸）。
    # 海底摸月 1 + 门前清自摸和 1 = 2 番；20 + 自摸 2 + 南雀头（自风）2 = 24 → 30 符；闲家自摸 500/1000 = 2000
    wall = build_wall(hands={1: h('1m 2m 3m 4p 5p 6p 7s 8s 9s 2z 2z 4m 5m')}, draws=['9p', '9p', '1s', '1s'],
                      dora=['3z'], avoid=['3m', '6m'], aka=False)
    put_last(wall, '3m')
    st, sc, end = play(c, wall, [(1, 'tsumo')], rules={'aka_dora': False}, max_requests=1500)
    w = win_of(end, 1)
    ck = Check()
    ck.true('役里有海底摸月', has_yaku(w, '海底'), [y['name'] for y in w['yaku']])
    ck.eq('(han, fu, points)', (w['han'], w['fu'], w['points']), (2, 30, 2000))
    return ck.result()


@case('R6', '河底捞鱼：最后一张打出的牌荣和')
def r6(c):
    # 座位 2：123m 456p 789s 西西 45m，听 3m 6m。座位 1 摸到 wall[121] 的 3m 摸切，座位 2 荣和。
    # 河底捞鱼 1 番；20 + 门清荣和 10 + 西雀头（自风）2 = 32 → 40 符；闲家 1300
    wall = build_wall(hands={2: h('1m 2m 3m 4p 5p 6p 7s 8s 9s 3z 3z 4m 5m')}, draws=['9p', '9p', '1s', '1s'],
                      dora=['4z'], avoid=['3m', '6m'], aka=False)
    put_last(wall, '3m')
    st, sc, end = play(c, wall, [(2, 'ron')], rules={'aka_dora': False}, max_requests=1500)
    w = win_of(end, 2)
    ck = Check()
    ck.true('役里有河底捞鱼', has_yaku(w, '河底'), [y['name'] for y in w['yaku']])
    ck.eq('(han, fu, points)', (w['han'], w['fu'], w['points']), (1, 40, 1300))
    return ck.result()


# ---------------------------------------------------------------- V 规则变体探测
#
# 这一节不判对错（除非程序前后矛盾或走不下去），只记下程序实际采用哪一种，结果写成 VAR(...)，
# 之后和各家自己的规则文档对照（参考规则第 8 节的开关表）。

from harness import ScriptStuck  # noqa: E402

YAOCHU = set('1m 9m 1p 9p 1s 9s 1z 2z 3z 4z 5z 6z 7z'.split())


def run_steps(c, wall, steps, rules=None, length='tonpuu', max_requests=600):
    """按剧本打；剧本走不完（一局提前结束）不报错。返回 (game_id, 座位 0 视角的最终状态, 剩下没走的步数)。"""
    st = start(c, wall, rules=rules, length=length)
    gid = st['game_id']
    sc = Script(c, gid, max_requests=max_requests)
    left = 0
    try:
        sc.run(steps)
    except ScriptStuck as e:
        left = int(str(e).split('剧本还剩 ')[1].split(' ')[0]) if '剧本还剩' in str(e) else -1
    return gid, c.state(gid, 0), left


def brief(res):
    r = res or {}
    if r.get('type') == 'agari':
        return 'agari wins=%s delta=%s' % ([(w['seat'], w['points'], w.get('yakuman')) for w in r['wins']], r.get('delta'))
    return '%s/%s delta=%s' % (r.get('type'), r.get('reason'), r.get('delta'))


@case('V1', '一炮双响 / 头跳')
def v1(c):
    # 庄家第一巡摸切 3p；座位 1（123m 456s 中中中 12p 99s，听 3p）和座位 2（456m 789s 發發發 45p 22m，听 3p 6p）都荣和
    wall = build_wall(hands={1: h('1m 2m 3m 4s 5s 6s 7z 7z 7z 1p 2p 9s 9s'),
                             2: h('4m 5m 6m 7s 8s 9s 6z 6z 6z 4p 5p 2m 2m')},
                      draws=['3p'], dora=['3z'], avoid=['3p', '6p'], aka=False)
    gid, s0, left = run_steps(c, wall, [(0, 'discard', D('3p')), (1, 'ron'), (2, 'ron')], rules={'aka_dora': False})
    r = s0.get('result') or {}
    n = len(r.get('wins') or [])
    kind = {2: '双响', 1: '头跳'}.get(n, '其他')
    return VAR('%s（%s）' % (kind, brief(r)))


@case('V2', '三家和了：流局 / 三人都和 / 头跳')
def v2(c):
    # 在 V1 基础上座位 3（345s 678m 白白白 12p 88s）也听 3p
    wall = build_wall(hands={1: h('1m 2m 3m 4s 5s 6s 7z 7z 7z 1p 2p 9s 9s'),
                             2: h('4m 5m 6m 7s 8s 9s 6z 6z 6z 4p 5p 2m 2m'),
                             3: h('3s 4s 5s 6m 7m 8m 5z 5z 5z 1p 2p 8s 8s')},
                      draws=['3p'], dora=['3z'], avoid=['3p', '6p'], aka=False)
    gid, s0, left = run_steps(c, wall, [(0, 'discard', D('3p')), (1, 'ron'), (2, 'ron'), (3, 'ron')], rules={'aka_dora': False})
    r = s0.get('result') or {}
    if r.get('type') == 'ryuukyoku':
        kind = '流局'
    else:
        kind = {3: '三人都和', 2: '两人和', 1: '头跳'}.get(len(r.get('wins') or []), '其他')
    return VAR('%s（%s）' % (kind, brief(r)))


@case('V3', '九种九牌')
def v3(c):
    # 庄家配牌 1m 9m 1p 9p 1s 9s 东南西 + 5m 6m 7p 8s，摸北：十种幺九
    wall = build_wall(hands={0: h('1m 9m 1p 9p 1s 9s 1z 2z 3z 5m 6m 7p 8s')}, draws=['4z'], dora=['5z'], aka=False)
    st = start(c, wall, rules={'aka_dora': False})
    gid = st['game_id']
    if legal(c.state(gid, 0), 'kyuushu') is None:
        return VAR('不采用（第一巡没有 kyuushu 选项）')
    c.action(gid, 0, 'kyuushu')
    s0 = c.state(gid, 0)
    r = s0.get('result') or {}
    if s0['phase'] == 'playing' or r.get('type') != 'ryuukyoku':
        return FAIL('给了 kyuushu 选项，执行后没有流局：phase %s，%s' % (s0['phase'], brief(r)))
    return VAR('采用（%s）' % brief(r))


@case('V4', '四风连打')
def v4(c):
    # 四家第一巡都摸到东、摸切（谁手里都没有东）
    wall = build_wall(draws=['1z', '1z', '1z', '1z'], dora=['5z'], aka=False)
    gid, s0, left = run_steps(c, wall, [(s, 'discard', D('1z')) for s in range(4)], rules={'aka_dora': False})
    r = s0.get('result') or {}
    if s0['phase'] == 'playing':
        return VAR('不采用（四张东打完还在打）')
    return VAR('采用（%s）' % brief(r)) if r.get('reason') == 'four_winds' else FAIL('四张东打完结束了，但不是 four_winds：%s' % brief(r))


@case('V5', '四家立直')
def v5(c):
    # 四家都听牌，第一巡依次摸 白 打白立直（庄家是两立直，无所谓）
    wall = build_wall(hands={0: h('1m 2m 3m 4m 5m 6m 7m 8m 9m 1z 1z 2p 3p'),
                             1: h('1s 2s 3s 4s 5s 6s 7s 8s 9s 2z 2z 5p 6p'),
                             2: h('1m 2m 3m 4s 5s 6s 7p 8p 9p 3z 3z 2s 3s'),
                             3: h('7m 8m 9m 4m 5m 6m 1p 2p 3p 4z 4z 8s 9s')},
                      draws=['5z', '5z', '5z', '5z'], dora=['6z'], ura=['6z'],
                      avoid=['1p', '4p', '7p', '1s', '4s', '7s'], aka=False)
    gid, s0, left = run_steps(c, wall, [(s, 'riichi', D('5z')) for s in range(4)], rules={'aka_dora': False})
    r = s0.get('result') or {}
    if left:
        return FAIL('四家立直剧本没走完（还剩 %d 步），%s' % (left, brief(r)))
    if s0['phase'] == 'playing':
        return VAR('不采用（第四家立直后还在打）')
    return VAR('采用（%s）' % brief(r)) if r.get('reason') == 'four_riichi' else FAIL('第四家立直后结束了，但不是 four_riichi：%s' % brief(r))


@case('V6', '流局满贯')
def v6(c):
    # 座位 1 整局摸到的全是幺九牌、一直摸切、没人鸣；四家配牌都是中张牌。荒牌时看座位 1 有没有流局满贯
    import random as _r
    rng = _r.Random(6)
    simples = [n + s for s in 'mps' for n in '2345678' for _ in range(4)]
    rng.shuffle(simples)
    hands = {k: simples[13 * k:13 * k + 13] for k in range(4)}
    wall = build_wall(hands=hands, dora=['5z'], aka=False)
    targets = [53 + 4 * k for k in range(18)]          # 座位 1 的 18 次摸牌
    for t in targets:
        if wall[t] in YAOCHU:
            continue
        j = next(i for i in range(56, 136) if i not in targets and i != 122 and wall[i] in YAOCHU)
        wall[t], wall[j] = wall[j], wall[t]
    gid, s0, left = run_steps(c, wall, [], rules={'aka_dora': False}, max_requests=1500)
    sc = Script(c, gid, max_requests=1500)
    s0 = sc.run([], until=lambda s: False)
    r = s0.get('result') or {}
    river = [d['tile'] for d in c.state(gid, 0)['players'][1]['discards']]
    if not all(t in YAOCHU for t in river):
        return FAIL('剧本没拼对：座位 1 河里有中张 %r' % river)
    d = r.get('delta') or [0, 0, 0, 0]
    if d[1] >= 8000:
        return VAR('采用（%s）' % brief(r))
    return VAR('不采用（%s）' % brief(r))


@case('V7', '明杠后的杠宝：立即翻 / 打牌后翻')
def v7(c):
    # 座位 1 手里三张 9p，庄家摸切 9p，座位 1 大明杠，摸岭上牌后、打牌前看 dora_indicators 有几张
    wall = build_wall(hands={1: h('9p 9p 9p 1m 4m 7m 2s 5s 8s 1z 2z 3z 4z')}, draws=['9p'], dora=['5z', '6z'],
                      rinshan=['7z'], aka=False)
    st = start(c, wall, rules={'aka_dora': False})
    gid = st['game_id']
    c.action(gid, 0, 'discard', **D('9p'))
    for s in (2, 3):
        if s in (c.state(gid, 0).get('waiting_for') or []) and legal(c.state(gid, s), 'pass'):
            c.action(gid, s, 'pass')
    if legal(c.state(gid, 1), 'minkan') is None:
        return FAIL('座位 1 没有大明杠选项')
    c.action(gid, 1, 'minkan')
    n_before = len(c.state(gid, 1).get('dora_indicators') or [])
    s1 = c.state(gid, 1)
    t = s1.get('drawn') or (legal(s1, 'discard') or {}).get('tiles', [None])[-1]
    c.action(gid, 1, 'discard', tile=t, tsumogiri=bool(s1.get('drawn')))
    n_after = len(c.state(gid, 1).get('dora_indicators') or [])
    if (n_before, n_after) == (2, 2):
        return VAR('立即翻')
    if (n_before, n_after) == (1, 2):
        return VAR('打牌后翻')
    return FAIL('杠宝指示牌张数：杠后 %d、打牌后 %d' % (n_before, n_after))


@case('V8', '食替')
def v8(c):
    # 座位 1 手里 2m 3m 4m 5m，庄家摸切 2m，座位 1 用 3m 4m 吃：看 2m（现物食替）和 5m（筋食替）能不能打
    wall = build_wall(hands={1: h('2m 3m 4m 5m 1p 4p 7p 2s 5s 8s 1z 2z 3z')}, draws=['2m'], dora=['5z'], aka=False)
    st = start(c, wall, rules={'aka_dora': False})
    gid = st['game_id']
    c.action(gid, 0, 'discard', **D('2m'))
    for s in (2, 3):
        if s in (c.state(gid, 0).get('waiting_for') or []) and legal(c.state(gid, s), 'pass'):
            c.action(gid, s, 'pass')
    chi = legal(c.state(gid, 1), 'chi')
    if chi is None:
        return FAIL('座位 1 没有吃的选项')
    c.action(gid, 1, 'chi', tiles=['3m', '4m'])
    tiles = (legal(c.state(gid, 1), 'discard') or {}).get('tiles') or []
    same, suji = '2m' in tiles, '5m' in tiles
    if not same and not suji:
        return VAR('禁止（2m、5m 都不能打）')
    if same and suji:
        return VAR('允许（2m、5m 都能打）')
    return VAR('只禁%s（2m %s，5m %s）' % ('现物' if not same else '筋', '能打' if same else '不能打', '能打' if suji else '不能打'))


@case('V9', '包（大三元）')
def v9(c):
    # 座位 1：白白 發發 中中 123m 45p 99s。依次碰庄家的白、座位 2 的發、座位 3 的中（第三张三元牌，座位 3 包），
    # 之后自摸 3p：大三元。包：座位 3 一家付 32000；不包：庄 16000、闲各 8000
    wall = build_wall(hands={1: h('5z 5z 6z 6z 7z 7z 1m 2m 3m 4p 5p 9s 9s')},
                      draws=['5z', '6z', '9m', '7z', '9m', '9m', '9m', '3p'], dora=['1z'], avoid=['3p', '6p'], aka=False)
    steps = [(0, 'discard', D('5z')), (1, 'pon', {'tiles': ['5z', '5z']}), (1, 'discard', D('1m', False)),
             (2, 'discard', D('6z')), (1, 'pon', {'tiles': ['6z', '6z']}), (1, 'discard', D('2m', False)),
             (2, 'discard', D('9m')), (3, 'discard', D('7z')), (1, 'pon', {'tiles': ['7z', '7z']}),
             (1, 'discard', D('3m', False)), (1, 'tsumo')]
    gid, s0, left = run_steps(c, wall, steps, rules={'aka_dora': False})
    r = s0.get('result') or {}
    if left or r.get('type') != 'agari':
        return FAIL('剧本没走完（还剩 %d 步）：%s' % (left, brief(r)))
    d = r['delta']
    if d == [0, 32000, 0, -32000]:
        return VAR('采用（座位 3 付 32000）')
    if d == [-16000, 32000, -8000, -8000]:
        return VAR('不采用（%s）' % d)
    return FAIL('大三元自摸 delta 对不上两种规则：%s' % brief(r))


@case('V10', '击飞')
def v10(c):
    # 庄家暗刻 白白白 發發發 + 中中 123m 99s，座位 1 第一巡打中，庄家荣和大三元 48000：座位 1 变成 -23000
    wall = build_wall(hands={0: h('5z 5z 5z 6z 6z 6z 7z 7z 1m 2m 3m 9s 9s'),
                             1: h('7z 1p 4p 7p 2s 5s 8s 2m 5m 8m 3p 6p 1z')},
                      draws=['2z', '4z'], dora=['3z'], avoid=['7z', '9s'], aka=False)
    gid, s0, left = run_steps(c, wall, [(0, 'discard', D('2z')), (1, 'discard', D('7z', False)), (0, 'ron')],
                              rules={'aka_dora': False})
    r = s0.get('result') or {}
    if r.get('type') != 'agari':
        return FAIL('没和牌：%s' % brief(r))
    return VAR('%s（phase %s，%s）' % ('采用' if s0['phase'] == 'game_end' else '不采用', s0['phase'], brief(r)))


def _pass_others(c, gid, skip=()):
    for s in range(4):
        if s in skip:
            continue
        if s in (c.state(gid, 0).get('waiting_for') or []) and legal(c.state(gid, s), 'pass'):
            c.action(gid, s, 'pass')


@case('V7b', '明杠后打出的牌被碰：杠宝什么时候翻')
def v7b(c):
    # 同 V7，座位 1 大明杠后打 1z，座位 2（手里两张 1z）碰。看碰之后 dora_indicators 有几张
    wall = build_wall(hands={1: h('9p 9p 9p 1m 4m 7m 2s 5s 8s 1z 2z 3z 4z'),
                             2: h('1z 1z 2m 5m 8m 3p 6p 3s 6s 9s 5z 6z 7z')},
                      draws=['9p'], dora=['5z', '6z'], rinshan=['7z'], avoid=['1z'], aka=False)
    st = start(c, wall, rules={'aka_dora': False})
    gid = st['game_id']
    c.action(gid, 0, 'discard', **D('9p'))
    _pass_others(c, gid, skip=(1,))
    if legal(c.state(gid, 1), 'minkan') is None:
        return FAIL('座位 1 没有大明杠选项')
    c.action(gid, 1, 'minkan')
    n_kan = len(c.state(gid, 1).get('dora_indicators') or [])
    c.action(gid, 1, 'discard', tile='1z', tsumogiri=False)
    _pass_others(c, gid, skip=(2,))
    if legal(c.state(gid, 2), 'pon') is None:
        return FAIL('座位 2 没有碰 1z 的选项')
    c.action(gid, 2, 'pon', tiles=['1z', '1z'])
    n_pon = len(c.state(gid, 2).get('dora_indicators') or [])
    return VAR('杠后 %d 张、打出的牌被碰后 %d 张' % (n_kan, n_pon))


@case('V11', '国士无双抢暗杠')
def v11(c):
    # 座位 1 国士听 1z（单骑）；座位 2 手里三张东、第一次摸到第四张东暗杠：座位 1 能不能抢
    wall = build_wall(hands={1: h('1m 9m 1p 9p 1s 9s 2z 3z 4z 5z 6z 7z 9s'),
                             2: h('1z 1z 1z 2m 5m 8m 3p 6p 3s 6s 4m 7p 8s')},
                      draws=['2s', '2p', '1z'], dora=['5z'], aka=False)
    st, sc, end = play(c, wall, [(0, 'discard', D('2s')), (1, 'discard', D('2p'))], rules={'aka_dora': False})
    gid = st['game_id']
    if legal(c.state(gid, 2), 'ankan') is None:
        return FAIL('座位 2 没有暗杠选项')
    c.action(gid, 2, 'ankan', tile='1z')
    if legal(c.state(gid, 1), 'ron') is None:
        return VAR('不允许')
    c.action(gid, 1, 'ron')
    _pass_others(c, gid, skip=(1,))
    s0 = c.state(gid, 0)
    r = s0.get('result') or {}
    if r.get('type') != 'agari':
        return FAIL('给了 ron 选项，荣和后没有结算：%s' % brief(r))
    return VAR('允许（%s）' % brief(r))


@case('V12', '四杠散了：两个人合计四杠')
def v12(c):
    # 庄家手里 9p×4、1s×4，第一巡连开两个暗杠；座位 1 手里 9m×4、1p×4，也连开两个暗杠，然后打出岭上牌
    wall = build_wall(hands={0: h('9p 9p 9p 9p 1s 1s 1s 1s 2m 5m 8m 3p 6p'),
                             1: h('9m 9m 9m 9m 1p 1p 1p 1p 2s 5s 8s 4m 7m')},
                      draws=['4z', '4z'], dora=['5z'], rinshan=['2z', '2z', '3z', '3z'],
                      avoid=['2z', '3z', '4z'], aka=False)
    st = start(c, wall, rules={'aka_dora': False})
    gid = st['game_id']

    def kan_then_discard(seat, tiles):
        for t in tiles:
            a = legal(c.state(gid, seat), 'ankan')
            if a is None or t not in (a.get('tiles') or []):
                raise AssertionError('座位 %d 没有暗杠 %s 的选项' % (seat, t))
            c.action(gid, seat, 'ankan', tile=t)
            if c.state(gid, 0)['phase'] != 'playing':
                return
        s = c.state(gid, seat)
        c.action(gid, seat, 'discard', tile=s['drawn'], tsumogiri=True)
        _pass_others(c, gid)

    kan_then_discard(0, ['9p', '1s'])
    kan_then_discard(1, ['9m', '1p'])
    s0 = c.state(gid, 0)
    r = s0.get('result') or {}
    if s0['phase'] == 'playing':
        return VAR('不流局（两人合计四杠后还在打）')
    return VAR('流局（%s）' % brief(r)) if r.get('reason') == 'four_kans' else FAIL('结束了但不是 four_kans：%s' % brief(r))


# ---------------------------------------------------------------- C Codex 补测（2026-11-23，牌例见 bug清单.md “补测牌例”）

@case('I4b', '四席都是电脑：开局直接推进，不等座位 0')
def i4b(c):
    st = c.new_game(players=['bot'] * 4, length='tonpuu', seed=1)
    s0 = c.state(st['game_id'], 0)
    if s0['phase'] == 'playing' and (s0.get('waiting_for') or []):
        return FAIL('四个 bot 时停在 playing，waiting_for %r' % s0.get('waiting_for'))
    return PASS()


@case('I4c', '只有座位 1 是真人：new_game 仍返回座位 0 的视角')
def i4c(c):
    st = c.new_game(players=['bot', 'human', 'bot', 'bot'], length='tonpuu', seed=1)
    return PASS() if st.get('viewer') == 0 else FAIL('new_game 返回的 viewer 是 %r（接口说明：座位 0 的视角）' % st.get('viewer'))


@case('I16', '和牌结算里的副露带 type、from、called_tile')
def i16(c):
    # 座位 1：白白 222m 666s 88p 99s 东；碰庄家摸切的白，打东；第二巡自摸 8p（白 + 对对和 + 三暗刻）
    wall = build_wall(hands={1: h('5z 5z 2m 2m 2m 6s 6s 6s 8p 8p 9s 9s 1z')}, draws=['5z', '9m', '9m', '9m', '8p'],
                      dora=['3z'], avoid=['8p', '9s'], aka=False)
    st, sc, end = play(c, wall, [(0, 'discard', D('5z')), (1, 'pon', {'tiles': ['5z', '5z']}), (1, 'discard', D('1z', False)),
                                 (1, 'tsumo')], rules={'aka_dora': False})
    w = win_of(end, 1)
    m = (w.get('melds') or [None])[0] or {}
    ck = Check()
    ck.eq('wins[].melds[0].type', m.get('type'), 'pon')
    ck.eq('wins[].melds[0].from', m.get('from'), 0)
    ck.eq('wins[].melds[0].called_tile', m.get('called_tile'), '5z')
    return ck.result()


@case('W4', '食替：吃完只剩禁打的牌，这种吃法不该给')
def w4(c):
    # 座位 1：白白 發發 中中 2340m 123p。依次碰庄家的白、發、中（每次碰后打 1p、2p、3p），手里剩 2m 3m 4m 0m。
    # 庄家再打 2m：用 3m 4m 吃会只剩 2m（现物）和 0m（筋），都是食替禁牌，这个吃法应被过滤
    wall = build_wall(hands={1: h('5z 5z 6z 6z 7z 7z 2m 3m 4m 0m 1p 2p 3p')},
                      draws=['5z', '9m', '1s', '6z', '9m', '1s', '7z', '9m', '1s', '2m'], dora=['3z'], avoid=['2m', '5m'])
    steps = [(0, 'discard', D('5z')), (1, 'pon', {'tiles': ['5z', '5z']}), (1, 'discard', D('1p', False)),
             (2, 'discard', D('9m')), (3, 'discard', D('1s')), (0, 'discard', D('6z')),
             (1, 'pon', {'tiles': ['6z', '6z']}), (1, 'discard', D('2p', False)),
             (2, 'discard', D('9m')), (3, 'discard', D('1s')), (0, 'discard', D('7z')),
             (1, 'pon', {'tiles': ['7z', '7z']}), (1, 'discard', D('3p', False)),
             (2, 'discard', D('9m')), (3, 'discard', D('1s')), (0, 'discard', D('2m'))]
    st, sc, end = play(c, wall, steps)
    s1 = c.state(st['game_id'], 1)
    if legal(s1, 'ron') is None:
        raise AssertionError('牌例没拼对：座位 1 这时应能荣和 2m（大三元）')
    chi = legal(s1, 'chi')
    opts = [sorted(map(norm, o)) for o in (chi or {}).get('options') or []]
    return FAIL('吃的选项里有 3m 4m：%r' % chi.get('options')) if ['3m', '4m'] in opts else PASS()


@case('W5b', '立直宣言牌被荣和：结算里宣言者 riichi 为 false')
def w5b(c):
    wall = build_wall(hands={1: h('2m 3m 4m 6p 7p 8p 2s 3s 4s 6s 7s 9p 1z'),
                             2: h('7z 7z 7z 3m 4m 5m 4p 5p 6p 6s 7s 8s 1z')},
                      draws=['2z', '9p'], dora=['3z'], avoid=['1z'])
    st, sc, end = play(c, wall, [(1, 'riichi', D('1z', False)), (2, 'ron')])
    r = end['players'][1].get('riichi')
    return PASS() if not r else FAIL('座位 1 的 riichi 是 %r' % r)


@case('H3', '立直后的弃牌提示只列能打的牌')
def h3(c):
    # 庄家听 3p 6p，第一巡摸东打出立直；其余三家摸切；庄家第二巡摸 6p：只能摸切（或自摸），提示的键也只能是 6p
    wall = build_wall(hands={0: WAIT_3P6P}, draws=['1z', '9p', '9p', '1s', '6p'], dora=['3z'], ura=['3z'],
                      avoid=['3p', '6p'], aka=False)
    st, sc, end = play(c, wall, [(0, 'riichi', D('1z')), (1, 'discard', D('9p')), (2, 'discard', D('9p')),
                                 (3, 'discard', D('1s'))], rules={'aka_dora': False})
    s = c.state(st['game_id'], 0)
    can = set((legal(s, 'discard') or {}).get('tiles') or [])
    keys = set(((s.get('hints') or {}).get('discards') or {}).keys())
    extra = keys - can
    return FAIL('提示了不能打的牌 %s（能打的只有 %s）' % (sorted(extra), sorted(can))) if extra else PASS()


# 多局：W7b、W10、W11 共用的前三局。每局和牌方 111z 456m 789p 234p 9s 单骑，庄家第一张摸切 9s 放铳
WIN_9S = h('1z 1z 1z 4m 5m 6m 7p 8p 9p 2p 3p 4p 9s')


def _three_rounds(c, length):
    plan = [(0, 3, '8m'), (1, 0, '8s'), (2, 0, '8m')]   # (庄家=放铳者, 和牌者, 宝牌指示牌)
    gid = None
    for i, (dealer, winner, dora) in enumerate(plan):
        wall = build_wall(hands={winner: WIN_9S}, draws=['9s'], dora=[dora], avoid=['9s'], aka=False)
        if i == 0:
            gid = start(c, wall, rules={'aka_dora': False}, length=length)['game_id']
        else:
            c.next(gid, 0, wall=wall)
        Script(c, gid).run([(dealer, 'discard', D('9s')), (winner, 'ron')])
    scores = [p['score'] for p in c.state(gid, 0)['players']]
    if scores != [30200, 19800, 23700, 26300]:
        raise AssertionError('前三局后点数 %r（应为 [30200, 19800, 23700, 26300]）' % scores)
    return gid


@case('W7b', '半庄战：东 4 局有人过 30000 也要进南场')
def w7b(c):
    gid = _three_rounds(c, 'hanchan')
    # 东 4（庄家座位 3）：庄家摸切 9s，座位 0 荣和 1300，最高 31500
    c.next(gid, 0, wall=build_wall(hands={0: WIN_9S}, draws=['9s'], dora=['8m'], avoid=['9s'], aka=False))
    end = Script(c, gid).run([(3, 'discard', D('9s')), (0, 'ron')])
    return PASS() if end['phase'] == 'round_end' else FAIL('半庄东 4 局后 phase 是 %s' % end['phase'])


@case('W10', '末局庄家和牌后和起家同分：按起家顺序不是第一，不能和了止')
def w10(c):
    gid = _three_rounds(c, 'tonpuu')
    # 东 4：庄家座位 3、座位 0、1 摸切中，座位 2 摸切 9s，庄家荣和（连风东刻 2 番 40 符 3900）→ 座位 0、3 都是 30200
    c.next(gid, 0, wall=build_wall(hands={3: WIN_9S}, draws=['7z', '7z', '7z', '9s'], dora=['8m'], avoid=['9s'], aka=False))
    end = Script(c, gid).run([(3, 'discard', D('7z')), (0, 'discard', D('7z')), (1, 'discard', D('7z')),
                              (2, 'discard', D('9s')), (3, 'ron')])
    sc = [p['score'] for p in end['players']]
    if sc[0] != 30200 or sc[3] != 30200:
        return FAIL('东 4 后点数 %r，牌例没拼对' % sc)
    return PASS() if end['phase'] == 'round_end' else FAIL('同分时 phase 是 %s（起家优先，庄家不是第一）' % end['phase'])


@case('W11', '终局剩余供托归第一名：要算进最后一局的 delta')
def w11(c):
    gid = _three_rounds(c, 'tonpuu')
    # 东 4：R4 的四家配牌；庄家座位 3 摸切 9p，座位 0 摸 9p 打出立直，大家摸切到荒牌。座位 0、2 听牌。
    # 座位 0：立直交 1000（29200），听牌料 +1500，终局拿回供托 +1000 → 31700，delta[0] 应为 2500
    wall = build_wall(hands={0: WAIT_3P6P,
                             1: h('1m 4m 7m 2p 5p 8p 3s 6s 1z 2z 3z 4z 9m'),
                             2: h('2m 3m 4m 5p 6p 7p 3s 4s 5s 8s 8s 8s 9s'),
                             3: h('3m 6m 9m 1p 4p 7p 1s 4s 6s 9p 5z 6z 2z')},
                      draws=['9p', '9p', '1s', '1s'], dora=['3z'], ura=['3z'], avoid=['3p', '6p', '7s', '9s'], aka=False)
    c.next(gid, 0, wall=wall)
    sc = Script(c, gid, max_requests=1500)
    sc.run([(3, 'discard', D('9p')), (0, 'riichi', D('9p'))])
    end = sc.run([], until=lambda s: False)
    r = end.get('result') or {}
    ck = Check()
    ck.eq('phase', end['phase'], 'game_end')
    ck.eq('座位 0 终局点数', end['players'][0]['score'], 31700)
    ck.eq('delta', r.get('delta'), [2500, -1500, 1500, -1500])
    return ck.result()


@case('K6', '两人合计第四杠打出的牌没人荣和：四杠散了，不能再碰')
def k6(c):
    wall = build_wall(hands={0: h('9p 9p 9p 9p 1s 1s 1s 1s 2m 5m 8m 3p 7p'),
                             1: h('9m 9m 9m 9m 1p 1p 1p 1p 2s 2s 2s 3p 4p'),
                             2: h('6p 6p 1m 4m 7m 1z 2z 3z 4z 3s 4s 5s 8s'),
                             3: h('5z 5z 5z 4m 5m 6m 7s 8s 9s 4p 5p 6z 6z')},
                      draws=['4z', '2p', '7z'], dora=['3z', '4s', '4m', '5s', '7m'], ura=['1z'],
                      rinshan=['2z', '2z', '6p', '6p'], aka=False)
    st = start(c, wall, rules={'aka_dora': False})
    gid = st['game_id']
    for seat, tiles in ((0, ['9p', '1s']), (1, ['9m', '1p'])):
        for t in tiles:
            c.action(gid, seat, 'ankan', tile=t)
        d = c.state(gid, seat)['drawn']
        c.action(gid, seat, 'discard', tile=d, tsumogiri=True)
        if seat == 0:
            _pass_others(c, gid)
    # 座位 1 打出 6p；座位 3 能荣和，pass
    if legal(c.state(gid, 3), 'ron') is not None:
        c.action(gid, 3, 'ron' if False else 'pass')
    s0 = c.state(gid, 0)
    if s0['phase'] != 'playing':
        r = s0.get('result') or {}
        return PASS('流局 %s' % r.get('reason'))
    p = legal(c.state(gid, 2), 'pon')
    if p is None:
        return VAR('没流局，座位 2 也没有碰的选项（%r）' % s0.get('waiting_for'))
    c.action(gid, 2, 'pon', tiles=['6p', '6p'])
    s0 = c.state(gid, 0)
    if s0['phase'] != 'playing':
        return PASS('给了碰的选项，但碰后仍按四杠散了流局（%s）' % (s0.get('result') or {}).get('reason'))
    return FAIL('第四杠打出的牌被碰成功，牌局继续（没按四杠散了流局）')
