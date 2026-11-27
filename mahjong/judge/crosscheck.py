"""算点对拍：随机生成和了的局面，拼成牌山打到和牌，拿参考后端的结算当标准答案，比各份提交。

用法：
    python3 mahjong/judge/crosscheck.py -n 2000                  # 全部提交
    python3 mahjong/judge/crosscheck.py -n 300 gpt-6 qwen4-max   # 只比这几份
    python3 mahjong/judge/crosscheck.py --replay 17              # 重放第 17 号样本，打印各家结果

样本由种子决定（--seed，默认 1），同样的参数跑出同样的样本。
每个样本先在参考后端上跑；参考后端判定和不了（比如没有役）的样本丢掉。
比对：和牌者的 han、fu（只在 5 番以下、非役满时比）、yakuman、points，和四家 delta。
结果：分歧明细写到 mahjong/judge/out/crosscheck-<选手>.jsonl，终端打印按“差在哪”归类的统计。

缓存：每个样本在每份程序上的结果存在 mahjong/judge/out/cc-cache/<名字>-<代码指纹>.json（忽略目录，不进仓库）。
代码指纹 = 这份程序的全部 .py 加上 harness.py、本文件的 run_sample 的内容；改了程序或跑法就自动失效。
样本按牌山、剧本、规则开关算键，所以换 -n、换种子时重叠的样本也能复用。--no-cache 不读不写缓存。
"""

import argparse
import hashlib
import inspect
import collections
import json
import os
import random
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MAHJONG = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(MAHJONG, 'reference'))

from harness import Client, Script, ScriptStuck, Server, full_set  # noqa: E402
import agari as ref_agari                                             # noqa: E402
import tiles as ref_tiles                                             # noqa: E402

ROUND1 = os.path.join(MAHJONG, 'round-1', 'submissions')
ROUND15 = os.path.join(MAHJONG, 'round-1.5', 'submissions')


def norm(t):
    return '5' + t[1] if t[0] == '0' else t


def D(tile, tsumogiri=True):
    return {'tile': tile, 'tsumogiri': tsumogiri}


# ---------------------------------------------------------------- 生成一手和了的牌

SUITS = 'mps'


def _seq(rng, suits, lo=1, hi=7):
    s = rng.choice(suits)
    n = rng.randint(lo, hi)
    return ['%d%s' % (n + i, s) for i in range(3)]


def _gen_complete(rng):
    """返回 (style, 14 张的牌种字符串列表 [普通五写 5x])。"""
    style = rng.choices(['random', 'tanyao', 'flush', 'yakuhai', 'toitoi', 'chiitoi', 'chanta'],
                        weights=[30, 15, 12, 15, 8, 8, 5])[0]
    for _ in range(200):
        groups = []
        if style == 'chiitoi':
            pool = ['%d%s' % (n, s) for s in SUITS for n in range(1, 10)] + ['%dz' % n for n in range(1, 8)]
            pairs = rng.sample(pool, 7)
            tiles = [t for p in pairs for t in (p, p)]
            return style, tiles
        suits = list(SUITS)
        honors = ['%dz' % n for n in range(1, 8)]
        if style == 'flush':
            suits = [rng.choice(SUITS)]
            if rng.random() < 0.5:
                honors = honors
            else:
                honors = []
        for gi in range(4):
            r = rng.random()
            if style == 'toitoi' or (style in ('random', 'flush', 'yakuhai') and r < 0.3):
                if (style in ('random', 'yakuhai', 'toitoi', 'flush') and honors and rng.random() < 0.3) \
                        or (style == 'yakuhai' and gi == 0):
                    t = rng.choice(['5z', '6z', '7z', '1z', '2z'] if style == 'yakuhai' else honors)
                else:
                    t = '%d%s' % (rng.randint(2, 8) if style == 'tanyao' else rng.randint(1, 9), rng.choice(suits))
                groups.append([t] * 3)
            elif style == 'chanta':
                s = rng.choice(suits)
                n = rng.choice([1, 7])
                groups.append(['%d%s' % (n + i, s) for i in range(3)])
            elif style == 'tanyao':
                groups.append(_seq(rng, suits, 2, 6))
            else:
                groups.append(_seq(rng, suits))
        if style == 'chanta':
            pair = rng.choice(['1z', '5z', '9' + rng.choice(SUITS), '1' + rng.choice(SUITS)])
        elif style == 'tanyao':
            pair = '%d%s' % (rng.randint(2, 8), rng.choice(suits))
        elif honors and rng.random() < 0.25:
            pair = rng.choice(honors)
        else:
            pair = '%d%s' % (rng.randint(1, 9), rng.choice(suits))
        tiles = [t for g in groups for t in g] + [pair, pair]
        if max(collections.Counter(tiles).values()) <= 4:
            return style, tiles
    return None


def gen_sample(rng, sid):
    """生成一个样本：规则、牌山、剧本。生成不出来返回 None。"""
    rules = {'aka_dora': rng.random() < 0.7, 'kuitan': rng.random() < 0.7,
             'kiriage_mangan': rng.random() < 0.3, 'renpu_fu': rng.choice([4, 2])}
    g = _gen_complete(rng)
    if not g:
        return None
    style, tiles = g
    pool = full_set(rules['aka_dora'])

    # 用实际的牌（红五按开关换进来）
    def take(kind_str):
        cands = [t for t in pool if norm(t) == kind_str]
        if not cands:
            raise ValueError
        reds = [t for t in cands if t[0] == '0']
        plain = [t for t in cands if t[0] != '0']
        t = reds[0] if (reds and (not plain or rng.random() < 0.35)) else plain[0]
        pool.remove(t)
        return t
    try:
        hand14 = [take(t) for t in tiles]
    except ValueError:
        return None

    winner = rng.randrange(4)
    mode = rng.choice(['ron', 'tsumo'])
    opened = style not in ('chiitoi',) and rng.random() < 0.3
    # 和了张
    win_i = rng.randrange(14)
    win = hand14[win_i]
    rest13 = hand14[:win_i] + hand14[win_i + 1:]

    pon_tile = None
    if opened:
        c = collections.Counter(norm(t) for t in rest13)
        trips = [k for k, v in c.items() if v >= 3 and k != norm(win)]
        if not trips:
            opened = False
        else:
            pon_tile = rng.choice(trips)
    riichi = (not opened) and rng.random() < 0.5
    riichi_turn = rng.choice([0, 1]) if riichi else None   # 自己的第几次摸牌时立直（0 = 两立直）

    def kinds_of(ts):
        return ref_tiles.counts(ts)

    # 门清 13 张的听牌
    if opened:
        # 碰之前手里：碰的那种拿 2 张，另外 10 张（去掉碰的 3 张和和了张），加 1 张要打掉的闲牌
        rest = list(rest13)
        for _ in range(3):
            rest.remove(next(t for t in rest if norm(t) == pon_tile))
        conc10 = rest
        waits = ref_agari.waits(kinds_of(conc10), 1)
    else:
        waits = ref_agari.waits(kinds_of(rest13), 0)
    if ref_tiles.kind(win) not in waits:
        return None
    wait_strs = {ref_tiles.kind_str(k) for k in waits}

    def take_junk():
        cands = [t for t in pool if norm(t) not in wait_strs and t[0] != '0' and norm(t) != pon_tile]
        t = rng.choice(cands)
        pool.remove(t)
        return t

    fixed = {}        # 牌山下标 -> 牌
    steps = []
    hands = {}
    if opened:
        # 碰的 3 张都在 rest13 里：两张留在手里，第三张由别人摸到后打出
        mine = [t for t in rest13 if norm(t) == pon_tile][:3]
        called = mine[2]
        mine2 = mine[:2]
        junk0 = take_junk()
        pre = conc10 + mine2 + [junk0]
        hands[winner] = pre
    else:
        hands[winner] = rest13

    # ---- 排剧本：模拟轮次，算出每个关键摸牌在牌山的下标
    cur, idx = 0, 52
    events = []
    if opened:
        p = rng.choice([s for s in range(4) if s != winner])
        events.append(('dd', p, called, False))
        events.append(('pon', winner, [mine2[0], mine2[1]], junk0))
    if riichi:
        for k in range(riichi_turn):
            events.append(('dd', winner, take_junk(), False))
        events.append(('dd', winner, take_junk(), True))
    if mode == 'ron':
        d = rng.choice([s for s in range(4) if s != winner])
        events.append(('dd', d, win, False))
        events.append(('ron', winner))
    else:
        if not riichi and rng.random() < 0.9 and not opened:
            events.append(('dd', winner, take_junk(), False))   # 一般不让天和、地和太多
        events.append(('tsumo_draw', winner, win))
        events.append(('tsumo', winner))

    first_discards = []
    for ev in events:
        if ev[0] in ('dd', 'tsumo_draw'):
            seat = ev[1]
            while cur != seat:            # 中间别人摸牌、摸切（默认）
                cur = (cur + 1) % 4
                idx += 1
            fixed[idx] = ev[2]
            if ev[0] == 'dd':
                typ = 'riichi' if ev[3] else 'discard'
                steps.append((seat, typ, D(ev[2], True)))
                cur = (cur + 1) % 4
            idx += 1
        elif ev[0] == 'pon':
            steps.append((ev[1], 'pon', {'tiles': ev[2]}))
            steps.append((ev[1], 'discard', D(ev[3], False)))
            cur = (ev[1] + 1) % 4
        elif ev[0] == 'ron':
            steps.append((ev[1], 'ron'))
        elif ev[0] == 'tsumo':
            steps.append((ev[1], 'tsumo'))
    if idx > 52 + 60:
        return None

    # ---- 填牌山：指定的位置先占，宝牌指示牌、里宝随机；听的牌往牌山深处放
    # 手牌、和了张、闲牌在上面取的时候都已经从 pool 里拿掉了
    dora_ind = rng.choice(pool)
    pool.remove(dora_ind)
    ura_ind = rng.choice(pool)
    pool.remove(ura_ind)
    rng.shuffle(pool)
    pool.sort(key=lambda t: norm(t) in wait_strs)
    wall = [None] * 136
    wall[13 * winner:13 * winner + 13] = hands[winner]
    wall[122] = dora_ind
    wall[127] = ura_ind
    for i, t in fixed.items():
        wall[i] = t
    for i in range(136):
        if wall[i] is None:
            wall[i] = pool.pop(0)
    if sorted(wall) != sorted(full_set(rules['aka_dora'])):
        return None
    return {'id': sid, 'style': style, 'winner': winner, 'mode': mode, 'opened': opened,
            'riichi_turn': riichi_turn, 'rules': rules, 'wall': wall, 'steps': steps}


# ---------------------------------------------------------------- 跑一个样本

def run_sample(c, smp):
    st = c.new_game(players=['human'] * 4, length='tonpuu', seed=1, rules=smp['rules'], wall=smp['wall'])
    steps = [tuple(x) if not isinstance(x, tuple) else x for x in smp['steps']]
    end = Script(c, st['game_id'], max_requests=300).run(steps)
    r = end.get('result') or {}
    if r.get('type') != 'agari':
        raise ScriptStuck('没有和牌：%s' % r.get('type'))
    w = next((x for x in r['wins'] if x['seat'] == smp['winner']), None)
    if w is None:
        raise ScriptStuck('和牌的不是座位 %d' % smp['winner'])
    return {'han': w['han'], 'fu': w['fu'], 'yakuman': w['yakuman'], 'points': w['points'],
            'delta': r['delta'], 'yaku': [(y['name'], y['han']) for y in w['yaku']], 'nwins': len(r['wins'])}


def code_hash(root):
    """程序目录里全部 .py（不含测试）加上跑法本身的指纹。"""
    h = hashlib.sha1()
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in ('__pycache__', 'tests', 'test'))
        for fn in sorted(fns):
            if fn.endswith('.py') and not fn.startswith('test_'):
                fp = os.path.join(dp, fn)
                h.update(os.path.relpath(fp, root).encode())
                with open(fp, 'rb') as f:
                    h.update(f.read())
    with open(os.path.join(HERE, 'harness.py'), 'rb') as f:
        h.update(f.read())
    h.update(inspect.getsource(run_sample).encode())
    return h.hexdigest()[:12]


def sample_key(smp):
    raw = json.dumps([smp['wall'], smp['steps'], smp['rules'], smp['winner']], sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


class Cache:
    """一份程序的结果缓存：{样本键: 结果 dict 或 {'error': ...}}。"""

    def __init__(self, name, root, enabled):
        self.enabled = enabled
        d = os.path.join(HERE, 'out', 'cc-cache')
        self.path = os.path.join(d, '%s-%s.json' % (name, code_hash(root)))
        self.data = {}
        self.dirty = False
        if enabled:
            os.makedirs(d, exist_ok=True)
            if os.path.isfile(self.path):
                with open(self.path, encoding='utf-8') as f:
                    self.data = json.load(f)

    def get(self, smp):
        return self.data.get(sample_key(smp)) if self.enabled else None

    def put(self, smp, val):
        if self.enabled:
            self.data[sample_key(smp)] = val
            self.dirty = True

    def save(self):
        if self.enabled and self.dirty:
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False)
            os.replace(tmp, self.path)


def run_cached(cache, samples, root, log_path=None):
    """按缓存取结果，缺的才起服务器去跑。返回和 samples 同序的结果列表（失败的是 {'error': ...}）。"""
    out = [cache.get(s) for s in samples]
    miss = [i for i, v in enumerate(out) if v is None]
    if miss:
        with Server(root, log_path=log_path) as srv:
            c = Client(srv)
            for k, i in enumerate(miss):
                try:
                    v = run_sample(c, samples[i])
                    v['yaku'] = [list(y) for y in v['yaku']]
                except Exception as e:
                    v = {'error': '%s: %s' % (type(e).__name__, e)}
                out[i] = v
                cache.put(samples[i], v)
                if k % 200 == 199:
                    cache.save()
        cache.save()
    return out, len(miss)


def compare(ref, got):
    diffs = []
    for k in ('yakuman', 'han', 'points'):
        if ref[k] != got[k]:
            diffs.append(k)
    if ref['yakuman'] == 0 and ref['han'] < 5 and ref['fu'] != got['fu']:
        diffs.append('fu')
    if ref['delta'] != got['delta']:
        diffs.append('delta')
    return diffs


def targets(names):
    allt = [(d, os.path.join(ROUND1, d)) for d in sorted(os.listdir(ROUND1))
            if os.path.isfile(os.path.join(ROUND1, d, 'server.py'))]
    if os.path.isdir(ROUND15):   # round 1.5 的提交，名字加后缀 @r1.5（只在点名时跑）
        allt += [(d + '@r1.5', os.path.join(ROUND15, d)) for d in sorted(os.listdir(ROUND15))
                 if os.path.isfile(os.path.join(ROUND15, d, 'server.py')) and names and d + '@r1.5' in names]
    return [t for t in allt if not names or t[0] in names]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('names', nargs='*')
    ap.add_argument('-n', type=int, default=300, help='生成多少个样本（丢掉不合格的之前）')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--replay', type=int, default=None)
    ap.add_argument('--no-cache', action='store_true', help='不读也不写 out/cc-cache/')
    a = ap.parse_args()
    out_dir = os.path.join(HERE, 'out')
    os.makedirs(out_dir, exist_ok=True)

    rng = random.Random(a.seed)
    samples = []
    for i in range(a.n):
        try:
            s = gen_sample(rng, i)
        except Exception:
            s = None
        if s:
            samples.append(s)
    if a.replay is not None:
        samples = [s for s in samples if s['id'] == a.replay]

    # 参考后端先跑，得到标准答案
    t0 = time.time()
    ref_root = os.path.join(MAHJONG, 'reference')
    refs, nmiss = run_cached(Cache('reference', ref_root, not a.no_cache), samples, ref_root)
    good = []
    for s, v in zip(samples, refs):
        if 'error' not in v:
            s['ref'] = v
            good.append(s)
    print('样本：生成 %d，参考后端能和的 %d（%.0f 秒，新跑 %d 个，其余来自缓存）'
          % (len(samples), len(good), time.time() - t0, nmiss), file=sys.stderr)
    if a.replay is not None and good:
        print(json.dumps({k: v for k, v in good[0].items() if k != 'wall'}, ensure_ascii=False, indent=1))
        print('wall', good[0]['wall'])

    results = {}

    def work(name, root):
        stat = collections.Counter()
        with open(os.path.join(out_dir, 'crosscheck-%s.jsonl' % name), 'w', encoding='utf-8') as fh:
            try:
                gots, _ = run_cached(Cache(name, root, not a.no_cache), good, root,
                                     log_path=os.path.join(out_dir, 'crosscheck-%s.server.log' % name))
            except Exception as e:
                results[name] = ('启动失败 %s' % e, stat)
                return
            if True:
                for s, got in zip(good, gots):
                    if 'error' in got:
                        diffs = ['error']
                    else:
                        try:
                            diffs = compare(s['ref'], got)
                        except Exception as e:
                            got, diffs = {'error': '%s: %s' % (type(e).__name__, e)}, ['error']
                    stat['total'] += 1
                    if diffs:
                        stat['diff'] += 1
                        stat['+'.join(diffs)] += 1
                        fh.write(json.dumps({'id': s['id'], 'style': s['style'], 'mode': s['mode'],
                                             'opened': s['opened'], 'riichi_turn': s['riichi_turn'],
                                             'rules': s['rules'], 'diffs': diffs, 'ref': s['ref'], 'got': got},
                                            ensure_ascii=False) + '\n')
                        if a.replay is not None:
                            print(name, diffs, got)
        results[name] = ('', stat)

    ths = [threading.Thread(target=work, args=t) for t in targets(a.names)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    print('| 选手 | 比了 | 不一致 | 主要差在哪 |')
    print('|---|---|---|---|')
    for name in sorted(results):
        err, st = results[name]
        kinds = ', '.join('%s×%d' % (k, v) for k, v in st.most_common() if k not in ('total', 'diff'))[:120]
        print('| %s | %d | %d | %s%s |' % (name, st['total'], st['diff'], err, kinds))


if __name__ == '__main__':
    main()
