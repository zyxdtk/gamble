class PlayerTag:
    """玩家类型标签常量体系"""
    UNKNOWN = "样本不足"
    STATION = "跟注站 (Calling Station)"
    MANIAC = "疯子 (Maniac)"
    NIT = "紧逼 (Nit/Tight)"
    TAG = "紧凶 (TAG)"
    FISH = "宽松被动 (Fish)"
    AVERAGE = "普通 (Average)"


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
