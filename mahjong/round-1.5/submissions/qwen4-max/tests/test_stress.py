# -*- coding: utf-8 -*-
import sys, os, random
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0,ROOT)
import game, yaku, score

def stress():
    for seed in range(30):
        g=game.Game(human_seats=[0],seed=100+seed,length='hanchan')
        rng=random.Random(seed); steps=0
        while not g.game_over:
            if g.phase=='end':
                assert sum(g.scores)+g.kyotaku*1000==100000,(seed,g.scores,g.kyotaku)
                g.next_round(); continue
            acts=g.get_legal_actions(0)
            if not acts:
                # 可能在等别人（call 阶段但 seat0 无选项）——不应发生，seat0 是唯一人类
                raise AssertionError(('no acts',seed,g.phase,g.get_state(0)))
            types=[a['type'] for a in acts]
            if 'tsumo' in types: g.do_action(0,'tsumo')
            elif 'ron' in types: g.do_action(0,'ron')
            elif 'riichi' in types and rng.random()<0.7:
                g.do_action(0,'riichi',tile=rng.choice([a for a in acts if a['type']=='riichi'][0]['tiles']))
            elif 'ankan' in types and rng.random()<0.5:
                g.do_action(0,'ankan',tile=rng.choice([a for a in acts if a['type']=='ankan'][0]['tiles']))
            elif 'kakan' in types and rng.random()<0.5:
                g.do_action(0,'kakan',tile=rng.choice([a for a in acts if a['type']=='kakan'][0]['tiles']))
            elif 'pon' in types and rng.random()<0.5:
                a=[a for a in acts if a['type']=='pon'][0]; g.do_action(0,'pon',tiles=rng.choice(a['options']))
            elif 'chi' in types and rng.random()<0.4:
                a=[a for a in acts if a['type']=='chi'][0]; g.do_action(0,'chi',tiles=rng.choice(a['options']))
            elif 'minkan' in types and rng.random()<0.5: g.do_action(0,'minkan')
            elif 'kyuushu' in types and rng.random()<0.3: g.do_action(0,'kyuushu')
            elif 'discard' in types:
                g.do_action(0,'discard',tile=rng.choice([a for a in acts if a['type']=='discard'][0]['tiles']))
            else: g.do_action(0,'pass')
            steps+=1
            assert steps<5000,('runaway',seed)
        assert sum(g.scores)==100000,(seed,g.scores)
    print('stress ok (30 hanchan with random human seat0)')

def ankan_riichi():
    # 立直后暗杠仍门清：构造 seat0 听牌含四张同牌
    # 手牌 13 张: 1111m 234p 567s 99s 听 ... 需要听牌且摸到能暗杠
    # 用直接 yaku 校验：门清 + 暗杠 + 立直自摸 应算立直/自摸
    h=['1m','1m','1m','1m','2p','3p','4p','5s','6s','7s','9s','9s','5m','5m']
    melds=[['1m','1m','1m','1m']]
    hand=['2p','3p','4p','5s','6s','7s','9s','9s','5m','5m']  # 10 张 + 杠 = 13+1
    st={'riichi':True,'ankan_indices':[0]}
    names,han=yaku.calc_yaku(hand,melds,'5m',True,'1z','2z',[],st)
    assert '立直' in names and '门前清自摸和' in names, names
    print('ankan+riichi keeps menzen ok', names)

def double_yakuman():
    # 大四喜(2倍) 字一色 复合 -> 至少 2 倍
    # 直接测 score 倍数
    assert score.calc_score(0,26,False,False,yakuman=2)['get']==64000
    assert score.calc_score(0,39,True,False,yakuman=3)['get']==144000
    print('double/triple yakuman ok')

def kuitan_off():
    hand=['5p','6p','7p','2s','3s','4s','5s','6s','7s','8m','8m']
    melds=[['2m','3m','4m']]
    n,_=yaku.calc_yaku(hand,melds,'8m',False,'1z','2z',[],{},{'kuitan':False})
    assert '断幺九' not in n
    print('kuitan off ok')

if __name__=='__main__':
    ankan_riichi(); double_yakuman(); kuitan_off(); stress()
    print('ALL STRESS OK')