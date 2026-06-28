"""
自动游戏循环编排器
结合 BrowserPlatform 的所有能力，实现全自动扑克游戏

支持三种 pilot 模式：
- AUTO: AI 全自主，异常退出提示人类
- MANAGED: AI 自主运行 + 人类可通过 stdin 打断/接管
- ASSIST: AI 建议动作 + 人类确认/覆盖
"""
import asyncio
import os
import yaml
from typing import Optional, Union

from .browser_platform import BrowserPlatform, BrowserPlatformConfig
from .exit_checker import ExitChecker
from .human_delay import human_delay
from ...core.interfaces import GameAction, ActionType
from ...core.pilot_decider import PilotDecider
from ...core.payload import browser_state_to_payload
from ...strategies.strategy_base import Strategy
from ...strategies.strategy_manager import StrategyManager
from ...strategies.game_state import GameState as PokerGameState
from ...strategies.table_strategy import DefaultTableStrategy, TableState, TableActionType
from ...utils.logger import bot_logger, brain_logger
from ...utils.cli_player import PilotMode, StdinMonitor, ActionChoice
from .snapshot import save_anomaly_snapshot


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
        buyin_amount: Optional[Union[int, str]] = None,
        pilot_mode: PilotMode = PilotMode.AUTO,
    ):
        self.platform = platform
        self.strategy_type = strategy_type
        self.buyin_amount = buyin_amount
        self.pilot_mode = pilot_mode

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
        self._start_time: Optional[float] = None
        self._current_table_id: Optional[str] = None
        self._hands_played = 0
        self._dealer_cycles = 0
        self._last_hand_id = 0

        # Pilot 模式相关
        self._stdin_monitor: Optional[StdinMonitor] = None
        self._override_action = None  # managed 模式下的人类覆盖动作 (action_str, amount_parts)
        self._pilot_decider: Optional[PilotDecider] = None  # 创建策略后初始化

        # 日志追踪
        self._loop_count = 0
        self._last_logged_stage = ""      # 上次记录的街道（避免重复日志）
        self._last_logged_hand_id = 0     # 上次记录的手牌 ID
        self._last_logged_my_turn = False  # 上次记录的 is_my_turn
        self._action_count = 0            # 本手牌执行动作计数

        # 动作失败退避：连续失败时指数退避，避免无意义重试刷屏
        self._consecutive_action_failures = 0
        self._max_action_failures = 5     # 超过此值后跳过本手等待下一手

        # 卡住检测 / 换桌
        self._stuck_counter = 0           # 连续"未入座且无动作"的轮数
        self._stuck_threshold = int(self._config.get("stuck_threshold", 30))  # 触发换桌的阈值
        self._consecutive_switches = 0    # 连续换桌次数（成功入座后重置）
        self._max_consecutive_switches = int(self._config.get("max_table_switches", 5))

        # 手牌历史记录器
        hh_cfg = self._config.get("hand_history", {}) or {}
        self._hand_history_enabled = bool(hh_cfg.get("enabled", False))
        self._hand_recorder = None

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
        import time
        self._start_time = time.time()
        bot_logger.info(
            f"=== 自动游戏模式启动 (pilot={self.pilot_mode.value}) ===\n"
            f"  策略: {self.strategy_type}\n"
            f"  买入: {self.buyin_amount or '默认'}\n"
            f"  退出阈值: stop_loss={self.exit_checker.stop_loss_bb}BB "
            f"take_profit={self.exit_checker.take_profit_bb}BB "
            f"low_chips={self.exit_checker.low_chips_bb}BB "
            f"max_chips={self.exit_checker.max_chips_bb}BB"
        )

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

            # 4b. 创建 PilotDecider
            self._pilot_decider = PilotDecider(
                strategy=self._strategy,
                pilot_mode=self.pilot_mode,
                table_strategy=self._table_strategy,
            )

            # 5. 尝试入座
            await human_delay("action")
            await self.platform._check_and_sit_in(
                self._current_table_id, self.buyin_amount
            )

            # 5b. 初始化手牌历史记录器
            if self._hand_history_enabled:
                from .hand_recorder import HandRecorder, HandHistoryStore
                try:
                    store = HandHistoryStore()
                    self._hand_recorder = HandRecorder(store, self._current_table_id)
                    if self.platform._state_manager and self.platform._state_manager.ws_listener:
                        self.platform._state_manager.ws_listener.register_update_callback(
                            self._hand_recorder.on_ws_update
                        )
                    bot_logger.info("手牌历史记录器已启动")
                except Exception as e:
                    bot_logger.warning(f"手牌历史记录器初始化失败: {e}")
                    self._hand_recorder = None

            # 6. 启动 stdin 监控（managed/assist 模式）
            if self.pilot_mode in (PilotMode.MANAGED, PilotMode.ASSIST):
                self._stdin_monitor = StdinMonitor()
                await self._stdin_monitor.start()
                bot_logger.info("StdinMonitor 已启动，可输入命令 (pause/resume/takeover/status/help)")
                from rich.console import Console
                Console().print(
                    "[dim]输入 help 查看可用命令 | pause 暂停 | resume 恢复 | takeover 接管[/dim]"
                )

            # 7. 主循环
            await self._game_loop()

        except KeyboardInterrupt:
            bot_logger.info("用户中断，退出自动模式")
        except Exception as e:
            bot_logger.error(f"自动模式异常: {e}", exc_info=True)
        finally:
            self._running = False
            if self._hand_recorder:
                try:
                    self._hand_recorder.finalize_hand({})
                except Exception:
                    pass
            if self._stdin_monitor:
                await self._stdin_monitor.stop()
            await self._print_summary()
            await self.platform.shutdown()

    async def _game_loop(self):
        """主游戏循环（支持三种 pilot 模式）"""
        while self._running:
            try:
                self._loop_count += 1

                # 0. 检查页面是否仍然可用（浏览器关闭时优雅退出）
                page = self.platform._get_table_page(self._current_table_id)
                if not page or page.is_closed():
                    bot_logger.warning("[退出] 浏览器页面已关闭，退出游戏循环")
                    break

                # 1. 检查人类指令（managed/assist 模式）
                if self._stdin_monitor:
                    cmd = await self._stdin_monitor.get_command(timeout=0.01)
                    if cmd:
                        await self._handle_human_command(cmd)

                # 如果人类暂停了游戏，跳过本轮
                if self._stdin_monitor and self._stdin_monitor.is_paused:
                    await human_delay("poll")
                    continue

                # 清除弹窗
                await self.platform._dismiss_overlays(self._current_table_id)

                # 确保已入座
                sit_in_progress = await self.platform._check_and_sit_in(
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
                table_action = await self._decide_table_action(state)
                if table_action:
                    await human_delay("action")
                    continue

                # 获取可用动作
                actions = await self.platform.get_available_actions(self._current_table_id)

                # --- 日志：状态变化时输出摘要 ---
                self._log_state_change(state, actions)

                # ── 卡住检测：未入座且无可用动作 ──
                # 桌子满员/无法入座时，_check_and_sit_in 返回 False 且
                # state.my_seat_id 为 None、actions 为空。连续多轮如此则换桌。
                is_seated = state.my_seat_id is not None
                has_actions = bool(actions.get("available"))

                if not is_seated and not has_actions:
                    if sit_in_progress:
                        # 本轮有入座动作（点击了座位/弹窗），给时间让流程完成
                        self._stuck_counter = 0
                    else:
                        self._stuck_counter += 1
                        if self._stuck_counter % 10 == 1:
                            bot_logger.info(
                                f"[等待入座] 已等待 {self._stuck_counter} 轮 "
                                f"(threshold={self._stuck_threshold}, "
                                f"table={self._current_table_id})"
                            )
                        if self._stuck_counter >= self._stuck_threshold:
                            bot_logger.warning(
                                f"[卡住] 连续 {self._stuck_counter} 轮无法入座，"
                                f"桌子可能已满，尝试换桌"
                            )
                            switched = await self._switch_table()
                            self._stuck_counter = 0
                            if switched:
                                self._consecutive_switches += 1
                                if self._consecutive_switches >= self._max_consecutive_switches:
                                    bot_logger.warning(
                                        f"[换桌] 已连续换桌 {self._consecutive_switches} 次"
                                        f"仍无法入座，等待 60s 后重试"
                                    )
                                    await asyncio.sleep(60)
                                    self._consecutive_switches = 0
                            else:
                                bot_logger.warning("[换桌] 无可用桌子，等待 30s 后重试")
                                await asyncio.sleep(30)
                            continue
                else:
                    if self._stuck_counter > 0:
                        self._stuck_counter = 0
                    if self._consecutive_switches > 0 and is_seated:
                        bot_logger.info(
                            f"[恢复] 已成功入座，重置换桌计数 "
                            f"(was {self._consecutive_switches})"
                        )
                        self._consecutive_switches = 0

                if actions.get("available"):
                    # 连续失败退避：超过阈值后跳过本手，等待下一手重新开始
                    if self._consecutive_action_failures >= self._max_action_failures:
                        bot_logger.warning(
                            f"[退避] 连续动作失败 {self._consecutive_action_failures} 次，"
                            f"跳过本手等待下一手"
                        )
                        await asyncio.sleep(5)
                        continue

                    # 2. 决策：通过 PilotDecider 统一编排
                    payload = browser_state_to_payload(state, actions)
                    choice = await self._pilot_decider.decide_hand(
                        payload, prompt_prefix="poker",
                    )
                    game_action = self._choice_to_game_action(choice, actions, state)
                    if self._hand_recorder and self._hand_recorder.is_recording:
                        try:
                            street = state.current_stage or "preflop"
                            self._hand_recorder.record_decision(choice, street)
                        except Exception as e:
                            bot_logger.debug(f"手牌记录 decision 异常: {e}")
                    success = await self.platform.execute_action(game_action, self._current_table_id)

                    if success:
                        self._consecutive_action_failures = 0
                        await human_delay("action")
                    else:
                        self._consecutive_action_failures += 1
                        # 指数退避：1s, 2s, 4s, 8s（上限 8s）
                        backoff = min(8, 2 ** (self._consecutive_action_failures - 1))
                        bot_logger.debug(
                            f"[退避] 动作失败 {self._consecutive_action_failures} 次，"
                            f"等待 {backoff}s 后重试"
                        )
                        await asyncio.sleep(backoff)
                else:
                    # 不是我的回合，轮询间隔
                    await human_delay("poll")

                # 退出条件检查
                exit_reason = self._check_exit(state)
                if exit_reason:
                    bot_logger.info(f"退出条件触发: {exit_reason}")
                    break

            except Exception as e:
                # 浏览器/页面关闭时优雅退出，不刷屏
                err_msg = str(e)
                if "has been closed" in err_msg or "Target page" in err_msg:
                    bot_logger.warning(f"[退出] 浏览器或页面已关闭: {err_msg}")
                    break
                bot_logger.error(f"游戏循环异常 (loop#{self._loop_count}): {e}", exc_info=True)
                # 异常快照
                page = self.platform._get_table_page(self._current_table_id)
                if page:
                    await save_anomaly_snapshot(
                        page, "game_loop_error",
                        extra={"loop": self._loop_count, "error": err_msg},
                        table_id=self._current_table_id,
                    )
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
        is_playing = is_seated and my_player is not None and my_player.status != "sit_out"

        # 计算盈利
        total_profit = 0
        if self._initial_chips is not None:
            total_profit = my_chips - self._initial_chips

        # 统计桌上活跃人数
        active_count = sum(1 for p in state.players.values() if p.status != "sit_out")
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
        """桌位级别策略决策（补筹/sit out 等），通过 PilotDecider 统一编排"""
        if not self._pilot_decider:
            return False

        table_state_payload = self._build_table_state_payload(state)
        choice = await self._pilot_decider.decide_table(
            table_state_payload, prompt_prefix="poker", title="桌位状态",
        )

        if choice.action == "none":
            self._last_table_action = None
            return False

        # 避免重复执行同一动作
        action_key = f"{choice.action}:{choice.amount}"
        if action_key == self._last_table_action:
            return False

        bot_logger.info(f"桌位决策: {choice.reasoning or choice.action}")

        if choice.action == "add_chips":
            success = await self.platform.add_chips(
                amount=choice.amount, table_id=self._current_table_id
            )
            if success:
                self._last_table_action = action_key
                bot_logger.info(f"补筹成功: +{choice.amount}")
            else:
                bot_logger.warning("补筹失败，下轮将重试")
            return success

        elif choice.action == "sit_out":
            success = await self.platform.sit_out(self._current_table_id)
            if success:
                self._last_table_action = action_key
            return success

        elif choice.action == "sit_in":
            success = await self.platform.sit_in(self._current_table_id)
            if success:
                self._last_table_action = action_key
            return success

        elif choice.action == "leave":
            bot_logger.info(f"桌位策略要求离场: {choice.reasoning}")
            self._running = False
            return True

        return False

    async def _switch_table(self) -> bool:
        """离开当前桌子（已满/卡住），切换到新桌子

        流程：
        1. 离开旧桌子（关闭页面）
        2. 移除旧策略
        3. 重置桌位级状态（初始筹码、手数追踪等）
        4. 打开新桌子（select_best_table 会过滤已访问的）
        5. 创建新策略 + 重建 PilotDecider
        """
        old_table_id = self._current_table_id
        bot_logger.info(f"[换桌] 离开桌子 {old_table_id}（连续无法入座）")

        # 1. 离开旧桌子
        if old_table_id:
            try:
                await self.platform.leave_table(old_table_id)
            except Exception as e:
                bot_logger.warning(f"[换桌] 离开旧桌子异常: {e}")

        # 2. 移除旧策略
        if old_table_id:
            try:
                self._strategy_mgr.remove_strategy(old_table_id)
            except Exception:
                pass

        # 3. 重置桌位级状态
        self._initial_chips = None
        # 丢弃未完成的手牌记录（换桌中途无法知道结果）
        if self._hand_recorder:
            try:
                self._hand_recorder.abort()
            except Exception:
                pass
        self._last_hand_id = 0
        self._last_logged_stage = ""
        self._last_logged_my_turn = False
        self._action_count = 0
        self._consecutive_action_failures = 0

        # 4. 打开新桌子
        new_table_id = await self.platform.open_table()
        if not new_table_id:
            bot_logger.error("[换桌] 没有可用桌子")
            self._current_table_id = None
            return False

        self._current_table_id = new_table_id

        # 5. 创建新策略
        self._strategy = self._strategy_mgr.create_strategy(
            new_table_id, self.strategy_type
        )
        if not self._strategy:
            bot_logger.warning(
                f"[换桌] 策略 '{self.strategy_type}' 创建失败，使用 balanced"
            )
            self._strategy = self._strategy_mgr.create_strategy(
                new_table_id, "balanced"
            )

        # 6. 重建 PilotDecider
        if self._strategy:
            self._pilot_decider = PilotDecider(
                strategy=self._strategy,
                pilot_mode=self.pilot_mode,
                table_strategy=self._table_strategy,
            )
            bot_logger.info(
                f"[换桌] 已切换到 {new_table_id}, "
                f"策略={self._strategy.strategy_name}"
            )
            # 为新桌子重建手牌记录器
            if self._hand_history_enabled:
                from .hand_recorder import HandRecorder, HandHistoryStore
                try:
                    store = HandHistoryStore()
                    self._hand_recorder = HandRecorder(store, new_table_id)
                    if self.platform._state_manager and self.platform._state_manager.ws_listener:
                        self.platform._state_manager.ws_listener.register_update_callback(
                            self._hand_recorder.on_ws_update
                        )
                except Exception as e:
                    bot_logger.warning(f"[换桌] 手牌记录器重建失败: {e}")
                    self._hand_recorder = None
            return True
        else:
            bot_logger.error("[换桌] 策略创建失败，无法继续")
            return False

    def _build_table_state_payload(self, state: PokerGameState) -> dict:
        """从 PokerGameState 构建桌位状态 payload"""
        table_state = self._build_table_state(state)
        return {
            "my_chips": table_state.my_chips,
            "my_bank": 0,  # BrowserPlatform 无银行概念
            "is_seated": table_state.is_seated,
            "is_playing": table_state.is_playing,
            "hands_played": table_state.hands_played,
            "total_profit": table_state.total_profit,
            "current_bb": table_state.current_bb,
            "seat_count": table_state.seat_count,
            "active_count": table_state.active_count,
            "stop_loss_bb": table_state.stop_loss_bb,
            "take_profit_bb": table_state.take_profit_bb,
            "low_chips_bb": table_state.low_chips_bb,
            "max_chips_bb": table_state.max_chips_bb,
        }

    def _choice_to_game_action(self, choice: ActionChoice, actions: dict, state=None) -> GameAction:
        """将 ActionChoice 转换为 GameAction（浏览器平台）"""
        action = choice.action
        if action == "allin":
            action_type = ActionType.ALL_IN
            amount = int(actions.get("max_raise", 0) or 0)
        elif action == "fold":
            action_type = ActionType.FOLD
            amount = 0
        elif action == "check":
            action_type = ActionType.CHECK
            amount = 0
        elif action == "call":
            action_type = ActionType.CALL
            amount = int(actions.get("to_call", 0) or 0)
        elif action in ("raise", "bet"):
            action_type = ActionType.RAISE
            amount = choice.amount
        else:
            action_type = ActionType.FOLD
            amount = 0

        # ── 诊断：检测 raise 金额超出自身筹码的场景 ──
        # 当对手 all-in 金额 > 我的筹码时，策略可能算出 to_call*3 / pot*0.75
        # 等超出自身筹码的 raise 金额，导致 ReplayPoker 把 Raise 按钮置灰。
        if state is not None and action_type in (ActionType.RAISE, ActionType.ALL_IN):
            my_chips = 0
            to_call = int(actions.get("to_call", 0) or 0)
            my_seat = getattr(state, "my_seat_id", None)
            players = getattr(state, "players", {}) or {}
            if my_seat is not None and my_seat in players:
                my_chips = int(getattr(players[my_seat], "chips", 0) or 0)

            if my_chips > 0:
                # 情形 A: 面对的全押金额已 >= 自身筹码 → 规则上只能 call/fold，不该 raise
                if to_call >= my_chips and action_type == ActionType.RAISE:
                    bot_logger.warning(
                        f"[筹码冲突#{self._action_count}] 面对超额 all-in: "
                        f"to_call={to_call} >= my_chips={my_chips}, "
                        f"但策略返回 RAISE amount={amount} (source={choice.source}, "
                        f"reasoning={choice.reasoning})。"
                        f"此情形下 ReplayPoker 会将 Raise 按钮置灰，无法点击。"
                    )
                # 情形 B: raise 金额本身超出自身筹码
                elif amount > my_chips:
                    bot_logger.warning(
                        f"[筹码冲突#{self._action_count}] raise 金额超出筹码: "
                        f"amount={amount} > my_chips={my_chips}, "
                        f"to_call={to_call}, pot={getattr(state, 'pot', 0)} "
                        f"(source={choice.source}, reasoning={choice.reasoning})。"
                        f"ReplayPoker 会拒绝此下注并把 Raise 按钮置灰。"
                    )

        bot_logger.info(
            f"[决策#{self._action_count}] {action}"
            f"{f' {amount}' if amount else ''} (来源={choice.source})"
        )
        self._action_count += 1

        return GameAction(action_type=action_type, amount=amount)

    async def _handle_human_command(self, cmd: str):
        """统一人类命令处理（managed/assist 共用）"""
        from rich.console import Console
        console = Console()

        parts = cmd.strip().lower().split()
        if not parts:
            return
        c = parts[0]

        # 托管模式控制命令
        if c == "pause":
            if self._stdin_monitor:
                self._stdin_monitor._paused = True
            console.print("[yellow]已暂停，输入 resume 继续[/yellow]")
        elif c == "resume":
            if self._stdin_monitor:
                self._stdin_monitor._paused = False
            console.print("[green]已恢复自动游戏[/green]")
        elif c == "takeover":
            if self._stdin_monitor:
                self._stdin_monitor._takeover = True
            console.print("[cyan]下一手将由你决策，决策后自动交还 AI[/cyan]")
        elif c == "status":
            self._print_status()
        elif c == "help":
            self._print_pilot_help()
        # 桌位命令
        elif c in ("sit_out",):
            success = await self.platform.sit_out(self._current_table_id)
            console.print(f"sit_out: {'成功' if success else '失败'}")
        elif c in ("sit_in",):
            success = await self.platform.sit_in(self._current_table_id)
            console.print(f"sit_in: {'成功' if success else '失败'}")
        elif c == "add" and len(parts) > 1:
            try:
                amount = int(parts[1])
                success = await self.platform.add_chips(amount=amount, table_id=self._current_table_id)
                console.print(f"add {amount}: {'成功' if success else '失败'}")
            except ValueError:
                console.print("[red]金额必须是整数[/red]")
        elif c == "leave":
            await self.platform.leave_table()
            console.print("[yellow]已离场，停止游戏循环[/yellow]")
            self._running = False
        # 手牌覆盖命令（managed 模式下直接覆盖当前决策）
        elif c in ("fold", "check", "call", "raise", "allin"):
            self._override_action = (c, parts[1:] if len(parts) > 1 else [])
            console.print(f"[dim]已记录覆盖动作: {c}[/dim]")
        # 浏览器命令（委托给 main_browser 共享实现）
        elif c in ("login", "lobby", "tables", "best", "open", "sit", "buyin", "screenshot", "snap", "autosnap"):
            try:
                from src.main_browser import BROWSER_COMMANDS
                handler = BROWSER_COMMANDS.get(c)
                if handler:
                    # 传递 platform 和额外参数
                    extra = parts[1] if len(parts) > 1 else None
                    if c in ("tables", "open"):
                        await handler(self.platform, extra)
                    elif c in ("buyin",):
                        await handler(self.platform, extra or "default")
                    elif c == "autosnap":
                        console.print("[dim]autosnap 命令在托管/辅助模式下暂不支持[/dim]")
                    else:
                        await handler(self.platform)
                else:
                    console.print(f"[dim]未知浏览器命令: {c}[/dim]")
            except Exception as e:
                console.print(f"[red]命令执行失败: {e}[/red]")
        elif c == "config":
            console.print(f"策略: {self.strategy_type} | pilot: {self.pilot_mode.value}")
        else:
            console.print(f"[dim]未知命令: {c}，输入 help 查看帮助[/dim]")

    def _print_status(self):
        """打印当前状态"""
        from rich.console import Console
        from rich.panel import Panel
        console = Console()

        lines = [
            f"Pilot: {self.pilot_mode.value}",
            f"手数: {self._hands_played}",
            f"初始筹码: {self._initial_chips or '未知'}",
            f"策略: {self._strategy.strategy_name if self._strategy else '未知'}",
        ]
        if self._stdin_monitor:
            lines.append(f"暂停: {'是' if self._stdin_monitor.is_paused else '否'}")
            lines.append(f"接管: {'是' if self._stdin_monitor.is_takeover else '否'}")

        console.print(Panel("\n".join(lines), title="当前状态", border_style="blue"))

    def _print_pilot_help(self):
        """打印 pilot 模式帮助"""
        from rich.console import Console
        console = Console()

        console.print("\n[bold]托管/辅助模式命令:[/bold]")
        console.print("  pause           - 暂停自动游戏")
        console.print("  resume          - 恢复自动游戏")
        console.print("  takeover        - 接管下一手决策")
        console.print("  status          - 显示当前状态")
        console.print("  help            - 显示帮助")
        console.print()
        console.print("[bold]手牌命令:[/bold]")
        console.print("  fold/check/call/raise/allin - 覆盖当前决策")
        console.print()
        console.print("[bold]桌位命令:[/bold]")
        console.print("  sit_in/sit_out  - 桌位控制")
        console.print("  add <金额>      - 补充筹码")
        console.print("  leave           - 离场停止")
        console.print()
        console.print("[bold]浏览器命令:[/bold]")
        console.print("  login/lobby/tables/best/open/sit/buyin/screenshot/snap")
        console.print()

    def _track_hands(self, state: PokerGameState):
        """追踪手数和轮次"""
        # 通过 hand_id 变化追踪新手牌
        ws_state = {}
        if self.platform._state_manager:
            ws_state = self.platform._state_manager.ws_listener.get_state()

        hand_id = ws_state.get("hand_id", 0)
        if hand_id != self._last_hand_id and hand_id > 0:
            if self._last_hand_id > 0:
                # 结束上一手牌的记录
                if self._hand_recorder and self._hand_recorder.is_recording:
                    try:
                        self._hand_recorder.finalize_hand(ws_state)
                    except Exception as e:
                        bot_logger.debug(f"手牌记录 finalize 异常: {e}")
                self._hands_played += 1
                self._action_count = 0  # 重置动作计数
                self._consecutive_action_failures = 0  # 新手牌重置失败计数

                # 输出 VPIP/PFR 统计
                vpip_tracker = ws_state.get("vpip_tracker", {})
                if vpip_tracker:
                    my_user_id = ws_state.get("my_user_id")
                    if my_user_id and my_user_id in vpip_tracker:
                        stats = vpip_tracker[my_user_id]
                        bot_logger.info(
                            f"[手数#{self._hands_played}] "
                            f"VPIP: {stats['vpip_count']}/{stats['hands']} "
                            f"({stats['vpip_count']/max(stats['hands'],1)*100:.0f}%) | "
                            f"PFR: {stats['pfr_count']}/{stats['hands']} "
                            f"({stats['pfr_count']/max(stats['hands'],1)*100:.0f}%)"
                        )

            # 新手牌开始日志
            my_chips = 0
            my_player = state.players.get(state.my_seat_id) if state.my_seat_id is not None else None
            if my_player:
                my_chips = my_player.chips

            profit = my_chips - self._initial_chips if self._initial_chips is not None else 0
            bot_logger.info(
                f"[新手牌] hand_id={hand_id} "
                f"底牌={state.hole_cards or '等待发牌'} "
                f"筹码={my_chips} 盈亏={profit:+d} "
                f"BB={ws_state.get('big_blind', '?')}"
            )

            self._last_hand_id = hand_id
            self._last_logged_stage = ""  # 重置街道追踪

            # 开始新一手牌的记录
            if self._hand_recorder:
                try:
                    self._hand_recorder.start_hand(hand_id, ws_state)
                except Exception as e:
                    bot_logger.debug(f"手牌记录 start 异常: {e}")

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
        # 获取最终筹码
        final_chips = 0
        try:
            state = await self.platform.get_game_state(self._current_table_id)
            my_player = state.players.get(state.my_seat_id) if state.my_seat_id is not None else None
            if my_player:
                final_chips = my_player.chips
        except Exception:
            pass

        profit = final_chips - self._initial_chips if self._initial_chips is not None else 0
        duration = ""
        if self._start_time:
            import time
            elapsed = time.time() - self._start_time
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            duration = f"\n  运行时长: {mins}分{secs}秒"

        bot_logger.info(
            f"=== 自动模式结束 ===\n"
            f"  手数: {self._hands_played}\n"
            f"  循环次数: {self._loop_count}\n"
            f"  初始筹码: {self._initial_chips or '未知'}\n"
            f"  最终筹码: {final_chips}\n"
            f"  盈亏: {profit:+d}"
            f"{duration}\n"
            f"  策略: {self._strategy.strategy_name if self._strategy else '未知'}"
        )

    def _log_state_change(self, state: PokerGameState, actions: dict):
        """状态变化时输出摘要日志，避免轮询时重复刷屏"""
        current_stage = state.current_stage or ""

        # 街道变化时输出（preflop -> flop -> turn -> river）
        if current_stage and current_stage != self._last_logged_stage:
            my_chips = 0
            my_player = state.players.get(state.my_seat_id) if state.my_seat_id is not None else None
            if my_player:
                my_chips = my_player.chips

            bot_logger.info(
                f"[街道变化] {self._last_logged_stage or '等待'} -> {current_stage} | "
                f"公牌={state.community_cards} "
                f"底牌={state.hole_cards} "
                f"pot={state.pot} "
                f"to_call={actions.get('to_call', 0)} "
                f"筹码={my_chips}"
            )
            self._last_logged_stage = current_stage

        # is_my_turn 变化时输出
        is_my_turn = bool(actions.get("available"))
        if is_my_turn != self._last_logged_my_turn:
            if is_my_turn:
                bot_logger.info(
                    f"[轮到我] 可用={actions.get('available', [])} "
                    f"to_call={actions.get('to_call', 0)} "
                    f"min_raise={actions.get('min_raise', 0)}"
                )
            self._last_logged_my_turn = is_my_turn

        # 定期心跳：每 100 轮输出一次简短状态
        if self._loop_count % 100 == 0:
            my_chips = 0
            my_player = state.players.get(state.my_seat_id) if state.my_seat_id is not None else None
            if my_player:
                my_chips = my_player.chips
            profit = my_chips - self._initial_chips if self._initial_chips is not None else 0
            ws_healthy = self.platform._state_manager.is_healthy() if self.platform._state_manager else False
            bot_logger.info(
                f"[心跳] loop#{self._loop_count} 手数={self._hands_played} "
                f"筹码={my_chips} 盈亏={profit:+d} "
                f"WS={'OK' if ws_healthy else 'DOWN'}"
            )

    def stop(self):
        """停止自动游戏循环"""
        self._running = False
        bot_logger.info("自动模式停止请求已发送")
