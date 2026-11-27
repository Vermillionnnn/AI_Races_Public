# -*- coding: utf-8 -*-
import sys, os
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0,ROOT)
import game

def fresh():
    g=game.Game(human_seats=[0,1,2,3],seed=1)
    return g

def chankan():
    g=fresh()
    # seat0 有 5m 碰，手里第4张5m；seat1 听 5m 能和
    g.melds[0]=[{'type':'pon','tiles':['5m','5m','5m'],'from':2,'called_tile':'5m'}]
    g.hands[0]=['5m','1p','2p','3p','7s','8s','9s','1z','2z','3z']  # 10张+碰=13
    g.hands[1]=['4m','6m','2p','3p','4p','7s','8s','9s','9p','9p','1z','1z','1z'] # 听5m(46m嵌张)+...
    # seat1 需能和5m: 46m 嵌5m, 234p,789s,99p,111z -> 5m 完成 456m
    g.current=0; g.drawn='5m'; g.hands[0].append('5m'); g.phase='discard'
    g.riichi=[False]*4; g.first_turn=[False]*4; g.no_call_yet=False
    acts=g.get_legal_actions(0)
    assert any(a['type']=='kakan' for a in acts), acts
    g.do_action(0,'kakan',tile='5m')
    # seat1 应能荣和（抢杠）
    a1=g.get_legal_actions(1)
    assert any(a['type']=='ron' for a in a1), a1
    g.do_action(1,'ron')
    win=g.result['wins'][0]
    assert any(y['name']=='抢杠' for y in win['yaku']), win['yaku']
    assert win['seat']==1 and win['from']==0
    print('chankan ok', [y['name'] for y in win['yaku']])

def four_kans():
    g=fresh()
    g.kan_seats=[0,1,2,0]  # 4 杠、两人以上
    g.phase='call'; g.call_options={}; g.responses={}
    g.last_discard=(3,'1m'); g.wall_pos=g.wall_end  # remaining 0? 不，先触发四杠
    g.wall_pos=60
    g._after_discard_pass()
    assert g.result and g.result['reason']=='four_kans', g.result
    print('four_kans ok')

def dealer_rotate():
    # 非庄家和了 → 换庄。直接构造 seat1 荣和
    g=fresh()
    g.hands[1]=['1m','2m','3m','4p','5p','6p','7s','8s','9s','2s','3s','5m','5m']
    g.hands[0]=['9p','9p','9p','1z','2z','3z','4z','5z','6z','7z','1s','2s','3s']
    g.current=0; g.drawn=None; g.phase='call'
    g.last_discard=(0,'4s')
    g.call_options={1:[{'type':'ron'}]}; g.responses={1:{'type':'ron'}}
    g._resolve_calls()
    assert g.result['type']=='ron'
    assert g.next_renchan is False
    g.next_round()
    assert g.oya==1, g.oya
    print('dealer rotate ok')

def riichi_stick():
    g=fresh()
    # seat0 立直宣言，无人应 → 扣1000、供托+1
    g.scores=[25000]*4
    g.riichi_pending=0; g.riichi=[True,False,False,False]
    g.phase='call'; g.call_options={}; g.responses={}
    g.last_discard=(0,'5m'); g.wall_pos=60
    g._after_discard_pass()
    assert g.scores[0]==24000 and g.kyotaku==1, (g.scores,g.kyotaku)
    print('riichi stick ok')

if __name__=='__main__':
    chankan(); four_kans(); dealer_rotate(); riichi_stick()
    print('ALL EDGES OK')