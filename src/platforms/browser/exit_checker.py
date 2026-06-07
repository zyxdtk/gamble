"""
退出条件检查器
退出条件检查器
"""
import os
import yaml
from typing import Optional
from ...utils.logger import bot_logger


class ExitChecker:
    """
    检查是否应该退出牌桌

    条件（从 config/settings.yaml 读取阈值）：
    - stop_loss_bb: 输掉 N 个大盲注 -> 退出
    - take_profit_bb: 赢了 N 个大盲注 -> 退出
    - low_chips_bb: 筹码低于 N 个大盲注 -> 退出
    - max_chips_bb: 筹码高于 N 个大盲注 -> 退出
    """

    def __init__(
        self,
        stop_loss_bb: Optional[int] = None,
        take_profit_bb: Optional[int] = None,
        low_chips_bb: Optional[int] = None,
        max_chips_bb: Optional[int] = None,
    ):
        self.stop_loss_bb = stop_loss_bb
        self.take_profit_bb = take_profit_bb
        self.low_chips_bb = low_chips_bb
        self.max_chips_bb = max_chips_bb

        # 未显式传入时，从配置文件读取
        if all(v is None for v in [stop_loss_bb, take_profit_bb, low_chips_bb, max_chips_bb]):
            self._load_from_config()

    def _load_from_config(self):
        """从 config/settings.yaml 读取退出阈值"""
        config_path = os.path.join(os.getcwd(), "config", "settings.yaml")
        if not os.path.exists(config_path):
            return
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            thresholds = data.get("game", {}).get("exit_thresholds", {})
            if self.stop_loss_bb is None:
                self.stop_loss_bb = thresholds.get("stop_loss_bb")
            if self.take_profit_bb is None:
                self.take_profit_bb = thresholds.get("take_profit_bb")
            if self.low_chips_bb is None:
                self.low_chips_bb = thresholds.get("low_chips_bb")
            if self.max_chips_bb is None:
                self.max_chips_bb = thresholds.get("max_chips_bb")
        except Exception as e:
            bot_logger.warning(f"ExitChecker: 读取配置失败: {e}")

    def should_exit(
        self,
        current_chips: int,
        buy_in: int,
        big_blind: int,
        initial_chips: int,
    ) -> Optional[str]:
        """
        检查是否应该退出牌桌

        Args:
            current_chips: 当前筹码
            buy_in: 买入金额（用于计算盈亏基准）
            big_blind: 大盲注金额
            initial_chips: 初始筹码（首次入座时的筹码）

        Returns:
            退出原因字符串，或 None 表示不退出
        """
        bb = big_blind if big_blind > 0 else 2
        profit = current_chips - initial_chips

        # 止损：亏损超过 N 个 BB
        if self.stop_loss_bb is not None and self.stop_loss_bb > 0:
            stop_loss = bb * self.stop_loss_bb
            if profit <= -stop_loss:
                return f"stop_loss: 亏损 {profit} (阈值 -{stop_loss})"

        # 止盈：盈利超过 N 个 BB
        if self.take_profit_bb is not None and self.take_profit_bb > 0:
            take_profit = bb * self.take_profit_bb
            if profit >= take_profit:
                return f"take_profit: 盈利 +{profit} (阈值 +{take_profit})"

        # 筹码过低：低于 N 个 BB
        if self.low_chips_bb is not None and self.low_chips_bb > 0:
            low_chips = bb * self.low_chips_bb
            if current_chips < low_chips:
                return f"low_chips: 筹码 {current_chips} (阈值 {low_chips})"

        # 筹码过高：超过 N 个 BB
        if self.max_chips_bb is not None and self.max_chips_bb > 0:
            max_chips = bb * self.max_chips_bb
            if current_chips > max_chips:
                return f"max_chips: 筹码 {current_chips} (阈值 {max_chips})"

        return None
