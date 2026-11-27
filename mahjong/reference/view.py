"""状态对象：某个座位看到的样子（格式照 接口说明.md“状态”）。"""

import copy

from tiles import counts, kind_str
from agari import waits

ACTION_ORDER = ['discard', 'riichi', 'tsumo', 'ankan', 'kakan', 'kyuushu', 'ron', 'minkan', 'pon', 'chi', 'pass']


def format_actions(acts):
    out = []
    for typ in ACTION_ORDER:
        if typ not in acts:
            continue
        v = acts[typ]
        if typ in ('discard', 'riichi', 'ankan', 'kakan'):
            out.append({'type': typ, 'tiles': list(v)})
        elif typ in ('chi', 'pon'):
            out.append({'type': typ, 'options': [list(o) for o in v]})
        else:
            out.append({'type': typ})
    return out


def _wait_list(ks, vis):
    return [{'tile': kind_str(k), 'left': max(0, 4 - vis[k])} for k in ks]


def hints(r, viewer, acts):
    """听牌提示。轮到 viewer 打牌（14 张形）时给 discards，waits 为空；否则给 13 张时的 waits 和振听。"""
    vis = r.visible_counts(viewer)
    if r.phase == 'turn' and r.turn == viewer:
        t14 = r._tiles14(viewer)
        n_melds = len(r.melds[viewer])
        disc = {}
        for t in acts.get('discard', []):
            rest = list(t14)
            rest.remove(t)
            w = waits(counts(rest), n_melds)
            if w:
                disc[t] = _wait_list(w, vis)
        return {'waits': [], 'furiten': False, 'discards': disc}
    w = r.player_waits(viewer)
    return {'waits': _wait_list(w, vis), 'furiten': r.is_furiten(viewer) if w else False, 'discards': {}}


def build_state(g, viewer):
    r = g.round
    playing = g.phase == 'playing'
    acts = r.legal_actions(viewer) if playing else {}
    players = []
    for s in range(4):
        p = {
            'seat': s, 'name': g.names[s], 'score': g.scores[s],
            'seat_wind': kind_str(r.seat_wind(s)), 'riichi': r.riichi[s],
            'discards': [dict(d) for d in r.discards[s]],
            'melds': [dict(m, tiles=list(m['tiles'])) for m in r.melds[s]],
            'hand_count': len(r.hands[s]),
        }
        if s == viewer:
            p['hand'] = list(r.hands[s])
        players.append(p)
    events = []
    for e in r.events:
        e = dict(e)
        if e['type'] == 'draw' and e['seat'] != viewer:
            e['tile'] = None
        events.append(e)
    return {
        'version': 1,
        'game_id': g.gid,
        'phase': g.phase,
        'round': {'wind': kind_str(g.round_wind), 'number': g.number, 'honba': g.honba,
                  'riichi_sticks': g.riichi_sticks, 'dealer': g.dealer},
        'dora_indicators': list(r.dora_indicators()),
        'wall_left': r.wall_left(),
        'viewer': viewer,
        'turn': r.turn,
        'waiting_for': r.waiting_for(),
        'rules': dict(g.rules),
        'players': players,
        'drawn': r.drawn if r.turn == viewer else None,
        'legal_actions': format_actions(acts),
        'hints': hints(r, viewer, acts) if playing else None,
        'events': events,
        'result': copy.deepcopy(r.result),
    }
