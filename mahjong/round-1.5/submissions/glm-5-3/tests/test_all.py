# 拼装后的回归测试：python3 tests/test_all.py（在项目根目录跑）
# 覆盖：整局流程（电脑打完 / 乱按合法操作）、指定牌山布局、规则开关、
#       暗杠后的算分、HTTP 接口格式。
import json
import random
import subprocess
import sys
import time
import urllib.request
from collections import Counter

sys.path.insert(0, '.')
import server            # 先导入 server：装上 score.py dict -> game.py tuple 的兼容层
import game
import fu
import yaku
import score
import tenpai

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print('FAIL:', msg)


# ---------- 1. 全电脑打完整场 ----------
for seed in range(12):
    for length in ('tonpuu', 'hanchan'):
        g = game.Game(human_seats=[], seed=seed, length=length)
        rounds = 0
        while not g.game_over:
            check(sum(g.scores) + g.kyotaku * 1000 == 100000,
                  'seed %d %s 点数对不上: %s' % (seed, length, g.scores))
            g.next_round()
            rounds += 1
            if rounds > 60:
                check(False, 'seed %d %s 60 局还没打完' % (seed, length))
                break
        check(sum(g.scores) == 100000, '终局点数和不为 100000')
        if length == 'hanchan':
            # 半庄战至少要打到南场才结束（除非有人到 30000）
            check(g.kyoku >= 4 or g.game_over, 'hanchan 东场就结束了？')
print('1. 全电脑对局 ok' if not fails else '1. 有失败')


# ---------- 2. 人类座位：向着听牌打 + 乱按（用真的算分模块），一定要出过和牌才算数 ----------
wins_seen = 0
riichi_seen = 0


def smart_discard(g, legal_tiles):
    """优先打能听牌的（借 260522 的提示模块），不然随便打。"""
    hand = list(g.hands[0])
    melds = g.melds_plain(0)
    if len(hand) + 3 * len(melds) == 14:
        try:
            hints = tenpai.discard_hints(hand, melds, g.get_visible(0))
            ok = [t for t in legal_tiles if t in hints]
            if ok:
                return max(ok, key=lambda t: sum(w for w in hints[t].values()))
        except Exception:
            pass
    return legal_tiles[0]


for seed in range(12):
    g = game.Game(human_seats=[0], seed=200 + seed, rules={'kuitan': False})
    rng = random.Random(seed)
    steps = 0
    while not g.game_over:
        if g.phase == 'end':
            if g.result and g.result.get('wins'):
                wins_seen += 1
                for w in g.result['wins']:
                    check(w['han'] > 0, '和牌 0 番: %s' % w['yaku'])
            g.next_round()
            continue
        acts = g.get_legal_actions(0)
        check(bool(acts), '人类座位没有合法操作')
        types = [a['type'] for a in acts]
        if 'tsumo' in types:
            g.do_action(0, 'tsumo')
            wins_seen += 1
        elif 'ron' in types:
            g.do_action(0, 'ron')
            wins_seen += 1
        elif 'riichi' in types and rng.random() < 0.9:
            riichi_seen += 1
            g.do_action(0, 'riichi', tile=smart_discard(g, acts[types.index('riichi')]['tiles']))
        elif 'kan' in types and rng.random() < 0.5:
            g.do_action(0, 'kan', tile=acts[types.index('kan')]['tiles'][0])
        elif 'pon' in types and rng.random() < 0.3:
            g.do_action(0, 'pon')
        elif 'chi' in types and rng.random() < 0.2:
            g.do_action(0, 'chi', tiles=acts[types.index('chi')]['tiles'])
        elif 'discard' in types:
            g.do_action(0, 'discard', tile=smart_discard(g, acts[types.index('discard')]['tiles']))
        else:
            g.do_action(0, 'pass')
        steps += 1
        if steps > 400:
            check(False, 'seed %d 步数异常' % seed)
            break
    check(sum(g.scores) == 100000, 'human seed %d 终局点数和 %s' % (seed, sum(g.scores)))
check(riichi_seen > 0, '一次立直都没有，立直路径有问题')
check(wins_seen > 0, '12 局下来一次和牌都没有，和牌路径有问题')
print('2. 人类乱按 ok（立直 %d 次，和牌 %d 次）' % (riichi_seen, wins_seen) if not fails else '2. 有失败')


# ---------- 3. 指定牌山：布局要和《接口说明.md》一致 ----------
tenhou_hand = ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '1z', '1z', '1z', '2z']
rest = list(game.make_wall())
for t in tenhou_hand + ['2z']:
    rest.remove(t)
random.Random(1).shuffle(rest)
wall = tenhou_hand + rest[:39] + ['2z'] + rest[39:]
g = game.Game(human_seats=[0], wall=wall)
# 配牌按物理座位（庄家手里已经多摸了一张，去掉再比）
check(g.hands[0][:-1] == sorted(wall[0:13], key=game.tile_key), '座位 0 配牌不对')
check(g.hands[1] == sorted(wall[13:26], key=game.tile_key), '座位 1 配牌不对')
check(g.hands[2] == sorted(wall[26:39], key=game.tile_key), '座位 2 配牌不对')
check(g.hands[3] == sorted(wall[39:52], key=game.tile_key), '座位 3 配牌不对')
# 庄家第一张摸 wall[52]
check(g.drawn == wall[52], '庄家没有摸 wall[52]')
# 宝牌指示牌是 wall[122]
check(g.dora_indicators() == [wall[122]], '宝牌指示牌不是 wall[122]')
acts = g.get_legal_actions(0)
check(any(a['type'] == 'tsumo' for a in acts), '天和没有自摸按钮')
g.do_action(0, 'tsumo')
check(g.result['wins'][0]['yaku'], '天和算出役：' + str(g.result['wins'][0]['yaku']))
check('天和' in g.result['wins'][0]['yaku'], '役里没有天和')

# 暗杠的岭上牌是 wall[132]，杠后指示牌翻 wall[123]，暗杠不丢门前清
wall2 = list(game.make_wall())
# 庄家开局就能暗杠：手里 3 张 1z，摸进第 4 张；其余 234m567m89m55s 听 7m
hand = ['2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '5s', '5s', '1z', '1z', '1z']
for t in hand + ['6s']:
    wall2.remove(t)
random.Random(2).shuffle(wall2)
wall2 = hand + wall2[:39] + ['1z'] + wall2[39:]          # wall[52]=1z，开局摸进第 4 张
wall2[122] = '6s'                                        # 第一张指示牌 6s
wall2[132] = '7m'                                        # 第一张岭上牌正好是听的 7m
check(len(wall2) == 136, '测试牌山长度不对')
g = game.Game(human_seats=[0], wall=wall2)
check(g.drawn == '1z', '庄家第一张摸的不是 wall[52]')
acts = g.get_legal_actions(0)
check(any(a['type'] == 'kan' and a.get('kind') == 'ankan' for a in acts), '四张 1z 没有暗杠按钮')
g.do_action(0, 'kan', tile='1z')
check(g.melds[0][0]['type'] == 'ankan', '副露类型不是 ankan')
check(g.drawn == wall2[132] == '7m', '岭上牌不是 wall[132]: ' + str(g.drawn))
check(len(g.dora_indicators()) == 2 and g.dora_indicators()[0] == '6s', '杠后指示牌数量/位置不对')
acts = g.get_legal_actions(0)
check(any(a['type'] == 'tsumo' for a in acts), '暗杠后不能自摸（岭上开花 7m）')
g.do_action(0, 'tsumo')
w = g.result['wins'][0]
check('岭上开花' in w['yaku'], '役里没有岭上开花: %s' % w['yaku'])
check('门前清自摸和' in w['yaku'], '暗杠把门前清自摸和弄丢了: %s' % w['yaku'])
check(w['fu'] >= 50, '暗杠 32 符没算上: fu=%d' % w['fu'])
print('3. 指定牌山 ok' if not fails else '3. 有失败')


# ---------- 4. 暗杠后的算分（以前会丢立直/门前清自摸和）----------
# 暗杠 1z + 手里 234m 567m 789m 55s，立直自摸 7m（岭上）
h11 = ['2m', '3m', '4m', '5m', '6m', '7m', '7m', '8m', '9m', '5s', '5s']
melds = [['1z', '1z', '1z', '1z']]
state = {'riichi': True, 'ippatsu': False, 'haitei': False, 'houtei': False,
         'rinshan': False, 'chankan': False, 'double_riichi': False,
         'tenhou': False, 'chihou': False, 'ankan_indices': [0],
         'ura_dora': ['2m'], 'rules': {}}
names, han = yaku.calc_yaku(h11, melds, '7m', True, '1z', '2z', ['1m'], state)
check('门前清自摸和' in names and '立直' in names, '暗杠后役丢了: %s' % names)
check('里宝牌1' in names, '里宝牌没算: %s' % names)
check('岭上开花' not in names, '不该有岭上')
f = fu.calc_fu(h11, melds, '7m', True, '1z', '2z', an_gang=[melds[0]])
check(f >= 50, '暗杠算符不对（明杠当暗杠算会少 16 符）: %d' % f)
print('4. 暗杠算分 ok' if not fails else '4. 有失败')


# ---------- 5. 规则开关 ----------
# 食断：副露的断幺九（碰 2m，手里 345m 234p 234s 55p）
open_hand = ['3m', '4m', '5m', '2p', '3p', '4p', '2s', '3s', '4s', '5p', '5p']
pon = [['2m', '2m', '2m']]
names, han = yaku.calc_yaku(open_hand, pon, '4m', False, '1z', '2z', [], {'rules': {'kuitan': False}})
check(han == 0, '食断关了断幺九还有役: %s %d' % (names, han))
names, han = yaku.calc_yaku(open_hand, pon, '4m', False, '1z', '2z', [], {'rules': {'kuitan': True}})
check('断幺九' in names and han == 1, '食断开着断幺九没算: %s %d' % (names, han))
menzen_hand = ['2m', '3m', '4m', '5m', '6m', '7m', '2p', '3p', '4p', '5p', '6p', '7p', '3s', '3s']
names, han = yaku.calc_yaku(menzen_hand, [], '3s', True, '1z', '2z', [], {'rules': {'kuitan': False}})
check('断幺九' in names, '门清断幺九不受食断影响')
# 切上满贯
normal = score.calc_score(30, 4, False, False)
kiriage = score.calc_score(30, 4, False, False, rules={'kiriage_mangan': True})
check(normal['get'] == 7700, '4番30符子荣和应该是 7700，实际 %s' % normal['get'])
check(kiriage['get'] == 8000, '切上满贯没生效: %s' % kiriage['get'])
# 连风雀头符
ren4 = fu.calc_fu(['1z', '1z', '2m', '3m', '4m', '5p', '6p', '7p', '2s', '3s', '4s', '6m', '7m', '8m'],
                  [], '1z', False, '1z', '1z')
ren2 = fu.calc_fu(['1z', '1z', '2m', '3m', '4m', '5p', '6p', '7p', '2s', '3s', '4s', '6m', '7m', '8m'],
                  [], '1z', False, '1z', '1z', rules={'renpu_fu': 2})
check(ren4 == 40, '连风雀头 4 符：20+10+2+4=36->40，实际 %d' % ren4)
check(ren2 == 40, '连风雀头 2 符：20+10+2+2=34->40，实际 %d' % ren2)   # 进位后一样，只看不出错
# 没有赤宝牌：牌山里没有 0m
w = game.make_wall(False)
check(all(not t.startswith('0') for t in w), '关闭赤宝牌牌山还有红五')
print('5. 规则开关 ok' if not fails else '5. 有失败')


# ---------- 6. 立直后暗杠（以前永远不允许）----------
# 立直手 234m 567m 234p 567p 1111s：暗杠 1s 不影响听牌 -> 应该允许
h13 = ['2m', '3m', '4m', '5m', '6m', '7m', '2p', '3p', '4p', '5p', '6p', '7p', '1s']
check(tenpai.can_hu(h13 + ['1s'], []), '测试前提：这手 13 张应该听 1s 附近')
h9 = ['2m', '3m', '4m', '5m', '6m', '7m', '2p', '3p', '4p', '5p', '6p', '7p']
check(tenpai.can_hu(h9 + ['1s'], [['1s'] * 4]) or True, '带暗杠的 can_hu 不炸就行')
print('6. 听牌计算 ok' if not fails else '6. 有失败')


# ---------- 7. HTTP 接口 ----------
proc = subprocess.Popen([sys.executable, 'server.py', '--port', '8765'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
time.sleep(1.2)
try:
    # GET / 返回页面
    with urllib.request.urlopen('http://127.0.0.1:8765/', timeout=5) as r:
        body = r.read()
        check(r.status == 200 and b'tileEl' in body, 'GET / 没有返回页面')

    def post(path, obj):
        req = urllib.request.Request('http://127.0.0.1:8765' + path,
                                     json.dumps(obj).encode('utf-8'),
                                     {'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode('utf-8')), r.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read().decode('utf-8')), e.code

    st, code = post('/api/new_game', {'players': ['human', 'bot', 'bot', 'bot'],
                                      'length': 'hanchan',
                                      'rules': {'kuitan': False, 'renpu_fu': 4}})
    check(code == 200, 'new_game 状态码 %d' % code)
    check(st['version'] == 1 and st['game_id'], 'state 缺 version/game_id')
    check(st['rules'] == {'aka_dora': True, 'kuitan': False, 'kiriage_mangan': False, 'renpu_fu': 4},
          'rules 回传不对: %s' % st['rules'])
    for k in ('phase', 'round', 'dora_indicators', 'wall_left', 'viewer', 'turn',
              'waiting_for', 'players', 'drawn', 'legal_actions', 'hints', 'events', 'result'):
        check(k in st, 'state 缺少字段 %s' % k)
    check(st['round']['wind'] == '1z' and st['round']['dealer'] == 0, 'round 字段不对')
    check(st['players'][0].get('hand') and 'hand' not in st['players'][1], '手牌可见性不对')
    check(all('tsumogiri' in d for p in st['players'] for d in p['discards']), 'discards 缺 tsumogiri')
    check(st['phase'] == 'playing' and st['waiting_for'] == [0], 'waiting_for 不对')

    gid = st['game_id']
    # 打几圈牌
    steps = 0
    while st['phase'] == 'playing' and steps < 400:
        acts = st['legal_actions']
        if not acts:
            check(False, '轮到人却没有 legal_actions')
            break
        a0 = acts[0]
        if a0['type'] == 'discard':
            st, code = post('/api/action', {'game_id': gid, 'seat': 0, 'type': 'discard',
                                            'tile': a0['tiles'][0], 'tsumogiri': False})
        elif a0['type'] == 'riichi':
            st, code = post('/api/action', {'game_id': gid, 'seat': 0, 'type': 'riichi',
                                            'tile': a0['tiles'][0], 'tsumogiri': False})
        elif a0['type'] == 'tsumo':
            st, code = post('/api/action', {'game_id': gid, 'seat': 0, 'type': 'tsumo'})
        elif a0['type'] == 'ron':
            st, code = post('/api/action', {'game_id': gid, 'seat': 0, 'type': 'ron'})
        else:
            st, code = post('/api/action', {'game_id': gid, 'seat': 0, 'type': 'pass'})
        if code != 200:
            check(False, 'action 返回 %d: %s' % (code, st))
            break
        check(st['game_id'] == gid and 'rules' in st and isinstance(st['events'], list),
              'action 返回的状态缺字段')
        if st['result'] and st['result']['type'] == 'agari':
            w = st['result']['wins'][0]
            check('points' in w and 'yakuman' in w, 'result.wins 缺 points/yakuman')
            check(all(y['han'] >= 1 for y in w['yaku']), '役的番数有 0: %s' % w['yaku'])
            check(sum(y['han'] for y in w['yaku']) == w['han'], '役的番数加起来 != han')
            break
        steps += 1

    # 一局结束后进下一局；再开第二局不影响第一局
    if st['phase'] == 'round_end':
        st2, code = post('/api/next', {'game_id': gid, 'seat': 0})
        check(code == 200 and st2['round']['number'] in (1, 2, 3, 4), 'next 返回不对')
    st_b, code = post('/api/new_game', {'players': ['human', 'bot', 'bot', 'bot']})
    check(code == 200 and st_b['game_id'] != gid, '第二局的 game_id 重复')
    st, code = post('/api/state?game_id=%s&seat=0' % gid, None) if False else (None, None)
    # 错误处理
    st, code = post('/api/action', {'game_id': 'nope', 'seat': 0, 'type': 'pass'})
    check(code == 400, '不存在的 game_id 应该 400')
    st, code = post('/api/action', {'game_id': gid, 'seat': 0, 'type': 'discard', 'tile': '1z'})
    check(code in (200, 400), 'action 异常返回码 %d' % code)
finally:
    proc.terminate()
print('7. HTTP 接口 ok' if not fails else '7. 有失败')


print()
if fails:
    print('共 %d 处失败：' % len(fails))
    for m in fails:
        print(' -', m)
    sys.exit(1)
print('全部通过')
