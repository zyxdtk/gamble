"""
CLITournamentPlayer 单元测试
"""
import asyncio
import inspect
import pytest

from src.strategies.strategies.check_or_fold import CheckOrFoldStrategy
from src.platforms.arena.agent import ArenaAgent
from src.platforms.arena.tournament_cli import CLITournamentPlayer


class TestCLITournamentPlayer:

    def test_create_patches_agent(self):
        """CLITournamentPlayer.create() 应替换 get_action 并设置 is_human"""
        async def _test():
            strategy = CheckOrFoldStrategy()
            agent = ArenaAgent(seat_id=0, strategy=strategy, player_id="test_p0")

            # create 前
            assert not agent.is_human
            original_get_action = agent.get_action

            # create 替换决策钩子
            CLITournamentPlayer.create(agent)
            assert agent.is_human is True
            assert agent.get_action is not original_get_action
            assert inspect.iscoroutinefunction(agent.get_action)

        asyncio.run(_test())

    def test_create_preserves_state(self):
        """CLITournamentPlayer.create() 应保留 agent 的所有状态"""
        async def _test():
            strategy = CheckOrFoldStrategy()
            agent = ArenaAgent(seat_id=2, strategy=strategy, player_id="test_p2")
            agent.name = "TestPlayer"
            agent.global_player_stats = {0: {"hands": 5, "vpip_count": 2, "pfr_count": 1}}

            CLITournamentPlayer.create(agent)

            # 状态保持不变
            assert agent.seat_id == 2
            assert agent.player_id == "test_p2"
            assert agent.name == "TestPlayer"
            assert agent.strategy is strategy
            assert agent.global_player_stats == {0: {"hands": 5, "vpip_count": 2, "pfr_count": 1}}

        asyncio.run(_test())

    def test_create_returns_same_agent(self):
        """CLITournamentPlayer.create() 应返回同一个 agent 对象"""
        async def _test():
            strategy = CheckOrFoldStrategy()
            agent = ArenaAgent(seat_id=0, strategy=strategy, player_id="test_p0")

            result = CLITournamentPlayer.create(agent)
            assert result is agent

        asyncio.run(_test())
