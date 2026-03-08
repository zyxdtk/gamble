# 测试策略改进方案

## 当前问题

### ❌ 现有测试的局限性

1. **完全 Mock DOM 操作**
   ```python
   # 当前测试
   locator.count = AsyncMock(return_value=5)  # 任意返回值
   locator.text_content = AsyncMock(return_value="1/2")  # 假设的格式
   ```

2. **无法验证选择器是否正确**
   - `.Pot__value` 选择器可能已变更
   - `.Stack__value` 可能在某些页面不存在

3. **无法验证文本解析逻辑**
   - 真实页面的盲注格式可能不是 "1/2"
   - 筹码显示可能包含货币符号、空格等

---

## 解决方案：三层测试架构

### Level 1: 单元测试 (Mock) - 已有 ✅

**位置**: `tests/unit/bot/`

**目的**: 快速验证逻辑分支和算法

**特点**:
- 使用 Mock/AsyncMock
- 测试边界条件
- 测试异常处理
- 运行速度快 (<1 秒)

**示例**:
```python
# tests/unit/bot/test_table_manager.py
async def test_stop_loss_triggers():
    m = make_manager()
    m.initial_chips = 1000
    m.state.total_chips = 799  # 亏损 201
    assert await m.lifecycle_mgr.check_exit_conditions() is True
```

---

### Level 2: 半集成测试 (Snapshot) - 新建 🆕

**位置**: `tests/snapshots/`

**目的**: 使用真实的 DOM 快照验证解析逻辑

**特点**:
- 从真实页面捕获 DOM 结构
- 保存为 JSON/HTML 文件
- 测试时加载快照
- 可验证选择器和解析逻辑

**实现方式**:

#### 2.1 创建 DOM 快照捕获工具

```python
# tests/snapshots/capture.py
import asyncio
import json
from playwright.async_api import async_playwright

async def capture_table_dom():
    """捕获真实牌桌的 DOM 结构"""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 打开真实牌桌
        await page.goto("https://www.casino.org/replaypoker/play/table/99999")
        
        # 等待牌局加载
        await page.wait_for_selector(".Pot__value")
        
        # 捕获关键元素
        snapshot = {
            "pot": await page.locator(".Pot__value").first.text_content(),
            "stacks": [],
            "buttons": [],
            "community_cards": [],
        }
        
        # 捕获所有座位的筹码
        stacks = page.locator(".Stack__value")
        for i in range(await stacks.count()):
            snapshot["stacks"].append(await stacks.nth(i).text_content())
        
        # 捕获动作按钮
        for btn_name in ["Fold", "Call", "Check", "Raise"]:
            btn = page.get_by_role("button", name=btn_name)
            if await btn.count() > 0:
                snapshot["buttons"].append({
                    "name": btn_name,
                    "text": await btn.first.text_content()
                })
        
        # 保存快照
        with open("tests/snapshots/table_state_001.json", "w") as f:
            json.dump(snapshot, f, indent=2)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(capture_table_dom())
```

#### 2.2 创建基于快照的测试

```python
# tests/snapshots/test_dom_parsing.py
import json
import pytest
from pathlib import Path
from src.bot.play_manager import PlayManager

@pytest.fixture
def table_snapshot():
    """加载真实的 DOM 快照"""
    snapshot_path = Path(__file__).parent / "table_state_001.json"
    with open(snapshot_path) as f:
        return json.load(f)

class TestRealDomParsing:
    """使用真实 DOM 快照测试解析逻辑"""
    
    def test_pot_parsing(self, table_snapshot):
        """测试底池解析"""
        pot_text = table_snapshot["pot"]  # 例如："Pot: 150"
        # 验证解析逻辑能正确处理真实格式
        val = re.sub(r"[^\d]", "", pot_text)
        assert int(val) == 150
    
    def test_stack_parsing(self, table_snapshot):
        """测试筹码解析"""
        for stack_text in table_snapshot["stacks"]:
            # 验证所有筹码格式都能解析
            val = re.sub(r"[^\d]", "", stack_text)
            assert val.isdigit()
    
    def test_button_detection(self, table_snapshot):
        """测试按钮检测"""
        button_names = [b["name"] for b in table_snapshot["buttons"]]
        # 验证预期的按钮存在
        assert "Call" in button_names or "Check" in button_names
```

---

### Level 3: 真实浏览器集成测试 - 已有 🔄

**位置**: `tests/integration/`

**目的**: 在真实浏览器中运行完整流程

**特点**:
- 使用真实的浏览器
- 连接真实的牌桌
- 测试完整的用户流程
- 运行时间长 (几分钟到几小时)

**示例**:
```python
# tests/integration/test_profit_target.py
@pytest.mark.asyncio
async def test_profit_target():
    """真实浏览器测试盈利目标"""
    test_runner = ProfitTargetTest(target_profit=1000)
    await test_runner.run()
    assert test_runner.result.profit >= 1000
```

---

## 实施计划

### 第一阶段：创建快照基础设施 (1-2 天)

1. ✅ 创建 `tests/snapshots/` 目录
2. ✅ 创建 DOM 捕获脚本
3. ✅ 捕获 5-10 个不同场景的快照：
   - 翻牌前
   - 翻牌后
   - 转牌
   - 河牌
   - 不同盲注级别
   - 多人底池
   - 单挑

### 第二阶段：补充快照测试 (2-3 天)

1. ✅ 测试所有 DOM 解析逻辑
2. ✅ 测试选择器匹配
3. ✅ 测试按钮检测
4. ✅ 测试文本提取

### 第三阶段：定期更新快照 (持续)

1. 每次 UI 更新后重新捕获
2. 使用 Git 跟踪快照变化
3. 作为 UI 回归测试

---

## 测试金字塔

```
        /\
       /  \      Level 3: 集成测试 (少量，慢速)
      /____\     验证完整流程
     
     /      \
    /        \   Level 2: 快照测试 (中量，中速)
   /__________\  验证 DOM 解析
   
  /            \
 /              \ Level 1: 单元测试 (大量，快速)
/________________\ 验证逻辑分支
```

---

## 各层级覆盖率目标

| 层级 | 测试数量 | 运行时间 | 覆盖率目标 |
|------|---------|---------|-----------|
| Level 1: 单元测试 | 50+ | <1 秒 | 60%+ |
| Level 2: 快照测试 | 20+ | <10 秒 | 80%+ (DOM 解析) |
| Level 3: 集成测试 | 5+ | 几分钟 | 关键流程 |

---

## 立即行动项

1. **创建 `tests/snapshots/` 目录结构**
2. **编写 DOM 捕获脚本**
3. **捕获第一批快照数据**
4. **编写基于快照的解析测试**
5. **将快照测试加入 CI/CD**
