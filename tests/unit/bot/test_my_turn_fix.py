"""
测试 My Turn 状态识别修复
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio


class TestMyTurnStateFix:
    """测试 My Turn 状态识别的修复"""
    
    @pytest.mark.asyncio
    async def test_is_acting_set_when_buttons_available(self):
        """当有可用按钮时，应该设置 is_acting = True"""
        from src.bot.play_manager import PlayManager
        from src.bot.table_manager import TableManager
        from src.strategies.game_state import Player
        
        # 创建 mock page
        mock_page = MagicMock()
        
        # 创建 TableManager
        with patch.object(TableManager, '_load_settings'):
            tm = TableManager(mock_page, strategy_type="gto")
        
        # 设置初始状态
        tm.state.my_seat_id = 1
        tm.state.players[1] = Player(seat_id=1)
        tm.state.players[1].is_acting = False
        tm.is_sitting = True
        
        # Mock find_action_buttons 返回有按钮
        tm.play_mgr.find_action_buttons = AsyncMock(return_value={
            "fold": MagicMock(),
            "call": MagicMock(),
            "raise": MagicMock()
        })
        
        # 运行 update_state_from_dom
        await tm.play_mgr.update_state_from_dom()
        
        # 验证 is_acting 被设置为 True
        assert tm.state.players[1].is_acting == True
        assert tm.state.active_seat == 1
    
    @pytest.mark.asyncio
    async def test_is_acting_cleared_when_no_buttons(self):
        """当没有可用按钮时，应该清除 is_acting = False"""
        from src.bot.play_manager import PlayManager
        from src.bot.table_manager import TableManager
        from src.strategies.game_state import Player
        
        # 创建 mock page
        mock_page = MagicMock()
        
        # 创建 TableManager
        with patch.object(TableManager, '_load_settings'):
            tm = TableManager(mock_page, strategy_type="gto")
        
        # 设置初始状态 - is_acting 为 True
        tm.state.my_seat_id = 1
        tm.state.players[1] = Player(seat_id=1)
        tm.state.players[1].is_acting = True
        tm.state.active_seat = 1
        tm.is_sitting = True
        
        # Mock find_action_buttons 返回空字典（没有按钮）
        tm.play_mgr.find_action_buttons = AsyncMock(return_value={})
        
        # 运行 update_state_from_dom
        await tm.play_mgr.update_state_from_dom()
        
        # 验证 is_acting 被清除为 False
        assert tm.state.players[1].is_acting == False
    
    @pytest.mark.asyncio
    async def test_is_my_turn_property(self):
        """测试 is_my_turn 属性是否正确反映 is_acting 状态"""
        from src.strategies.game_state import GameState, Player
        
        state = GameState()
        state.my_seat_id = 1
        
        # 情况1: 没有玩家信息
        assert state.is_my_turn == False
        
        # 情况2: 玩家存在但 is_acting = False
        state.players[1] = Player(seat_id=1, is_acting=False)
        assert state.is_my_turn == False
        
        # 情况3: 玩家存在且 is_acting = True
        state.players[1].is_acting = True
        assert state.is_my_turn == True
        
        # 情况4: my_seat_id 为 None
        state.my_seat_id = None
        assert state.is_my_turn == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
