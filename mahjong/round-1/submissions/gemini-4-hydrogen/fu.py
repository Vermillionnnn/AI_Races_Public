# 学号：260331
# 负责：算符（fu.py）

YAO_JIU = ['1m', '9m', '1p', '9p', '1s', '9s',
           '1z', '2z', '3z', '4z', '5z', '6z', '7z']

SAN_YUAN = ['5z', '6z', '7z']

MIAN_ZI_FU = {
    'ming_ke': (2, 4),      # 明刻
    'an_ke': (4, 8),        # 暗刻
    'ming_gang': (8, 16),   # 明杠
    'an_gang': (16, 32),    # 暗杠
    'shun_zi': (0, 0),      # 顺子
}

TING_PAI_FU = {
    'liang_mian': 0,   # 两面
    'shuang_peng': 0,  # 双碰
    'qian_zhang': 2,   # 嵌张
    'bian_zhang': 2,   # 边张
    'dan_qi': 2,       # 单骑
}


def gui_yi_hua(pai):
    """把红五 0m/0p/0s 变成普通的 5m/5p/5s。其他牌原样返回。"""
    if pai[0] == '0':
        return '5' + pai[1]
    return pai


def shi_yao_jiu(pai):
    """是不是幺九牌"""
    return pai in YAO_JIU


def pai_jian(pai):
    """排序用的 key：先按花色 m p s z，再按数字。"""
    hua_se_shun_xu = {'m': 0, 'p': 1, 's': 2, 'z': 3}
    return (hua_se_shun_xu[pai[1]], int(pai[0]))


def que_tou_fu(pai, bakaze, jikaze, renpu_fu=4):
    """雀头的符。连风牌雀头按 renpu_fu 算（2 或 4）。"""
    if pai in SAN_YUAN:
        return 2
    if pai == bakaze and pai == jikaze:
        return renpu_fu
    if pai == bakaze or pai == jikaze:
        return 2
    return 0


def mian_zi_fu(zhong_lei, pai):
    """面子的符，zhong_lei 是 MIAN_ZI_FU 里的 key"""
    zhong_zhang_fu, yao_jiu_fu = MIAN_ZI_FU[zhong_lei]
    if shi_yao_jiu(pai):
        return yao_jiu_fu
    return zhong_zhang_fu


def jin_wei(fu):
    """个位往上进到 10"""
    if fu % 10 == 0:
        return fu
    return (fu // 10 + 1) * 10


def chai_mian_zi(pai_list):
    """把（已经排好序的）牌拆成全是面子，返回所有拆法的列表。拆不了返回 []。"""
    if len(pai_list) == 0:
        return [[]]
    jie_guo = []
    di_yi_zhang = pai_list[0]

    # 试刻子
    if pai_list.count(di_yi_zhang) >= 3:
        sheng_xia = list(pai_list)
        for _ in range(3):
            sheng_xia.remove(di_yi_zhang)
        for hou_mian in chai_mian_zi(sheng_xia):
            jie_guo.append([('ke', di_yi_zhang)] + hou_mian)

    # 试顺子（字牌不能组顺子）
    if di_yi_zhang[1] != 'z' and int(di_yi_zhang[0]) <= 7:
        hua_se = di_yi_zhang[1]
        shu = int(di_yi_zhang[0])
        di_er = str(shu + 1) + hua_se
        di_san = str(shu + 2) + hua_se
        if di_er in pai_list and di_san in pai_list:
            sheng_xia = list(pai_list)
            sheng_xia.remove(di_yi_zhang)
            sheng_xia.remove(di_er)
            sheng_xia.remove(di_san)
            for hou_mian in chai_mian_zi(sheng_xia):
                jie_guo.append([('shun', di_yi_zhang)] + hou_mian)

    return jie_guo


def chai_pai(shou_pai):
    """把手里的牌（不含副露）拆成 雀头 + 若干面子。"""
    pai_list = sorted(shou_pai, key=pai_jian)
    suo_you_chai_fa = []
    yi_jing_shi_guo = []
    for pai in pai_list:
        if pai in yi_jing_shi_guo:
            continue
        yi_jing_shi_guo.append(pai)
        if pai_list.count(pai) >= 2:
            sheng_xia = list(pai_list)
            sheng_xia.remove(pai)
            sheng_xia.remove(pai)
            for mian_zi_men in chai_mian_zi(sheng_xia):
                suo_you_chai_fa.append((pai, mian_zi_men))
    return suo_you_chai_fa


def shi_qi_dui_zi(shou_pai):
    """七对子：14 张，正好七种不同的对子（四张一样的不能算两对）"""
    if len(shou_pai) != 14:
        return False
    zhong_lei = set(shou_pai)
    if len(zhong_lei) != 7:
        return False
    for pai in zhong_lei:
        if shou_pai.count(pai) != 2:
            return False
    return True


def shi_guo_shi(shou_pai):
    """国士无双：13 种幺九各一张，再多一张幺九"""
    if len(shou_pai) != 14:
        return False
    for pai in shou_pai:
        if not shi_yao_jiu(pai):
            return False
    return len(set(shou_pai)) == 13


def pan_ting_pai_xing(mian_zi, win_tile):
    """和的那张牌在这个顺子里，判断是两面、嵌张还是边张。mian_zi 是 ('shun', 最小的那张)。"""
    qi_dian = int(mian_zi[1][0])
    he_pai_shu = int(win_tile[0])
    if he_pai_shu == qi_dian + 1:
        return 'qian_zhang'
    if he_pai_shu == qi_dian:
        if qi_dian == 7:
            return 'bian_zhang'
        return 'liang_mian'
    if qi_dian == 1:
        return 'bian_zhang'
    return 'liang_mian'


def _melds_info(melds, an_gang):
    fu_lu = [[gui_yi_hua(p) for p in m] for m in (melds or [])]
    an_gang_sorted = [sorted(gui_yi_hua(p) for p in a) for a in (an_gang or [])]
    men_qing = True
    fu_lu_fu = 0
    used_an_gang = []
    for m in fu_lu:
        sm = sorted(m)
        if len(m) == 4:
            # 按张匹配暗杠列表，避免影响门清与暗杠符数
            matched = False
            for idx, ag in enumerate(an_gang_sorted):
                if idx not in used_an_gang and sm == ag:
                    used_an_gang.append(idx)
                    matched = True
                    break
            if matched:
                fu_lu_fu += mian_zi_fu('an_gang', m[0])
            else:
                men_qing = False
                fu_lu_fu += mian_zi_fu('ming_gang', m[0])
        else:
            men_qing = False
            if len(m) == 3 and m[0] == m[1] == m[2]:
                fu_lu_fu += mian_zi_fu('ming_ke', m[0])
    return fu_lu, men_qing, fu_lu_fu


def calc_fu_decomp(pair, hand_groups, melds, win_tile, is_tsumo, bakaze, jikaze,
                   wait, an_gang=None, renpu_fu=4):
    """
    按给定的一种拆法 (pair, hand_groups, wait) 精确算符，供与算番模块联合执行高点法。
    hand_groups 元素为 ('triplet' | 'sequence', tile, is_open) 或 ('ke' | 'shun', tile)。
    wait 为 ('pair', None) | ('triplet', tile) | ('sequence', start_tile)。
    """
    win_tile = gui_yi_hua(win_tile)
    pair = gui_yi_hua(pair)
    bakaze = gui_yi_hua(bakaze)
    jikaze = gui_yi_hua(jikaze)

    fu_lu, men_qing, fu_lu_fu = _melds_info(melds, an_gang)

    if wait[0] == 'pair':
        ting_pai_xing = 'dan_qi'
    elif wait[0] == 'triplet':
        ting_pai_xing = 'shuang_peng'
    else:
        ting_pai_xing = pan_ting_pai_xing(('shun', gui_yi_hua(wait[1])), win_tile)

    fu_shu = 20 + fu_lu_fu + TING_PAI_FU[ting_pai_xing]

    quan_shun_zi = (fu_lu_fu == 0)
    used_ron_triplet = False
    for g in hand_groups:
        kind = g[0]
        pai = gui_yi_hua(g[1])
        if kind in ('triplet', 'ke'):
            quan_shun_zi = False
            if (not is_tsumo and not used_ron_triplet
                    and wait[0] == 'triplet' and pai == gui_yi_hua(wait[1])):
                fu_shu += mian_zi_fu('ming_ke', pai)
                used_ron_triplet = True
            else:
                fu_shu += mian_zi_fu('an_ke', pai)

    qt_fu = que_tou_fu(pair, bakaze, jikaze, renpu_fu=renpu_fu)
    fu_shu += qt_fu

    shi_ping_he = (len(fu_lu) == 0 and quan_shun_zi and qt_fu == 0
                   and ting_pai_xing == 'liang_mian')

    if shi_ping_he:
        return 20 if is_tsumo else 30

    if is_tsumo:
        fu_shu += 2
    elif men_qing:
        fu_shu += 10
    fu_shu = jin_wei(fu_shu)
    if not men_qing and fu_shu == 20:
        fu_shu = 30
    return fu_shu


def calc_fu(hand, melds, win_tile, is_tsumo, bakaze, jikaze, an_gang=None, renpu_fu=4):
    """
    返回符数（整数）。
    hand：手里的牌（含和的那张，14 - 3×副露组数 张，也兼容 13 - 3×副露组数 张）
    melds：副露，暗杠也放这里
    win_tile：和的那张牌
    is_tsumo：是不是自摸
    bakaze / jikaze：场风、自风，比如 '1z'
    an_gang：melds 里面哪些是暗杠，不传就当都是明杠
    renpu_fu：连风牌雀头的符数（2 或 4，默认 4）
    """
    if melds is None:
        melds = []
    if an_gang is None:
        an_gang = []

    shou_pai = [gui_yi_hua(p) for p in hand]
    win_tile = gui_yi_hua(win_tile)
    fu_lu = [[gui_yi_hua(p) for p in m] for m in melds]
    bakaze = gui_yi_hua(bakaze)
    jikaze = gui_yi_hua(jikaze)

    ying_gai_zhang_shu = 14 - 3 * len(fu_lu)
    if len(shou_pai) == ying_gai_zhang_shu - 1:
        shou_pai.append(win_tile)

    if len(fu_lu) == 0 and shi_guo_shi(shou_pai):
        return 30

    zui_da_fu = 0
    you_yi_ban_xing = False

    for que_tou, mian_zi_men in chai_pai(shou_pai):
        ke_neng_waits = []
        if que_tou == win_tile:
            ke_neng_waits.append(('pair', None))
        for lei_xing, pai in mian_zi_men:
            if lei_xing == 'ke' and pai == win_tile:
                ke_neng_waits.append(('triplet', pai))
            elif lei_xing == 'shun' and pai[1] == win_tile[1]:
                qi_dian = int(pai[0])
                if qi_dian <= int(win_tile[0]) <= qi_dian + 2:
                    ke_neng_waits.append(('sequence', pai))

        for wait in ke_neng_waits:
            you_yi_ban_xing = True
            fu_shu = calc_fu_decomp(
                que_tou, mian_zi_men, fu_lu, win_tile, is_tsumo,
                bakaze, jikaze, wait, an_gang=an_gang, renpu_fu=renpu_fu
            )
            if fu_shu > zui_da_fu:
                zui_da_fu = fu_shu

    if you_yi_ban_xing:
        return zui_da_fu

    if len(fu_lu) == 0 and shi_qi_dui_zi(shou_pai):
        return 25

    return 0


if __name__ == '__main__':
    shou = ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '2s', '3s', '4s', '5m', '5m']
    print('平和荣和 应该30:', calc_fu(shou, [], '4s', False, '1z', '2z'))
    print('平和自摸 应该20:', calc_fu(shou, [], '4s', True, '1z', '2z'))
    shou = ['2m', '2m', '2m', '4p', '5p', '6p', '6s', '7s', '8s', '2s', '3s', '4s', '1z', '1z']
    print('连风单骑(4符) 应该40:', calc_fu(shou, [], '1z', False, '1z', '1z', renpu_fu=4))
    print('连风单骑(2符) 应该40:', calc_fu(shou, [], '1z', False, '1z', '1z', renpu_fu=2))
    shou = ['2m', '3m', '4m', '4p', '5p', '6p', '6s', '7s', '8s', '5m', '5m']
    gang = [['1z', '1z', '1z', '1z']]
    print('东暗杠自摸 应该60:', calc_fu(shou, gang, '4m', True, '2z', '3z', gang))
    print('东明杠自摸 应该40:', calc_fu(shou, gang, '4m', True, '2z', '3z'))
