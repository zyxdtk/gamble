"""
Ring Game 单元测试
"""
import asyncio
import pytest

from src.core.messaging import AsyncChannel, Message, MessageType
from src.strategies.table_strategy import (
    AggressiveTableStrategy,
    ConservativeTableStrategy,
    DefaultTableStrategy,
    TableAction,
    TableActionType,
    TableState,
)
from src.strategies.hand_strategy import HandStrategy, StrategyHandAdapter
from src.platforms.arena.ring import (
    RingConfig,
    RingPlayerConfig,
    RingPlatform,
    RingPlayer,
    RingReport,
    RingPlayerStats,
    RingSeatState,
    RingTable,
)


# ─── Messaging 测试 ───

class TestAsyncChannel:
    """双工通信通道测试"""

    def test_send_and_receive(self):
        async def _test():
            ch = AsyncChannel(player_id="test")
            msg = Message(msg_type=MessageType.TABLE_STATE, payload={"chips": 100})

            # Platform -> Player
            await ch.send_to_player(msg)
            received = await ch.receive_from_platform(timeout=1.0)
            assert received.msg_type == MessageType.TABLE_STATE
            assert received.payload["chips"] == 100

        asyncio.run(_test())

    def test_player_to_platform(self):
        async def _test():
            ch = AsyncChannel(player_id="test")
            msg = Message(msg_type=MessageType.HAND_ACTION, payload={"action": "FOLD"})

            await ch.send_to_platform(msg)
            received = await ch.receive_from_player(timeout=1.0)
            assert received.msg_type == MessageType.HAND_ACTION
            assert received.payload["action"] == "FOLD"

        asyncio.run(_test())

    def test_request_response(self):
        async def _test():
            ch = AsyncChannel(player_id="test")

            # 模拟 Platform 发送请求，Player 在另一个任务中响应
            request = Message(
                msg_type=MessageType.REQUEST_ACTION,
                payload={"to_call": 10},
            )

            async def player_respond():
                req = await ch.receive_from_platform(timeout=2.0)
                assert req.msg_type == MessageType.REQUEST_ACTION
                response = Message(
                    msg_type=MessageType.HAND_ACTION,
                    payload={"action": "CALL", "amount": 10},
                    request_id=req.request_id,
                )
                await ch.send_to_platform(response)

            # 启动 Player 响应任务
            task = asyncio.create_task(player_respond())

            # Platform 等待响应
            result = await ch.request_response(request, timeout=2.0)
            assert result.msg_type == MessageType.HAND_ACTION
            assert result.payload["action"] == "CALL"

            await task

        asyncio.run(_test())

    def test_request_response_timeout(self):
        async def _test():
            ch = AsyncChannel(player_id="test")
            request = Message(msg_type=MessageType.REQUEST_ACTION, payload={})

            with pytest.raises(asyncio.TimeoutError):
                await ch.request_response(request, timeout=0.1)

        asyncio.run(_test())

    def test_close_cancels_pending(self):
        async def _test():
            ch = AsyncChannel(player_id="test")
            request = Message(msg_type=MessageType.REQUEST_ACTION, payload={})
            request.request_id = Message.make_request_id()

            loop = asyncio.get_running_loop()
            future = loop.create_future()
            ch._pending_requests[request.request_id] = future

            ch.close()
            assert future.cancelled() or future.done()
            assert len(ch._pending_requests) == 0

        asyncio.run(_test())


# ─── TableStrategy 测试 ───

class TestDefaultTableStrategy:
    """默认桌位策略测试"""

    def setup_method(self):
        self.strategy = DefaultTableStrategy()

    def test_none_action_when_ok(self):
        state = TableState(
            my_chips=200, my_bank=1800, is_seated=True, is_playing=True,
            hands_played=10, total_profit=0, current_bb=2,
        )
        action = self.strategy.decide(state)
        assert action.action_type == TableActionType.NONE

    def test_stop_loss_leave(self):
        state = TableState(
            my_chips=0, my_bank=1500, is_seated=True, is_playing=False,
            total_profit=-500, current_bb=2,
        )
        action = self.strategy.decide(state)
        assert action.action_type == TableActionType.LEAVE

    def test_take_profit_leave(self):
        state = TableState(
            my_chips=800, my_bank=1800, is_seated=True, is_playing=True,
            total_profit=600, current_bb=2,
        )
        action = self.strategy.decide(state)
        assert action.action_type == TableActionType.LEAVE

    def test_low_chips_add_chips(self):
        state = TableState(
            my_chips=10, my_bank=1800, is_seated=True, is_playing=True,
            total_profit=0, current_bb=2,
        )
        action = self.strategy.decide(state)
        assert action.action_type == TableActionType.ADD_CHIPS
        assert action.amount > 0

    def test_max_chips_sit_out(self):
        state = TableState(
            my_chips=1700, my_bank=200, is_seated=True, is_playing=True,
            total_profit=0, current_bb=2,
        )
        action = self.strategy.decide(state)
        assert action.action_type == TableActionType.SIT_OUT

    def test_sit_in_when_sit_out(self):
        state = TableState(
            my_chips=200, my_bank=1800, is_seated=True, is_playing=False,
        )
        action = self.strategy.decide(state)
        assert action.action_type == TableActionType.SIT_IN


class TestConservativeTableStrategy:
    """保守桌位策略测试"""

    def test_profit_sit_out(self):
        strategy = ConservativeTableStrategy()
        state = TableState(
            my_chips=400, my_bank=1800, is_seated=True, is_playing=True,
            total_profit=220, current_bb=2,
        )
        action = strategy.decide(state)
        assert action.action_type == TableActionType.SIT_OUT


class TestAggressiveTableStrategy:
    """激进桌位策略测试"""

    def test_no_take_profit(self):
        strategy = AggressiveTableStrategy()
        state = TableState(
            my_chips=2000, my_bank=0, is_seated=True, is_playing=True,
            total_profit=1800, current_bb=2,
        )
        action = strategy.decide(state)
        # 激进策略不止盈
        assert action.action_type != TableActionType.LEAVE


# ─── HandStrategy 测试 ───

class TestStrategyHandAdapter:
    """手牌策略适配器测试"""

    def test_adapter_delegates_make_decision(self):
        from src.strategies.strategies.check_or_fold import CheckOrFoldStrategy
        from src.strategies.game_state import GameState

        strategy = CheckOrFoldStrategy()
        adapter = StrategyHandAdapter(strategy)

        state = GameState()
        plan = adapter.make_decision(state)
        # CheckOrFold 应该返回 CHECK 或 FOLD
        from src.strategies.action_plan import ActionType
        assert plan.primary_action in (ActionType.CHECK, ActionType.FOLD)

    def test_adapter_preserves_name(self):
        from src.strategies.strategies.check_or_fold import CheckOrFoldStrategy
        strategy = CheckOrFoldStrategy()
        adapter = StrategyHandAdapter(strategy)
        assert adapter.strategy_name == strategy.strategy_name


# ─── RingTable 测试 ───

class TestRingTable:
    """Ring Game 桌位管理测试"""

    def test_sit_player(self):
        table = RingTable(table_id="t1", max_seats=9, sb=1, bb=2)
        seat_id = table.sit_player("p1", "Alice", 200)
        assert seat_id == 0
        assert table.seats[0].chips == 200
        assert table.seats[0].is_playing is True

    def test_sit_multiple_players(self):
        table = RingTable(table_id="t1", max_seats=9, sb=1, bb=2)
        s1 = table.sit_player("p1", "Alice", 200)
        s2 = table.sit_player("p2", "Bob", 300)
        assert s1 == 0
        assert s2 == 1

    def test_remove_player(self):
        table = RingTable(table_id="t1", max_seats=9, sb=1, bb=2)
        table.sit_player("p1", "Alice", 200)
        seat = table.remove_player(0)
        assert seat.name == "Alice"
        assert table.seats[0] is None

    def test_sit_in_out(self):
        table = RingTable(table_id="t1", max_seats=9, sb=1, bb=2)
        table.sit_player("p1", "Alice", 200)
        table.sit_out(0)
        assert table.seats[0].is_playing is False
        assert len(table.get_playing_players()) == 0

        table.sit_in(0)
        assert table.seats[0].is_playing is True
        assert len(table.get_playing_players()) == 1

    def test_add_chips(self):
        table = RingTable(table_id="t1", max_seats=9, sb=1, bb=2)
        table.sit_player("p1", "Alice", 200)
        table.add_chips(0, 100)
        assert table.seats[0].chips == 300

    def test_table_full(self):
        table = RingTable(table_id="t1", max_seats=2, sb=1, bb=2)
        table.sit_player("p1", "Alice", 200)
        table.sit_player("p2", "Bob", 200)
        with pytest.raises(ValueError):
            table.sit_player("p3", "Charlie", 200)


# ─── RingPlatform 集成测试 ───

class TestRingPlatform:
    """Ring Game 平台集成测试"""

    def test_initialize(self):
        async def _test():
            players = [
                RingPlayerConfig(name="A", hand_strategy="gto", initial_bank=2000, buyin_amount=200),
                RingPlayerConfig(name="B", hand_strategy="range", initial_bank=2000, buyin_amount=200),
            ]
            config = RingConfig(players=players, max_rounds=5)
            platform = RingPlatform(config)
            await platform.initialize()
            assert platform.table is not None
            assert len(platform.players) == 2
            # 初始买入在 run() 中执行，initialize 后桌位为空
            assert platform.table.active_count == 0

        asyncio.run(_test())

    def test_run_short_game(self):
        async def _test():
            players = [
                RingPlayerConfig(name="A", hand_strategy="gto", initial_bank=2000, buyin_amount=200),
                RingPlayerConfig(name="B", hand_strategy="range", initial_bank=2000, buyin_amount=200),
                RingPlayerConfig(name="C", hand_strategy="aggressive", initial_bank=2000, buyin_amount=200),
            ]
            config = RingConfig(players=players, max_rounds=5)
            platform = RingPlatform(config)
            await platform.initialize()
            report = await platform.run()

            assert isinstance(report, RingReport)
            assert report.num_hands == 5
            assert len(report.player_stats) == 3

            # 验证胜场总数（边池时一手可能多个赢家，所以 >= num_hands）
            total_wins = sum(ps.hands_won for ps in report.player_stats)
            assert total_wins >= 5

        asyncio.run(_test())

    def test_table_strategy_actions(self):
        async def _test():
            players = [
                RingPlayerConfig(name="A", hand_strategy="checkorfold", table_strategy="default",
                                 initial_bank=2000, buyin_amount=200),
                RingPlayerConfig(name="B", hand_strategy="checkorfold", table_strategy="default",
                                 initial_bank=2000, buyin_amount=200),
            ]
            config = RingConfig(players=players, max_rounds=3)
            platform = RingPlatform(config)
            await platform.initialize()
            report = await platform.run()

            assert report.num_hands > 0

        asyncio.run(_test())


# ─── RingPlayer 测试 ───

class TestRingPlayer:
    """Ring Game 玩家测试"""

    def test_handle_request_action(self):
        async def _test():
            from src.strategies.strategies.check_or_fold import CheckOrFoldStrategy
            strategy = CheckOrFoldStrategy()
            hand_strategy = StrategyHandAdapter(strategy)
            table_strategy = DefaultTableStrategy()
            channel = AsyncChannel(player_id="p1")

            player = RingPlayer(
                player_id="p1", name="Test", table_strategy=table_strategy,
                hand_strategy=hand_strategy, channel=channel,
            )

            msg = Message(
                msg_type=MessageType.REQUEST_ACTION,
                payload={
                    "my_seat_id": 0,
                    "hole_cards": ["Ah", "Kd"],
                    "community_cards": [],
                    "pot": 10,
                    "to_call": 0,
                    "min_raise": 2,
                    "max_raise": 200,
                    "available_actions": ["FOLD", "CHECK", "RAISE", "ALL_IN"],
                    "current_stage": "preflop",
                    "players": {
                        "0": {"name": "Test", "chips": 200, "is_active": True, "status": "active", "bet": 0},
                        "1": {"name": "Opp", "chips": 200, "is_active": True, "status": "active", "bet": 5},
                    },
                },
            )

            response = await player._handle_message(msg)
            assert response is not None
            assert response.msg_type == MessageType.HAND_ACTION
            assert "action" in response.payload

        asyncio.run(_test())

    def test_handle_request_table_action(self):
        async def _test():
            table_strategy = DefaultTableStrategy()
            from src.strategies.strategies.check_or_fold import CheckOrFoldStrategy
            hand_strategy = StrategyHandAdapter(CheckOrFoldStrategy())
            channel = AsyncChannel(player_id="p1")

            player = RingPlayer(
                player_id="p1", name="Test", table_strategy=table_strategy,
                hand_strategy=hand_strategy, channel=channel,
            )

            msg = Message(
                msg_type=MessageType.REQUEST_TABLE_ACTION,
                payload={
                    "my_chips": 200, "my_bank": 1800, "is_seated": True,
                    "is_playing": True, "hands_played": 10, "total_profit": 0,
                    "current_bb": 2, "seat_count": 3, "active_count": 3,
                },
            )

            response = await player._handle_message(msg)
            assert response is not None
            assert response.msg_type == MessageType.TABLE_ACTION
            assert "action_type" in response.payload

        asyncio.run(_test())


# ─── CLIRingPlayer 测试 ───

class TestCLIRingPlayer:
    """CLI 人类玩家测试"""

    def test_create_patches_player(self):
        """CLIRingPlayer.create() 应替换决策钩子"""
        async def _test():
            from src.strategies.strategies.check_or_fold import CheckOrFoldStrategy
            from src.platforms.arena.ring_cli import CLIRingPlayer

            strategy = CheckOrFoldStrategy()
            hand_strategy = StrategyHandAdapter(strategy)
            table_strategy = DefaultTableStrategy()
            channel = AsyncChannel(player_id="p1")

            player = RingPlayer(
                player_id="p1", name="Human", table_strategy=table_strategy,
                hand_strategy=hand_strategy, channel=channel,
            )

            # create 前是 AI 决策
            assert not player.is_human

            # create 替换决策钩子
            CLIRingPlayer.create(player)
            assert player.is_human is True

            # _decide_hand_action 和 _decide_table_action 已被替换
            # 无法直接测试 CLI 输入（需要终端），但可以验证方法已被替换
            import inspect
            assert inspect.iscoroutinefunction(player._decide_hand_action)
            assert inspect.iscoroutinefunction(player._decide_table_action)

        asyncio.run(_test())

    def test_create_preserves_state(self):
        """CLIRingPlayer.create() 应保留 RingPlayer 的所有状态"""
        async def _test():
            from src.strategies.strategies.check_or_fold import CheckOrFoldStrategy
            from src.platforms.arena.ring_cli import CLIRingPlayer

            strategy = CheckOrFoldStrategy()
            hand_strategy = StrategyHandAdapter(strategy)
            table_strategy = DefaultTableStrategy()
            channel = AsyncChannel(player_id="p1")

            player = RingPlayer(
                player_id="p1", name="Human", table_strategy=table_strategy,
                hand_strategy=hand_strategy, channel=channel,
            )
            player.bank = 2000
            player.chips_on_table = 200
            player.is_seated = True
            player.seat_id = 3

            CLIRingPlayer.create(player)

            # 状态保持不变
            assert player.player_id == "p1"
            assert player.name == "Human"
            assert player.bank == 2000
            assert player.chips_on_table == 200
            assert player.is_seated is True
            assert player.seat_id == 3
            assert player.channel is channel
            # table_strategy / hand_strategy 也保留（fallback 用）
            assert player.table_strategy is table_strategy
            assert player.hand_strategy is hand_strategy

        asyncio.run(_test())


# ─── Message 类型测试 ───

class TestMessageType:
    """消息类型完整性测试"""

    def test_all_message_types(self):
        expected = [
            "TABLE_STATE", "HAND_STATE", "REQUEST_ACTION",
            "REQUEST_TABLE_ACTION", "HAND_RESULT", "GAME_OVER",
            "HAND_ACTION", "TABLE_ACTION",
        ]
        for name in expected:
            assert hasattr(MessageType, name), f"缺少 MessageType.{name}"

    def test_message_dataclass(self):
        msg = Message(
            msg_type=MessageType.GAME_OVER,
            payload={"reason": "test"},
            request_id="abc123",
        )
        assert msg.msg_type == MessageType.GAME_OVER
        assert msg.payload["reason"] == "test"
        assert msg.request_id == "abc123"
        assert msg.timestamp > 0
