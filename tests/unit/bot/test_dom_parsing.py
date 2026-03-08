"""
tests/unit/bot/test_dom_parsing.py

使用真实 DOM 快照验证选择器是否正确。

快照文件来源: tests/explore/data/
"""
import re
from pathlib import Path
from bs4 import BeautifulSoup
import pytest

SNAPSHOT_DIR = Path(__file__).parent / "fixtures"


class TestRealDomSelectors:
    """验证选择器在真实 DOM 中工作。"""

    def setup_method(self):
        """加载所有 HTML 文件。"""
        self.html_files = list(SNAPSHOT_DIR.glob("*.html"))
        if not self.html_files:
            pytest.skip("No HTML snapshot files found in tests/explore/data/")

        self.soups = []
        for html_path in self.html_files:
            with open(html_path, encoding="utf-8") as f:
                self.soups.append(BeautifulSoup(f.read(), "html.parser"))

    def test_pot_selector(self):
        """测试 .Pot__value 选择器。"""
        found = False
        for soup in self.soups:
            pots = soup.select(".Pot__value")
            if pots:
                found = True
                text = pots[0].get_text().strip()
                print(f"✓ 找到底池: {text}")
                # 验证包含数字
                assert any(c.isdigit() for c in text), f"底池应该包含数字: {text}"
        assert found, "应该在至少一个快照中找到 .Pot__value"

    def test_button_selectors(self):
        """测试按钮选择器（通过文本内容找按钮）。"""
        button_texts = ["Fold", "Call", "Check", "Raise", "Bet", "All In"]

        for soup in self.soups:
            buttons = soup.find_all("button")
            found_buttons = []

            for btn in buttons:
                text = btn.get_text().strip()
                for target in button_texts:
                    if re.search(f"^{target}", text, re.I):
                        found_buttons.append(target)
                        print(f"✓ 找到按钮: {target} (完整文本: '{text}')")

            if found_buttons:
                print(f"  本页找到: {set(found_buttons)}")

    def test_seat_selectors(self):
        """测试座位选择器。"""
        for soup in self.soups:
            seats = soup.select(".Seat")
            if seats:
                print(f"✓ 找到 {len(seats)} 个座位")
                # 检查是否有庄家按钮
                dealer_buttons = soup.select(".DealerButton")
                print(f"  庄家按钮: {len(dealer_buttons)}")
                # 检查是否有筹码
                stacks = soup.select(".Stack__value, .Seat__stack")
                print(f"  筹码显示: {len(stacks)}")

    def test_community_card_selectors(self):
        """测试公共牌选择器。"""
        for soup in self.soups:
            cards = soup.select(".CommunityCard")
            if cards:
                print(f"✓ 找到 {len(cards)} 张公共牌")

    def test_parse_pot_value(self):
        """测试从底池文本提取数值。"""
        test_cases = [
            ("7", 7),
            ("51", 51),
            ("1,000", 1000),
            ("2,500", 2500),
        ]

        from src.bot.play_manager import PlayManager

        # 创建 mock table manager 来测试 _parse_amount_string
        class MockTableManager:
            pass

        pm = PlayManager(MockTableManager())

        for text, expected in test_cases:
            result = pm._parse_amount_string(text)
            print(f"_parse_amount_string('{text}') = {result} (expected: {expected})")
            assert result == expected, f"{text} 应该解析为 {expected}"

    def test_parse_to_call_from_button(self):
        """测试从按钮文本提取 to_call。"""
        test_cases = [
            ("Call 2", 2),
            ("Call 518", 518),
            ("Call 1,000", 1000),
        ]

        for text, expected in test_cases:
            digits = re.sub(r"[^\d]", "", text)
            result = int(digits) if digits else 0
            print(f"'{text}' -> digits='{digits}' -> {result} (expected: {expected})")
            assert result == expected

    def test_raise_preset_buttons(self):
        """测试加注预设按钮（MIN/½POT/POT/MAX）。"""
        print("\n" + "=" * 60)
        print("查找加注预设按钮:")
        print("=" * 60)

        preset_labels = [
            "MIN", "Min", "min",
            "½", "1/2", "Half", "HALF",
            "POT", "Pot",
            "MAX", "Max",
        ]

        found_any = False
        for html_path in self.html_files:
            with open(html_path, encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), "html.parser")

            print(f"\n{html_path.name}:")
            found_in_file = []

            # 搜索所有包含这些标签的元素
            all_elements = soup.find_all(True)
            for el in all_elements:
                text = el.get_text(strip=True)
                if not text:
                    continue
                for label in preset_labels:
                    if label in text:
                        # 检查元素类型
                        tag = el.name
                        classes = el.get("class", [])
                        found_in_file.append(f"'{text}' [tag={tag}, class={classes}]")
                        break

            if found_in_file:
                found_any = True
                print(f"  找到 {len(found_in_file)} 个预设按钮候选:")
                for item in found_in_file[:5]:
                    print(f"    - {item}")
                if len(found_in_file) > 5:
                    print(f"    ... 还有 {len(found_in_file)-5} 个")

        if not found_any:
            print("\n⚠️ 未在当前快照中找到预设按钮，这可能是因为：")
            print("   1. 快照是在点击 Raise 按钮之前截取的")
            print("   2. 快照是在点击 Raise 按钮之后截取的")
            print("   3. 网站的 UI 结构发生了变化")

    def test_all_snapshots_overview(self):
        """打印所有快照的概览。"""
        print("\n" + "=" * 60)
        print("快照概览:")
        print("=" * 60)

        for html_path in self.html_files:
            print(f"\n{html_path.name}:")
            with open(html_path, encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), "html.parser")

            # 底池
            pots = soup.select(".Pot__value")
            if pots:
                print(f"  底池: {pots[0].get_text().strip()}")

            # 按钮
            buttons = soup.find_all("button")
            action_buttons = []
            for btn in buttons:
                text = btn.get_text().strip()
                for target in ["Fold", "Call", "Check", "Raise", "Bet", "All In"]:
                    if re.search(f"^{target}", text, re.I):
                        action_buttons.append(f"{target}('{text}')")
                        break
            if action_buttons:
                print(f"  按钮: {', '.join(action_buttons)}")

            # 座位
            seats = soup.select(".Seat")
            print(f"  座位数: {len(seats)}")

            # 公共牌
            community = soup.select(".CommunityCard")
            print(f"  公共牌: {len(community)} 张")
