# 学号：260331（已整理修复）
# 负责：算符（fu.py）

YAO_JIU = {
    '1m', '9m', '1p', '9p', '1s', '9s',
    '1z', '2z', '3z', '4z', '5z', '6z', '7z',
}

SAN_YUAN = {'5z', '6z', '7z'}

VALID_TILES = {
    f'{n}{s}' for s in 'mps' for n in range(1, 10)
} | {f'{n}z' for n in range(1, 8)}

# 面子符表：MIAN_ZI_FU[面子种类] = (中张的符, 幺九的符)
MIAN_ZI_FU = {
    'ming_ke': (2, 4),      # 明刻
    'an_ke': (4, 8),        # 暗刻
    'ming_gang': (8, 16),   # 明杠
    'an_gang': (16, 32),    # 暗杠
    'shun_zi': (0, 0),      # 顺子
}

# 听牌形符表
TING_PAI_FU = {
    'liang_mian': 0,   # 两面
    'shuang_peng': 0,  # 双碰
    'qian_zhang': 2,   # 嵌张
    'bian_zhang': 2,   # 边张
    'dan_qi': 2,       # 单骑
}


def gui_yi_hua(pai):
    """把红五 0m/0p/0s 变成普通的 5m/5p/5s。其他牌原样返回。"""
    if pai and len(pai) == 2 and pai[0] == '0' and pai[1] in 'mps':
        return '5' + pai[1]
    return pai


def shi_yao_jiu(pai):
    """是不是幺九牌。"""
    return pai in YAO_JIU


def pai_jian(pai):
    """排序用的 key：先按花色 m p s z，再按数字。"""
    hua_se_shun_xu = {'m': 0, 'p': 1, 's': 2, 'z': 3}
    return (hua_se_shun_xu[pai[1]], int(pai[0]))


def que_tou_fu(pai, bakaze, jikaze, renpu_fu=4):
    """雀头的符。连风牌雀头按规则开关 renpu_fu（2 或 4）计算。"""
    fu = 0
    if pai in SAN_YUAN:
        fu += 2
    if pai == bakaze and pai == jikaze:
        fu += renpu_fu
    else:
        if pai == bakaze:
            fu += 2
        if pai == jikaze:
            fu += 2
    return fu


def mian_zi_fu(zhong_lei, pai):
    """面子的符，zhong_lei 是 MIAN_ZI_FU 里的 key。"""
    zhong_zhang_fu, yao_jiu_fu = MIAN_ZI_FU[zhong_lei]
    if shi_yao_jiu(pai):
        return yao_jiu_fu
    return zhong_zhang_fu


def jin_wei(fu):
    """个位往上进到 10。"""
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
    yi_jing_shi_guo = set()
    for pai in pai_list:
        if pai in yi_jing_shi_guo:
            continue
        yi_jing_shi_guo.add(pai)
        if pai_list.count(pai) >= 2:
            sheng_xia = list(pai_list)
            sheng_xia.remove(pai)
            sheng_xia.remove(pai)
            for mian_zi_men in chai_mian_zi(sheng_xia):
                suo_you_chai_fa.append((pai, mian_zi_men))
    return suo_you_chai_fa


def shi_qi_dui_zi(shou_pai):
    """七对子：14 张，正好七种不同的对子（四张一样的不算两对）。"""
    if len(shou_pai) != 14:
        return False
    zhong_lei = set(shou_pai)
    if len(zhong_lei) != 7:
        return False
    return all(shou_pai.count(pai) == 2 for pai in zhong_lei)


def shi_guo_shi(shou_pai):
    """国士无双：13 种幺九各一张，再多一张幺九。"""
    if len(shou_pai) != 14:
        return False
    for pai in shou_pai:
        if not shi_yao_jiu(pai):
            return False
    return len(set(shou_pai)) == 13


def pan_ting_pai_xing(mian_zi, win_tile):
    """和的那张牌在这个顺子里，判断是两面、嵌张还是边张。
    mian_zi 是 ('shun', 最小的那张) 或 ('sequence', 最小的那张)。
    """
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


def calc_fu_for_split(pair, hand_groups, meld_groups, win_tile, wait,
                      is_tsumo, bakaze, jikaze, renpu_fu=4):
    """针对某一种确定的拆法和听牌位置计算符数（供高点法与算番联合使用）。

    pair: 归一化后的雀头牌，如 '5m'
    hand_groups: 手牌面子列表，每项为 (kind, rep_tile, False)，kind 为 'triplet' 或 'sequence'
    meld_groups: 副露面子列表，每项为 (kind, rep_tile, is_open)，kind 为 'kan'/'triplet'/'sequence'
    win_tile: 归一化后的和牌
    wait: ('pair', None) / ('triplet', tile) / ('sequence', start_tile)
    """
    men_qing = not any(is_open for _, _, is_open in meld_groups)

    fu_lu_fu = 0
    for kind, tile, is_open in meld_groups:
        if kind == 'kan':
            fu_lu_fu += mian_zi_fu('ming_gang' if is_open else 'an_gang', tile)
        elif kind == 'triplet':
            fu_lu_fu += mian_zi_fu('ming_ke', tile)

    wait_type, wait_tile = wait
    if wait_type == 'pair':
        ting_pai_xing = 'dan_qi'
    elif wait_type == 'triplet':
        ting_pai_xing = 'shuang_peng'
    else:
        ting_pai_xing = pan_ting_pai_xing(('shun', wait_tile), win_tile)

    hand_fu = 0
    ron_triplet_applied = False
    all_hand_seq = True
    for kind, tile, _ in hand_groups:
        if kind == 'triplet':
            all_hand_seq = False
            if (not is_tsumo and not ron_triplet_applied
                    and wait_type == 'triplet' and tile == wait_tile):
                hand_fu += mian_zi_fu('ming_ke', tile)
                ron_triplet_applied = True
            else:
                hand_fu += mian_zi_fu('an_ke', tile)

    qt_fu = que_tou_fu(pair, bakaze, jikaze, renpu_fu=renpu_fu)

    # 平和：没有任何副露（含暗杠）、全顺子、雀头非役牌、两面听
    shi_ping_he = (
        len(meld_groups) == 0
        and all_hand_seq
        and qt_fu == 0
        and ting_pai_xing == 'liang_mian'
    )

    if shi_ping_he:
        return 20 if is_tsumo else 30

    fu_shu = 20 + fu_lu_fu + hand_fu + qt_fu + TING_PAI_FU[ting_pai_xing]
    if is_tsumo:
        fu_shu += 2
    elif men_qing:
        fu_shu += 10
    fu_shu = jin_wei(fu_shu)
    # 副露后无任何加符（20 符）按 30 符算（喰い平和形）
    if not men_qing and fu_shu == 20:
        fu_shu = 30
    return fu_shu


def calc_fu(hand, melds, win_tile, is_tsumo, bakaze, jikaze,
            an_gang=None, ankan_indices=None, renpu_fu=4):
    """
    返回符数（整数）。
    hand：手里的牌（含或不含和的那张均可）
    melds：副露（暗杠也放这里）
    win_tile：和的那张牌
    is_tsumo：是不是自摸
    bakaze / jikaze：场风、自风，比如 '1z'
    an_gang：暗杠的牌组列表（兼容旧参数）
    ankan_indices：暗杠在 melds 中的下标集合/列表（与 yaku.py 统一）
    renpu_fu：连风牌雀头的符数（2 或 4，默认 4）
    拆不成和牌形的话返回 0。
    """
    if melds is None:
        melds = []
    if an_gang is None:
        an_gang = []

    shou_pai = [gui_yi_hua(p) for p in hand]
    win_tile = gui_yi_hua(win_tile)
    fu_lu = [[gui_yi_hua(p) for p in m] for m in melds]
    an_gang_sorted = [sorted(gui_yi_hua(p) for p in m) for m in an_gang]
    ankan_idx_set = set(ankan_indices) if ankan_indices is not None else set()
    bakaze = gui_yi_hua(bakaze)
    jikaze = gui_yi_hua(jikaze)

    if len(fu_lu) > 4:
        return 0
    if win_tile not in VALID_TILES:
        return 0
    if any(p not in VALID_TILES for p in shou_pai):
        return 0
    if any(p not in VALID_TILES for m in fu_lu for p in m):
        return 0

    ying_gai_zhang_shu = 14 - 3 * len(fu_lu)
    if len(shou_pai) == ying_gai_zhang_shu - 1:
        shou_pai.append(win_tile)
    elif len(shou_pai) != ying_gai_zhang_shu:
        return 0

    if win_tile not in shou_pai:
        return 0

    # 特殊形：国士无双
    if len(fu_lu) == 0 and shi_guo_shi(shou_pai):
        return 30

    # 解析副露
    meld_groups = []
    for i, m in enumerate(fu_lu):
        ms = sorted(m, key=pai_jian)
        if len(ms) == 4 and ms[0] == ms[-1]:
            is_ankan = (i in ankan_idx_set) or (sorted(ms) in an_gang_sorted)
            meld_groups.append(('kan', ms[0], not is_ankan))
        elif len(ms) == 3 and ms[0] == ms[-1]:
            meld_groups.append(('triplet', ms[0], True))
        elif len(ms) == 3 and ms[0][1] != 'z' and ms[0][1] == ms[1][1] == ms[2][1]:
            n0 = int(ms[0][0])
            if int(ms[1][0]) == n0 + 1 and int(ms[2][0]) == n0 + 2:
                meld_groups.append(('sequence', ms[0], True))
            else:
                return 0
        else:
            return 0

    # 一般形：枚举所有拆法和和牌位置，取最大符
    zui_da_fu = 0
    you_yi_ban_xing = False

    for que_tou, mian_zi_men in chai_pai(shou_pai):
        hand_groups = [
            ('triplet' if lei == 'ke' else 'sequence', pai, False)
            for lei, pai in mian_zi_men
        ]
        waits = []
        if que_tou == win_tile:
            waits.append(('pair', None))
        for kind, pai, _ in hand_groups:
            if kind == 'triplet' and pai == win_tile:
                waits.append(('triplet', pai))
            elif kind == 'sequence' and pai[1] == win_tile[1]:
                qi_dian = int(pai[0])
                if qi_dian <= int(win_tile[0]) <= qi_dian + 2:
                    waits.append(('sequence', pai))

        for wait in waits:
            you_yi_ban_xing = True
            fu_shu = calc_fu_for_split(
                que_tou, hand_groups, meld_groups, win_tile, wait,
                is_tsumo, bakaze, jikaze, renpu_fu=renpu_fu,
            )
            if fu_shu > zui_da_fu:
                zui_da_fu = fu_shu

    if you_yi_ban_xing:
        return zui_da_fu

    if len(fu_lu) == 0 and shi_qi_dui_zi(shou_pai):
        return 25

    return 0
