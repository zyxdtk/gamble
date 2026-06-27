class PlayerTag:
    """玩家类型标签常量体系"""
    UNKNOWN = "样本不足"
    STATION = "跟注站 (Calling Station)"
    MANIAC = "疯子 (Maniac)"
    NIT = "紧逼 (Nit/Tight)"
    TAG = "紧凶 (TAG)"
    FISH = "宽松被动 (Fish)"
    AVERAGE = "普通 (Average)"
    # 疑似标签：样本不足但有一定方向信号
    PROVISIONAL_LAG = "疑似松凶 (Provisional LAG)"
    PROVISIONAL_STATION = "疑似跟注站 (Provisional Station)"
    PROVISIONAL_NIT = "疑似紧逼 (Provisional Nit)"
    PROVISIONAL_UNKNOWN = "未知倾向 (Provisional Unknown)"


def get_player_tag(player) -> str:
    """根据玩家的统计数据计算其分类标签"""
    if player.hands_played < 5:
        return PlayerTag.UNKNOWN

    vpip = player.vpip
    pfr = player.pfr

    if vpip > 40 and pfr < 10:
        return PlayerTag.STATION
    if vpip > 50 and pfr > 30:
        return PlayerTag.MANIAC
    if vpip < 15:
        return PlayerTag.NIT
    if vpip < 25 and pfr > 15:
        return PlayerTag.TAG
    if vpip > 30 and pfr < 15:
        return PlayerTag.FISH

    return PlayerTag.AVERAGE


def get_provisional_tag(player) -> str:
    """
    改善冷启动盲区：在样本不足时提供方向性标签。

    - 5+ 手 → 复用 get_player_tag()
    - 2-4 手 → 基于 VPIP/PFR 方向粗估
    - 1 手 → 返回 "未知倾向"
    """
    if player.hands_played >= 5:
        return get_player_tag(player)

    if player.hands_played <= 1:
        return PlayerTag.PROVISIONAL_UNKNOWN

    # 2-4 手：基于 VPIP/PFR 方向粗估
    vpip = player.vpip
    pfr = player.pfr

    if vpip > 50 and pfr > 25:
        return PlayerTag.PROVISIONAL_LAG
    if vpip > 50 and pfr < 15:
        return PlayerTag.PROVISIONAL_STATION
    if vpip == 0:
        return PlayerTag.PROVISIONAL_NIT

    return PlayerTag.PROVISIONAL_UNKNOWN


def classify_by_action_signature(action: str, pot_ratio: float, street: str) -> str:
    """
    根据单次动作特征推断对手倾向。

    - raise + pot_ratio > 1.0 → "激进倾向"
    - call + pot_ratio > 0.5 → "跟注倾向"
    - fold + preflop + pot_ratio <= 0.5 → "较紧倾向"
    """
    if action == "raise" and pot_ratio > 1.0:
        return "激进倾向"
    if action == "call" and pot_ratio > 0.5:
        return "跟注倾向"
    if action == "fold" and street == "preflop" and pot_ratio <= 0.5:
        return "较紧倾向"
    return "中性倾向"
