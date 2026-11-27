import random

from game import make_wall


def wall_with(hands=None, draws=(), dead=None, *, red=True):
    """从一副完整牌中预留指定位置，其余用固定种子填充。"""
    fixed = dict(dead or {})
    for seat, hand in (hands or {}).items():
        for i, tile in enumerate(hand):
            fixed[seat * 13 + i] = tile
    fixed.update(enumerate(draws, 52))
    rest = make_wall(red)
    for tile in fixed.values():
        rest.remove(tile)
    random.Random(217).shuffle(rest)
    free = iter(rest)
    return [fixed[i] if i in fixed else next(free) for i in range(136)]


def pass_calls(g):
    for seat in range(4):
        if any(a['type'] == 'pass' for a in g.get_legal_actions(seat)):
            g.do_action(seat, 'pass')
