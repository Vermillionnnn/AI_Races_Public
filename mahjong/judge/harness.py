"""隐藏测试的框架：启动选手的后端、拼牌山、按剧本推进一局。

只走前端用的那套 HTTP 接口（见 club-project/frontend/接口说明.md），不碰选手的内部代码。
四个座位一律设成 human，由剧本决定谁做什么；剧本没写到的决定按默认处理：
轮到自己打牌就摸切，别人打牌后能鸣牌或荣和就 pass。
"""

import json
import os
import random
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from checkstate import check_state

# ---------------------------------------------------------------- 启动

def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server:
    """按接口说明的上线方式启动：在项目根目录跑 python3 server.py --port N，30 秒内 GET / 返回 200。"""

    def __init__(self, root, port=None, log_path=None, original=False):
        """original=True：学生原件按老师自己的跑法启动（PORT=N python3 server_patch.py），
        用来确认 bug 在原件上能复现；选手的提交一律按上线方式启动。"""
        self.root = root
        self.port = port or free_port()
        self.log_path = log_path
        self.original = original
        self.proc = None

    def __enter__(self):
        log = open(self.log_path, 'w') if self.log_path else subprocess.DEVNULL
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
        if self.original:
            cmd = [sys.executable, 'server_patch.py']
            env['PORT'] = str(self.port)
        else:
            cmd = [sys.executable, 'server.py', '--port', str(self.port)]
        self.proc = subprocess.Popen(cmd, cwd=self.root, stdout=log, stderr=subprocess.STDOUT, env=env)
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError('服务进程退出了，返回码 %s' % self.proc.returncode)
            try:
                with urllib.request.urlopen(self.url('/'), timeout=2) as r:
                    if r.status == 200:
                        return self
            except (urllib.error.URLError, ConnectionError, socket.timeout):
                pass
            time.sleep(0.3)
        self.__exit__(None, None, None)
        raise RuntimeError('30 秒内 GET / 没有返回 200')

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()

    def url(self, path):
        return 'http://127.0.0.1:%d%s' % (self.port, path)


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__('HTTP %s: %s' % (status, body))
        self.status = status
        self.body = body


class Client:
    TIMEOUT = 5  # 接口说明：每个请求 5 秒内要回

    def __init__(self, server):
        self.server = server
        self.format_problems = []   # 每次返回的状态都过一遍前端的 checkState，有问题记在这里（I3）

    def _req(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.server.url(path), data=data, method=method,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as r:
                out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ApiError(e.code, e.read().decode('utf-8', 'replace')) from None
        if path.startswith('/api/'):
            for p in check_state(out):
                self.format_problems.append('%s %s：%s' % (method, path.split('?')[0], p))
        return out

    def new_game(self, **body):
        return self._req('POST', '/api/new_game', body)

    def state(self, game_id, seat):
        return self._req('GET', '/api/state?game_id=%s&seat=%d' % (game_id, seat))

    def action(self, game_id, seat, type, **kw):
        return self._req('POST', '/api/action', dict(game_id=game_id, seat=seat, type=type, **kw))

    def next(self, game_id, seat=0, wall=None):
        body = dict(game_id=game_id, seat=seat)
        if wall is not None:
            body['wall'] = wall
        return self._req('POST', '/api/next', body)


# ---------------------------------------------------------------- 牌山

def full_set(aka=True):
    tiles = []
    for s in 'mps':
        for n in range(1, 10):
            for k in range(4):
                tiles.append('0' + s if (aka and n == 5 and k == 0) else '%d%s' % (n, s))
    for n in range(1, 8):
        tiles += ['%dz' % n] * 4
    return tiles


def build_wall(hands=None, draws=(), dora=(), ura=(), rinshan=(), aka=True, seed=0, avoid=(), mirror_original=True):
    """按接口说明的“指定牌山”拼 136 张。

    hands:   {物理座位: [13 张]}，没给的座位用剩下的牌随机补
    draws:   从 wall[52] 起依次摸的牌（庄家先摸），没给完的部分随机补
    dora:    宝牌指示牌 wall[122..]，ura: 里宝 wall[127..]，rinshan: 岭上牌 wall[132..]
    avoid:   补位时尽量不要发出去的牌种（比如不想让别人碰到的牌），放到牌山最深处
    mirror_original: 学生原件把 wall[126] 当宝牌指示牌（W1 的 bug）。为了不让这个 bug 把别的用例也带坏，
             默认在 wall[126]（按接口是第 5 张杠宝指示牌，极少用到）再放一张同样的指示牌；只有 W1 自己关掉。
             里宝 wall[127] 原件和接口恰好一致，不用管。
    """
    pool = full_set(aka)

    def take(t):
        if t not in pool:
            raise ValueError('牌不够或写法不对：%s' % t)
        pool.remove(t)
        return t

    hands = {k: [take(t) for t in v] for k, v in (hands or {}).items()}
    draws = [take(t) for t in draws]
    dead = {122 + i: take(t) for i, t in enumerate(dora)}
    dead.update({127 + i: take(t) for i, t in enumerate(ura)})
    dead.update({132 + i: take(t) for i, t in enumerate(rinshan)})
    if mirror_original and dora and 126 not in dead and dora[0] in pool:
        dead[126] = take(dora[0])

    rng = random.Random(seed)
    rng.shuffle(pool)
    if avoid:
        kinds = {norm(t) for t in avoid}
        pool.sort(key=lambda t: norm(t) in kinds)  # 稳定排序，要避开的放最后

    wall = [None] * 136
    for seat in range(4):
        h = hands.get(seat) or [pool.pop(0) for _ in range(13)]
        if len(h) != 13:
            raise ValueError('座位 %d 配牌不是 13 张' % seat)
        wall[13 * seat:13 * seat + 13] = h
    for i, t in enumerate(draws):
        wall[52 + i] = t
    for i, t in dead.items():
        wall[i] = t
    rest = [i for i in range(136) if wall[i] is None]
    # 要避开的牌放到正常摸牌的最后和王牌的空位里
    for i in rest:
        wall[i] = pool.pop(0)
    assert not pool and len(wall) == 136
    return wall


def norm(t):
    return '5' + t[1] if t[0] == '0' else t


# ---------------------------------------------------------------- 推进

class ScriptStuck(Exception):
    """剧本走不下去：一局提前结束、该做的操作一直不合法。记成 FAIL（程序没按规则给出该有的选项）。"""


class Script:
    """一局的剧本。steps 是 [(座位, 操作类型, 附带字段), ...]，按顺序执行。

    推进规则：每一步先问一遍 waiting_for 里的人；剧本下一步的座位在等，而且这个操作合法，就执行；
    否则让在等的人做默认决定（轮到打牌就摸切，能鸣牌/荣和就 pass）。
    """

    def __init__(self, client, game_id, max_requests=400):
        self.c = client
        self.gid = game_id
        self.max = max_requests
        self.log = []

    def view(self, seat):
        return self.c.state(self.gid, seat)

    def waiting(self):
        return self.view(0).get('waiting_for') or []

    def default(self, seat, st):
        legal = {a['type']: a for a in st.get('legal_actions') or []}
        if 'pass' in legal:
            self.log.append((seat, 'pass'))
            return self.c.action(self.gid, seat, 'pass')
        if 'discard' in legal:
            d = st.get('drawn')
            if d is not None:
                self.log.append((seat, 'discard', d, True))
                return self.c.action(self.gid, seat, 'discard', tile=d, tsumogiri=True)
            t = legal['discard']['tiles'][-1]
            self.log.append((seat, 'discard', t, False))
            return self.c.action(self.gid, seat, 'discard', tile=t, tsumogiri=False)
        raise RuntimeError('座位 %d 在等，但没有 pass 也没有 discard：%s' % (seat, list(legal)))

    def run(self, steps, until=None):
        """执行到剧本走完；until(state) 返回 True 时提前停。返回最后一次看到的座位 0 视角状态。"""
        steps = list(steps)
        # 剧本最后一步是和牌时，别人可能还能对同一张牌鸣牌或荣和，服务端要等大家表态才结算：
        # 继续替别人做默认决定（pass），直到这一局结束
        finishing = bool(steps) and steps[-1][1] in ('ron', 'tsumo', 'kyuushu')
        for _ in range(self.max):
            st0 = self.view(0)
            if st0['phase'] != 'playing':
                if steps:
                    raise ScriptStuck('一局结束了，剧本还剩 %d 步：%s' % (len(steps), steps[:3]))
                return st0
            if until and until(st0):
                return st0
            if not steps and until is None and not finishing:
                return st0
            waiting = st0.get('waiting_for') or []
            if not waiting:
                raise RuntimeError('playing 但 waiting_for 为空')
            if steps and steps[0][0] in waiting:
                seat, typ, kw = steps[0][0], steps[0][1], (steps[0][2] if len(steps[0]) > 2 else {})
                st = self.view(seat)
                legal = {a['type'] for a in st.get('legal_actions') or []}
                if typ in legal:
                    steps.pop(0)
                    self.log.append((seat, typ, kw))
                    self.c.action(self.gid, seat, typ, **kw)
                    continue
            # 剧本下一步还没轮到：让在等的人里第一个做默认决定
            seat = waiting[0]
            if steps and steps[0][0] == seat and len(waiting) > 1:
                seat = waiting[1]
            self.default(seat, self.view(seat))
        raise RuntimeError('超过 %d 次请求还没走完' % self.max)


RULES_DEFAULT = {'aka_dora': True, 'kuitan': True, 'kiriage_mangan': False, 'renpu_fu': 4}


def start(client, wall, rules=None, length='tonpuu', seed=1):
    return client.new_game(players=['human'] * 4, length=length, seed=seed,
                           rules=dict(RULES_DEFAULT, **(rules or {})), wall=wall)
