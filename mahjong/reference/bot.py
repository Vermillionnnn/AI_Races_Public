"""电脑玩家：能和就和；否则打掉后向听数最小、有效进张最多的牌；门清听牌就立直；副露只碰役牌。"""

from tiles import DRAGONS, counts, dora_from_indicator, is_honor, is_terminal, kind
from agari import _candidates, shanten


def decide(r, s):
    acts = r.legal_actions(s)
    if 'tsumo' in acts:
        return {'type': 'tsumo'}
    if 'ron' in acts:
        return {'type': 'ron'}
    if r.phase == 'response':
        if 'pon' in acts:
            k = kind(r.window_tile)
            if k in DRAGONS or k == r.seat_wind(s) or k == r.round_wind:
                return {'type': 'pon', 'tiles': acts['pon'][0]}
        return {'type': 'pass'}
    if 'kyuushu' in acts:
        return {'type': 'kyuushu'}
    if r.riichi[s]:
        return {'type': 'discard', 'tile': r.drawn, 'tsumogiri': True}
    tile, sh = choose_discard(r, s, acts['discard'])
    if sh == 0 and tile in acts.get('riichi', []):
        typ = 'riichi'
    else:
        typ = 'discard'
    return {'type': typ, 'tile': tile, 'tsumogiri': tile == r.drawn}


def _keep_value(r, s, t, dora_kinds):
    """打牌时的次序：越小越先打。"""
    k = kind(t)
    v = 0
    if is_honor(k):
        v = 1 if (k in DRAGONS or k == r.seat_wind(s) or k == r.round_wind) else 0
    elif is_terminal(k):
        v = 1
    elif k % 9 in (1, 7):
        v = 2
    else:
        v = 3
    if t[0] == '0':
        v += 2
    if k in dora_kinds:
        v += 2
    return v


def choose_discard(r, s, candidates):
    t14 = r._tiles14(s)
    n_melds = len(r.melds[s])
    vis = r.visible_counts(s)
    dora_kinds = {dora_from_indicator(kind(t)) for t in r.dora_indicators()}
    c14 = counts(t14)
    scored = []
    for t in candidates:
        c = list(c14)
        c[kind(t)] -= 1
        scored.append((shanten(c, n_melds), t, c))
    best_sh = min(x[0] for x in scored)
    best = None
    for sh, t, c in scored:
        if sh != best_sh:
            continue
        uke = 0
        for k in _candidates(c, n_melds):
            left = 4 - vis[k]
            if left <= 0 or c[k] >= 4:
                continue
            c[k] += 1
            if shanten(c, n_melds) < sh:
                uke += left
            c[k] -= 1
        key = (-uke, _keep_value(r, s, t, dora_kinds))
        if best is None or key < best[0]:
            best = (key, t)
    return best[1], best_sh
