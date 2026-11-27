# 学号：260409
# 日本麻将点数计算

MANGAN_BASE = 2000
LIMIT_BASE = {
    '満貫': MANGAN_BASE,
    '跳満': 3000,
    '倍満': 4000,
    '三倍満': 6000,
    '役満': 8000,
}


def _round_up_100(points):
    return (points + 99) // 100 * 100


def _get_limit_rank(fu, han, kiriage_mangan=False):
    if han >= 13:
        return '役満'
    if han >= 11:
        return '三倍満'
    if han >= 8:
        return '倍満'
    if han >= 6:
        return '跳満'
    base = fu * (2 ** (han + 2))
    if han == 5 or base >= MANGAN_BASE or (kiriage_mangan and (fu, han) in ((30, 4), (60, 3))):
        return '満貫'
    return ''


def calc_score(fu, han, is_oya, is_tsumo, honba=0, kyotaku=0, *,
               kiriage_mangan=False, yakuman=0):
    """返回和家总收入、放铳或自摸各家支出及点数档位。

    本场每本 300 点，供托每根 1000 点。yakuman 单独传牌型役满倍数，
    普通役累计 13 番或以上统一按一倍役满点数。
    """
    gain = ron_pay = oya_pay = ko_pay = 0
    rank = ''
    if yakuman or han > 0:
        if fu != 25:
            fu = (fu + 9) // 10 * 10
        rank = '役満' if yakuman else _get_limit_rank(fu, han, kiriage_mangan)
        if rank:
            base = LIMIT_BASE[rank] * (yakuman or 1)
        else:
            base = fu * (2 ** (han + 2))

        if is_tsumo:
            ko_pay = _round_up_100(base * (2 if is_oya else 1)) + honba * 100
            if is_oya:
                gain = ko_pay * 3
            else:
                oya_pay = _round_up_100(base * 2) + honba * 100
                gain = oya_pay + ko_pay * 2
        else:
            ron_pay = _round_up_100(base * (6 if is_oya else 4)) + honba * 300
            gain = ron_pay
        gain += kyotaku * 1000

    return {'get': gain, 'ron_pay': ron_pay, 'oya_pay': oya_pay, 'ko_pay': ko_pay, 'rank': rank}


if __name__ == '__main__':
    print('子 30 符 2 番荣和:', calc_score(30, 2, False, False))
    print('子 30 符 4 番荣和（切上满贯）:',
          calc_score(30, 4, False, False, 1, 1, kiriage_mangan=True))
    print('亲 40 符 3 番自摸:', calc_score(40, 3, True, True, 2))
    print('子 25 符 3 番自摸:', calc_score(25, 3, False, True, kyotaku=1))
    print('子双倍役满自摸:', calc_score(0, 26, False, True, yakuman=2))
