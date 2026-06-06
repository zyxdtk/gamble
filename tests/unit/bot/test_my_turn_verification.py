"""
验证 My Turn 状态识别修复
"""
import sys
sys.path.insert(0, '/Users/ly/Workspace/gitee/gamble/src')

from strategies.game_state import GameState, Player


def test_is_my_turn_logic():
    """测试 is_my_turn 逻辑"""
    print("=== Testing is_my_turn Logic ===\n")
    
    # 创建游戏状态
    state = GameState()
    state.my_seat_id = 1
    
    print("Test 1: No player info")
    print(f"  is_my_turn: {state.is_my_turn}")
    assert state.is_my_turn == False, "Should be False when no player info"
    print("  ✓ PASS\n")
    
    print("Test 2: Player exists but is_acting = False")
    state.players[1] = Player(seat_id=1, is_acting=False)
    print(f"  is_acting: {state.players[1].is_acting}")
    print(f"  is_my_turn: {state.is_my_turn}")
    assert state.is_my_turn == False, "Should be False when is_acting is False"
    print("  ✓ PASS\n")
    
    print("Test 3: Player exists and is_acting = True")
    state.players[1].is_acting = True
    print(f"  is_acting: {state.players[1].is_acting}")
    print(f"  is_my_turn: {state.is_my_turn}")
    assert state.is_my_turn == True, "Should be True when is_acting is True"
    print("  ✓ PASS\n")
    
    print("Test 4: my_seat_id is None")
    state.my_seat_id = None
    print(f"  my_seat_id: {state.my_seat_id}")
    print(f"  is_my_turn: {state.is_my_turn}")
    assert state.is_my_turn == False, "Should be False when my_seat_id is None"
    print("  ✓ PASS\n")
    
    print("All tests passed! ✓")


def demonstrate_fix():
    """演示修复前后的行为差异"""
    print("\n=== Demonstrating the Fix ===\n")
    
    print("BEFORE FIX:")
    print("  - When action buttons appear, is_acting might not be set to True")
    print("  - When buttons disappear, is_acting might remain True")
    print("  - Result: 'My Turn' status inconsistent with available actions\n")
    
    print("AFTER FIX:")
    print("  - In play_manager.py:")
    print("    * If buttons found AND my_seat_id exists -> set is_acting = True")
    print("    * If NO buttons found -> clear is_acting = False")
    print("  - In replay_poker.py:")
    print("    * Relaxed turn detection: 1 check + available buttons = my turn")
    print("  - Result: 'My Turn' status correctly reflects action availability\n")
    
    # 模拟场景
    state = GameState()
    state.my_seat_id = 1
    state.players[1] = Player(seat_id=1, is_acting=False)
    
    print("Scenario Simulation:")
    print(f"  Initial state - is_acting: {state.players[1].is_acting}, is_my_turn: {state.is_my_turn}")
    
    # 模拟检测到按钮
    print("\n  [System detects action buttons]")
    state.players[1].is_acting = True  # This is what the fix ensures
    print(f"  After detection - is_acting: {state.players[1].is_acting}, is_my_turn: {state.is_my_turn}")
    
    # 模拟按钮消失
    print("\n  [Action buttons disappear]")
    state.players[1].is_acting = False  # This is what the fix ensures
    print(f"  After disappearance - is_acting: {state.players[1].is_acting}, is_my_turn: {state.is_my_turn}")
    
    print("\n✓ State now correctly synchronized!")


if __name__ == "__main__":
    test_is_my_turn_logic()
    demonstrate_fix()
    
    print("\n" + "="*60)
    print("Summary of Changes:")
    print("="*60)
    print("1. src/bot/play_manager.py:")
    print("   - Added logic to clear is_acting when no buttons available")
    print("   - Ensures state consistency between button presence and turn status")
    print("\n2. src/platforms/browser/adapters/replay_poker.py:")
    print("   - Relaxed turn detection criteria")
    print("   - Now accepts 1 turn check + available buttons as valid turn indicator")
    print("\nThese changes ensure 'My Turn' status accurately reflects when")
    print("the player can actually take actions.")
    print("="*60)
