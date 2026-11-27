"""一场：局的顺序、庄家和本场、结束条件、电脑玩家推进（规则.md 第 2 节和“连庄和本场”）。"""

import random

from tiles import WINDS, full_set, kind, valid
from kyoku import ActionError, Round
import bot


class Game:
    def __init__(self, gid, players, length, seed, rules, wall=None):
        self.gid = gid
        self.players = players            # 每个座位 'human' / 'bot'
        self.length = length              # 'tonpuu' / 'hanchan'
        self.rules = rules
        self.rng = random.Random(seed)
        self.scores = [25000] * 4
        self.wind_idx = 0                 # 0 东场 1 南场 2 西场
        self.number = 1                   # 第几局（1-4）
        self.honba = 0
        self.riichi_sticks = 0
        self.phase = 'playing'
        self.round = None
        self._next = None                 # 这一局结束后下一局的 (wind_idx, number, honba)
        n_human = players.count('human')
        self.names = [('你' if n_human == 1 else '玩家 %d' % s) if p == 'human' else '电脑 %d' % s
                      for s, p in enumerate(players)]
        self._start_round(wall)

    @property
    def dealer(self):
        return self.number - 1

    @property
    def round_wind(self):
        return WINDS[self.wind_idx]

    # ------------------------------------------------------------ 牌山

    def _make_wall(self, wall):
        aka = self.rules['aka_dora']
        if wall is None:
            tiles = full_set(aka)
            self.rng.shuffle(tiles)
            return tiles
        if not isinstance(wall, list) or len(wall) != 136:
            raise ActionError('wall 应该是 136 张牌的数组')
        for i, t in enumerate(wall):
            if not valid(t):
                raise ActionError('wall[%d] 不是合法的牌：%r' % (i, t))
        if not aka:   # 没有赤宝牌时，红五当普通的五
            wall = [('5' + t[1]) if t[0] == '0' else t for t in wall]
        c = [0] * 34
        for t in wall:
            c[kind(t)] += 1
        if any(x != 4 for x in c):
            raise ActionError('wall 里每种牌应该正好 4 张')
        for s in 'mps':
            if wall.count('0' + s) > 1:
                raise ActionError('wall 里 0%s 超过 1 张' % s)
        return list(wall)

    def _start_round(self, wall):
        tiles = self._make_wall(wall)
        self.phase = 'playing'
        self._next = None
        self.round = Round(self, tiles)
        self.advance()

    # ------------------------------------------------------------ 推进

    def act(self, seat, req):
        if self.phase != 'playing':
            raise ActionError('这一局已经结束了' + ('，整场也结束了' if self.phase == 'game_end' else '，请调用 /api/next'))
        if self.players[seat] == 'bot':
            raise ActionError('座位 %d 是电脑，不接受操作' % seat)
        self.round.act(seat, req)
        self.advance()

    def advance(self):
        """电脑该做的都做完，直到又要等人类、或者这一局结束。"""
        for _ in range(10000):
            if self.phase != 'playing':
                return
            bots = [s for s in self.round.waiting_for() if self.players[s] == 'bot']
            if not bots:
                return
            self.round.act(bots[0], bot.decide(self.round, bots[0]))
        raise RuntimeError('电脑推进不停')

    def next_round(self, wall=None):
        if self.phase == 'playing':
            raise ActionError('这一局还没结束')
        if self.phase == 'game_end':
            raise ActionError('整场已经结束了，请开新游戏')
        tiles = self._make_wall(wall)       # 先检查牌山，出错时不动状态
        self.wind_idx, self.number, self.honba = self._next
        self.phase = 'playing'
        self._next = None
        self.round = Round(self, tiles)
        self.advance()

    # ------------------------------------------------------------ 一局结束

    def ranking(self):
        """名次顺序（座位号列表）：点数高的在前，同分按起家顺序。"""
        return sorted(range(4), key=lambda s: (-self.scores[s], s))

    def round_over(self, result, renchan, honba_reset):
        honba = 0 if honba_reset else self.honba + 1
        if renchan:
            nxt = (self.wind_idx, self.number, honba)
        elif self.number == 4:
            nxt = (self.wind_idx + 1, 1, honba)
        else:
            nxt = (self.wind_idx, self.number + 1, honba)
        dealer_kept = renchan and (result['type'] == 'agari' or result.get('reason') == 'exhaustive')
        if self._game_should_end(renchan, dealer_kept):
            self._finish_game(result)
        else:
            self.phase = 'round_end'
            self._next = nxt

    def _game_should_end(self, renchan, dealer_kept):
        r = self.rules
        if r['tobi'] and any(s < 0 for s in self.scores):
            return True
        last_wind = 0 if self.length == 'tonpuu' else 1
        ext = r['tonpuu_extension'] if self.length == 'tonpuu' else r['hanchan_extension']
        pos = (self.wind_idx, self.number)
        if pos < (last_wind, 4):
            return False
        in_ext = self.wind_idx > last_wind
        top = max(self.scores)
        if in_ext and top >= 30000:
            return True
        if renchan:
            if dealer_kept and r['agari_yame'] and self.ranking()[0] == self.dealer \
                    and (not ext or self.scores[self.dealer] >= 30000):
                return True
            return False
        if not in_ext:
            return not (ext and top < 30000)
        return pos == (last_wind + 1, 4)

    def _finish_game(self, result):
        self.phase = 'game_end'
        order = self.ranking()
        if self.riichi_sticks and self.rules['leftover_sticks_to_top']:
            top = order[0]
            n = self.riichi_sticks
            self.scores[top] += 1000 * n
            result['delta'][top] += 1000 * n
            result['leftover_sticks'] = {'to': top, 'count': n}
            self.riichi_sticks = 0
        ranks = [0] * 4
        for i, s in enumerate(order):
            ranks[s] = i + 1
        result['final'] = {'scores': list(self.scores), 'ranks': ranks}
