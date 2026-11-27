# 学号：260409（已整理修复）
# 日本麻将点数计算（支持切上满贯开关、高符满贯封顶、多倍役满、累计役满）

import math

# 満貫以上的点数表：(親ロン, 親ツモ每人, 子ロン, 子ツモ(子付, 親付))
LIMIT_TABLE = {
    '満貫': (12000, 4000, 8000, (2000, 4000)),
    '跳満': (18000, 6000, 12000, (3000, 6000)),
    '倍満': (24000, 8000, 16000, (4000, 8000)),
    '三倍満': (36000, 12000, 24000, (6000, 12000)),
    '役満': (48000, 16000, 32000, (8000, 16000)),
}

# 親（庄家）ロン点数表：key 是 (番, 符)
OYA_RON_TABLE = {
    (1, 30): 1500, (1, 40): 2000, (1, 50): 2400, (1, 60): 2900,
    (1, 70): 3400, (1, 80): 3900, (1, 90): 4400, (1, 100): 4800, (1, 110): 5300,
    (2, 25): 2400, (2, 30): 2900, (2, 40): 3900, (2, 50): 4800, (2, 60): 5800,
    (2, 70): 6800, (2, 80): 7700, (2, 90): 8700, (2, 100): 9600, (2, 110): 10600,
    (3, 25): 4800, (3, 30): 5800, (3, 40): 7700, (3, 50): 9600, (3, 60): 11600,
    (4, 25): 9600, (4, 30): 11600,
}

# 親（庄家）ツモ点数表（三家子各付多少，即オール）
OYA_TSUMO_TABLE = {
    (1, 30): 500, (1, 40): 700, (1, 50): 800, (1, 60): 1000,
    (1, 70): 1200, (1, 80): 1300, (1, 90): 1500, (1, 100): 1600, (1, 110): 1800,
    (2, 20): 700, (2, 25): 800, (2, 30): 1000, (2, 40): 1300, (2, 50): 1600, (2, 60): 2000,
    (2, 70): 2300, (2, 80): 2600, (2, 90): 2900, (2, 100): 3200, (2, 110): 3600,
    (3, 20): 1300, (3, 25): 1600, (3, 30): 2000, (3, 40): 2600, (3, 50): 3200, (3, 60): 3900,
    (4, 20): 2600, (4, 25): 3200, (4, 30): 3900,
}

# 子（闲家）ロン点数表
KO_RON_TABLE = {
    (1, 30): 1000, (1, 40): 1300, (1, 50): 1600, (1, 60): 2000,
    (1, 70): 2300, (1, 80): 2600, (1, 90): 2900, (1, 100): 3200, (1, 110): 3600,
    (2, 25): 1600, (2, 30): 2000, (2, 40): 2600, (2, 50): 3200, (2, 60): 3900,
    (2, 70): 4500, (2, 80): 5200, (2, 90): 5800, (2, 100): 6400, (2, 110): 7100,
    (3, 25): 3200, (3, 30): 3900, (3, 40): 5200, (3, 50): 6400, (3, 60): 7700,
    (4, 25): 6400, (4, 30): 7700,
}

# 子（闲家）ツモ点数表：(子家付, 親家付)
KO_TSUMO_TABLE = {
    (1, 30): (300, 500), (1, 40): (400, 700), (1, 50): (400, 800), (1, 60): (500, 1000),
    (1, 70): (600, 1200), (1, 80): (700, 1300), (1, 90): (800, 1500), (1, 100): (800, 1600), (1, 110): (900, 1800),
    (2, 20): (400, 700), (2, 25): (400, 800), (2, 30): (500, 1000), (2, 40): (700, 1300), (2, 50): (800, 1600), (2, 60): (1000, 2000),
    (2, 70): (1200, 2300), (2, 80): (1300, 2600), (2, 90): (1500, 2900), (2, 100): (1600, 3200), (2, 110): (1800, 3600),
    (3, 20): (700, 1300), (3, 25): (800, 1600), (3, 30): (1000, 2000), (3, 40): (1300, 2600), (3, 50): (1600, 3200), (3, 60): (2000, 3900),
    (4, 20): (1300, 2600), (4, 25): (1600, 3200), (4, 30): (2000, 3900),
}


def _round_up_100(score):
    """100 点未満切り上げ。"""
    return int(math.ceil(score / 100.0)) * 100


def _get_limit_rank(fu, han, kiriage_mangan=False, yakuman=0):
    if yakuman > 0:
        return '役満'
    if han >= 13:
        return '役満'
    if han >= 11:
        return '三倍満'
    if han >= 8:
        return '倍満'
    if han >= 6:
        return '跳満'
    if han >= 5:
        return '満貫'
    # 基本点达到 2000 即封顶满贯（包括 4 番 40+ 符、3 番 70+ 符、2 番 130+ 符等）
    base = fu * (2 ** (han + 2))
    if base >= 2000:
        return '満貫'
    # 切上满贯：4 番 30 符、3 番 60 符（基本点 1920）按满贯算
    if kiriage_mangan and ((han == 4 and fu == 30) or (han == 3 and fu == 60)):
        return '満貫'
    return ''


def calc_score(fu, han, is_oya, is_tsumo, honba=0, kyotaku=0,
               kiriage_mangan=False, yakuman=0):
    """
    计算和牌点数（含本场和供托）。
    kyotaku 按立直棒根数算（每根 1000 点），honba 按本场数算（每本场 300 点）。
    kiriage_mangan：是否启用切上满贯（3 番 60 符 / 4 番 30 符算满贯）。
    yakuman：真役满倍数（0 表示非役满牌型；累计役满传 0、han>=13 仍按 1 倍役满算；
             双倍/复合役满传 2、3 等）。

    返回 dict：
    - get: 和牌者总共获得的点数（含本场、供托）
    - base_points: 这手牌本身的点值（不含本场、供托）
    - ron_pay: 荣和时放铳者付的点数（含本场，自摸时为 0）
    - oya_pay: 子家自摸时親付的点数（含本场，否则为 0）
    - ko_pay: 自摸时每个子家付的点数（含本场，荣和时为 0）
    - rank: 満貫/跳満/倍満/三倍満/役満/N倍役満，普通牌型为空字符串
    """
    if han <= 0 and yakuman <= 0:
        return {
            'get': 0, 'base_points': 0,
            'ron_pay': 0, 'oya_pay': 0, 'ko_pay': 0, 'rank': '',
        }

    # 符数切り上げ（七対子 25 符不进位；役满时 fu 可为 0）
    if yakuman <= 0 and fu != 25 and fu > 0:
        fu = int(math.ceil(fu / 10.0)) * 10

    rank = _get_limit_rank(fu, han, kiriage_mangan=kiriage_mangan, yakuman=yakuman)
    kyotaku_pts = kyotaku * 1000

    if rank:
        mult = yakuman if yakuman > 0 else 1
        oya_ron, oya_tsumo, ko_ron, (ko_tsumo_ko, ko_tsumo_oya) = LIMIT_TABLE[rank]
        oya_ron *= mult
        oya_tsumo *= mult
        ko_ron *= mult
        ko_tsumo_ko *= mult
        ko_tsumo_oya *= mult
        display_rank = f'{mult}倍役満' if (rank == '役満' and mult > 1) else rank

        if is_tsumo:
            if is_oya:
                ko_pay = oya_tsumo + honba * 100
                return {
                    'get': ko_pay * 3 + kyotaku_pts,
                    'base_points': oya_tsumo * 3,
                    'ron_pay': 0,
                    'oya_pay': 0,
                    'ko_pay': ko_pay,
                    'rank': display_rank,
                }
            else:
                ko_pay = ko_tsumo_ko + honba * 100
                oya_pay = ko_tsumo_oya + honba * 100
                return {
                    'get': oya_pay + ko_pay * 2 + kyotaku_pts,
                    'base_points': ko_tsumo_oya + ko_tsumo_ko * 2,
                    'ron_pay': 0,
                    'oya_pay': oya_pay,
                    'ko_pay': ko_pay,
                    'rank': display_rank,
                }
        else:
            base_ron = oya_ron if is_oya else ko_ron
            ron_pay = base_ron + honba * 300
            return {
                'get': ron_pay + kyotaku_pts,
                'base_points': base_ron,
                'ron_pay': ron_pay,
                'oya_pay': 0,
                'ko_pay': 0,
                'rank': display_rank,
            }

    # 満貫以下查表，表里没有的高符用基本点公式兜底
    key = (han, fu)
    base = fu * (2 ** (han + 2))

    if is_tsumo:
        if is_oya:
            pay_each = OYA_TSUMO_TABLE.get(key, _round_up_100(base * 2))
            ko_pay = pay_each + honba * 100
            return {
                'get': ko_pay * 3 + kyotaku_pts,
                'base_points': pay_each * 3,
                'ron_pay': 0,
                'oya_pay': 0,
                'ko_pay': ko_pay,
                'rank': '',
            }
        else:
            if key in KO_TSUMO_TABLE:
                ko_base, oya_base = KO_TSUMO_TABLE[key]
            else:
                ko_base = _round_up_100(base)
                oya_base = _round_up_100(base * 2)
            ko_pay = ko_base + honba * 100
            oya_pay = oya_base + honba * 100
            return {
                'get': oya_pay + ko_pay * 2 + kyotaku_pts,
                'base_points': oya_base + ko_base * 2,
                'ron_pay': 0,
                'oya_pay': oya_pay,
                'ko_pay': ko_pay,
                'rank': '',
            }
    else:
        if is_oya:
            base_ron = OYA_RON_TABLE.get(key, _round_up_100(base * 6))
        else:
            base_ron = KO_RON_TABLE.get(key, _round_up_100(base * 4))
        ron_pay = base_ron + honba * 300
        return {
            'get': ron_pay + kyotaku_pts,
            'base_points': base_ron,
            'ron_pay': ron_pay,
            'oya_pay': 0,
            'ko_pay': 0,
            'rank': '',
        }
