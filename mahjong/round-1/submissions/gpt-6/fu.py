# 学号：260331
# 负责：算符（fu.py）
#
# 说明（写给老师和拼代码的 250226）：
#   主函数是 calc_fu(hand, melds, win_tile, is_tsumo, bakaze, jikaze)，返回一个整数（符数）。
#   按群里老师说的，hand 是“和了的时候 14 张”，也就是 hand 里面已经包括和的那张牌（win_tile）。
#   但是 250118 那边说他的 hand 是 13 张，所以我这里也兼容一下：
#   如果发现 hand 里的张数少了一张（还没把和牌放进去），我就自己把 win_tile 加进去。
#   有副露的时候 hand 只放手里剩下的牌，副露的牌不要重复放进 hand。
#
#   副露 melds 是 list 套 list，比如 [['7z','7z','7z'], ['1m','2m','3m']]。
#   老师说暗杠也放进 melds（四张），但是 melds 里看不出来哪个杠是暗杠，
#   所以我在最后多加了一个参数 an_gang（暗杠的列表，写法和 melds 一样），不改前面参数的顺序。
#   不传 an_gang 的话，melds 里的四张都当明杠算。
#   （250207 你那边如果知道是暗杠，麻烦传一下，暗杠符数差很多，而且暗杠不算破门清。）
#
#   红五 0m/0p/0s：算符跟红不红没关系，一进来我就全部换成 5m/5p/5s。
#
# 算符的规则是照《麻将竞技入门》这本书上的表写的：
#   1. 底符 20 符（书上叫“副底”）。
#   2. 门前清荣和 +10 符（门前加符）。
#   3. 自摸 +2 符（但是平和自摸不加，平和自摸就是 20 符）。
#   4. 面子的符（见下面 MIAN_ZI_FU 表）：
#        明刻 中张 2 / 幺九 4
#        暗刻 中张 4 / 幺九 8
#        明杠 中张 8 / 幺九 16
#        暗杠 中张 16 / 幺九 32
#      顺子 0 符。
#      注意：荣和的时候，如果和的那张牌是用来凑成刻子的（双碰），那个刻子算明刻。
#   5. 雀头的符：三元牌 2 符，场风 2 符，自风 2 符，
#      场风和自风是同一张的时候（连风牌，比如东场的东家拿东做雀头）书上写的是 4 符。
#      （雀魂好像也是 4 符，有的规则是 2 符，我按书上的来。）
#   6. 听牌形的符（ting_pai_xing）：嵌张 2 符，边张 2 符，单骑 2 符，两面和双碰 0 符。
#   7. 加完以后个位数往上进到 10（比如 32 符算 40 符）。
#   8. 特殊情况：
#        平和自摸 20 符，平和荣和 30 符。
#        七对子固定 25 符（不进位）。
#        副露了、但是算出来只有 20 符的（就是没有任何加符），书上说按 30 符算。
#
# 整局结算使用与算役相同的拆法，按实际和牌点数选择。
# 单独调用 calc_fu 时仍返回有效拆法中的最高符数。

from yaku import DRAGONS, ORPHANS, hand_shapes, normal_tile, parse_hand, yaku_pinfu


# ---------------- 一些全局的表 ----------------

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


# ---------------- 小工具函数 ----------------

def que_tou_fu(pai, bakaze, jikaze, renpu_fu=4):
    """雀头的符。连风牌雀头按本桌设置算 2 或 4 符。"""
    if pai == bakaze == jikaze:
        return renpu_fu
    return 2 if pai in DRAGONS or pai in (bakaze, jikaze) else 0


def mian_zi_fu(zhong_lei, pai):
    """面子的符，zhong_lei 是 MIAN_ZI_FU 里的 key"""
    zhong_zhang_fu, yao_jiu_fu = MIAN_ZI_FU[zhong_lei]
    if pai in ORPHANS:
        return yao_jiu_fu
    return zhong_zhang_fu


def jin_wei(fu):
    """个位往上进到 10"""
    if fu % 10 == 0:
        return fu
    return (fu // 10 + 1) * 10


# ---------------- 听牌形 ----------------

def pan_ting_pai_xing(mian_zi, win_tile):
    """
    和的那张牌在这个顺子里，判断是两面、嵌张还是边张。
    mian_zi 的第二项是顺子最小的那张。
    """
    qi_dian = int(mian_zi[1][0])   # 顺子最小的数字
    he_pai_shu = int(win_tile[0])
    if he_pai_shu == qi_dian + 1:
        return 'qian_zhang'        # 和的是中间那张，嵌张
    if he_pai_shu == qi_dian:
        # 和的是最左边：比如 23 听 1 就是 123，如果顺子是 789 和 7，那是 89 听 7，边张
        if qi_dian == 7:
            return 'bian_zhang'
        return 'liang_mian'
    # 和的是最右边：比如 12 听 3，是边张；45 听 6 是两面
    if qi_dian == 1:
        return 'bian_zhang'
    return 'liang_mian'


# ---------------- 主函数 ----------------

def calc_fu_for_shape(shape, win_tile, is_tsumo, bakaze, jikaze, renpu_fu=4):
    if shape.kind == 'seven_pairs':
        return 25
    if shape.kind == 'thirteen_orphans':
        return 30

    win_tile = normal_tile(win_tile)
    closed = not any(is_open for _, _, is_open in shape.groups)
    sequences = [tile for kind, tile, _ in shape.groups if kind == 'sequence']
    if yaku_pinfu(closed, shape.pair, sequences, shape.wait, win_tile, bakaze, jikaze):
        return 20 if is_tsumo else 30

    wait_kind = shape.wait[0]
    if wait_kind == 'sequence':
        wait_fu = TING_PAI_FU[pan_ting_pai_xing(shape.wait, win_tile)]
    elif wait_kind == 'pair':
        wait_fu = TING_PAI_FU['dan_qi']
    else:
        wait_fu = TING_PAI_FU['shuang_peng']

    fu = 20 + wait_fu + que_tou_fu(shape.pair, bakaze, jikaze, renpu_fu)
    for kind, tile, is_open in shape.groups:
        if kind == 'kan':
            fu += mian_zi_fu('ming_gang' if is_open else 'an_gang', tile)
        elif kind == 'triplet':
            ron_triplet = not is_tsumo and shape.wait == ('triplet', tile)
            fu += mian_zi_fu('ming_ke' if is_open or ron_triplet else 'an_ke', tile)

    if is_tsumo:
        fu += 2
    elif closed:
        fu += 10
    return max(30, jin_wei(fu))


def calc_fu(hand, melds, win_tile, is_tsumo, bakaze, jikaze, an_gang=None, *, renpu_fu=4):
    """返回整数符数。hand 可含或不含和牌。an_gang 按原约定传暗杠各组。"""
    melds = melds or []
    concealed_kans = {tuple(sorted(map(normal_tile, meld))) for meld in an_gang or []}
    ankan_indices = [
        i for i, meld in enumerate(melds)
        if len(meld) == 4 and tuple(sorted(map(normal_tile, meld))) in concealed_kans
    ]
    parsed = parse_hand([normal_tile(tile) for tile in hand], melds, normal_tile(win_tile), ankan_indices)
    if parsed is None:
        return 0
    _, hand_counts, groups, win_tile = parsed
    return max((calc_fu_for_shape(shape, win_tile, is_tsumo, bakaze, jikaze, renpu_fu)
                for shape in hand_shapes(hand_counts, groups, win_tile)), default=0)


# ---------------- 简单自测 ----------------
if __name__ == '__main__':
    # 1. 平和荣和：123m 456p 789s 23s(和4s)... 这里写 234s 和 4s 两面，雀头 55m
    shou = ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '2s', '3s', '4s', '5m', '5m']
    print('平和荣和 应该30:', calc_fu(shou, [], '4s', False, '1z', '2z'))
    print('平和自摸 应该20:', calc_fu(shou, [], '4s', True, '1z', '2z'))

    # 2. 七对子
    shou = ['1m', '1m', '3m', '3m', '5p', '5p', '7p', '7p', '2s', '2s', '9s', '9s', '7z', '7z']
    print('七对子 应该25:', calc_fu(shou, [], '7z', False, '1z', '2z'))

    # 3. 嵌张荣和：13m 听 2m，暗刻 中 ，雀头 99p
    #    20 + 10(门前) + 2(嵌张) + 8(幺九暗刻) = 40
    shou = ['1m', '2m', '3m', '7z', '7z', '7z', '4p', '5p', '6p', '6s', '7s', '8s', '9p', '9p']
    print('嵌张+中暗刻 应该40:', calc_fu(shou, [], '2m', False, '1z', '2z'))

    # 4. 双碰荣和：55m 99s 和 9s -> 9s 算明刻
    #    20 + 10 + 4(9s 明刻) + 4(连风？不是) ... 雀头 55m 0
    shou = ['1m', '2m', '3m', '4p', '5p', '6p', '6s', '7s', '8s', '9s', '9s', '9s', '5m', '5m']
    print('双碰荣和 应该40(20+10+4→34→40):', calc_fu(shou, [], '9s', False, '1z', '2z'))

    # 5. 副露没符：吃了 123m，其他全顺子，两面荣和 -> 30
    shou = ['4p', '5p', '6p', '6s', '7s', '8s', '2s', '3s', '4s', '5m', '5m']
    print('副露平和型 应该30:', calc_fu(shou, [['1m', '2m', '3m']], '4s', False, '1z', '2z'))

    # 6. 连风雀头：东场东家 11z 单骑，暗刻 2m
    #    20 + 10 + 2(单骑) + 4(连风) + 4(中张暗刻) = 40
    shou = ['2m', '2m', '2m', '4p', '5p', '6p', '6s', '7s', '8s', '2s', '3s', '4s', '1z', '1z']
    print('连风单骑 应该40:', calc_fu(shou, [], '1z', False, '1z', '1z'))

    # 7. 红五和 13 张写法
    shou = ['1m', '2m', '3m', '4p', '0p', '6p', '7s', '8s', '9s', '2s', '3s', '5m', '5m']
    print('13张+红五 平和 应该30:', calc_fu(shou, [], '4s', False, '1z', '2z'))

    # 8. 暗杠 1z（传 an_gang）+ 自摸
    #    20 + 32 + 2 = 54 -> 60
    shou = ['2m', '3m', '4m', '4p', '5p', '6p', '6s', '7s', '8s', '5m', '5m']
    gang = [['1z', '1z', '1z', '1z']]
    print('东暗杠自摸 应该60:', calc_fu(shou, gang, '4m', True, '2z', '3z', gang))
    print('东明杠自摸 应该40:', calc_fu(shou, gang, '4m', True, '2z', '3z'))
