# round-2 学生反馈的回归测试：python3 tests/test_round2.py（在项目根目录跑）
import json
import random
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, '.')
import server            # 兼容层
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


# ---------- 1. 满贯边界：4番40符、3番70符（以前会算出 10300/9000） ----------
check(score.calc_score(40, 4, False, False)['get'] == 8000, '4番40符子荣和应为满贯 8000: %s'
      % score.calc_score(40, 4, False, False))
check(score.calc_score(40, 4, True, False)['get'] == 12000, '4番40符庄荣和应为 12000')
check(score.calc_score(70, 3, False, False)['get'] == 8000, '3番70符子荣和应为满贯 8000')
ko_t = score.calc_score(40, 4, False, True)
check((ko_t['oya_pay'], ko_t['ko_pay']) == (4000, 2000), '4番40符子自摸应 2000/4000: %s' % ko_t)
check(score.calc_score(30, 4, False, False)['get'] == 7700, '4番30符（切上关）还是 7700')
check(score.calc_score(25, 4, False, False)['get'] == 6400, '4番25符不应满贯')
print('1. 满贯边界 ok' if not fails else '1. 有失败')


# ---------- 2. 多倍役满 + 累计役满的显示 ----------
check(score.calc_score(30, 26, False, False)['get'] == 64000, '二倍役满子荣和 64000: %s'
      % score.calc_score(30, 26, False, False))
check(score.calc_score(30, 26, True, True)['get'] == 96000, '二倍役满庄自摸 96000')
check(score.calc_score(30, 39, False, False)['get'] == 96000, '三倍役满子荣和 96000')
check(score.calc_score(30, 52, False, False)['get'] == 128000, '四倍役满子荣和 128000')
# 累计 13 番（普通役凑的）：点数按役满，但 yakuman 标志应为 0
g = game.Game(human_seats=[0], seed=99)
g.result = {'type': 'tsumo', 'wins': [{'seat': 0, 'from': None, 'tile': '3m',
                                       'hand': ['1m', '2m', '3m'], 'melds': [],
                                       'yaku': ['清一色', '宝牌7'], 'han': 13, 'fu': 30,
                                       'delta': [32000, -8000, -8000, -16000], 'points': 32000}],
            'dora_indicators': [], 'ura_indicators': [], 'delta': [32000, -8000, -8000, -16000]}
r = server._result(g)
check(r['wins'][0]['yakuman'] == 0, '累计 13 番不应标成役满: %s' % r['wins'][0])
check(r['wins'][0]['han'] == 13, '累计役满 han 照常显示')
print('2. 役满 ok' if not fails else '2. 有失败')


# ---------- 3. 地和（键名对不上：chihou / chiihou） ----------
h = ['2m', '3m', '4m', '5p', '6p', '7p', '2s', '3s', '4s', '7z', '7z', '7z', '5m']
names, han = yaku.calc_yaku(h, [], '5m', True, '1z', '2z', [],
                            {'chihou': True, 'rules': {}})
check('地和' in names, '闲家第一张自摸应该算地和: %s' % names)
names, han = yaku.calc_yaku(h, [], '5m', True, '1z', '2z', [],
                            {'chiihou': True, 'rules': {}})
check('地和' in names, 'chiihou 写法也要认: %s' % names)
names, han = yaku.calc_yaku(h, [], '5m', True, '1z', '1z', [],
                            {'tenhou': True, 'rules': {}})
check('天和' in names, '天和还在')
print('3. 地和 ok' if not fails else '3. 有失败')


# ---------- 4. 双立直不被之后的鸣牌取消（只取消一发） ----------
hand0 = ['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '2p', '3p', '5p', '5p']
pool = list(game.make_wall())
hand1 = ['9s', '9s'] + ['1p', '2p', '3p', '4p', '5p', '6p', '7p', '8p', '9p', '5z', '5z']
for t in hand0 + hand1 + ['9s', '1p']:
    pool.remove(t)
rng = random.Random(11)
rng.shuffle(pool)
# 手工排：座位0=hand0、座位1=hand1(两张9s等着碰)
wall = (hand0 + hand1 + pool[:26] + ['9s'] + pool[26:66] + ['1p'] + pool[66:])
assert len(wall) == 136
g = game.Game(human_seats=[0, 1], wall=wall)
check(g.drawn == '9s', '庄家第一张摸 9s（拿来立直宣言）')
g.do_action(0, 'riichi', tile='9s', tsumogiri=True)
# 座位 1 碰 9s（手里有两张）
acts = g.get_legal_actions(1)
check(any(a['type'] == 'pon' for a in acts), '座位 1 应该能碰 9s')
g.do_action(1, 'pon')
# 座位 1 打一张，然后电脑打两轮，座位 0 摸到 wall 里的 1p
g.do_action(1, 'discard', tile='5z')
# 现在 _run 跑到座位 0 摸牌为止；摸到 1p 和牌
acts = g.get_legal_actions(0)
check(any(a['type'] == 'tsumo' for a in acts), '座位 0 摸 1p 应能自摸')
g.do_action(0, 'tsumo')
w = g.result['wins'][0]
check('两立直' in w['yaku'], '碰过的双立直不能降级: %s' % w['yaku'])
check('一发' not in w['yaku'], '被碰之后一发应该没了: %s' % w['yaku'])
print('4. 双立直 ok' if not fails else '4. 有失败')


# ---------- 5. 立直后暗杠（摸到第四张） ----------
hand0 = ['1z', '1z', '1z', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '5p', '5p']
pool = list(game.make_wall())
for t in hand0 + ['9s', '1z']:
    pool.remove(t)
rng = random.Random(12)
rng.shuffle(pool)
# 摸牌顺序：座位0 摸 9s（立直宣言）、座位1/2/3 各摸一张废牌、座位0 摸第 4 张 1z
wall = hand0 + pool[:39] + ['9s'] + pool[39:42] + ['1z'] + pool[42:]
assert len(wall) == 136
wall[132] = '7m'   # 岭上牌正好是听的 7m（89m 的边张）
g = game.Game(human_seats=[0], wall=wall)
g.do_action(0, 'riichi', tile='9s', tsumogiri=True)
# 电脑打三轮，回到座位 0 摸第 4 张 1z
acts = g.get_legal_actions(0)
kans = [a for a in acts if a['type'] == 'kan' and a.get('kind') == 'ankan']
check(kans, '立直后摸到第 4 张 1z 应该可以暗杠: %s' % acts)
g.do_action(0, 'kan', tile='1z')
check(g.drawn == '7m', '岭上牌 7m: %s' % g.drawn)
acts = g.get_legal_actions(0)
check(any(a['type'] == 'tsumo' for a in acts), '暗杠后岭上开花 7m')
g.do_action(0, 'tsumo')
w = g.result['wins'][0]
check('岭上开花' in w['yaku'] and '两立直' in w['yaku'], '岭上+双立直: %s' % w['yaku'])
print('5. 立直暗杠 ok' if not fails else '5. 有失败')


# ---------- 6. 平和的符（拆法取最大符把平和拆没了） ----------
# 123m 456m 789m 55s + 23s 两面听 1s/4s
h = ['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '2s', '3s', '5s', '5s']
names, han = yaku.calc_yaku(h, [], '4s', False, '1z', '2z', [], {'rules': {}})
check('平和' in names, '应是平和: %s' % names)
f = fu.calc_fu(h, [], '4s', False, '1z', '2z', yaku=names)
check(f == 30, '平和荣和固定 30 符（以前拆最大符会到 40）: %d' % f)
f = fu.calc_fu(h, [], '4s', True, '1z', '2z', yaku=['平和'])
check(f == 20, '平和自摸固定 20 符: %d' % f)
# 反向兼容：不传 yaku 时老算法还在
check(fu.calc_fu(h, [], '4s', False, '1z', '2z') in (30, 40), '不传 yaku 也能算出符')
print('6. 平和符 ok' if not fails else '6. 有失败')


# ---------- 7. 副露混一色 / 宝牌 番数（检查是不是真有错） ----------
# 碰中 + 123m 456m 789m 55m，和 5m；宝牌 5m（手里 3 张）
open_hand = ['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '5m', '5m']
names, han = yaku.calc_yaku(open_hand, [['7z', '7z', '7z']], '5m', False, '1z', '2z', ['5m'],
                            {'rules': {}})
# 混一色（副露 2）+ 役牌中（1）+ 一气通贯（副露 1）+ 宝牌3 = 7 番
check(han == 7 and '混一色' in names, '副露混一色+役牌+一气+宝牌3 应为 7 番: %s %s' % (names, han))
# 暗杠不破门清：混一色 3 + 役牌 1 + 一气通贯（门清 2）+ 宝牌3 = 9 番
names, han = yaku.calc_yaku(open_hand, [['7z', '7z', '7z', '7z']], '5m', False, '1z', '2z',
                            ['5m'], {'rules': {}, 'ankan_indices': [0]})
check(han == 9 and '混一色' in names, '暗杠后混一色按门清 3 番: %s %s' % (names, han))
print('7. 副露番数 ok（如果手算对不上，先看看是不是暗杠的门清/一气通贯的明暗番差）'
      if not fails else '7. 有失败')


# ---------- 8. 抢杠：只有抢杠一个役也要能和 ----------
g = game.Game(human_seats=[1], seed=3)
g.phase = 'discard'
g.current = 0
g.melds[0] = [{'type': 'pon', 'tiles': ['4s', '4s', '4s'], 'from': 2, 'called_tile': '4s'}]
g.hands[0] = ['4s', '1p', '2p', '3p', '7p', '8p', '9p', '1m', '2m', '3m', '5z']
g.melds[1] = [{'type': 'pon', 'tiles': ['1m', '1m', '1m'], 'from': 2, 'called_tile': '1m'}]
g.hands[1] = ['2m', '3m', '4m', '4p', '5p', '6p', '5s', '6s', '8p', '8p']
g.riichi = [False] * 4
g._kakan(0, '4s')
check(1 in g.call_options and any(o['type'] == 'ron' for o in g.call_options[1]),
      '加杠 4s，座位 1 听 4s 应该能抢杠')
g.do_action(1, 'ron')
w = g.result['wins'][0]
check('抢杠' in w['yaku'], '抢杠应该在役里: %s' % w['yaku'])
check(w['han'] >= 1, '只有抢杠也不能 0 番')
print('8. 抢杠 ok' if not fails else '8. 有失败')


# ---------- 9. 四个杠：两个人各杠两次不流局；四家各一个杠才流局 ----------
g = game.Game(human_seats=[0], seed=3)
g.last_discard = (0, '1m')
g.phase = 'call'
g.call_options = {}
g.responses = {}
g.kan_seats = [0, 1, 0, 1]
g.rinshan_used = 3      # 第四次杠之前
g._after_kan(0)         # 第四次杠（两家各两个）
check(not g.four_kans_pending, '两家各两个杠不算四杠散了')
g.four_kans_pending = True
g._after_discard_pass()
check(g.result and g.result.get('reason') == '四杠散了', '四家各杠一次应流局')
print('9. 四杠 ok（按天凤/雀魂规则：杠满 4 次且是 4 家各一次才流局，'
      '一家或两家杠满 4 次不流，给别人留四杠子的机会）' if not fails else '9. 有失败')


# ---------- 10. 红五碰的拿法 ----------
g = game.Game(human_seats=[1], seed=4)
g.hands[1] = ['5m', '5m', '0m', '1p', '2p', '3p', '7p', '8p', '9p', '1s', '2s', '3s', '5s']
g.riichi = [False] * 4
g._discard(0, '5m')
opts = [o for o in g.call_options.get(1, []) if o['type'] == 'pon']
pairs = sorted(tuple(sorted(o['tiles'])) for o in opts)
check(pairs == [('0m', '5m'), ('5m', '5m')], '红五+普通五碰应该两种拿法: %s' % pairs)
print('10. 红五碰 ok' if not fails else '10. 有失败')


# ---------- 11. 食替不会卡死（副露很多、剩下的牌全在食替里） ----------
g = game.Game(human_seats=[1], seed=5)
g.melds[1] = [
    {'type': 'chi', 'tiles': ['4m', '5m', '6m'], 'from': 0, 'called_tile': '6m'},
    {'type': 'pon', 'tiles': ['7p', '7p', '7p'], 'from': 0, 'called_tile': '7p'},
    {'type': 'chi', 'tiles': ['1s', '2s', '3s'], 'from': 0, 'called_tile': '2s'},
    {'type': 'pon', 'tiles': ['9s', '9s', '9s'], 'from': 0, 'called_tile': '9s'},
]
g.hands[1] = ['3m', '6m']      # 副露满 4 组以后手里就剩两张，还都在食替里
g.phase = 'discard'
g.current = 1
g.drawn = None
g.after_call = True
g.kuikae = ['3m', '6m']
acts = g.get_legal_actions(1)
disc = [a for a in acts if a['type'] == 'discard']
check(disc and disc[0]['tiles'], '食替把所有牌都禁掉时也要给个能打的（兜底全放开）: %s'
      % (disc and disc[0]['tiles']))
g.do_action(1, 'discard', tile=disc[0]['tiles'][0])
acts2 = g.get_legal_actions(1)
check(bool(acts2), '没有卡死：轮到人类时始终有合法操作')
print('11. 食替 ok' if not fails else '11. 有失败')


# ---------- 12. 立直宣言牌被荣和：立直标记撤掉 ----------
hand0 = ['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '5p', '5p']
hand1 = ['7z', '7z', '7z', '2m', '3m', '4m', '5m', '6m', '7m', '1p', '2p', '8p', '8p']
pool = list(game.make_wall())
for t in hand0 + hand1 + ['3p']:
    pool.remove(t)
rng = random.Random(13)
rng.shuffle(pool)
wall = hand0 + hand1 + pool[:26] + ['3p'] + pool[26:]
assert len(wall) == 136
g = game.Game(human_seats=[0, 1], wall=wall)
check(g.drawn == '3p', '庄家摸 3p')
g.do_action(0, 'riichi', tile='3p', tsumogiri=True)   # 宣言牌正好是座位 1 听的 3p
acts = g.get_legal_actions(1)
check(any(a['type'] == 'ron' for a in acts), '座位 1 应能荣和宣言牌')
g.do_action(1, 'ron')
check(not g.riichi[0], '宣言牌被荣和，立直不成立（标记应撤掉）')
check(g.kyotaku == 0, '立直棒没放，供托还是 0')
check(g.result['wins'][0]['yaku'] and '役牌 中' in g.result['wins'][0]['yaku'],
      '和牌的人役正常: %s' % g.result['wins'][0]['yaku'])
print('12. 宣言牌 ok' if not fails else '12. 有失败')


# ---------- 13. all last 同分按起家顺序 ----------
g = game.Game(human_seats=[0], seed=7, length='tonpuu')
g.kyoku = 3            # 东4，庄家 = 座位 3
g.scores = [30000, 25000, 25000, 30000]
check(g._check_game_over(True, True) is False, '庄家(座位3)和了但和起家同分，起家算第一，应继续')
g.scores = [25000, 25000, 25000, 30000]
check(g._check_game_over(True, True) is True, '庄家单独第一且过 30000 时应结束')
print('13. 同分 ok' if not fails else '13. 有失败')


# ---------- 14. 终局供托进 delta ----------
g = game.Game(human_seats=[0], seed=8)
g.kyoku = 3            # 东4，庄家 = 座位 3
g.scores = [25000, 25000, 22000, 31000]   # 庄家第一且过 30000
g.kyotaku = 2
result = {'type': 'tsumo', 'wins': [], 'dora_indicators': [], 'ura_indicators': []}
delta = [0, 0, 0, 8000]
g.phase = 'discard'
g.current = 0
g._end_round(result, delta, True, True)
check(g.game_over, '应该结束')
check(result['delta'][3] == 8000 + 2000, '终局供托 2000 应计入 delta: %s' % result['delta'])
print('14. 供托 ok' if not fails else '14. 有失败')


# ---------- 15. 听牌提示：自己副露别扣两次 / 打牌提示多一张 ----------
g = game.Game(human_seats=[0], seed=9)
g.melds[0] = [{'type': 'chi', 'tiles': ['4m', '5m', '6m'], 'from': 1, 'called_tile': '6m'}]
g.hands[0] = ['4m', '1p', '2p', '3p', '5s', '6s', '7s', '2z', '2z', '2z']
g.drawn = None
h = server._build_hints(g, 0)
left = {w['tile']: w['left'] for w in h['waits']}
# 听 4m（第 4 张）：手里 1 张 + 吃的顺子里 1 张 = 剩 2 张（以前会把自己副露再扣一次变 1）
check(left.get('4m') == 2, '听的 4m 应剩 2 张（自己的副露不能扣两次）: %s' % left)
# 打牌提示：打出去的那张也算看得到的（听自己刚打出去的牌时别多算一张）
hand14 = ['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '2p', '3p', '4p', '5p', '5p']
hints = tenpai.discard_hints(hand14, [], [])
# 手里两张 5p，打掉一张：剩 4 - 手里 1 - 刚打的 1 = 2（以前会把刚打的那张也算成能摸到，得 3）
check(hints.get('5p', {}).get('5p') == 2, '打 5p 听 5p 时应剩 2: %s' % hints.get('5p'))
# 立直后只提示听什么
g2 = game.Game(human_seats=[0], seed=10)
g2.riichi[0] = True
g2.hands[0] = ['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '2p', '3p', '4p', '5p']
h2 = server._build_hints(g2, 0)
check(h2 and h2['waits'] and not h2['discards'], '立直后不该再提示打哪张: %s' % h2)
print('15. 提示 ok' if not fails else '15. 有失败')


# ---------- 16. HTTP：全电脑、视角、事件隐藏、手牌排序、摸切、called_tile ----------
proc = subprocess.Popen([sys.executable, 'server.py', '--port', '8766'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
time.sleep(1.2)
try:
    def post(path, obj):
        req = urllib.request.Request('http://127.0.0.1:8766' + path,
                                     json.dumps(obj).encode('utf-8'),
                                     {'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode('utf-8')), r.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read().decode('utf-8')), e.code

    # 四个全是电脑：不能卡死
    st, code = post('/api/new_game', {'players': ['bot', 'bot', 'bot', 'bot']})
    check(code == 200 and st['phase'] != 'playing', '全电脑开局应该直接打完一局: %s' % st.get('phase'))
    # 真人在别的座位：new_game 一律回座位 0 视角
    st, code = post('/api/new_game', {'players': ['bot', 'human', 'bot', 'bot']})
    check(code == 200 and st['viewer'] == 0, 'new_game 应回座位 0 视角: %s' % st.get('viewer'))
    gid = st['game_id']
    # 玩几手
    steps = 0
    while st['phase'] == 'playing' and steps < 100:
        acts = st['legal_actions']
        if not acts:
            break
        a0 = acts[0]
        if a0['type'] == 'discard':
            st, code = post('/api/action', {'game_id': gid, 'seat': 0, 'type': 'discard',
                                            'tile': a0['tiles'][0], 'tsumogiri': False})
        else:
            st, code = post('/api/action', {'game_id': gid, 'seat': 0, 'type': 'pass'})
        steps += 1
    # 别人的摸牌事件 tile 必须是 null
    draws = [e for e in st['events'] if e['type'] == 'draw']
    check(all(e['tile'] is None for e in draws if e['seat'] != 0),
          '别人的摸牌事件 tile 应该是 null')
    check(all(e['tile'] is not None for e in draws if e['seat'] == 0),
          '自己的摸牌事件 tile 应该看得见')
    # 手牌要排好序
    hand = st['players'][0].get('hand')
    if hand:
        check(hand == sorted(hand, key=game.tile_key), '手牌没排好序: %s' % hand)
    # 电脑的河里应有摸切标记
    bots_river = [d for p in st['players'][1:] for d in p['discards']]
    check(any(d['tsumogiri'] for d in bots_river) if bots_river else True,
          '电脑摸切在河里应该标记出来')
finally:
    proc.terminate()
print('16. HTTP ok' if not fails else '16. 有失败')


print()
if fails:
    print('共 %d 处失败：' % len(fails))
    for m in fails:
        print(' -', m)
    sys.exit(1)
print('round-2 全部通过')
