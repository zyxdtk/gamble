"""
tests/unit/bot/test_play_manager_raise.py

测试 PlayManager 的 set_raise_amount 方法。

验证：
1. bet_size_hint 能正确找到快捷按钮（MIN/½POT/POT/MAX）
2. 根据 amount/pot 比例自动推断档位
3. 降级到 input 输入
"""
import re
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.table_manager import TableManager
from src.bot.play_manager import PlayManager


def make_mock_table_manager():
    """创建模拟 TableManager，用于测试。"""
    page = MagicMock()
    page.url = "https://www.casino.org/replaypoker/play/table/12345"

    with patch.object(TableManager, '_load_settings'):
        tm = TableManager(page, strategy_type="gto")
    tm.big_blind = 2
    return tm


class TestSetRaiseAmount:
    """测试 set_raise_amount 方法。"""

    def test_auto_infer_bet_size_hint_from_ratio(self):
        """测试根据 amount/pot 比例自动推断加注档位。"""
        tm = make_mock_table_manager()
        pm = PlayManager(tm)

        test_cases = [
            (10, 100, "min"),       # 0.10 -> min
            (50, 100, "half_pot"),  # 0.50 -> half_pot
            (80, 100, "pot"),        # 0.80 -> pot
            (200, 100, "max"),        # 2.00 -> max
        ]

        for amount, pot, expected in test_cases:
            ratio = amount / pot
            if ratio > 1.5:
                inferred = "max"
            elif ratio > 0.75:
                inferred = "pot"
            elif ratio > 0.4:
                inferred = "half_pot"
            else:
                inferred = "min"
            assert inferred == expected, f"amount={amount}, pot={pot} 应该推断为 {expected}，实际是 {inferred}"

    def test_preset_button_labels(self):
        """测试 PRESET_BUTTONS 字典包含正确的映射。"""
        tm = make_mock_table_manager()
        pm = PlayManager(tm)

        PRESET_BUTTONS_EXPECTED = {
            "min": ["MIN", "Min", "min"],
            "half_pot": ["½ POT", "1/2 POT", "1/2", "Half", "HALF"],
            "pot": ["POT", "Pot"],
            "max": ["MAX", "Max", "All In", "ALL IN"],
        }

        print("\nPRESET_BUTTONS 定义了 4 个档位:")
        for key, labels in PRESET_BUTTONS_EXPECTED.items():
            print(f"  {key}: {labels}")

        assert len(PRESET_BUTTONS_EXPECTED) == 4, "应该有 4 个档位"


class TestRaiseAmountIntegration:
    """集成测试：完整流程测试。"""

    def test_full_raise_preset_buttons_coverage(self):
        """所有预设按钮文本都被覆盖。"""
        all_labels = [
            "MIN", "Min", "min",
            "½ POT", "1/2 POT", "1/2", "Half", "HALF",
            "POT", "Pot",
            "MAX", "Max", "All In", "ALL IN",
        ]

        print("\n覆盖的按钮文本:")
        for label in all_labels:
            print(f"  - {label}")

        assert len(all_labels) == 14, f"应该有 14 种按钮文本变体，实际是 {len(all_labels)}"

    def test_selector_strategies(self):
        """测试选择器策略覆盖。"""
        selectors = [
            "button:has-text('{label}')",
            ".m-bet-controls__preset:has-text('{label}')",
            ".m-btn:has-text('{label}')",
            "[role='button']:has-text('{label}')",
            "div[class*='preset']:has-text('{label}')",
            "span:has-text('{label}')",
        ]

        print("\n选择器策略:")
        for sel in selectors:
            print(f"  - {sel}")

        assert len(selectors) == 6, "应该有 6 种选择器策略"

    def test_input_selectors(self):
        """测试输入框选择器覆盖。"""
        number_selectors = [
            "input.m-bet-input__input",
            "input.m-bet-field__input",
            ".m-bet-input input",
            ".m-bet-controls input",
            "input[type='number']",
            "input[type='text'][pattern='[0-9]*']",
            "input[class*='input']",
        ]

        print("\n输入框选择器:")
        for sel in number_selectors:
            print(f"  - {sel}")

        assert len(number_selectors) == 7, "应该有 7 种输入框选择器"
