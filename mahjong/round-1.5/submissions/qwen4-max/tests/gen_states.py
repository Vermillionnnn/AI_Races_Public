# -*- coding: utf-8 -*-
import sys, os, json
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0,ROOT)
import game

def wrap(g,seat,gid='g1'):
    st=g.get_state(seat); st['version']=1; st['game_id']=gid; return st

states=[]
# playing
deal0=['1m','2m','3m','4p','5p','6p','7s','8s','9s','1z','1z','1z','2z']
import random
w=game.make_wall(True); rest=list(w)
for t in deal0+['2z']: rest.remove(t)
random.Random(1).shuffle(rest)
wall=deal0+rest[:39]+['2z']+rest[39:]
g=game.Game(human_seats=[0],wall=wall)
states.append(('playing',wrap(g,0)))
# agari (tenhou)
g.do_action(0,'tsumo')
states.append(('agari',wrap(g,0)))
# ryuukyoku via random all-bot game
g2=game.Game(human_seats=[],seed=3,length='tonpuu')
states.append(('ryuukyoku',wrap(g2,0)))
# a mid-game playing state with a few discards, viewer seat1
g3=game.Game(human_seats=[0,1,2,3],seed=5)
for _ in range(6):
    if g3.phase=='end': break
    cur=g3.current
    acts=g3.get_legal_actions(cur)
    if not acts: break
    d=[a for a in acts if a['type']=='discard']
    if d: g3.do_action(cur,'discard',tile=d[0]['tiles'][0])
    else: g3.do_action(cur,'pass')
states.append(('mid',wrap(g3,1)))

out=os.path.join(HERE,'_states.json')
json.dump(states,open(out,'w',encoding='utf-8'),ensure_ascii=False)
print('wrote',out,len(states))