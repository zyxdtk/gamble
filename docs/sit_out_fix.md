# Sit Out 状态处理修复

## 问题描述

用户尝试使用 `sit in` 命令从 "Sit Out" 状态恢复，但失败了：

```
test-cli> sit in
19:49:48 - bot - WARNING - Sit in button not found (replay_poker.py:756)
Sit in: ✗ Failed
```

同时，快照显示页面状态为：
- 有 `Add Chips` 和 `Stand` 按钮（说明已经坐下）
- "Sit Out Next Hand" 复选框被勾选
- 没有 "Sit In" 按钮

## 根本原因

### ReplayPoker 的座位状态机制

ReplayPoker 有两种"离开"状态：

1. **Stand（站立）**：完全离开桌子，需要重新买入才能坐下
   - 按钮：`Sit Down` 或 `Buy-in`

2. **Sit Out（坐出）**：坐在桌上但暂时不参与游戏
   - 表现："Sit Out Next Hand" 复选框被勾选
   - 按钮：`Add Chips` 和 `Stand`
   - 恢复方式：**取消勾选** "Sit Out Next Hand" 复选框

### 代码问题

原来的 `sit_in()` 方法只查找 "Sit In" 按钮：

```python
# 方法1: 查找 .SeatControls__action--sitIn 按钮
sit_in_btn = page.locator(".SeatControls__action--sitIn")

# 方法2: 查找包含 "Sit in" 文字的按钮
sit_in_text = page.get_by_text("Sit in", exact=False)
```

但在 "Sit Out" 状态下，页面上**没有** "Sit In" 按钮，只有被勾选的复选框。

## 解决方案

在 `sit_in()` 方法中添加第三种检测方法：

```python
# [FIX] 方法3: 检查是否是 "Sit Out" 状态，需要取消勾选
sit_out_checkbox = page.locator(".Footer__settings--sittingOut .CheckBox.CheckBox--checked")
if await sit_out_checkbox.count() > 0:
    bot_logger.info("Detected 'Sit Out' state, unchecking checkbox...")
    await sit_out_checkbox.click()
    await asyncio.sleep(0.5)
    bot_logger.info("Uncheked 'Sit Out Next Hand' - you are now sitting in!")
    return True
```

### 工作原理

1. **检测 Sit Out 状态**：查找 `.Footer__settings--sittingOut .CheckBox.CheckBox--checked`
   - `.Footer__settings--sittingOut`：表示当前处于 Sit Out 状态
   - `.CheckBox--checked`：表示复选框被勾选

2. **取消勾选**：点击复选框，取消 "Sit Out Next Hand"

3. **自动恢复**：取消勾选后，系统会自动将你恢复到 "Sit In" 状态，可以参与下一手牌

## 完整的 sit_in() 逻辑

现在 `sit_in()` 方法支持三种情况：

```python
async def sit_in(self, page: Page) -> bool:
    """Sit in from sitting out state."""
    try:
        # 方法1: 查找 Sit in 按钮（通过类名）
        sit_in_btn = page.locator(".SeatControls__action--sitIn")
        if await sit_in_btn.count() > 0 and await sit_in_btn.is_visible():
            await sit_in_btn.click()
            return True
        
        # 方法2: 备用：通过文字查找
        sit_in_text = page.get_by_text("Sit in", exact=False)
        if await sit_in_text.count() > 0 and await sit_in_text.is_visible():
            await sit_in_text.click()
            return True
        
        # 方法3: [新增] 检查并取消 "Sit Out" 复选框
        sit_out_checkbox = page.locator(".Footer__settings--sittingOut .CheckBox.CheckBox--checked")
        if await sit_out_checkbox.count() > 0:
            await sit_out_checkbox.click()
            return True
        
        return False
    except Exception as e:
        bot_logger.error(f"Failed to sit in: {e}")
        return False
```

## 使用场景

### 场景1: 标准的 Sit In 按钮
```
页面状态: 有 "Sit In" 按钮
操作: 点击按钮
结果: ✓ 成功
```

### 场景2: Sit Out 复选框
```
页面状态: "Sit Out Next Hand" 被勾选
操作: 取消勾选复选框
结果: ✓ 成功（本次修复支持）
```

### 场景3: 已经 Sit In
```
页面状态: 没有 Sit Out 标记，也没有 Sit In 按钮
操作: 无操作
结果: 已经在游戏中
```

## 测试建议

```bash
# 1. 先坐下
test-cli> join

# 2. 手动勾选 "Sit Out Next Hand"（或在游戏中自动进入此状态）

# 3. 尝试 sit in
test-cli> sit in

# 预期输出：
# Detected 'Sit Out' state, unchecking checkbox...
# Uncheked 'Sit Out Next Hand' - you are now sitting in!
# Sit in: ✓ Success
```

## 相关文件

- **修改文件**: `src/platforms/browser/adapters/replay_poker.py` (第 749-775 行)
- **快照分析**: `data/snapshots/snap_1780746596/table_16902280.html`

## 注意事项

1. **Sit Out vs Stand**
   - Sit Out: 坐着但不玩，可以快速恢复
   - Stand: 完全离开，需要重新买入

2. **自动 Sit Out**
   - 筹码不足时可能自动进入 Sit Out 状态
   - 长时间不操作可能自动 Sit Out
   - 需要使用 `sit in` 命令恢复

3. **UI 变化**
   - 不同网站可能有不同的 Sit Out UI
   - 当前实现针对 ReplayPoker
   - 其他网站需要适配相应的选择器
