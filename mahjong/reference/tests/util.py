"""测试共用：写牌的简写、直接算点、进程内的接口客户端（和 judge/harness.py 的 Client 同一套方法）。"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.dirname(HERE)
JUDGE = os.path.join(REF, '..', 'judge')
sys.path.insert(0, REF)
sys.path.insert(0, JUDGE)

import harness                                   # noqa: E402
from rules import parse_rules                    # noqa: E402
from score import best_win                       # noqa: E402
from tiles import EAST, SOUTH, WEST, NORTH       # noqa: E402,F401
from yaku_fu import WinContext                   # noqa: E402
import server                                    # noqa: E402
from kyoku import ActionError                    # noqa: E402


def T(s):
    """'123m55z' -> ['1m','2m','3m','5z','5z']。"""
    out, nums = [], ''
    for ch in s.replace(' ', ''):
        if ch.isdigit():
            nums += ch
        else:
            out += [n + ch for n in nums]
            nums = ''
    return out


def M(typ, s, frm=1):
    """副露的简写：M('pon', '555z')、M('chi', '345m')、M('ankan', '1111z')。"""
    tiles = T(s)
    return {'type': typ, 'tiles': tiles, 'from': None if typ == 'ankan' else frm,
            'called_tile': None if typ == 'ankan' else tiles[-1]}


def W(hand, win, melds=(), tsumo=False, seat_wind=SOUTH, round_wind=EAST, dealer=None, rules=None,
      dora=('9z',), ura=(), **kw):
    """算一手和了：hand 是不含和了牌的手牌简写，win 是和了牌。dora 默认放一张不存在的指示牌占位（'9z' 被忽略）。"""
    r = parse_rules(rules or {})
    if dealer is None:
        dealer = seat_wind == EAST
    ctx = WinContext(tsumo=tsumo, seat_wind=seat_wind, round_wind=round_wind, dealer=dealer, rules=r,
                     dora_indicators=[d for d in dora if d != '9z'], ura_indicators=list(ura), **kw)
    return best_win(T(hand) + [win], win, list(melds), ctx)


def yaku_names(res):
    return [n for n, _ in res['yaku']]


class InProcClient:
    """不起服务、直接调 server.py 的处理函数；方法和 harness.Client 一样，场景测试两边共用。"""

    def _call(self, fn, *args):
        try:
            return fn(*args)
        except server.ApiError as e:
            raise harness.ApiError(e.status, e.args[0]) from None
        except ActionError as e:
            raise harness.ApiError(400, str(e)) from None

    def new_game(self, **body):
        return self._call(server.api_new_game, body)

    def state(self, game_id, seat):
        return self._call(server.api_state, {'game_id': [game_id], 'seat': [str(seat)]})

    def action(self, game_id, seat, type, **kw):
        return self._call(server.api_action, dict(game_id=game_id, seat=seat, type=type, **kw))

    def next(self, game_id, seat=0, wall=None):
        body = dict(game_id=game_id, seat=seat)
        if wall is not None:
            body['wall'] = wall
        return self._call(server.api_next, body)

    def game(self, game_id):
        """进程内才有：直接拿到 Game 对象（改点数、本场等，搭特殊局面用）。"""
        return server.GAMES[game_id]


# ---------------------------------------------------------------- checkState（用 node 跑页面里的函数）

import json        # noqa: E402
import shutil      # noqa: E402
import subprocess  # noqa: E402
import tempfile    # noqa: E402

PAGE = os.path.normpath(os.path.join(REF, '..', 'club-project', 'frontend', 'index.html'))


def check_states(named_states):
    """[(名字, 状态), ...] 交给 node 跑一遍 checkState。返回 (是否全过, 输出)；没有 node 时返回 (None, 说明)。"""
    if not shutil.which('node'):
        return None, '没有 node，跳过 checkState'
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump(named_states, f, ensure_ascii=False)
        path = f.name
    try:
        p = subprocess.run(['node', os.path.join(HERE, 'check_state.js'), PAGE, path],
                           capture_output=True, text=True, timeout=120)
        return p.returncode == 0, p.stdout + p.stderr
    finally:
        os.unlink(path)
