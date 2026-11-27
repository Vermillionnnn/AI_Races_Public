"""前端 index.html 里 checkState 的 Python 照搬（逐条对应，改动只为语法）。

页面顶上的红字提示就是这些检查；隐藏测试对每次返回的状态都跑一遍，有问题记进 I3。
"""

import re

TILE_RE = re.compile(r'^([0-9][mps]|[1-7]z)$')
RULE_KEYS = [('aka_dora', 'bool'), ('kuitan', 'bool'), ('kiriage_mangan', 'bool'), ('renpu_fu', 'fu')]


def _js_type(v):
    if isinstance(v, bool):
        return 'boolean'
    if isinstance(v, (int, float)):
        return 'number'
    if isinstance(v, str):
        return 'string'
    if isinstance(v, list):
        return 'array'
    return 'object'


def check_state(s):
    problems = []

    def need(obj, key, where, typ=None):
        if not isinstance(obj, dict) or key not in obj:
            problems.append('%s 缺少字段 "%s"' % (where, key))
            return False
        v = obj[key]
        if v is None:
            problems.append('%s.%s 不能是 null' % (where, key))
            return False
        if typ == 'array' and not isinstance(v, list):
            problems.append('%s.%s 应该是数组' % (where, key))
            return False
        if typ and typ != 'array':
            jt = _js_type(v)
            # JS 的 typeof 数组是 object
            if jt == 'array':
                jt_cmp = 'object'
            else:
                jt_cmp = jt
            if jt_cmp != typ:
                problems.append('%s.%s 应该是 %s，实际是 %s' % (where, key, typ, jt))
                return False
        return True

    def tiles(arr, where):
        if not isinstance(arr, list):
            return
        for i, t in enumerate(arr):
            if not (isinstance(t, str) and TILE_RE.match(t)):
                problems.append('%s[%d] 不是合法的牌："%s"' % (where, i, t))

    if not isinstance(s, dict):
        return ['返回值不是对象']
    if s.get('version') != 1:
        problems.append('version 应该是 1')
    need(s, 'game_id', 'state', 'string')
    if need(s, 'phase', 'state', 'string') and s['phase'] not in ('playing', 'round_end', 'game_end'):
        problems.append('phase 只能是 playing / round_end / game_end，实际是 "%s"' % s['phase'])
    if need(s, 'round', 'state', 'object') and s.get('round'):
        r = s['round']
        need(r, 'wind', 'round', 'string')
        for k in ('number', 'honba', 'riichi_sticks', 'dealer'):
            need(r, k, 'round', 'number')
        if r.get('wind') and r['wind'] not in ('1z', '2z', '3z', '4z'):
            problems.append('round.wind 应该是 1z~4z')
    if need(s, 'dora_indicators', 'state', 'array'):
        tiles(s['dora_indicators'], 'dora_indicators')
    need(s, 'wall_left', 'state', 'number')
    need(s, 'viewer', 'state', 'number')
    need(s, 'turn', 'state', 'number')
    need(s, 'waiting_for', 'state', 'array')
    if need(s, 'rules', 'state', 'object'):
        for k, kind in RULE_KEYS:
            if not need(s['rules'], k, 'rules'):
                continue
            v = s['rules'][k]
            if kind == 'bool' and not isinstance(v, bool):
                problems.append('rules.%s 应该是 true / false' % k)
            if kind == 'fu' and (isinstance(v, bool) or v not in (2, 4)):
                problems.append('rules.%s 应该是 2 或 4' % k)
    if need(s, 'players', 'state', 'array'):
        if len(s['players']) != 4:
            problems.append('players 应该有 4 个')
        for i, p in enumerate(s['players']):
            w = 'players[%d]' % i
            if not isinstance(p, dict):
                problems.append(w + ' 应该是对象')
                continue
            for k in ('seat', 'score', 'hand_count'):
                need(p, k, w, 'number')
            if _js_type(p.get('seat')) == 'number' and p['seat'] != i:
                problems.append('%s.seat 应该等于 %d（players 按座位号排列）' % (w, i))
            need(p, 'seat_wind', w, 'string')
            need(p, 'riichi', w, 'boolean')
            if need(p, 'discards', w, 'array'):
                for j, d in enumerate(p['discards']):
                    if not isinstance(d, dict) or not TILE_RE.match(str(d.get('tile'))):
                        problems.append('%s.discards[%d] 应该是 {tile, ...}' % (w, j))
            if need(p, 'melds', w, 'array'):
                for j, m in enumerate(p['melds']):
                    if not isinstance(m, dict) or m.get('type') not in ('chi', 'pon', 'minkan', 'ankan', 'kakan'):
                        problems.append('%s.melds[%d].type 不对' % (w, j))
                    if isinstance(m, dict):
                        if isinstance(m.get('tiles'), list):
                            tiles(m['tiles'], '%s.melds[%d].tiles' % (w, j))
                        else:
                            problems.append('%s.melds[%d].tiles 应该是数组' % (w, j))
            if i == s.get('viewer'):
                if need(p, 'hand', w, 'array'):
                    tiles(p['hand'], w + '.hand')
    if 'drawn' in s and s['drawn'] is not None and not (isinstance(s['drawn'], str) and TILE_RE.match(s['drawn'])):
        problems.append('drawn 不是合法的牌："%s"' % s['drawn'])
    if need(s, 'legal_actions', 'state', 'array'):
        for i, a in enumerate(s['legal_actions']):
            if not isinstance(a, dict) or not isinstance(a.get('type'), str):
                problems.append('legal_actions[%d] 缺少 type' % i)
    if s.get('phase') and s['phase'] != 'playing' and not s.get('result'):
        problems.append('phase 是 %s 时 result 不能为空' % s['phase'])
    r = s.get('result')
    if r:
        if r.get('type') == 'agari':
            if need(r, 'wins', 'result', 'array'):
                for i, w in enumerate(r['wins']):
                    where = 'result.wins[%d]' % i
                    if not isinstance(w, dict):
                        problems.append(where + ' 应该是对象')
                        continue
                    for k in ('seat', 'han', 'fu', 'yakuman', 'points'):
                        need(w, k, where, 'number')
                    if 'hand' in w:
                        if isinstance(w['hand'], list):
                            tiles(w['hand'], where + '.hand')
                        else:
                            problems.append(where + '.hand 应该是数组')
                    if 'melds' in w:
                        if not isinstance(w['melds'], list):
                            problems.append(where + '.melds 应该是数组')
                        else:
                            for j, m in enumerate(w['melds']):
                                if not isinstance(m, dict) or not isinstance(m.get('tiles'), list):
                                    problems.append('%s.melds[%d].tiles 应该是数组' % (where, j))
                                else:
                                    tiles(m['tiles'], '%s.melds[%d].tiles' % (where, j))
                    if need(w, 'yaku', where, 'array'):
                        for j, y in enumerate(w['yaku']):
                            if not isinstance(y, dict) or not isinstance(y.get('name'), str) \
                                    or _js_type(y.get('han')) != 'number':
                                problems.append('%s.yaku[%d] 应该是 {name, han}' % (where, j))
        elif r.get('type') != 'ryuukyoku':
            problems.append('result.type 只能是 agari / ryuukyoku')
        if need(r, 'delta', 'result', 'array'):
            if len(r['delta']) != 4:
                problems.append('result.delta 应该有 4 个')
            for i, d in enumerate(r['delta']):
                if _js_type(d) != 'number':
                    problems.append('result.delta[%d] 应该是数字' % i)
    return problems
