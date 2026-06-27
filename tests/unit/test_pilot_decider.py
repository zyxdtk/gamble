"""PilotDecider 单元测试"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.pilot_decider import PilotDecider
from src.utils.cli_player import ActionChoice, PilotMode, StdinMonitor
from src.strategies.table_strategy import TableAction, TableActionType


def _make_strategy():
    """创建 mock Strategy"""
    strategy = MagicMock()
    strategy.strategy_name = "gto"
    return strategy


def _make_payload():
    """创建测试 payload"""
    return {
        "my_seat_id": 0,
        "hole_cards": ["Ah", "Kd"],
        "community_cards": [],
        "pot": 100,
        "to_call": 10,
        "min_raise": 20,
        "max_raise": 500,
        "available_actions": ["FOLD", "CALL", "RAISE", "ALL_IN"],
        "current_stage": "preflop",
        "players": {
            "0": {"user_id": "p0", "name": "Me", "chips": 500, "is_active": True, "status": "active", "bet": 0},
            "1": {"user_id": "p1", "name": "Opp", "chips": 500, "is_active": True, "status": "active", "bet": 0},
        },
    }


def _make_table_payload():
    """创建桌位测试 payload"""
    return {
        "my_chips": 200,
        "my_bank": 1000,
        "is_seated": True,
        "is_playing": True,
        "hands_played": 10,
        "total_profit": 50,
        "current_bb": 2,
        "seat_count": 6,
        "active_count": 5,
    }


class TestSuggest:
    """suggest() 同步返回 AI 建议"""

    def test_returns_action_choice(self):
        decider = PilotDecider(strategy=_make_strategy(), pilot_mode=PilotMode.AUTO)
        result = decider.suggest(_make_payload())
        assert isinstance(result, ActionChoice)

    def test_suggest_uses_strategy_name(self):
        strategy = _make_strategy()
        strategy.strategy_name = "range"
        decider = PilotDecider(strategy=strategy, pilot_mode=PilotMode.AUTO)
        with patch("src.core.pilot_decider.build_default") as mock_bd:
            mock_bd.return_value = ActionChoice("fold", 0, "fold", "", "strategy:range")
            decider.suggest({"hole_cards": [], "available_actions": []})
            mock_bd.assert_called_once()
            assert mock_bd.call_args[1].get("strategy_name") == "range" or mock_bd.call_args[0][1] == "range" if len(mock_bd.call_args[0]) > 1 else True


class TestDecideHandAuto:
    """AUTO 模式直接返回 AI 建议"""

    @pytest.mark.asyncio
    async def test_auto_returns_suggest(self):
        decider = PilotDecider(strategy=_make_strategy(), pilot_mode=PilotMode.AUTO)
        expected = ActionChoice("call", 10, "call (10)", "AI", "strategy:gto")
        with patch.object(decider, "suggest", return_value=expected):
            result = await decider.decide_hand(_make_payload())
            assert result.action == "call"
            assert result.amount == 10

    @pytest.mark.asyncio
    async def test_auto_never_prompts(self):
        decider = PilotDecider(strategy=_make_strategy(), pilot_mode=PilotMode.AUTO)
        with patch("src.core.pilot_decider.prompt_hand_action") as mock_prompt:
            mock_prompt.return_value = ActionChoice("fold", 0, "fold", "", "manual")
            await decider.decide_hand(_make_payload())
            mock_prompt.assert_not_called()


class TestDecideHandAssist:
    """ASSIST 模式调用 prompt"""

    @pytest.mark.asyncio
    async def test_assist_calls_prompt(self):
        decider = PilotDecider(strategy=_make_strategy(), pilot_mode=PilotMode.ASSIST)
        ai_choice = ActionChoice("call", 10, "call (10)", "AI", "strategy:gto")
        with patch.object(decider, "suggest", return_value=ai_choice):
            with patch("src.core.pilot_decider.prompt_hand_action", new_callable=AsyncMock) as mock_prompt:
                mock_prompt.return_value = ActionChoice("fold", 0, "fold", "用户", "manual")
                result = await decider.decide_hand(_make_payload())
                mock_prompt.assert_called_once()
                assert result.action == "fold"


class TestDecideHandManaged:
    """MANAGED 模式：默认 AI，takeover 时才 prompt"""

    @pytest.mark.asyncio
    async def test_managed_default_ai(self):
        decider = PilotDecider(strategy=_make_strategy(), pilot_mode=PilotMode.MANAGED)
        ai_choice = ActionChoice("call", 10, "call (10)", "AI", "strategy:gto")
        with patch.object(decider, "suggest", return_value=ai_choice):
            with patch("src.core.pilot_decider.prompt_hand_action") as mock_prompt:
                result = await decider.decide_hand(_make_payload())
                mock_prompt.assert_not_called()
                assert result.action == "call"

    @pytest.mark.asyncio
    async def test_managed_takeover_prompts(self):
        stdin = StdinMonitor()
        stdin._takeover = True
        decider = PilotDecider(
            strategy=_make_strategy(), pilot_mode=PilotMode.MANAGED, stdin_monitor=stdin
        )
        ai_choice = ActionChoice("call", 10, "call (10)", "AI", "strategy:gto")
        with patch.object(decider, "suggest", return_value=ai_choice):
            with patch("src.core.pilot_decider.prompt_hand_action", new_callable=AsyncMock) as mock_prompt:
                mock_prompt.return_value = ActionChoice("fold", 0, "fold", "用户", "manual")
                result = await decider.decide_hand(_make_payload())
                mock_prompt.assert_called_once()
                assert result.action == "fold"
                # takeover 应在决策后重置
                assert stdin.is_takeover is False


class TestDecideTable:
    """桌位决策"""

    @pytest.mark.asyncio
    async def test_auto_table_returns_choice(self):
        decider = PilotDecider(strategy=_make_strategy(), pilot_mode=PilotMode.AUTO)
        result = await decider.decide_table(_make_table_payload())
        assert isinstance(result, ActionChoice)
        assert result.action == "none"  # DefaultTableStrategy 默认返回 NONE

    @pytest.mark.asyncio
    async def test_assist_table_calls_prompt(self):
        decider = PilotDecider(strategy=_make_strategy(), pilot_mode=PilotMode.ASSIST)
        with patch("src.core.pilot_decider.prompt_table_action", new_callable=AsyncMock) as mock_prompt:
            mock_prompt.return_value = ActionChoice("none", 0, "none", "", "manual")
            result = await decider.decide_table(_make_table_payload())
            mock_prompt.assert_called_once()


class TestTableActionToChoice:
    """TableAction → ActionChoice 转换"""

    def test_none_action(self):
        action = TableAction(action_type=TableActionType.NONE, reasoning="test")
        choice = PilotDecider._table_action_to_choice(action)
        assert choice.action == "none"
        assert choice.amount == 0

    def test_add_chips_action(self):
        action = TableAction(action_type=TableActionType.ADD_CHIPS, amount=100, reasoning="补筹")
        choice = PilotDecider._table_action_to_choice(action)
        assert choice.action == "add_chips"
        assert choice.amount == 100

    def test_sit_out_action(self):
        action = TableAction(action_type=TableActionType.SIT_OUT, reasoning="止盈")
        choice = PilotDecider._table_action_to_choice(action)
        assert choice.action == "sit_out"
        assert choice.amount == 0  # sit_out 不带金额
