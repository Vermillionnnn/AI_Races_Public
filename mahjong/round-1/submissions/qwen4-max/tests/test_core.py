# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import game, fu, yaku, score, tenpai

def wall_with(deal0, draw0, rest_seed=1):
    """deal0: seat0 13张; draw0: 庄家第一摸(wall[52]); 其余随机补齐"""
    import random
    w = game.make_wall(True)
    used = list(deal0) + [draw0]
    rest = list(w)
    for t in used:
        rest.remove(t)
    random.Random(rest_seed).shuffle(rest)
    # seat0=deal0, seat1/2/3 = rest[:39], wall[52]=draw0, 其余 rest[39:]
    return list(deal0) + rest[:39] + [draw0] + rest[39:]

# --- 单元：符 ---
def t_fu():
    shou = ['1m','2m','3m','4p','5p','6p','7s','8s','9s','2s','3s','4s','5m','5m']
    assert fu.calc_fu(shou, [], '4s', False, '1z','2z') == 30, '平和荣30'
    assert fu.calc_fu(shou, [], '4s', True, '1z','2z') == 20, '平和自摸20'
    chiitoi = ['1m','1m','3m','3m','5p','5p','7p','7p','2s','2s','9s','9s','7z','7z']
    assert fu.calc_fu(chiitoi, [], '7z', False, '1z','2z') == 25, '七对25'
    # 连风雀头开关（选一个不会被进位掩盖的例子：111m暗刻+两面荣和+连风雀头）
    h = ['1m','1m','1m','4p','5p','6p','7s','8s','9s','2s','3s','4s','1z','1z']
    assert fu.calc_fu(h, [], '4s', False, '1z','1z', renpu_fu=4) == 50, '连风4符'
    assert fu.calc_fu(h, [], '4s', False, '1z','1z', renpu_fu=2) == 40, '连风2符'
    assert fu.que_tou_fu('1z','1z','1z',4) == 4 and fu.que_tou_fu('1z','1z','1z',2) == 2
    # 暗杠
    h2 = ['2m','3m','4m','4p','5p','6p','6s','7s','8s','5m','5m']
    gang = [['1z','1z','1z','1z']]
    assert fu.calc_fu(h2, gang, '4m', True, '2z','3z', gang) == 60, '东暗杠自摸60'
    assert fu.calc_fu(h2, gang, '4m', True, '2z','3z') == 40, '东明杠自摸40'
    print('fu ok')

def t_score():
    assert score.calc_score(30,2,False,False)['get'] == 2000
    assert score.calc_score(30,4,False,False)['get'] == 7700, '不切上'
    assert score.calc_score(30,4,False,False,kiriage_mangan=True)['get'] == 8000, '切上'
    assert score.calc_score(40,3,True,True)['get'] == 2600*3, '亲40符3番自摸2600all'
    assert score.calc_score(0,26,False,False,yakuman=2)['get'] == 64000, '双倍役满子荣64000'
    assert score.calc_score(0,13,False,False)['get'] == 32000, '单倍役满子荣32000'
    assert score.calc_score(30,13,False,False)['get'] == 32000, '累计役满'
    print('score ok')

def t_yaku():
    # 立直平和自摸
    h = ['1m','2m','3m','4p','5p','6p','7s','8s','9s','2s','3s','4s','5m','5m']
    st = {'riichi':True,'ippatsu':False}
    names, han = yaku.calc_yaku(h, [], '4s', True, '1z','2z', [], st)
    assert '立直' in names and '平和' in names and '门前清自摸和' in names, names
    # 食断开关
    h2 = ['2m','3m','4m','5p','6p','7p','2s','3s','4s','5s','6s','7s','8m','8m']
    melds=[['2m','3m','4m']]
    hh = ['5p','6p','7p','2s','3s','4s','5s','6s','7s','8m','8m']
    n_open,_ = yaku.calc_yaku(hh, melds, '8m', False, '1z','2z', [], {}, {'kuitan':True})
    n_closed,_ = yaku.calc_yaku(hh, melds, '8m', False, '1z','2z', [], {}, {'kuitan':False})
    assert '断幺九' in n_open and '断幺九' not in n_closed, (n_open,n_closed)
    print('yaku ok')

def t_tenpai():
    h = ['1m','2m','3m','4m','5m','6m','7p','8p','9p','2s','3s','5z','5z']
    w = tenpai.get_waits(h, [], ['1s','4s'])
    assert '1s' in w and '4s' in w, w
    assert w['1s'] == 3 and w['4s'] == 3, w   # 4 - 河里1张
    print('tenpai ok')

# ---  forced win: 天和 ---
def t_tenhou():
    deal0 = ['1m','2m','3m','4p','5p','6p','7s','8s','9s','1z','1z','1z','2z']
    w = wall_with(deal0, '2z')
    g = game.Game(human_seats=[0], wall=w)
    acts = g.get_legal_actions(0)
    assert any(a['type']=='tsumo' for a in acts), acts
    g.do_action(0,'tsumo')
    r = g.result
    win = r['wins'][0]
    assert win['yakuman'] >= 1, win
    assert any(y['name']=='天和' for y in win['yaku']), win['yaku']
    assert sum(g.scores) == 100000
    print('tenhou ok', win['points'], win['yaku'])

# --- forced ron: 子家 立直平和荣和 ---
def t_ron():
    # seat0 听 4s (23s), 其余固定; seat1 打 4s
    deal0 = ['1m','2m','3m','4p','5p','6p','7s','8s','9s','2s','3s','5m','5m']
    # seat1 含 4s，第一摸后打 4s。让 seat1 摸一张别的，然后打 4s（从手牌）
    deal1 = ['4s','1p','1p','1p','9m','9m','9m','1s','2s','3s','5z','6z','7z']
    import random
    w = game.make_wall(True)
    used = deal0 + deal1
    rest = list(w)
    for t in used: rest.remove(t)
    random.Random(2).shuffle(rest)
    # wall[0:13]=seat0, [13:26]=seat1, [26:39]=seat2,[39:52]=seat3, [52]=庄家摸
    wall = deal0 + deal1 + rest[:26] + rest[26:27] + rest[27:]
    # 确保 wall[52] 不是让 seat0 能和的牌; seat0 庄家先摸 wall[52]
    g = game.Game(human_seats=[0,1], wall=wall)
    # seat0(庄)摸牌后打一张不听不影响的; 这里直接让 seat0 打 5m 保持听 4s? 5m 是雀头不能打
    # seat0 手牌 13 张已听 4s(23s)。摸 wall[52] 后需打出摸的牌(摸切)保持听牌
    a0 = g.get_legal_actions(0)
    # 摸切
    drawn = g.drawn
    g.do_action(0,'discard',tile=drawn,tsumogiri=True)
    # 现在 seat1 摸牌, 打 4s
    a1 = g.get_legal_actions(1)
    assert any(x['type']=='discard' for x in a1)
    g.do_action(1,'discard',tile='4s',tsumogiri=False)
    # seat0 应能荣和
    a = g.get_legal_actions(0)
    assert any(x['type']=='ron' for x in a), a
    g.do_action(0,'ron')
    win = g.result['wins'][0]
    assert win['from']==1
    assert win['points']>0
    assert sum(g.scores)==100000
    print('ron ok', win['points'], win['fu'], win['han'], [y['name'] for y in win['yaku']])

if __name__=='__main__':
    t_fu(); t_score(); t_yaku(); t_tenpai(); t_tenhou(); t_ron()
    print('ALL CORE OK')