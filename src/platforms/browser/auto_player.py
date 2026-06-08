"""
自动游戏循环编排器
结合 BrowserPlatform 的所有能力，实现全自动扑克游戏
"""
import os
import yaml
from typing import Optional

from .browser_platform import BrowserPlatform, BrowserPlatformConfig
from .exit_checker import ExitChecker
from .human_delay import human_delay
from ...core.interfaces import GameAction, ActionType
from ...strategies.strategy_manager import StrategyManager
from ...strategies.game_state import GameState as PokerGameState
from ...strategies.table_strategy import DefaultTableStrategy, TableState, TableActionType
from ...utils.logger import bot_logger


class BrowserAutoPlayer:
    """
    自动游戏循环编排器

    核心循环：
    1. _dismiss_overlays()    — 清除弹窗
    2. _check_and_sit_in()    — 确保已入座
    3. _ensure_ws_alive()     — 确保 WS 连接
    4. update_state()         — 获取状态
    5. if is_my_turn:
            action = strategy.make_decision(state)
            execute_action(action)
            human_delay("action")
    6. if exit_checker.should_exit(...):
            break
    7. human_delay("poll")    — 轮询间隔
    """

    def __init__(
        self,
        platform: BrowserPlatform,
        strategy_type: str = "gto",
        buyin_amount: Optional[int] = None,
    ):
        self.platform = platform
        self.strategy_type = strategy_type
        self.buyin_amount = buyin_amount

        # 加载配置
        self._config = self._load_config()
        self._poll_interval = self._config.get("poll_interval", 1.0)

        # 退出检查器
        config_obj = platform.config
        self.exit_checker = ExitChecker(
            stop_loss_bb=config_obj.stop_loss_bb,
            take_profit_bb=config_obj.take_profit_bb,
            low_chips_bb=config_obj.low_chips_bb,
            max_chips_bb=config_obj.max_chips_bb,
        )

        # 策略管理器
        self._strategy_mgr = StrategyManager()
        self._strategy = None

        # 桌位策略（管理 ADD_CHIPS / SIT_OUT 等桌位级别决策）
        self._table_strategy = DefaultTableStrategy()
        self._last_table_action = None  # 避免重复执行同一桌位动作

        # 状态
        self._running = False
        self._initial_chips: Optional[int] = None
        self._current_table_id: Optional[str] = None
        self._hands_played = 0
        self._dealer_cycles = 0
        self._last_hand_id = 0

    def _load_config(self) -> dict:
        """加载自动模式配置"""
        config_path = os.path.join(os.getcwd(), "config", "settings.yaml")
        if not os.path.exists(config_path):
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data.get("auto_mode", {})
        except Exception:
            return {}

    async def run(self):
        """启动自动游戏循环"""
        self._running = True
        bot_logger.info("=== 自动游戏模式启动 ===")

        try:
            # 1. 初始化平台
            if not self.platform._is_initialized:
                await self.platform.initialize()

            # 2. 确保已登录
            logged_in = await self.platform.ensure_logged_in()
            if not logged_in:
                bot_logger.error("登录失败，退出自动模式")
                return

            # 3. 打开牌桌
            self._current_table_id = await self.platform.open_table()
            if not self._current_table_id:
                bot_logger.error("无可用桌子，退出自动模式")
                return

            # 4. 创建策略实例
            self._strategy = self._strategy_mgr.create_strategy(
                self._current_table_id, self.strategy_type
            )
            if not self._strategy:
                bot_logger.warning(f"策略 '{self.strategy_type}' 创建失败，使用 balanced")
                self._strategy = self._strategy_mgr.create_strategy(
                    self._current_table_id, "balanced"
                )
            if self._strategy:
                bot_logger.info(f"策略已创建: {self._strategy.strategy_name}")
            else:
                bot_logger.error("策略创建失败，退出自动模式")
                return

            # 5. 尝试入座
            await human_delay("action")
            await self.platform._check_and_sit_in(
                self._current_table_id, self.buyin_amount
            )

            # 6. 主循环
            await self._game_loop()

        except KeyboardInterrupt:
            bot_logger.info("用户中断，退出自动模式")
        except Exception as e:
            bot_logger.error(f"自动模式异常: {e}", exc_info=True)
        finally:
            self._running = False
            await self._print_summary()
            await self.platform.shutdown()

    async def _game_loop(self):
        """主游戏循环"""
        while self._running:
            try:
                # 清除弹窗
                await self.platform._dismiss_overlays(self._current_table_id)

                # 确保已入座
                await self.platform._check_and_sit_in(
                    self._current_table_id, self.buyin_amount
                )

                # 确保 WS 连接
                await self.platform._ensure_ws_alive(self._current_table_id)

                # 获取状态
                state = await self.platform.get_game_state(self._current_table_id)

                # 记录初始筹码
                if self._initial_chips is None and state.my_seat_id is not None:
                    my_player = state.players.get(state.my_seat_id)
                    if my_player and my_player.chips > 0:
                        self._initial_chips = my_player.chips
                        bot_logger.info(f"初始筹码记录: {self._initial_chips}")

                # 追踪手数
                self._track_hands(state)

                # 桌位级别策略检查（补筹/sit out/sit in）
                table_action = self._decide_table_action(state)
                if table_action:
                    await human_delay("action")
                    continue

                # 获取可用动作
                actions = await self.platform.get_available_actions(self._current_table_id)

                if actions.get("available"):
                    # 策略决策
                    await self._make_decision(state, actions)
                    await human_delay("action")
                else:
                    # 不是我的回合，轮询间隔
                    await human_delay("poll")

                # 退出条件检查
                exit_reason = self._check_exit(state)
                if exit_reason:
                    bot_logger.info(f"退出条件触发: {exit_reason}")
                    break

            except Exception as e:
                bot_logger.error(f"游戏循环异常: {e}", exc_info=True)
                await human_delay("poll")

    def _build_table_state(self, state: PokerGameState) -> TableState:
        """从 PokerGameState 构建桌位状态"""
        ws_state = {}
        if self.platform._state_manager:
            ws_state = self.platform._state_manager.ws_listener.get_state()

        big_blind = ws_state.get("big_blind", 0)
        if big_blind <= 0:
            stakes = self.platform.config.preferred_stakes or "1/2"
            try:
                big_blind = int(stakes.split("/")[1])
            except (IndexError, ValueError):
                big_blind = 2

        my_player = state.players.get(state.my_seat_id) if state.my_seat_id is not None else None
        my_chips = my_player.chips if my_player else 0
        is_seated = state.my_seat_id is not None
        is_playing = is_seated and my_player is not None and my_player.status != "sitting_out"

        # 计算盈利
        total_profit = 0
        if self._initial_chips is not None:
            total_profit = my_chips - self._initial_chips

        # 统计桌上活跃人数
        active_count = sum(1 for p in state.players.values() if p.status != "sitting_out")
        seat_count = len(state.players)

        return TableState(
            my_chips=my_chips,
            is_seated=is_seated,
            is_playing=is_playing,
            hands_played=self._hands_played,
            total_profit=total_profit,
            current_bb=big_blind,
            seat_count=seat_count,
            active_count=active_count,
            stop_loss_bb=self.exit_checker.stop_loss_bb or 250,
            take_profit_bb=self.exit_checker.take_profit_bb or 300,
            low_chips_bb=self.exit_checker.low_chips_bb or 10,
            max_chips_bb=self.exit_checker.max_chips_bb or 800,
        )

    async def _decide_table_action(self, state: PokerGameState) -> bool:
        """桌位级别策略决策（补筹/sit out 等），返回 True 表示已执行动作"""
        table_state = self._build_table_state(state)
        action = self._table_strategy.decide(table_state)

        if action.action_type == TableActionType.NONE:
            self._last_table_action = None
            return False

        # 避免重复执行同一动作（仅成功后记录，失败允许重试）
        action_key = f"{action.action_type.value}:{action.amount}"
        if action_key == self._last_table_action:
            return False

        bot_logger.info(f"桌位决策: {action.reasoning}")

        if action.action_type == TableActionType.ADD_CHIPS:
            success = await self.platform.add_chips(
                amount=action.amount, table_id=self._current_table_id
            )
            if success:
                self._last_table_action = action_key
                bot_logger.info(f"补筹成功: +{action.amount}")
            else:
                bot_logger.warning("补筹失败，下轮将重试")
            return success

        elif action.action_type == TableActionType.SIT_OUT:
            success = await self.platform.sit_out(self._current_table_id)
            if success:
                self._last_table_action = action_key
            return success

        elif action.action_type == TableActionType.SIT_IN:
            success = await self.platform.sit_in(self._current_table_id)
            if success:
                self._last_table_action = action_key
            return success

        elif action.action_type == TableActionType.LEAVE:
            bot_logger.info(f"桌位策略要求离场: {action.reasoning}")
            self._running = False
            return True

        return False

    async def _make_decision(self, state: PokerGameState, actions: dict):
        """策略决策 + 执行动作"""
        if not self._strategy:
            return

        try:
            # 调用策略的 make_decision
            action_plan = self._strategy.make_decision(state)
            if not action_plan:
                bot_logger.debug("策略返回空 ActionPlan")
                return

            # 解析动作
            to_call = actions.get("to_call", 0)
            min_raise = actions.get("min_raise", 0)
            pot = state.pot

            # 使用 ActionPlan 的 get_action_for_bet 解析最终动作
            final_action, amount = action_plan.get_action_for_bet(to_call, pot)

            # 映射到核心 ActionType
            action_map = {
                "fold": ActionType.FOLD,
                "check": ActionType.CHECK,
                "call": ActionType.CALL,
                "raise": ActionType.RAISE,
                "all_in": ActionType.ALL_IN,
            }

            action_type = action_map.get(final_action, ActionType.FOLD)

            # 检查动作是否在可用列表中
            available = actions.get("available", [])
            action_name = action_type.value

            # 适配: core 的 CHECK 对应 DOM 的 check，RAISE 对应 raise/bet
            if action_type == ActionType.RAISE and "raise" not in available and "bet" in available:
                action_name = "bet"
            elif action_type == ActionType.CHECK and "check" not in available and "call" in available:
                action_type = ActionType.CALL
                action_name = "call"
                amount = to_call

            game_action = GameAction(action_type=action_type, amount=amount)

            bot_logger.info(
                f"决策: {action_plan.reasoning} -> {action_name}"
                f"{f' {amount}' if amount else ''}"
                f" (策略: {action_plan.strategy_name})"
            )

            success = await self.platform.execute_action(game_action, self._current_table_id)
            if not success:
                bot_logger.warning(f"动作执行失败: {action_name}")

        except Exception as e:
            bot_logger.error(f"决策异常: {e}", exc_info=True)

    def _track_hands(self, state: PokerGameState):
        """追踪手数和轮次"""
        # 通过 hand_id 变化追踪新手牌
        ws_state = {}
        if self.platform._state_manager:
            ws_state = self.platform._state_manager.ws_listener.get_state()

        hand_id = ws_state.get("hand_id", 0)
        if hand_id != self._last_hand_id and hand_id > 0:
            if self._last_hand_id > 0:
                self._hands_played += 1
                # 输出 VPIP/PFR 统计
                vpip_tracker = ws_state.get("vpip_tracker", {})
                if vpip_tracker:
                    my_user_id = ws_state.get("my_user_id")
                    if my_user_id and my_user_id in vpip_tracker:
                        stats = vpip_tracker[my_user_id]
                        bot_logger.info(
                            f"手数 #{self._hands_played} | "
                            f"VPIP: {stats['vpip_count']}/{stats['hands']} "
                            f"({stats['vpip_count']/max(stats['hands'],1)*100:.0f}%) | "
                            f"PFR: {stats['pfr_count']}/{stats['hands']} "
                            f"({stats['pfr_count']/max(stats['hands'],1)*100:.0f}%)"
                        )
            self._last_hand_id = hand_id

    def _check_exit(self, state: PokerGameState) -> Optional[str]:
        """检查退出条件"""
        if self._initial_chips is None:
            return None

        # 获取当前筹码
        my_player = state.players.get(state.my_seat_id)
        if not my_player or my_player.chips <= 0:
            return None

        # 获取大盲注
        ws_state = {}
        if self.platform._state_manager:
            ws_state = self.platform._state_manager.ws_listener.get_state()
        big_blind = ws_state.get("big_blind", 0)
        if big_blind <= 0:
            # 从配置的 preferred_stakes 解析
            stakes = self.platform.config.preferred_stakes or "1/2"
            try:
                big_blind = int(stakes.split("/")[1])
            except (IndexError, ValueError):
                big_blind = 2

        return self.exit_checker.should_exit(
            current_chips=my_player.chips,
            buy_in=self.buyin_amount or self._initial_chips,
            big_blind=big_blind,
            initial_chips=self._initial_chips,
        )

    async def _print_summary(self):
        """打印运行摘要"""
        bot_logger.info(
            f"=== 自动模式结束 ===\n"
            f"  手数: {self._hands_played}\n"
            f"  初始筹码: {self._initial_chips or '未知'}\n"
            f"  策略: {self._strategy.strategy_name if self._strategy else '未知'}"
        )

    def stop(self):
        """停止自动游戏循环"""
        self._running = False
        bot_logger.info("自动模式停止请求已发送")
