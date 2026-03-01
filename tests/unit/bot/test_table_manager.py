"""
tests/bot/test_table_manager.py

测试 TableManager 的核心逻辑（用 AsyncMock 替代真实 Playwright page）：
- 止损/止盈退出条件
- 满员计数与自动退桌
- 入座状态判断
- 离桌流程（Stand Up → Leave）
- 配置读取（username）
"""
import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.table_manager import TableManager
from src.bot.play_manager import PlayManager


def make_manager(page=None, strategy_type="check_or_fold"):
    """Helper：创建 TableManager，跳过 _load_settings 依赖配置文件。"""
    if page is None:
        page = MagicMock()
        page.url = "https://www.casino.org/replaypoker/play/table/99999?"
    with patch.object(TableManager, '_load_settings'):
        m = TableManager(page, strategy_type=strategy_type)
    # 设置 BB 倍数阈値（1/2 桌， big_blind=2）
    m.stop_loss_bb = 100
    m.take_profit_bb = 300
    m.low_chips_bb = 10
    m.big_blind = 2   # 1/2 桌
    return m


# ─── _parse_stakes_string ─────────────────────────────────────────────────────

class TestParseStakesString:
    """PlayManager._parse_stakes_string 的各种格式解析。"""

    def _make_play_manager(self):
        """创建一个带有 mock _parse_amount_string 的 PlayManager 实例。"""
        tm = MagicMock()
        pm = PlayManager(tm)
        pm._parse_amount_string = lambda s: int(float(re.sub(r"[^\d\.]", "", s))) if re.search(r"\d", s) else 0
        return pm

    def test_standard_1_2(self):
        pm = self._make_play_manager()
        assert pm._parse_stakes_string("1/2") == 2

    def test_standard_2_5(self):
        pm = self._make_play_manager()
        assert pm._parse_stakes_string("2/5") == 5

    def test_with_spaces(self):
        pm = self._make_play_manager()
        assert pm._parse_stakes_string(" 1 / 2 ") == 2

    def test_high_stakes(self):
        pm = self._make_play_manager()
        assert pm._parse_stakes_string("25/50") == 50

    def test_invalid_returns_zero(self):
        pm = self._make_play_manager()
        assert pm._parse_stakes_string("not_a_stake") == 0

    def test_empty_returns_zero(self):
        pm = self._make_play_manager()
        assert pm._parse_stakes_string("") == 0

    def test_lobby_display_format(self):
        """1 / 2 格式（大厅页面常见）。"""
        pm = self._make_play_manager()
        assert pm._parse_stakes_string("1 / 2") == 2


# ─── check_exit_conditions (via LifecycleManager) ────────────────────────────

class TestCheckExitConditions:
    """stop_loss_bb=100, take_profit_bb=300, low_chips_bb=10, big_blind=2 (1/2 桌)"""

    @pytest.mark.asyncio
    async def test_no_exit_when_initial_chips_not_set(self):
        """initial_chips 未设置时不触发退出。"""
        m = make_manager()
        m.lifecycle_mgr._detect_big_blind = AsyncMock()   # mock DOM 查找
        m.initial_chips = None
        assert await m.lifecycle_mgr.check_exit_conditions() is False

    @pytest.mark.asyncio
    async def test_stop_loss_triggers(self):
        """亏损 > stop_loss_bb(100) * big_blind(2) = 200 应触发。"""
        m = make_manager()
        m.lifecycle_mgr._detect_big_blind = AsyncMock()
        m.initial_chips = 1000
        m.state.total_chips = 799   # 亏损 201 > 200
        assert await m.lifecycle_mgr.check_exit_conditions() is True

    @pytest.mark.asyncio
    async def test_stop_loss_exact_boundary_triggers(self):
        """亏损 == stop_loss(200) 时也触发（使用 <=）。"""
        m = make_manager()
        m.lifecycle_mgr._detect_big_blind = AsyncMock()
        m.initial_chips = 1000
        m.state.total_chips = 800   # 亏损 200 = 100 BB
        assert await m.lifecycle_mgr.check_exit_conditions() is True

    @pytest.mark.asyncio
    async def test_stop_loss_within_limit_no_exit(self):
        """亏损 < 200 不触发。"""
        m = make_manager()
        m.lifecycle_mgr._detect_big_blind = AsyncMock()
        m.initial_chips = 1000
        m.state.total_chips = 850   # 亏损 150 < 200
        assert await m.lifecycle_mgr.check_exit_conditions() is False

    @pytest.mark.asyncio
    async def test_take_profit_triggers(self):
        """盈利 > take_profit_bb(300) * big_blind(2) = 600 应触发。"""
        m = make_manager()
        m.lifecycle_mgr._detect_big_blind = AsyncMock()
        m.initial_chips = 1000
        m.state.total_chips = 1601  # 盈利 601 > 600
        assert await m.lifecycle_mgr.check_exit_conditions() is True

    @pytest.mark.asyncio
    async def test_take_profit_exact_boundary_triggers(self):
        """盈利 == take_profit(600) 时也触发（使用 >=）。"""
        m = make_manager()
        m.lifecycle_mgr._detect_big_blind = AsyncMock()
        m.initial_chips = 1000
        m.state.total_chips = 1600  # 盈利 600 = 300 BB
        assert await m.lifecycle_mgr.check_exit_conditions() is True

    @pytest.mark.asyncio
    async def test_take_profit_within_limit_no_exit(self):
        """盈利 < 600 不触发。"""
        m = make_manager()
        m.lifecycle_mgr._detect_big_blind = AsyncMock()
        m.initial_chips = 1000
        m.state.total_chips = 1400  # 盈利 400 < 600
        assert await m.lifecycle_mgr.check_exit_conditions() is False

    @pytest.mark.asyncio
    async def test_low_chips_triggers_exit_when_sitting(self):
        """筹码 < low_chips_bb(10) * big_blind(2)=20 且已入座时触发。"""
        m = make_manager()
        m.lifecycle_mgr._detect_big_blind = AsyncMock()
        m.initial_chips = 200
        m.state.total_chips = 15    # < 20
        m.is_sitting = True
        assert await m.lifecycle_mgr.check_exit_conditions() is True

    @pytest.mark.asyncio
    async def test_low_chips_no_exit_when_not_sitting(self):
        """筹码少但未入座不触发。"""
        m = make_manager()
        m.lifecycle_mgr._detect_big_blind = AsyncMock()
        m.initial_chips = 200
        m.state.total_chips = 5
        m.is_sitting = False
        assert await m.lifecycle_mgr.check_exit_conditions() is False

    @pytest.mark.asyncio
    async def test_high_stakes_table_uses_bigger_bb(self):
        """5/10 桌， big_blind=10，stop_loss = 10*100 = 1000。"""
        m = make_manager()
        m.lifecycle_mgr._detect_big_blind = AsyncMock()
        m.big_blind = 10  # 5/10 桌
        m.initial_chips = 5000
        m.state.total_chips = 3999  # 亏损 1001 > 1000
        assert await m.lifecycle_mgr.check_exit_conditions() is True

    @pytest.mark.asyncio
    async def test_normal_range_no_exit(self):
        """正常波动不触发。"""
        m = make_manager()
        m.lifecycle_mgr._detect_big_blind = AsyncMock()
        m.initial_chips = 1000
        m.state.total_chips = 1050
        assert await m.lifecycle_mgr.check_exit_conditions() is False


# ─── full_table 满员计数与退桌 ─────────────────────────────────────────────────

class TestFullTableBehavior:

    def test_full_table_counter_initializes_to_zero(self):
        """满员计数器初始值应为 0。"""
        m = make_manager()
        assert m._full_table_ticks == 0

    def test_full_table_limit_default(self):
        """默认满员上限应为 5 次。"""
        m = make_manager()
        assert m._FULL_TABLE_LIMIT == 5

    @pytest.mark.asyncio
    async def test_full_table_counter_increments_on_failed_sit(self):
        """入座失败时满员计数器应递增。"""
        m = make_manager()
        m.is_sitting = False
        m.initial_chips = 1000
        m.state.total_chips = 1000

        # mock：play_mgr 返回决策，try_sit_and_buyin 返回 False，其他方法正常
        m.play_mgr.request_decision = MagicMock(return_value={"is_passive": False, "my_action": ""})
        m.update_state_from_dom = AsyncMock()
        m.lifecycle_mgr.try_sit_and_buyin = AsyncMock(return_value=False)
        m.lifecycle_mgr.check_exit_conditions = AsyncMock(return_value=False)
        m.lifecycle_mgr.check_overlays = AsyncMock()

        await m.execute_turn()
        assert m._full_table_ticks == 1

    @pytest.mark.asyncio
    async def test_full_table_triggers_leave_at_limit(self):
        """满员计数达到上限时应调用 leave_table。"""
        m = make_manager()
        m.is_sitting = False
        m.initial_chips = 1000
        m.state.total_chips = 1000
        m._full_table_ticks = m._FULL_TABLE_LIMIT - 1  # 已经 4 次了

        m.play_mgr.request_decision = MagicMock(return_value={"is_passive": False, "my_action": ""})
        m.update_state_from_dom = AsyncMock()
        m.lifecycle_mgr.try_sit_and_buyin = AsyncMock(return_value=False)
        m.lifecycle_mgr.check_exit_conditions = AsyncMock(return_value=False)
        m.lifecycle_mgr.check_overlays = AsyncMock()
        m.lifecycle_mgr.leave_table = AsyncMock()

        await m.execute_turn()
        m.lifecycle_mgr.leave_table.assert_called_once()

    @pytest.mark.asyncio
    async def test_successful_sit_resets_counter(self):
        """入座成功后满员计数器应重置为 0。"""
        m = make_manager()
        m.is_sitting = False
        m._full_table_ticks = 3  # 已有计数
        m.initial_chips = 1000
        m.state.total_chips = 1000

        m.play_mgr.request_decision = MagicMock(return_value={"is_passive": False, "my_action": ""})
        m.update_state_from_dom = AsyncMock()
        m.lifecycle_mgr.try_sit_and_buyin = AsyncMock(return_value=True)  # 入座成功
        m.lifecycle_mgr.check_exit_conditions = AsyncMock(return_value=False)
        m.lifecycle_mgr.check_overlays = AsyncMock()
        m.state.available_actions = []  # 无行动，不执行决策

        await m.execute_turn()
        assert m._full_table_ticks == 0


# ─── settings username ─────────────────────────────────────────────────────────

class TestSettingsUsername:

    def test_reads_username_from_config(self, tmp_path):
        """从配置文件中正确读取 username。"""
        m = make_manager()
        m.settings = {"player": {"username": "zyxdtk"}}
        username = m.settings.get("player", {}).get("username", "")
        assert username == "zyxdtk"

    def test_returns_empty_string_when_no_config(self):
        """配置未加载时应返回空字符串。"""
        m = make_manager()
        m.settings = {}
        username = m.settings.get("player", {}).get("username", "")
        assert username == ""

    def test_returns_empty_string_when_player_section_missing(self, tmp_path):
        """配置文件中无 player 段时返回空字符串。"""
        m = make_manager()
        m.settings = {"game": {"max_tables": 1}}
        username = m.settings.get("player", {}).get("username", "")
        assert username == ""


# ─── leave_table 离桌流程 ─────────────────────────────────────────────────────

class TestLeaveTable:

    def _make_mock_locator(self, count=1, visible=True):
        """构造一个模拟 Playwright Locator。"""
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=count)
        loc.is_visible = AsyncMock(return_value=visible)
        loc.click = AsyncMock()
        loc.first = loc
        return loc

    def _setup_leave_mocks(self, m, stand_count=1, leave_count=1, confirm_count=0):
        """设置 leave_table 需要的 mock locators。"""
        stand_btn = self._make_mock_locator(count=stand_count, visible=stand_count > 0)
        leave_btn = self._make_mock_locator(count=leave_count, visible=leave_count > 0)
        confirm_btn = self._make_mock_locator(count=confirm_count, visible=confirm_count > 0)

        def get_by_role_side_effect(role, name=None):
            if isinstance(name, type(re.compile(""))):
                pattern = name.pattern.lower()
                if "stand" in pattern or "站起" in pattern:
                    return stand_btn
                elif "leave" in pattern and "table" not in pattern and "确认" not in pattern:
                    return leave_btn
                elif "leave table" in pattern or "确认离开" in pattern:
                    return confirm_btn
            return self._make_mock_locator(count=0)

        m.page.get_by_role = MagicMock(side_effect=get_by_role_side_effect)
        m.page.is_closed = MagicMock(return_value=True)  # 避免实际关闭
        return stand_btn, leave_btn, confirm_btn

    @pytest.mark.asyncio
    async def test_stand_up_then_leave(self):
        """正常流程：先 Stand Up，再点 Leave（navigate_to_lobby=False）。"""
        m = make_manager()
        stand_btn, leave_btn, _ = self._setup_leave_mocks(m, stand_count=1, leave_count=1)

        await m.lifecycle_mgr.leave_table(navigate_to_lobby=False)

        stand_btn.click.assert_called()
        leave_btn.click.assert_called()
        assert m.is_closed is True
        assert m.exit_requested is True

    @pytest.mark.asyncio
    async def test_leave_without_stand_up_when_not_sitting(self):
        """Stand Up 按钮不存在时，直接尝试 Leave（navigate_to_lobby=False）。"""
        m = make_manager()
        stand_btn, leave_btn, _ = self._setup_leave_mocks(m, stand_count=0, leave_count=1)

        await m.lifecycle_mgr.leave_table(navigate_to_lobby=False)

        stand_btn.click.assert_not_called()
        leave_btn.click.assert_called()
        assert m.is_closed is True

    @pytest.mark.asyncio
    async def test_falls_back_to_page_close_when_leave_missing(self):
        """Leave 按钮也不存在时，直接 page.close()（navigate_to_lobby=False）。"""
        m = make_manager()
        m.page.close = AsyncMock()

        self._setup_leave_mocks(m, stand_count=0, leave_count=0)
        m.page.is_closed = MagicMock(return_value=False)  # 覆盖 setup 中的值

        await m.lifecycle_mgr.leave_table(navigate_to_lobby=False)

        m.page.close.assert_called_once()
        assert m.is_closed is True

    @pytest.mark.asyncio
    async def test_is_closed_set_even_on_exception(self):
        """即使 leave 过程抛出异常，is_closed 也必须被设置为 True。"""
        m = make_manager()
        m.page.get_by_role = MagicMock(side_effect=Exception("network error"))
        m.page.close = AsyncMock()

        await m.lifecycle_mgr.leave_table()

        assert m.is_closed is True
        assert m.exit_requested is True


# ─── end_to_end 完整流程测试 ───────────────────────────────────────────────────

class TestEndToEndFlow:
    """
    端到端测试：模拟完整的牌桌游戏流程。
    
    测试场景：
    1. 打开浏览器进入牌桌
    2. 找到空位并坐下
    3. 确认买入
    4. 使用 checkorfold 策略玩一局
    5. 执行动作（check/fold）
    6. 离开牌桌
    """

    def _make_mock_locator(self, count=1, visible=True, text_content=""):
        """构造一个模拟 Playwright Locator。"""
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=count)
        loc.is_visible = AsyncMock(return_value=visible)
        loc.click = AsyncMock()
        loc.text_content = AsyncMock(return_value=text_content)
        loc.first = loc
        loc.nth = MagicMock(return_value=loc)
        loc.locator = MagicMock(return_value=loc)
        return loc

    def _setup_e2e_mocks(self, m):
        """设置端到端测试需要的 mock locators。"""
        # 各种按钮
        seat_any_btn = self._make_mock_locator(count=1, visible=True)
        empty_seat = self._make_mock_locator(count=1, visible=True)
        confirm_btn = self._make_mock_locator(count=1, visible=True)
        stand_btn = self._make_mock_locator(count=1, visible=True)
        leave_btn = self._make_mock_locator(count=1, visible=True)
        
        # 筹码和底池显示
        chips_display = self._make_mock_locator(count=1, visible=True, text_content="1000")
        pot_elem = self._make_mock_locator(count=1, visible=True, text_content="20")
        
        # 座位相关
        seat_users = self._make_mock_locator(count=1, visible=True, text_content="testplayer")

        # 动作按钮
        fold_btn = self._make_mock_locator(count=1, visible=True, text_content="Fold")
        check_btn = self._make_mock_locator(count=1, visible=True, text_content="Check")
        
        # 输入框
        buyin_input = self._make_mock_locator(count=1, visible=True)
        buyin_input.input_value = AsyncMock(return_value="1000")

        # 模态框（买入对话框）
        modal_overlay = self._make_mock_locator(count=1, visible=True)

        # 设置 page.locator 的 side_effect
        def locator_side_effect(selector):
            if "Seat--empty" in selector or "Seat--open" in selector:
                return empty_seat
            elif "WaitingListControls" in selector:
                return self._make_mock_locator(count=0)
            elif "ModalOverlay" in selector or "modal" in selector:
                return modal_overlay
            elif "BuyIn" in selector or "chips-display" in selector:
                return chips_display
            elif "Pot__value" in selector:
                return pot_elem
            elif "Seat__username" in selector:
                return seat_users
            elif "Stack__value" in selector or "Seat__stack" in selector:
                return chips_display
            elif "input[type='number']" in selector:
                return buyin_input
            return self._make_mock_locator(count=0)
        
        m.page.locator = MagicMock(side_effect=locator_side_effect)
        
        # 设置 page.get_by_role 的 side_effect
        def get_by_role_side_effect(role, name=None):
            if isinstance(name, type(re.compile(""))):
                pattern = name.pattern.lower()
                if "seat me anywhere" in pattern:
                    return seat_any_btn
                elif "confirm" in pattern or "ok" in pattern or "buy" in pattern:
                    return confirm_btn
                elif "stand" in pattern or "站起" in pattern:
                    return stand_btn
                elif "leave" in pattern and "table" not in pattern and "确认" not in pattern:
                    return leave_btn
                elif "fold" in pattern:
                    return fold_btn
                elif "check" in pattern:
                    return check_btn
            elif isinstance(name, str):
                name_lower = name.lower()
                if "seat me anywhere" in name_lower:
                    return seat_any_btn
                elif "confirm" in name_lower or "ok" in name_lower:
                    return confirm_btn
                elif "stand" in name_lower:
                    return stand_btn
                elif "leave" in name_lower:
                    return leave_btn
                elif "fold" in name_lower:
                    return fold_btn
                elif "check" in name_lower:
                    return check_btn
            return self._make_mock_locator(count=0)
        
        m.page.get_by_role = MagicMock(side_effect=get_by_role_side_effect)
        m.page.is_closed = MagicMock(return_value=True)
        m.page.close = AsyncMock()
        
        return {
            "seat_any": seat_any_btn,
            "empty_seat": empty_seat,
            "confirm": confirm_btn,
            "stand": stand_btn,
            "leave": leave_btn,
            "fold": fold_btn,
            "check": check_btn,
            "chips": chips_display,
            "pot": pot_elem,
        }

    @pytest.mark.asyncio
    async def test_e2e_sit_buyin_play_one_hand_and_leave(self):
        """
        端到端测试：坐下 -> 买入 -> 玩一局 -> 离开。

        验证：
        1. 成功入座（is_sitting = True）
        2. 买入成功（total_buyin > 0）
        3. 执行了至少一个动作
        4. 成功离桌（is_closed = True）
        """
        m = make_manager(strategy_type="checkorfold")
        m.settings = {"player": {"username": "testplayer"}}

        mocks = self._setup_e2e_mocks(m)

        # 步骤 1: 尝试入座和买入
        # 注意：这里需要确保 _find_my_seat 返回 None 才能触发买入流程
        # 我们覆盖 mock 让 _find_my_seat 先返回 None，买入后再返回 seat
        m.lifecycle_mgr._find_my_seat = AsyncMock(return_value=None)

        result = await m.lifecycle_mgr.try_sit_and_buyin()
        assert result is True, "应该成功入座"
        assert m.is_sitting is True, "is_sitting 应该为 True"
        assert m.total_buyin > 0, "应该有买入金额"

        # 验证点击了确认按钮
        mocks["confirm"].click.assert_called()

        # 步骤 2: 模拟一局游戏 - 更新状态
        # 设置游戏状态：有可用动作
        m.state.available_actions = ["fold", "check"]
        m.state.to_call = 0
        m.state.pot = 20
        m.state.my_seat_id = 1

        # 模拟玩家已在座位上
        m.initial_chips = 1000
        m.state.total_chips = 1000

        # 步骤 3: 执行决策 - 使用 checkorfold 策略
        m.play_mgr.ensure_brain_exists("checkorfold")
        decision = m.play_mgr.request_decision()

        # 验证决策是 checkorfold 策略的决策
        assert decision is not None, "应该得到决策"
        decision_obj = decision.get("decision", {})
        action = decision_obj.get("action", "")
        assert action in ["CHECK", "FOLD"], f"应该是 CHECK 或 FOLD 动作，实际是 {action}"

        # 步骤 4: 执行动作
        action_executed = False
        if "check" in m.state.available_actions:
            await mocks["check"].click()
            action_executed = True
        elif "fold" in m.state.available_actions:
            await mocks["fold"].click()
            action_executed = True

        assert action_executed, "应该执行了动作"

        # 步骤 5: 离开牌桌（使用 navigate_to_lobby=False 测试旧行为）
        await m.lifecycle_mgr.leave_table(navigate_to_lobby=False)

        # 验证离桌流程
        mocks["stand"].click.assert_called()
        mocks["leave"].click.assert_called()
        assert m.is_closed is True, "应该已关闭"
        assert m.exit_requested is True, "应该已请求退出"

    @pytest.mark.asyncio
    async def test_e2e_full_table_then_leave(self):
        """
        端到端测试：满员 -> 尝试入座失败 -> 离开找新桌。
        """
        m = make_manager(strategy_type="checkorfold")
        
        # 模拟满员状态
        waiting_list_btn = self._make_mock_locator(count=1, visible=True)
        
        def locator_side_effect(selector):
            if "WaitingListControls" in selector:
                return waiting_list_btn
            return self._make_mock_locator(count=0)
        
        m.page.locator = MagicMock(side_effect=locator_side_effect)
        m.page.get_by_role = MagicMock(return_value=self._make_mock_locator(count=0))
        m.page.close = AsyncMock()
        m.page.is_closed = MagicMock(return_value=True)
        
        # 尝试入座
        result = await m.lifecycle_mgr.try_sit_and_buyin()
        
        # 满员时应该返回 False
        assert result is False, "满员时应该返回 False"
        assert m.lifecycle_mgr._table_full is True, "应该标记为满员"

    @pytest.mark.asyncio
    async def test_e2e_strategy_check_or_fold_consistency(self):
        """
        验证 checkorfold 策略的一致性：
        无论调用多少次，都应该返回 check 或 fold 动作。
        """
        from src.engine.strategies import CheckOrFoldBrain
        from src.core.game_state import GameState
        
        # 创建策略实例
        strategy = CheckOrFoldBrain()
        
        # 创建游戏状态
        state = GameState()
        state.pot = 100
        state.to_call = 20
        state.available_actions = ["fold", "check", "call", "raise"]
        
        # 多次调用策略
        for _ in range(10):
            plan = strategy.create_initial_plan(state)
            assert plan.primary_action.value in ["CHECK", "FOLD"], \
                f"checkorfold 策略应该只返回 CHECK 或 FOLD，但返回了 {plan.primary_action.value}"
            assert plan.fallback_action.value in ["CHECK", "FOLD"], \
                f"fallback 也应该是 CHECK 或 FOLD，但返回了 {plan.fallback_action.value}"
        
        # 验证 update_plan 和 deep_think 也保持一致
        plan1 = strategy.create_initial_plan(state)
        plan2 = strategy.update_plan(state)
        plan3 = strategy.deep_think(state)
        
        assert plan1.primary_action == plan2.primary_action == plan3.primary_action, \
            "所有方法应该返回一致的动作"
