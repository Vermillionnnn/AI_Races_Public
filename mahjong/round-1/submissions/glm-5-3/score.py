# 学号：260409
# 日本麻将点数计算（参考网上算点博客的点数表改写，规则按 M 联赛来）

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
    (3, 25): 4800, (3, 30): 5800, (3, 40): 7700, (3, 50): 9600,
    (4, 25): 9600,
}

# 親（庄家）ツモ点数表（三家子各付多少，即オール）
OYA_TSUMO_TABLE = {
    (1, 30): 500, (1, 40): 700, (1, 50): 800, (1, 60): 1000,
    (1, 70): 1200, (1, 80): 1300, (1, 90): 1500, (1, 100): 1600, (1, 110): 1800,
    (2, 20): 700, (2, 25): 800, (2, 30): 1000, (2, 40): 1300, (2, 50): 1600, (2, 60): 2000,
    (2, 70): 2300, (2, 80): 2600, (2, 90): 2900, (2, 100): 3200, (2, 110): 3600,
    (3, 20): 1300, (3, 25): 1600, (3, 30): 2000, (3, 40): 2600, (3, 50): 3200,
    (4, 20): 2600, (4, 25): 3200,
}

# 子（闲家）ロン点数表
KO_RON_TABLE = {
    (1, 30): 1000, (1, 40): 1300, (1, 50): 1600, (1, 60): 2000,
    (1, 70): 2300, (1, 80): 2600, (1, 90): 2900, (1, 100): 3200, (1, 110): 3600,
    (2, 25): 1600, (2, 30): 2000, (2, 40): 2600, (2, 50): 3200, (2, 60): 3900,
    (2, 70): 4500, (2, 80): 5200, (2, 90): 5800, (2, 100): 6400, (2, 110): 7100,
    (3, 25): 3200, (3, 30): 3900, (3, 40): 5200, (3, 50): 6400,
    (4, 25): 6400,
}

# 子（闲家）ツモ点数表：(子家付, 親家付)
KO_TSUMO_TABLE = {
    (1, 30): (300, 500), (1, 40): (400, 700), (1, 50): (400, 800), (1, 60): (500, 1000),
    (1, 70): (600, 1200), (1, 80): (700, 1300), (1, 90): (800, 1500), (1, 100): (800, 1600), (1, 110): (900, 1800),
    (2, 20): (400, 700), (2, 25): (400, 800), (2, 30): (500, 1000), (2, 40): (700, 1300), (2, 50): (800, 1600), (2, 60): (1000, 2000),
    (2, 70): (1200, 2300), (2, 80): (1300, 2600), (2, 90): (1500, 2900), (2, 100): (1600, 3200), (2, 110): (1800, 3600),
    (3, 20): (700, 1300), (3, 25): (800, 1600), (3, 30): (1000, 2000), (3, 40): (1300, 2600), (3, 50): (1600, 3200),
    (4, 20): (1300, 2600), (4, 25): (1600, 3200),
}


def _round_up_100(score):
    # 100点未満切り上げ
    return int(math.ceil(score / 100.0)) * 100


def _get_limit_rank(fu, han, kiriage_mangan=False):
    # 250118 说役满返回 13 番，所以 >=13 按役満算（M 联赛本来没有数え役満，先这样兼容）
    if han >= 13:
        return '役満'
    if han >= 11:
        return '三倍満'
    if han >= 8:
        return '倍満'
    if han >= 6:
        return '跳満'
    # 切り上げ満貫：4番30符、3番60符都算満貫（规则开关，默认关）
    if han >= 5 or (kiriage_mangan and ((han == 4 and fu >= 30) or (han == 3 and fu >= 60))):
        return '満貫'
    return ''


def calc_score(fu, han, is_oya, is_tsumo, honba=0, kyotaku=0, rules=None):
    """
    计算和牌点数（含本场和供托）
    kyotaku 按立直棒根数算（每根 1000 点），honba 按本场数算（每本场 300 点）
    rules：（拼装加的）规则开关，{'kiriage_mangan': true/false}，不传默认关

    返回 dict：
    - get: 和牌者总共获得的点数（含本场、供托）
    - ron_pay: 荣和时放铳者付的点数（自摸时为 0）
    - oya_pay: 子家自摸时親付的点数（否则为 0）
    - ko_pay: 自摸时每个子家付的点数（荣和时为 0）
    - rank: 満貫/跳満/倍満/三倍満/役満，普通牌型为空字符串
    """
    if han <= 0:
        return {'get': 0, 'ron_pay': 0, 'oya_pay': 0, 'ko_pay': 0, 'rank': ''}

    # 符数切り上げ（七対子 25 符不进位）
    if fu != 25:
        fu = int(math.ceil(fu / 10.0)) * 10

    rank = _get_limit_rank(fu, han, (rules or {}).get('kiriage_mangan', False))
    kyotaku_pts = kyotaku * 1000

    if rank:
        oya_ron, oya_tsumo, ko_ron, (ko_tsumo_ko, ko_tsumo_oya) = LIMIT_TABLE[rank]
        if is_tsumo:
            if is_oya:
                ko_pay = oya_tsumo + honba * 100
                return {
                    'get': ko_pay * 3 + kyotaku_pts,
                    'ron_pay': 0,
                    'oya_pay': 0,
                    'ko_pay': ko_pay,
                    'rank': rank,
                }
            else:
                ko_pay = ko_tsumo_ko + honba * 100
                oya_pay = ko_tsumo_oya + honba * 100
                return {
                    'get': oya_pay + ko_pay * 2 + kyotaku_pts,
                    'ron_pay': 0,
                    'oya_pay': oya_pay,
                    'ko_pay': ko_pay,
                    'rank': rank,
                }
        else:
            base_ron = oya_ron if is_oya else ko_ron
            ron_pay = base_ron + honba * 300
            return {
                'get': ron_pay + kyotaku_pts,
                'ron_pay': ron_pay,
                'oya_pay': 0,
                'ko_pay': 0,
                'rank': rank,
            }

    # 満貫以下查表，表里没有的冷门高符用基本点公式兜底
    key = (han, fu)
    base = fu * (2 ** (han + 2))

    if is_tsumo:
        if is_oya:
            pay_each = OYA_TSUMO_TABLE.get(key, _round_up_100(base * 2))
            ko_pay = pay_each + honba * 100
            return {
                'get': ko_pay * 3 + kyotaku_pts,
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
            'ron_pay': ron_pay,
            'oya_pay': 0,
            'ko_pay': 0,
            'rank': '',
        }

# TODO: 以后如果要加双倍役满或者包牌（パオ），再补充


if __name__ == '__main__':
    print('子 30符 2番 ロン:', calc_score(30, 2, False, False, 0, 0))
    print('子 30符 4番 ロン（默认没有切上满贯）:', calc_score(30, 4, False, False, 1, 1))
    print('子 30符 4番 ロン（切上满贯开）:', calc_score(30, 4, False, False, 0, 0, rules={'kiriage_mangan': True}))
    print('親 40符 3番 ツモ:', calc_score(40, 3, True, True, 2, 0))
    print('子 25符 3番 ツモ:', calc_score(25, 3, False, True, 0, 1))
    print('親 跳満 ロン:', calc_score(30, 6, True, False, 0, 0))
    print('子 役満 ツモ:', calc_score(40, 13, False, True, 0, 0))