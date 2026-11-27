# -*- coding: utf-8 -*-
import sys, os, json, subprocess, time, socket, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import game

def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p

PORT = free_port()
BASE = 'http://127.0.0.1:%d' % PORT

def req(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    if data: r.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def jreq(method, path, body=None):
    code, raw = req(method, path, body)
    try: return code, json.loads(raw.decode())
    except Exception: return code, raw

def wall_with(deal0, draw0, seed=1):
    import random
    w = game.make_wall(True); used = list(deal0)+[draw0]; rest=list(w)
    for t in used: rest.remove(t)
    random.Random(seed).shuffle(rest)
    return list(deal0)+rest[:39]+[draw0]+rest[39:]

proc = subprocess.Popen([sys.executable, os.path.join(ROOT,'server.py'), '--port', str(PORT)],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try:
    # wait for startup
    for _ in range(50):
        try:
            c,_ = req('GET','/'); 
            if c==200: break
        except Exception: time.sleep(0.1)
    else:
        raise RuntimeError('server did not start')

    # 1. GET / returns HTML
    c, raw = req('GET','/')
    assert c==200 and b'<html' in raw.lower(), 'GET / should return index.html'

    # 2. new_game with tenhou wall
    deal0 = ['1m','2m','3m','4p','5p','6p','7s','8s','9s','1z','1z','1z','2z']
    w = wall_with(deal0,'2z')
    c, st = jreq('POST','/api/new_game', {'players':['human','bot','bot','bot'],'length':'tonpuu','wall':w})
    assert c==200, st
    gid = st['game_id']
    # format contract
    assert st['version']==1
    assert st['phase']=='playing'
    for k in ['wind','number','honba','riichi_sticks','dealer']: assert k in st['round'], k
    for k in ['aka_dora','kuitan','kiriage_mangan','renpu_fu']: assert k in st['rules'], k
    assert st['rules']['aka_dora'] is True and st['rules']['renpu_fu']==4
    assert len(st['players'])==4
    assert 'hand' in st['players'][0] and 'hand' not in st['players'][1]
    assert st['viewer']==0 and st['waiting_for']==[0]
    assert any(a['type']=='tsumo' for a in st['legal_actions']), st['legal_actions']
    assert isinstance(st['events'],list) and len(st['events'])>0
    assert st['wall_left']==69, st['wall_left']
    assert st['drawn']=='2z', ('drawn must show for current player', st['drawn'])
    assert st['players'][0]['hand_count']==13

    # 3. state endpoint
    c, st2 = jreq('GET','/api/state?game_id=%s&seat=0'%gid)
    assert c==200 and st2['game_id']==gid

    # 4. tsumo -> round_end with agari result
    c, st3 = jreq('POST','/api/action', {'game_id':gid,'seat':0,'type':'tsumo'})
    assert c==200, st3
    assert st3['phase'] in ('round_end','game_end'), st3['phase']
    r = st3['result']
    assert r['type']=='agari'
    win = r['wins'][0]
    assert win['yakuman']>=1
    assert sum(y['han'] for y in win['yaku'])==win['han'], 'han must equal sum of yaku'
    assert len(r['delta'])==4 and sum(r['delta'])==0
    assert 'uradora_indicators' in r

    # 5. next round
    c, st4 = jreq('POST','/api/next', {'game_id':gid,'seat':0})
    assert c==200, st4
    assert st4['phase']=='playing'
    # 庄家和了 → 连庄：庄家不变、本场 +1
    assert st4['round']['dealer']==0, 'dealer win -> renchan'
    assert st4['round']['honba']==1
    assert st4['round']['number']==1

    # 6. error: bad game_id
    c, e = jreq('POST','/api/action', {'game_id':'nope','seat':0,'type':'pass'})
    assert c==400 and 'error' in e
    # 7. error: illegal action
    c, e = jreq('POST','/api/action', {'game_id':gid,'seat':0,'type':'ron'})
    assert c==400, (c,e)

    # 8. rules off: no red fives in wall
    c, st5 = jreq('POST','/api/new_game', {'players':['human','bot','bot','bot'],
                                           'rules':{'aka_dora':False,'kuitan':False,'kiriage_mangan':True,'renpu_fu':2}})
    assert c==200
    assert st5['rules']=={'aka_dora':False,'kuitan':False,'kiriage_mangan':True,'renpu_fu':2}
    # collect all tiles visible in wall via a fresh random game's deal; check no 0m by inspecting game wall
    g5 = None
    # verify make_wall honors aka off
    assert all(t[0]!='0' for t in game.make_wall(False))

    # 9. 4-human hotseat mode
    c, st6 = jreq('POST','/api/new_game', {'players':['human','human','human','human'],'length':'hanchan'})
    assert c==200 and st6['phase']=='playing'

    print('ALL HTTP OK')
finally:
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()