"""
测试胜率计算功能
"""
from src.decision_engine import DecisionEngine
from src.game_state import GameState, Player

def test_equity_with_multiple_opponents():
    """测试多对手胜率计算"""
    engine = DecisionEngine()
    state = GameState()
    
    # 设置手牌和公共牌
    state.hole_cards = ["Ks", "Kd"]  # 一对K
    state.community_cards = ["7h", "2c", "9s"]  # 翻牌
    
    # 添加玩家 (模拟6人桌)
    for i in range(6):
        player = Player(seat_id=i)
        player.is_active = True
        player.status = "active"
        state.players[i] = player
    
    print("测试场景 1: 6人桌,所有人都在")
    result = engine.calculate_equity(state, iterations=100)
    print(f"结果: {result}")
    assert "对 5 位对手" in result, f"应该显示5位对手,但得到: {result}"
    
    # 场景2: 2人弃牌
    state.players[1].status = "folded"
    state.players[1].is_active = False
    state.players[2].status = "folded"
    state.players[2].is_active = False
    
    print("\n测试场景 2: 2人弃牌,剩余3人")
    result = engine.calculate_equity(state, iterations=100)
    print(f"结果: {result}")
    assert "对 3 位对手" in result, f"应该显示3位对手,但得到: {result}"
    
    # 场景3: 只剩1个对手
    state.players[3].status = "folded"
    state.players[3].is_active = False
    state.players[4].status = "folded"
    state.players[4].is_active = False
    
    print("\n测试场景 3: 只剩1个对手")
    result = engine.calculate_equity(state, iterations=100)
    print(f"结果: {result}")
    assert "对 1 位对手" in result, f"应该显示1位对手,但得到: {result}"
    
    print("\n✅ 所有测试通过!")

if __name__ == "__main__":
    test_equity_with_multiple_opponents()
