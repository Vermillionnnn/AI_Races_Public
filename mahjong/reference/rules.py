"""规则开关（规则.md 第 8 节）。每个开关的默认值取规则.md 表里第一列。

接口说明.md 定了四个键（aka_dora、kuitan、kiriage_mangan、renpu_fu），其余是参考实现自己的键名。
状态里的 rules 回显全部键（前端 checkState 只检查那四个键，多出来的键不报错）。
"""

# 键: (默认值, 允许的取值)；允许的取值为 None 表示 true / false
DEFAULTS = {
    # 接口说明.md 里的四个键
    'aka_dora': (True, None),            # 赤宝牌：各花色一张红五
    'kuitan': (True, None),              # 食断
    'kiriage_mangan': (False, None),     # 切上满贯
    'renpu_fu': (4, (4, 2)),             # 连风雀头的符
    # 第 8 节其余开关
    'kazoe_yakuman': (True, None),       # 累计役满（13 番以上算役满）；false 封顶三倍满
    'double_yakuman': (True, None),      # 国士十三面、四暗刻单骑、纯正九莲、大四喜算 2 倍；false 一律 1 倍
    'composite_yakuman': (True, None),   # 复合役满倍数相加；false 只算最高的一个
    'tenhou_double': (True, None),       # 天和、地和时的九莲、国士、四暗刻都算 2 倍；false 都算 1 倍
    'double_ron': (True, None),          # 一炮双响；false 头跳（只有离放铳者最近的一人和了）
    'triple_ron_abort': (True, None),    # 三家和了流局；false 三人都和了
    'pao': (True, None),                 # 包（大三元、大四喜）
    'kan_dora_delay': (True, None),      # 明杠、加杠的杠宝在打牌后翻；false 一律立即翻
    'kokushi_ankan_rob': (True, None),   # 国士无双可以抢暗杠
    'tobi': (True, None),                # 击飞（低于 0 点结束）
    'tonpuu_extension': (False, None),   # 东风战南入
    'hanchan_extension': (False, None),  # 半庄战西入
    'agari_yame': (True, None),          # 最后一局庄家连庄且第一时结束
    'leftover_sticks_to_top': (True, None),  # 结束时剩余供托归第一名
    'nagashi_mangan': (False, None),     # 流局满贯
    'kuikae_ban': (True, None),          # 食替禁止
    'riichi_ankan': (True, None),        # 立直后暗杠（听的牌不变才允许）；false 不允许
    'four_riichi_abort': (True, None),   # 四家立直流局
    'four_winds_abort': (True, None),    # 四风连打流局
    'four_kans_abort': (True, None),     # 四杠散了流局
    'kyuushu': (True, None),             # 九种九牌
    # 规则.md 还没定的一处（见 README）
    'furiten_no_yaku': (True, None),     # 没役时漏掉听的牌也算同巡/立直振听
}


class RuleError(ValueError):
    pass


def parse_rules(given):
    """new_game 的 rules -> 完整的开关表。没传的键用默认值；未知的键或取值不对时报错。"""
    if given is None:
        given = {}
    if not isinstance(given, dict):
        raise RuleError('rules 应该是对象')
    rules = {k: v[0] for k, v in DEFAULTS.items()}
    for k, v in given.items():
        if k not in DEFAULTS:
            raise RuleError('不认识的规则开关：%s（可用的键见 reference/README.md）' % k)
        allowed = DEFAULTS[k][1]
        if allowed is None:
            if not isinstance(v, bool):
                raise RuleError('rules.%s 应该是 true / false' % k)
        else:
            if isinstance(v, bool) or v not in allowed:
                raise RuleError('rules.%s 只能是 %s' % (k, ' / '.join(map(str, allowed))))
        rules[k] = v
    return rules
