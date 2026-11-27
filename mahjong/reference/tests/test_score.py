"""算点：每种役各一手、符的各种来源、点数表各档、役满、开关、付点（含包）。

默认：自风南（闲家）、场风东、荣和。期望值都是按规则.md 手算的。
"""

import unittest

from util import EAST, M, W, yaku_names
from tiles import kind
from rules import parse_rules
from score import base_points, win_payments


class Yaku(unittest.TestCase):
    def check(self, res, han=None, fu=None, points=None, has=(), lacks=()):
        self.assertIsNotNone(res, '应该能和')
        names = yaku_names(res)
        for n in has:
            self.assertIn(n, names)
        for n in lacks:
            self.assertNotIn(n, names)
        if han is not None:
            self.assertEqual(res['han'], han, res)
        if fu is not None:
            self.assertEqual(res['fu'], fu, res)
        if points is not None:
            self.assertEqual(res['points'], points, res)

    def test_no_yaku(self):
        self.assertIsNone(W('123m456p789s13s55p', '2s'))

    def test_riichi(self):
        self.check(W('123m456p789s13s55p', '2s', riichi=True), 1, 40, 1300, ['立直'])

    def test_ippatsu(self):
        self.check(W('123m456p789s13s55p', '2s', riichi=True, ippatsu=True), 2, 40, 2600, ['立直', '一发'])

    def test_menzen_tsumo(self):
        self.check(W('123m456p789s13s55p', '2s', tsumo=True), 1, 30, 1100, ['门前清自摸和'])

    def test_tanyao_and_kuitan(self):
        self.check(W('234m456p678s34s55p', '2s'), 2, 30, 2000, ['断幺九', '平和'])
        self.check(W('456p678s34s55p', '5s', [M('chi', '234m')]), 1, 30, 1000, ['断幺九'])
        self.assertIsNone(W('456p678s34s55p', '5s', [M('chi', '234m')], rules={'kuitan': False}))

    def test_pinfu(self):
        self.check(W('123m456p789s23s55p', '4s'), 1, 30, 1000, ['平和'])
        self.check(W('123m456p789s23s55p', '4s', tsumo=True), 2, 20, 1500, ['平和', '门前清自摸和'])
        self.check(W('123m456p789s23s55p', '4s', tsumo=True, seat_wind=EAST), 2, 20, 2100)

    def test_iipeikou(self):
        self.check(W('112233m456p789s5s', '5s'), 1, 40, 1300, ['一杯口'])

    def test_yakuhai(self):
        self.check(W('123m456p789s9s', '9s', [M('pon', '555z')]), 1, 30, 1000, ['役牌 白'])
        # 连风：东场东家碰东，2 番；庄家 30 符 2 番荣和 2900
        self.check(W('123m456p789s9s', '9s', [M('pon', '111z')], seat_wind=EAST), 2, 30, 2900,
                   ['自风 东', '场风 东'])
        self.check(W('123m456p789s9s', '9s', [M('pon', '777z')]), 1, 30, 1000, ['役牌 中'])
        self.check(W('123m456p789s9s', '9s', [M('pon', '222z')]), 1, 30, 1000, ['自风 南'])

    def test_haitei_houtei_rinshan_chankan(self):
        chi = [M('chi', '123m')]
        self.check(W('456p789s111p2s', '2s', chi, tsumo=True, haitei=True), 1, 40, 1500, ['海底摸月'])
        self.check(W('456p789s111p2s', '2s', chi, houtei=True), 1, 30, 1000, ['河底捞鱼'])
        self.check(W('456p111p2s', '2s', chi + [M('minkan', '4444s')], tsumo=True, rinshan=True), 1, 40, 1500,
                   ['岭上开花'])
        self.check(W('456p789s111p2s', '2s', chi, chankan=True), 1, 30, 1000, ['抢杠'])

    def test_double_riichi(self):
        self.check(W('123m456p789s13s55p', '2s', double_riichi=True), 2, 40, 2600, ['两立直'], ['立直'])

    def test_chiitoi(self):
        self.check(W('1133m5577p22s66z4z', '4z'), 2, 25, 1600, ['七对子'])
        self.check(W('1133m5577p22s66z4z', '4z', tsumo=True, riichi=True), 4, 25, 6400)
        # 四张同种不算两对
        self.assertIsNone(W('1111m5577p22s66z4z', '4z', riichi=True))

    def test_sanshoku(self):
        self.check(W('234m234p234s789m5z', '5z'), 2, 40, 2600, ['三色同顺'])
        self.check(W('234m234p789m5z', '5z', [M('chi', '234s')]), 1, 30, 1000, ['三色同顺'])
        # 123 的三色加幺九字牌雀头还带混全
        self.check(W('123m123p123s789m5z', '5z'), 4, 40, 8000, ['三色同顺', '混全带幺九'])

    def test_ittsu(self):
        self.check(W('123456789m23p55s', '1p'), 3, 30, 3900, ['一气通贯', '平和'])

    def test_chanta(self):
        self.check(W('123m789p789s333z9m', '9m'), 2, 40, 2600, ['混全带幺九'])

    def test_junchan(self):
        # 9s 既可以当单骑也可以当 78s 的两面：两面解释有平和，4 番 30 符 7700 比单骑 3 番 40 符 5200 高
        self.check(W('123m789m123p789s9s', '9s'), 4, 30, 7700, ['纯全带幺九', '平和'], ['混全带幺九'])
        self.check(W('123m789m123p789s1s', '1s'), 3, 40, 5200, ['纯全带幺九'])

    def test_toitoi(self):
        self.check(W('666s88s99m', '8s', [M('pon', '222m'), M('pon', '444p')]), 2, 30, 2000, ['对对和'],
                   ['三暗刻'])

    def test_sanankou(self):
        self.check(W('222m444p666s78s99m', '9s'), 2, 50, 3200, ['三暗刻'])
        # 荣和完成的刻子算明刻
        self.check(W('222m444p345s99m11s', '9m', riichi=True), 1, 50, 1600, ['立直'], ['三暗刻'])
        self.check(W('222m444p345s99m11s', '9m', tsumo=True), 3, 40, 5200, ['三暗刻'])

    def test_sanshoku_doukou(self):
        self.check(W('222m222p222s34m77s', '5m'), 5, None, 8000, ['三色同刻', '三暗刻', '断幺九'])

    def test_sankantsu_70fu(self):
        # 暗杠 2222m 16 + 明杠 3333p 8 + 暗杠 4444s 16 + 单骑 2 = 62 -> 70 符；3 番 70 符 8000
        res = W('678m5s', '5s', [M('ankan', '2222m'), M('minkan', '3333p'), M('ankan', '4444s')])
        self.check(res, 3, 70, 8000, ['三杠子', '断幺九'])

    def test_shousangen(self):
        self.check(W('555z666z77z123m45p', '6p'), 4, 50, 8000, ['小三元', '役牌 白', '役牌 发'])

    def test_honroutou(self):
        self.check(W('999p111s99s33z', '3z', [M('pon', '111m')]), 4, 50, 8000, ['混老头', '对对和'])

    def test_honitsu_4han40fu(self):
        # 混一色 3 + 白 1 = 4 番；20+10+4(777m 暗刻)+4(555z 荣和明刻)+2(东雀头，场风)=40 符；闲家荣和 8000
        self.check(W('123m345m777m11z55z', '5z'), 4, 40, 8000, ['混一色', '役牌 白'])

    def test_ryanpeikou(self):
        self.check(W('223344m667788p5s', '5s'), 4, 40, 8000, ['二杯口', '断幺九'], ['一杯口', '七对子'])

    def test_chinitsu(self):
        self.check(W('123m345m567m789m5m', '5m'), None, None, 12000, ['清一色'])

    def test_best_decomposition(self):
        # 三暗刻（40 符 3 番）比一杯口（30 符 2 番）好
        self.check(W('111222333m456p9s', '9s', tsumo=True), 3, 40, 5200, ['三暗刻'], ['一杯口'])


class Fu(unittest.TestCase):
    def test_kanchan_penchan_tanki(self):
        self.assertEqual(W('123m456p789s13s55p', '2s', riichi=True)['fu'], 40)
        self.assertEqual(W('12m456p789s345s55p', '3m', riichi=True)['fu'], 40)
        self.assertEqual(W('112233m456p789s5s', '5s')['fu'], 40)

    def test_ryanmen_shanpon_zero(self):
        # 门清荣和 30 + 两面 0
        self.assertEqual(W('234m456p678s34s55p', '2s', riichi=True)['fu'], 30)
        # 双碰荣和：明刻 2 + 暗刻 4 + 20 + 10 = 36 -> 40
        self.assertEqual(W('234m456p678s44s55p', '5p', riichi=True)['fu'], 40)

    def test_open_no_fu_is_30(self):
        self.assertEqual(W('456p678s34s55p', '5s', [M('chi', '234m')])['fu'], 30)
        self.assertEqual(W('456p678s34s55p', '5s', [M('chi', '234m')], tsumo=True)['fu'], 30)

    def test_triplet_kan_values(self):
        # 明杠幺九 16 + 暗杠中张 16 + 中的明刻 4 + 单骑 2 = 58 -> 60（役牌 中）
        res = W('234m567p9s', '9s', [M('minkan', '1111p'), M('ankan', '5555s'), M('pon', '777z')])
        self.assertEqual(res['fu'], 60)
        # 明刻中张 2 + 暗刻中张 4：碰 222m，手里 444p 暗刻，嵌张：20 + 2 + 4 + 2 = 28 -> 30（断幺）
        res = W('444p456s68s55p', '7s', [M('pon', '222m')])
        self.assertEqual(res['fu'], 30)
        res = W('444p456s68s55p', '7s', [M('pon', '222m')], tsumo=True)   # +2 自摸 = 30
        self.assertEqual(res['fu'], 30)
        res = W('444p456s68s55z', '7s', [M('pon', '111m')], tsumo=True)   # 4+4+2+2+2(白雀头)=34 -> 40
        self.assertIsNone(res)   # 没役（门清没了、不断幺）
        # 暗杠幺九 32
        res = W('234m567p345s9s', '9s', [M('ankan', '1111z')], riichi=True)
        # 20 + 10 + 32 + 2 = 64 -> 70
        self.assertEqual(res['fu'], 70)

    def test_pair_fu_and_renpu(self):
        # 自风/场风雀头 +2：南家雀头南
        self.assertEqual(W('123m456p789s13s22z', '2s', riichi=True)['fu'], 40)   # 20+10+2+2=34
        # 连风雀头：东场东家，999m 暗刻 8 + 东雀头 4：20+10+8+4=42 -> 50；连风 2 符时 40
        r4 = W('999m456p789s23s11z', '4s', riichi=True, seat_wind=EAST)
        r2 = W('999m456p789s23s11z', '4s', riichi=True, seat_wind=EAST, rules={'renpu_fu': 2})
        self.assertEqual((r4['fu'], r4['points']), (50, 2400))
        self.assertEqual((r2['fu'], r2['points']), (40, 2000))
        # 三元牌雀头 +2
        self.assertEqual(W('123m456p789s13s55z', '2s', riichi=True)['fu'], 40)

    def test_tsumo_and_menzen_ron(self):
        self.assertEqual(W('123m456p789s13s55p', '2s', tsumo=True)['fu'], 30)    # 20+2+2=24
        self.assertEqual(W('123m456p789s13s55p', '2s', riichi=True)['fu'], 40)   # 20+10+2=32

    def test_pinfu_fixed(self):
        self.assertEqual(W('123m456p789s23s55p', '4s', tsumo=True)['fu'], 20)
        self.assertEqual(W('123m456p789s23s55p', '4s')['fu'], 30)

    def test_chiitoi_25(self):
        self.assertEqual(W('1133m5577p22s66z4z', '4z', riichi=True)['fu'], 25)


class Points(unittest.TestCase):
    def test_table(self):
        r = parse_rules({})
        k = parse_rules({'kiriage_mangan': True})
        self.assertEqual(base_points(4, 30, r), 1920)
        self.assertEqual(base_points(4, 30, k), 2000)
        self.assertEqual(base_points(3, 60, r), 1920)
        self.assertEqual(base_points(3, 60, k), 2000)
        self.assertEqual(base_points(4, 40, r), 2000)
        self.assertEqual(base_points(3, 70, r), 2000)
        self.assertEqual(base_points(5, 30, r), 2000)
        self.assertEqual(base_points(6, 30, r), 3000)
        self.assertEqual(base_points(7, 30, r), 3000)
        self.assertEqual(base_points(8, 30, r), 4000)
        self.assertEqual(base_points(10, 30, r), 4000)
        self.assertEqual(base_points(11, 30, r), 6000)
        self.assertEqual(base_points(12, 30, r), 6000)
        self.assertEqual(base_points(13, 30, r), 8000)
        self.assertEqual(base_points(13, 30, parse_rules({'kazoe_yakuman': False})), 6000)
        self.assertEqual(base_points(1, 30, r), 240)

    def test_30fu_4han_7700_and_kiriage(self):
        # 立直 平和 断幺 宝牌 1（指示牌 1s -> 宝牌 2s）
        a = W('234m456p678s34s55p', '2s', riichi=True, dora=['1s'])
        self.assertEqual((a['han'], a['fu'], a['points']), (4, 30, 7700))
        b = W('234m456p678s34s55p', '2s', riichi=True, dora=['1s'], rules={'kiriage_mangan': True})
        self.assertEqual(b['points'], 8000)
        # 庄家 30 符 4 番 11600，切上 12000
        c = W('234m456p678s34s55p', '2s', riichi=True, dora=['1s'], seat_wind=EAST)
        self.assertEqual(c['points'], 11600)

    def test_60fu_3han(self):
        # 暗杠 2222p 16 + 东暗刻 8 + 嵌张 2 + 门清荣和 10 = 56 -> 60；场风东 + 立直 + 宝牌（5m）= 3 番
        a = W('111z345m46s99p', '5s', [M('ankan', '2222p')], riichi=True, dora=['4m'])
        self.assertEqual((a['han'], a['fu'], a['points']), (3, 60, 7700))
        b = W('111z345m46s99p', '5s', [M('ankan', '2222p')], riichi=True, dora=['4m'],
              rules={'kiriage_mangan': True})
        self.assertEqual(b['points'], 8000)

    def test_dealer_and_tsumo_rounding(self):
        self.assertEqual(W('123m456p789s23s55p', '4s', seat_wind=EAST)['points'], 1500)
        self.assertEqual(W('123m456p789s13s55p', '2s', tsumo=True, seat_wind=EAST)['points'], 1500)  # 500 all

    def test_haneman_baiman_sanbaiman(self):
        # 清一色门清 6 番跳满
        self.assertEqual(W('123m345m567m789m5m', '5m')['points'], 12000)
        # 清一色 + 一气 + 平和 + 立直 = 6+2+1+1 = 10 番倍满
        res = W('123456789m99m23m', '4m', riichi=True)
        self.assertGreaterEqual(res['han'], 8)
        self.assertEqual(res['points'], 16000 if res['han'] <= 10 else 24000)

    def test_kazoe(self):
        res = W('1122335577889m', '9m', tsumo=True, riichi=True, dora=['8m', '6m'])
        self.assertGreaterEqual(res['han'], 13)
        self.assertEqual((res['yakuman'], res['points']), (0, 32000))
        res = W('1122335577889m', '9m', tsumo=True, riichi=True, dora=['8m', '6m'],
                rules={'kazoe_yakuman': False})
        self.assertEqual(res['points'], 24000)

    def test_dora_aka_ura(self):
        res = W('234m406p678s34s55p', '2s', riichi=True, dora=['1s'], ura=['4p'])
        names = dict(res['yaku'])
        self.assertEqual((names['宝牌'], names['赤宝牌'], names['里宝牌']), (1, 1, 3))   # 里宝 5p：0p 也算
        res = W('234m406p678s34s55p', '2s', riichi=True, dora=['1s'], ura=['4p'], rules={'aka_dora': False})
        self.assertNotIn('赤宝牌', yaku_names(res))
        # 没立直不算里宝
        res = W('234m406p678s34s55p', '2s', dora=['1s'], ura=['4p'])
        self.assertNotIn('里宝牌', yaku_names(res))
        # 宝牌不是役
        self.assertIsNone(W('123m456p789s13s55p', '2s', dora=['1s', '4p']))
        # 指示牌 9 -> 1、北 -> 东、中 -> 白
        self.assertEqual(dict(W('123m456p789s13s55p', '2s', riichi=True, dora=['9m'])['yaku'])['宝牌'], 1)
        self.assertEqual(dict(W('123m456p789s13s11z', '2s', riichi=True, dora=['4z'])['yaku'])['宝牌'], 2)
        self.assertEqual(dict(W('123m456p789s13s55z', '2s', riichi=True, dora=['7z'])['yaku'])['宝牌'], 2)


class Yakuman(unittest.TestCase):
    def ym(self, res, mult, points, names=()):
        self.assertIsNotNone(res)
        self.assertEqual(res['yakuman'], mult, res)
        self.assertEqual(res['points'], points, res)
        self.assertEqual(res['han'], 13 * mult)
        for n in names:
            self.assertIn(n, yaku_names(res))

    def test_tenhou_chiihou(self):
        self.ym(W('123m456p789s23s55p', '4s', tsumo=True, seat_wind=EAST, tenhou=True), 1, 48000, ['天和'])
        self.ym(W('123m456p789s23s55p', '4s', tsumo=True, chiihou=True), 1, 32000, ['地和'])

    def test_kokushi(self):
        self.ym(W('19m19p19s1234567z', '1m'), 2, 64000, ['国士无双十三面'])
        self.ym(W('119m19p19s123456z', '7z'), 1, 32000, ['国士无双'])
        self.ym(W('19m19p19s1234567z', '1m', rules={'double_yakuman': False}), 1, 32000)

    def test_suuankou(self):
        self.ym(W('111m333p555s777s2z', '2z', tsumo=True), 2, 64000, ['四暗刻单骑'])
        self.ym(W('111m333p555s77s44z', '4z', tsumo=True), 1, 32000, ['四暗刻'])
        self.ym(W('111m333p555s777s2z', '2z', tsumo=True, rules={'double_yakuman': False}), 1, 32000)
        # 双碰荣和不算四暗刻：对对和 + 三暗刻 4 番 50 符满贯
        res = W('111m333p555s77s44z', '4z')
        self.assertEqual((res['yakuman'], res['han'], res['fu'], res['points']), (0, 4, 50, 8000))

    def test_dragons_winds(self):
        self.ym(W('555z666z777z123m4p', '4p'), 1, 32000, ['大三元'])
        self.ym(W('111z222z333z4z123m', '4z'), 1, 32000, ['小四喜'])
        self.ym(W('222z333z444z5m', '5m', [M('pon', '111z')]), 2, 64000, ['大四喜'])
        self.ym(W('222z333z444z5m', '5m', [M('pon', '111z')], rules={'double_yakuman': False}), 1, 32000)

    def test_tsuuiisou_ryuuiisou_chinroutou(self):
        self.ym(W('1122334455667z', '7z'), 1, 32000, ['字一色'])
        self.ym(W('223344s666s888s6z', '6z'), 1, 32000, ['绿一色'])
        self.ym(W('223344s666s888s4s', '4s'), 1, 32000, ['绿一色'])
        self.ym(W('999m111p999p1s', '1s', [M('pon', '111m')]), 1, 32000, ['清老头'])

    def test_suukantsu(self):
        melds = [M('minkan', '2222m'), M('minkan', '3333p'), M('minkan', '4444s'), M('minkan', '6666s')]
        self.ym(W('7s', '7s', melds), 1, 32000, ['四杠子'])

    def test_chuuren(self):
        self.ym(W('1112345678999m', '5m'), 2, 64000, ['纯正九莲宝灯'])
        self.ym(W('1112345678899m', '9m'), 1, 32000, ['九莲宝灯'])

    def test_composite(self):
        self.ym(W('666z777z111z2z', '2z', [M('pon', '555z')]), 2, 64000, ['大三元', '字一色'])
        self.ym(W('666z777z111z2z', '2z', [M('pon', '555z')], rules={'composite_yakuman': False}), 1, 32000)
        # 四暗刻单骑 2 + 字一色 + 大四喜 2 = 5 倍
        self.ym(W('111z222z333z444z5z', '5z', tsumo=True), 5, 160000)

    def test_tenhou_chuuren_triple(self):
        # 天和九莲：纯正九莲 2 倍 + 天和 = 3 倍，庄家自摸 48000 all
        self.ym(W('1112345678999m', '5m', tsumo=True, seat_wind=EAST, tenhou=True), 3, 144000)
        self.ym(W('1112345678899m', '9m', tsumo=True, seat_wind=EAST, tenhou=True), 3, 144000)
        self.ym(W('1112345678899m', '9m', tsumo=True, seat_wind=EAST, tenhou=True,
                  rules={'tenhou_double': False}), 2, 96000)
        # 地和 + 四暗刻（双碰形也算 2 倍）
        self.ym(W('111m333p555s77s44z', '4z', tsumo=True, chiihou=True), 3, 96000)


class Payments(unittest.TestCase):
    R = parse_rules({})

    def win(self, base, mult=0, items=()):
        return {'base': base, 'yakuman': mult, 'yakuman_items': list(items)}

    def test_ron_tsumo_honba(self):
        w = self.win(240)
        self.assertEqual(win_payments(w, 1, 0, True, None, 2, None, self.R), [-700, 1700, -500, -500])
        self.assertEqual(win_payments(w, 1, 0, False, 3, 2, None, self.R), [0, 1600, 0, -1600])
        self.assertEqual(win_payments(w, 0, 0, True, None, 1, None, self.R), [1800, -600, -600, -600])

    def test_pao(self):
        w = self.win(8000, 1, [('大三元', 1)])
        # 自摸：包的人全付，本场也是他付
        self.assertEqual(win_payments(w, 1, 0, True, None, 1, 2, self.R), [0, 32300, -32300, 0])
        # 别人放铳：放铳者和包的人各一半
        self.assertEqual(win_payments(w, 1, 0, False, 3, 1, 2, self.R), [0, 32300, -16150, -16150])
        # 包的人自己放铳：全付
        self.assertEqual(win_payments(w, 1, 0, False, 2, 0, 2, self.R), [0, 32000, -32000, 0])
        # 不采用包
        self.assertEqual(win_payments(w, 1, 0, True, None, 0, 2, parse_rules({'pao': False})),
                         [-16000, 32000, -8000, -8000])
        # 复合役满：大三元归包，字一色照常自摸付
        w2 = self.win(16000, 2, [('大三元', 1), ('字一色', 1)])
        self.assertEqual(win_payments(w2, 1, 0, True, None, 0, 2, self.R), [-16000, 64000, -40000, -8000])


if __name__ == '__main__':
    unittest.main()


class Consistency(unittest.TestCase):
    """随机牌型：和了判定、拆牌枚举、向听数三者一致；立直后的和了型一定能算出点数。"""

    def test_random_hands(self):
        import random
        from agari import decompositions, is_agari, shanten, waits
        from tiles import kind_str
        rng = random.Random(42)
        for _ in range(3000):
            c = [0] * 34
            # 随机拼四面子一雀头（偶尔七对子），保证每种不超过 4 张
            ok = True
            if rng.random() < 0.1:
                for k in rng.sample(range(34), 7):
                    c[k] += 2
            else:
                for _ in range(4):
                    if rng.random() < 0.5:
                        k = rng.choice([x for x in range(27) if x % 9 <= 6])
                        for d in range(3):
                            c[k + d] += 1
                    else:
                        c[rng.randrange(34)] += 3
                c[rng.randrange(34)] += 2
            if max(c) > 4:
                continue
            self.assertTrue(is_agari(c, 0))
            self.assertEqual(shanten(c, 0), -1)
            if sum(1 for x in c if x == 2) != 7:
                self.assertTrue(decompositions(c))
            tiles = [kind_str(k) for k in range(34) for _ in range(c[k])]
            win = rng.choice(tiles)
            hand = list(tiles)
            hand.remove(win)
            res = W(''.join(hand), win, riichi=True)
            self.assertIsNotNone(res, tiles)
            self.assertEqual(res['han'], sum(h for _, h in res['yaku']))
            # 13 张：听牌 = 加一张后向听数 -1
            c13 = list(c)
            c13[kind(win)] -= 1
            w = set(waits(c13, 0))
            for k in range(34):
                if c13[k] < 4:
                    c13[k] += 1
                    self.assertEqual(k in w, shanten(c13, 0) == -1)
                    c13[k] -= 1
