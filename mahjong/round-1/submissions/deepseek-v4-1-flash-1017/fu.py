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
# 一副牌可能有好几种拆法（比如 111222333m 可以拆成三个刻子也可以拆成三个顺子），
# 和的那张牌也可能算在不同的面子里（比如 2345 听 2 和 5），
# 书上说“取对和牌者最有利的拆法”，我这里就把所有拆法都试一遍，取符数最大的那个。
# （严格来说应该是取“点数”最高的，番数也会跟着拆法变，比如一杯口、平和，
#  但是我这里拿不到番数，只能先取符最大的。TODO：以后跟 250118 商量一下。）


# ---------------- 一些全局的表 ----------------

# 幺九牌（老头牌 + 字牌）
YAO_JIU = ['1m', '9m', '1p', '9p', '1s', '9s',
           '1z', '2z', '3z', '4z', '5z', '6z', '7z']

# 三元牌：白、发、中
SAN_YUAN = ['5z', '6z', '7z']

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
    """雀头的符。连风牌雀头按规则开关算 2 或 4 符。"""
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


# ---------------- 拆牌 ----------------
#
# 思路：把手牌排好序，每次看最小的那张牌，
#   要么它和后面两张一样 -> 拆出一个刻子
#   要么它和下两张数字连起来（同花色、不是字牌）-> 拆出一个顺子
# 递归下去，能拆完就是一种拆法。雀头先在外面枚举。
# 拆出来的结果是一个 list，每个元素是 ('ke', '5m') 或者 ('shun', '3m')，
# 顺子记的是最小的那张。

def chai_mian_zi(pai_list):
    """把（已经排好序的）牌拆成全是面子，返回所有拆法的列表。拆不了返回 []。"""
    if len(pai_list) == 0:
        return [[]]
    jie_guo = []
    di_yi_zhang = pai_list[0]

    # 试刻子
    if pai_list.count(di_yi_zhang) >= 3:
        sheng_xia = list(pai_list)
        for i in range(3):
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
    """
    把手里的牌（不含副露）拆成 雀头 + 若干面子。
    返回 [(que_tou, [面子, ...]), ...]，所有拆法都列出来，可能有重复，不影响。
    """
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
    """七对子：14 张，正好七种不同的对子（四张一样的不算两对）"""
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


# ---------------- 听牌形 ----------------

def pan_ting_pai_xing(mian_zi, win_tile):
    """
    和的那张牌在这个顺子里，判断是两面、嵌张还是边张。
    mian_zi 是 ('shun', 最小的那张)。
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

def calc_fu(hand, melds, win_tile, is_tsumo, bakaze, jikaze, an_gang=None,
            rules=None, yaku_names=None):
    """
    返回符数（整数）。
    hand：手里的牌（含和的那张，14 - 3×副露组数 张）
    melds：副露，暗杠也放这里
    win_tile：和的那张牌
    is_tsumo：是不是自摸
    bakaze / jikaze：场风、自风，比如 '1z'
    an_gang：（我自己加的）melds 里面哪些是暗杠，不传就当都是明杠
    rules：renpu_fu（连风雀头 2/4 符）
    yaku_names：可选，用来让符数和实际选中的役一致（七对子固定 25 符）
    拆不成和牌形的话返回 0。
    """
    if melds is None:
        melds = []
    if an_gang is None:
        an_gang = []
    if rules is None:
        rules = {}
    if yaku_names is None:
        yaku_names = []
    renpu_fu = rules.get('renpu_fu', 4)

    # 统一把红五换掉
    shou_pai = [gui_yi_hua(p) for p in hand]
    win_tile = gui_yi_hua(win_tile)
    fu_lu = [[gui_yi_hua(p) for p in m] for m in melds]
    an_gang_list = [[gui_yi_hua(p) for p in m] for m in an_gang]
    bakaze = gui_yi_hua(bakaze)
    jikaze = gui_yi_hua(jikaze)

    # 手里应该有的张数：14 - 3 × 副露组数（杠也只占 3 张的位置）
    ying_gai_zhang_shu = 14 - 3 * len(fu_lu)
    if len(shou_pai) == ying_gai_zhang_shu - 1:
        # hand 是 13 张那种写法，没把和牌放进去，帮忙加上
        shou_pai.append(win_tile)

    # 门清判断：没有副露，或者副露全是暗杠
    men_qing = True
    for m in fu_lu:
        if len(m) == 4 and sorted(m) in [sorted(a) for a in an_gang_list]:
            continue
        men_qing = False

    # ---- 特殊形 ----
    if len(fu_lu) == 0 and shi_guo_shi(shou_pai):
        # 国士无双是役满，符没什么意义，书上也没写，就给个 30 符
        return 30
    # 七对子和二杯口可能都能拆，按 yaku.py 实际选中的役来定符
    if len(fu_lu) == 0 and '七对子' in yaku_names and shi_qi_dui_zi(shou_pai):
        return 25

    # ---- 先算副露的符（跟拆法无关，算一次就行）----
    fu_lu_fu = 0
    for m in fu_lu:
        if len(m) == 4:
            if sorted(m) in [sorted(a) for a in an_gang_list]:
                fu_lu_fu += mian_zi_fu('an_gang', m[0])
            else:
                fu_lu_fu += mian_zi_fu('ming_gang', m[0])
        elif len(m) == 3 and m[0] == m[1] == m[2]:
            fu_lu_fu += mian_zi_fu('ming_ke', m[0])
        # 吃的顺子 0 符

    # ---- 一般形：枚举所有拆法和所有“和牌在哪个面子里”的情况 ----
    zui_da_fu = 0
    you_yi_ban_xing = False

    for que_tou, mian_zi_men in chai_pai(shou_pai):
        # 和牌可能在的位置：雀头（单骑），或者某一个含有和牌的面子
        ke_neng_wei_zhi = []
        if que_tou == win_tile:
            ke_neng_wei_zhi.append(-1)   # -1 表示单骑
        for i in range(len(mian_zi_men)):
            lei_xing, pai = mian_zi_men[i]
            if lei_xing == 'ke' and pai == win_tile:
                ke_neng_wei_zhi.append(i)
            elif lei_xing == 'shun' and pai[1] == win_tile[1]:
                qi_dian = int(pai[0])
                if qi_dian <= int(win_tile[0]) <= qi_dian + 2:
                    ke_neng_wei_zhi.append(i)

        for wei_zhi in ke_neng_wei_zhi:
            you_yi_ban_xing = True
            fu_shu = 20  # 副底
            fu_shu += fu_lu_fu

            # 听牌形
            if wei_zhi == -1:
                ting_pai_xing = 'dan_qi'
            elif mian_zi_men[wei_zhi][0] == 'ke':
                ting_pai_xing = 'shuang_peng'
            else:
                ting_pai_xing = pan_ting_pai_xing(mian_zi_men[wei_zhi], win_tile)
            fu_shu += TING_PAI_FU[ting_pai_xing]

            # 手里的面子
            quan_shun_zi = True
            for i in range(len(mian_zi_men)):
                lei_xing, pai = mian_zi_men[i]
                if lei_xing == 'ke':
                    quan_shun_zi = False
                    if i == wei_zhi and not is_tsumo:
                        # 荣和别人的牌凑成的刻子，算明刻
                        fu_shu += mian_zi_fu('ming_ke', pai)
                    else:
                        fu_shu += mian_zi_fu('an_ke', pai)

            # 雀头
            qt_fu = que_tou_fu(que_tou, bakaze, jikaze, renpu_fu)
            fu_shu += qt_fu

            # 副露里面有刻子、杠的话也不是全顺子
            if fu_lu_fu > 0:
                quan_shun_zi = False

            # 平和：门清（不能有任何副露，暗杠也不行），全顺子，雀头不是役牌，两面听
            shi_ping_he = (len(fu_lu) == 0 and quan_shun_zi and qt_fu == 0
                           and ting_pai_xing == 'liang_mian')

            if shi_ping_he:
                if is_tsumo:
                    fu_shu = 20      # 平和自摸 20 符
                else:
                    fu_shu = 30      # 平和荣和 20 + 门前加符 10
            else:
                if is_tsumo:
                    fu_shu += 2      # 自摸符
                elif men_qing:
                    fu_shu += 10     # 门前清荣和
                fu_shu = jin_wei(fu_shu)
                # 副露了但是一个符都没有（20 符），书上说算 30 符
                if not men_qing and fu_shu == 20:
                    fu_shu = 30

            if fu_shu > zui_da_fu:
                zui_da_fu = fu_shu

    if you_yi_ban_xing:
        return zui_da_fu

    # 拆不成一般形，再看七对子
    # （二杯口那种两种都能拆的，上面一般形已经返回了，因为二杯口比七对子番高）
    if len(fu_lu) == 0 and shi_qi_dui_zi(shou_pai):
        return 25

    # 不是和牌形
    return 0


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
