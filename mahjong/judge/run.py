"""跑已知 bug 的复现用例，输出一张 用例 × 选手 的表。

用法（在仓库任意位置）：
    python3 mahjong/judge/run.py                 # 学生原件 + round-1 全部提交
    python3 mahjong/judge/run.py gpt-6 qwen4-max # 只跑这几份（目录名），原件写 original
    python3 mahjong/judge/run.py -k S4 P1        # 只跑这几个用例

结果打印成 Markdown 表；每格 PASS / FAIL / VAR / ERR（用例自己出错，多半是剧本走不下去，也算没过）。
详细原因写到 mahjong/judge/out/<选手>.txt（out/ 不进仓库）。
"""

import argparse
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from harness import Client, Script, ScriptStuck, Server  # noqa: E402
from cases import CASES             # noqa: E402

MAHJONG = os.path.dirname(HERE)
ROUND1 = os.path.join(MAHJONG, 'round-1', 'submissions')
ROUND15 = os.path.join(MAHJONG, 'round-1.5', 'submissions')


def targets(names):
    allt = [('original', os.path.join(MAHJONG, 'player-kit'), True)]
    allt += [(d, os.path.join(ROUND1, d), False) for d in sorted(os.listdir(ROUND1))
             if os.path.isfile(os.path.join(ROUND1, d, 'server.py'))]
    # round 1.5 的提交，名字加后缀 @r1.5（只在点名时跑）
    if os.path.isdir(ROUND15):
        allt += [(d + '@r1.5', os.path.join(ROUND15, d), False) for d in sorted(os.listdir(ROUND15))
                 if os.path.isfile(os.path.join(ROUND15, d, 'server.py')) and names and d + '@r1.5' in names]
    ref = os.path.join(MAHJONG, 'reference', 'server.py')
    if os.path.isfile(ref):
        allt.append(('reference', os.path.dirname(ref), False))
    if names:
        allt = [t for t in allt if t[0] in names]
    return allt


def run_target(name, root, original, cases, out_dir):
    res = {}
    lines = []
    try:
        srv = Server(root, original=original, log_path=os.path.join(out_dir, name + '.server.log'))
        srv.__enter__()
    except Exception as e:
        lines.append('启动失败：%s' % e)
        for f in cases:
            res[f.cid] = ('ERR', '启动失败')
        res['I1'] = ('FAIL', str(e))
        return res, lines
    res['I1'] = ('PASS', '')
    try:
        c = Client(srv)
        for f in cases:
            t0 = time.time()
            try:
                r = f(c)
                st, detail = r.status, r.detail
            except (ScriptStuck, AssertionError) as e:
                st, detail = 'FAIL', str(e)
            except Exception as e:
                st, detail = 'ERR', '%s: %s' % (type(e).__name__, e)
                lines.append(traceback.format_exc(limit=3))
            res[f.cid] = (st, detail)
            lines.append('%-4s %-5s %5.1fs  %s  %s' % (f.cid, st, time.time() - t0, f.title, detail))
        probs = sorted(set(p.split('：', 1)[1] for p in c.format_problems))
        res['I3'] = ('PASS', '') if not probs else ('FAIL', '；'.join(probs[:5]))
        lines.append('I3 格式检查：%s' % ('无问题' if not probs else '\n  '.join(probs)))
    finally:
        srv.__exit__(None, None, None)
    return res, lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('names', nargs='*')
    ap.add_argument('-k', nargs='+', default=None, help='只跑这些用例编号')
    a = ap.parse_args()
    cases = [f for f in CASES if not a.k or f.cid in a.k]
    out_dir = os.path.join(HERE, 'out')
    os.makedirs(out_dir, exist_ok=True)
    table = {}
    for name, root, original in targets(a.names):
        res, lines = run_target(name, root, original, cases, out_dir)
        table[name] = res
        with open(os.path.join(out_dir, name + '.txt'), 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
        print('%s：%s' % (name, ' '.join('%s=%s' % (k, v[0]) for k, v in res.items())), file=sys.stderr)
    ids = ['I1', 'I3'] + [f.cid for f in cases]
    names = list(table)
    print('| 用例 | ' + ' | '.join(names) + ' |')
    print('|---|' + '---|' * len(names))
    for cid in ids:
        if not any(cid in table[n] for n in names):
            continue
        print('| %s | %s |' % (cid, ' | '.join(table[n].get(cid, ('-',))[0] for n in names)))


if __name__ == '__main__':
    main()
