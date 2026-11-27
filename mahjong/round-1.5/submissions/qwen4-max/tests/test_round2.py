# -*- coding: utf-8 -*-
# 社团反馈的 10 个问题，逐条回归测试
import sys, os, json, subprocess, time, socket, urllib.request
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0,ROOT)
import game, score, tenpai

def fresh():
    return game.Game(human_seats=[0,1,2,3],seed=1)

# 1. 4番40符 / 3番70符 基本点>=2000 应封顶满贯
def i1():
    assert score.calc_score(40,4,False,False)['get']==8000, score.calc_score(40,4,False,False)
    assert score.calc_score(70,3,False,False)['get']==8000
    assert score.calc_score(40,4,True,False)['get']==12000  # 亲满贯
    assert score.calc_score(30,4,False,False)['get']==7700  # 不切上
    assert score.calc_score(30,4,False,False,kiriage_mangan=True)['get']==8000
    print('1 mangan cap ok')

# 2. 只有抢杠这一个役也能和
def i2():
    g=fresh()
    g.melds[0]=[{'type':'pon','tiles':['5m','5m','5m'],'from':2,'called_tile':'5m'}]
    g.hands[0]=['5m','1p','2p','3p','7s','8s','9s','1z','2z','3z']
    g.melds[1]=[{'type':'pon','tiles':['2m','2m','2m'],'from':3,'called_tile':'2m'}]
    g.hands[1]=['4m','6m','3p','4p','5p','6s','7s','8s','9p','9p']  # 副露、无其他役，听5m
    g.current=0; g.drawn='5m'; g.hands[0].append('5m'); g.phase='discard'
    g.riichi=[False]*4; g.first_turn=[False]*4; g.no_call_yet=False
    g.do_action(0,'kakan',tile='5m')
    assert any(a['type']=='ron' for a in g.get_legal_actions(1)), g.get_legal_actions(1)
    g.do_action(1,'ron')
    w=g.result['wins'][0]
    assert w['han']==1 and [y['name'] for y in w['yaku']]==['抢杠'], w['yaku']
    print('2 chankan-only yaku ok')

# 4. 碰后手牌重新排序
def i4():
    g=fresh()
    g.hands[0]=['9m','1m','5m','5m']
    g.rivers[1]=[{'tile':'5m','riichi':False,'called':False,'tsumogiri':False}]
    g._call_meld(0,1,'5m','pon',['5m','5m'])
    assert g.hands[0]==sorted(g.hands[0],key=game.tile_key), g.hands[0]
    st=g.get_state(0)
    assert st['players'][0]['hand']==sorted(st['players'][0]['hand'],key=game.tile_key)
    print('4 hand sorted after call ok')

# 5. 被碰走的牌不在河里重复扣
def i5():
    g=fresh()
    g.melds[1]=[{'type':'pon','tiles':['5m','5m','5m'],'from':2,'called_tile':'5m'}]
    g.rivers[2]=[{'tile':'5m','riichi':False,'called':True,'tsumogiri':False}]
    vis=g.get_visible(0)
    assert vis.count('5m')==3, vis.count('5m')   # 只算副露3张，河里那张called不算
    g.hands[0]=['1m','2m','3m','4p','5p','6p','7s','8s','9s','4m','6m','9p','9p']
    w=tenpai.get_waits(g.hands[0],[],vis)
    assert w.get('5m')==1, w   # 4-3=1
    print('5 called tile not double-counted ok')

# 6. 食替后无牌可打的吃/碰不该提供
def i6():
    g=fresh()
    g.hands[0]=['2m','3m','1m','4m']
    assert g._discardable_after_call(0,'1m',['2m','3m'],'chi') is False
    combos=g._chi_combos(0,'1m')
    assert ['2m','3m'] not in combos, combos
    print('6 illegal kuikae chi filtered ok')

# 7. 立直宣言牌被荣和 → 撤立直标记
def i7():
    g=fresh()
    g.riichi=[True,False,False,False]; g.riichi_pending=0
    g.rivers[0]=[{'tile':'5m','riichi':True,'called':False,'tsumogiri':False}]
    g.hands[1]=['1m','2m','3m','4p','5p','6p','7z','7z','7z','5m','5m','9p','9p']
    g.phase='call'; g.last_discard=(0,'5m')
    g.call_options={1:[{'type':'ron'}]}; g.responses={1:{'type':'ron'}}
    g._resolve_calls()
    assert g.riichi[0] is False and g.rivers[0][-1]['riichi'] is False
    assert g.kyotaku==0  # 没交棒
    print('7 riichi-ron reverts flag ok')

# 8. 立直后提示只留摸切那张
def i8():
    g=fresh()
    g.riichi[0]=True; g.current=0; g.phase='discard'
    g.hands[0]=['1m','2m','3m','4p','5p','6p','7s','8s','9s','2s','3s','5m','5m','9z']
    g.drawn='9z'
    h=g._build_hints(0)
    assert all(k=='9z' for k in h['discards']), h['discards'].keys()
    print('8 riichi hints only drawn ok')

# 9. 打牌提示：打出的听牌张要计入河，剩牌不多1
def i9():
    h14=['1m','2m','3m','4p','5p','6p','7s','8s','9s','4m','6m','5m','5m','5m']
    dh=tenpai.discard_hints(h14,[],[])
    assert dh['5m']['5m']==1, dh['5m']   # 4-手2-河1=1
    print('9 discard-hint left count ok')

# 10. 全电脑自动打完；真人在非0座位视角正确
def i10():
    s=socket.socket(); s.bind(('127.0.0.1',0)); port=s.getsockname()[1]; s.close()
    p=subprocess.Popen([sys.executable,os.path.join(ROOT,'server.py'),'--port',str(port)])
    try:
        B='http://127.0.0.1:%d'%port
        for _ in range(50):
            try: urllib.request.urlopen(B+'/',timeout=2); break
            except Exception: time.sleep(0.1)
        def post(path,body):
            r=urllib.request.Request(B+path,data=json.dumps(body).encode(),method='POST')
            r.add_header('Content-Type','application/json')
            return json.loads(urllib.request.urlopen(r,timeout=8).read())
        st=post('/api/new_game',{'players':['bot']*4,'seed':1})
        assert st['phase'] in ('round_end','game_end'), ('all-bot should auto-play',st['phase'],st['waiting_for'])
        st=post('/api/new_game',{'players':['bot','human','bot','bot'],'seed':1})
        assert st['viewer']==1 and 'hand' in st['players'][1], st['viewer']
        st=post('/api/new_game',{'players':['bot','bot','bot','human'],'seed':1})
        assert st['viewer']==3 and 'hand' in st['players'][3]
        print('10 all-bot + non-0 viewer ok')
    finally:
        p.terminate()
        try: p.wait(timeout=5)
        except Exception: p.kill()

if __name__=='__main__':
    i1(); i2(); i4(); i5(); i6(); i7(); i8(); i9(); i10()
    print('ALL ROUND-2 ISSUES OK')