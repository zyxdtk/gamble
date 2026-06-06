# Available Actions 错误显示修复

## 问题描述

用户报告 `Available Actions` 在 `My Turn: False` 时仍然显示动作：

```
test-cli> state

--- Game State ---
  Pot: 114
  Community Cards: []
  My Seat: None
  To Call: 0
  Min Raise: 0
  My Turn: False                  # ❌ 不是我的回合
  Available Actions: bet          # ❌ 但仍然显示有动作！

test-cli> state
--- Game State ---
  ...
  My Turn: False
  Available Actions: fold         # ❌ 错误！

test-cli> state
--- Game State ---
  ...
  My Turn: False
  Available Actions: call         # ❌ 错误！
```

快照分析显示页面实际状态：
```html
<div class="Footer__actions">
  <div class="AwaitTurn">
    <div class="AwaitTurn__description">Please wait for the next hand</div>
  </div>
</div>
```

**问题**：页面上没有动作按钮，只有 "Please wait for the next hand" 提示，但 CLI 却显示有可用动作。

## 根本原因

### Playwright 的 get_by_role 行为

代码使用 `page.get_by_role("button", name=re.compile(button_regex))` 来查找按钮。这个方法基于 **ARIA 可访问性角色** 来查找元素，会找到：

1. ✅ 可见的按钮
2. ❌ 隐藏的按钮（display: none）
3. ❌ 屏幕外的按钮（off-screen）
4. ❌ 被父容器隐藏的按钮（如 `.AwaitTurn` 容器）
5. ❌ DOM 中存在但不可交互的按钮

即使按钮对用户不可见，只要它在 DOM 中且有 `role="button"`，`get_by_role` 就能找到它。

### 原来的检查不足

原来的代码只做了两层检查：
```python
if await first_btn.is_visible():  # 检查1: 基本可见性
    disabled = await first_btn.get_attribute("disabled")
    if disabled is None:  # 检查2: disabled 属性
        # 检查 opacity
        actions["available"].append(action_name)
```

**缺少的检查**：
- ❌ 是否在 viewport 内
- ❌ 父元素是否隐藏
- ❌ CSS display/visibility 属性

## 解决方案

添加 **5层可见性检查**，确保按钮真正可用：

```python
for action_name, button_regex in targets.items():
    btn = page.get_by_role("button", name=re.compile(button_regex, re.IGNORECASE))
    if await btn.count() > 0:
        first_btn = btn.first
        
        # [FIX] 多重可见性检查
        # 1. 检查是否 visible
        if not await first_btn.is_visible():
            continue
        
        # 2. 检查是否在 viewport 内（排除屏幕外的元素）
        is_in_viewport = await first_btn.evaluate("""
            (el) => {
                const rect = el.getBoundingClientRect();
                return (
                    rect.top >= 0 &&
                    rect.left >= 0 &&
                    rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
                    rect.right <= (window.innerWidth || document.documentElement.clientWidth)
                );
            }
        """)
        if not is_in_viewport:
            continue
        
        # 3. 检查父元素是否隐藏（例如 .AwaitTurn 容器）
        parent_class = await first_btn.evaluate("""
            (el) => {
                let parent = el.parentElement;
                while (parent) {
                    const style = window.getComputedStyle(parent);
                    if (style.display === 'none' || style.visibility === 'hidden') {
                        return parent.className;
                    }
                    parent = parent.parentElement;
                }
                return '';
            }
        """)
        if parent_class:
            bot_logger.debug(f"Button '{action_name}' hidden by parent: {parent_class}")
            continue
        
        # 4. 检查按钮是否被禁用（灰色状态）
        disabled = await first_btn.get_attribute("disabled")
        if disabled is not None:  # 有 disabled 属性
            continue
        
        # 5. 检查样式中的 opacity，如果太低说明是禁用状态
        style = await first_btn.get_attribute("style") or ""
        opacity_match = re.search(r'opacity:\s*([\d.]+)', style)
        if opacity_match:
            opacity = float(opacity_match.group(1))
            if opacity < 0.5:  # 透明度过低，视为禁用
                continue
        
        actions["available"].append(action_name)
```

### 5层检查详解

| 层级 | 检查内容 | 目的 | 示例 |
|------|---------|------|------|
| 1 | `is_visible()` | 基本可见性 | 排除 display:none 的元素 |
| 2 | Viewport | 在屏幕内 | 排除 position:absolute 移出的元素 |
| 3 | Parent hidden | 父元素可见 | 排除 .AwaitTurn 等容器隐藏的情况 |
| 4 | Disabled | HTML 禁用 | 排除有 disabled 属性的按钮 |
| 5 | Opacity | CSS 透明度 | 排除灰色禁用的按钮（opacity<0.5） |

## 修复效果

### 场景1: 等待下一手牌（本次修复的场景）

**修复前**：
```
Page: "Please wait for the next hand"
CLI:  Available Actions: bet/fold/call  ❌
```

**修复后**：
```
Page: "Please wait for the next hand"
CLI:  Available Actions: (none)  ✓
```

**原因**：按钮被 `.AwaitTurn` 容器隐藏，第3层检查捕获。

### 场景2: 轮到你行动

**修复前后一致**：
```
Page: 显示 Fold/Call/Raise 按钮
CLI:  Available Actions: fold, call, raise  ✓
```

### 场景3: Sit Out 状态

**修复前后一致**：
```
Page: Add Chips, Stand 按钮
CLI:  Available Actions: (none)  ✓
```

## 技术细节

### Viewport 检查原理

```javascript
const rect = el.getBoundingClientRect();
return (
    rect.top >= 0 &&
    rect.left >= 0 &&
    rect.bottom <= window.innerHeight &&
    rect.right <= window.innerWidth
);
```

这确保按钮在可视区域内，而不是通过 CSS 移到屏幕外。

### 父元素隐藏检测

```javascript
let parent = el.parentElement;
while (parent) {
    const style = window.getComputedStyle(parent);
    if (style.display === 'none' || style.visibility === 'hidden') {
        return parent.className;  // 返回隐藏的父元素类名
    }
    parent = parent.parentElement;
}
```

向上遍历 DOM 树，检查所有祖先元素的可见性。

## 测试验证

运行测试脚本：
```bash
python tests/unit/platforms/test_button_visibility.py
```

输出：
```
=== Testing Button Visibility Checks ===

  ✓ visible=True, viewport=True, parent_hidden=False, disabled=False, opacity=1.0
      -> available=True (expected: True)
  ✓ visible=False, ... -> available=False
  ✓ ..., viewport=False, ... -> available=False
  ✓ ..., parent_hidden=True, ... -> available=False
  ✓ ..., disabled=True, ... -> available=False
  ✓ ..., opacity=0.4 -> available=False
  ✓ ..., opacity=0.6 -> available=True

All button visibility tests passed! ✓
```

## 相关文件

- **修改文件**: `src/platforms/browser/adapters/replay_poker.py` (第 619-675 行)
- **测试文件**: `tests/unit/platforms/test_button_visibility.py`
- **快照**: `data/snapshots/snap_1780746845/table_16902442.html`
- **文档**: `docs/my_turn_fix.md`

## 经验总结

### Web 自动化中的可见性判断

在 Web 自动化中，判断一个元素是否"可用"需要考虑多个层面：

1. **DOM 存在** ≠ **可见**
2. **可见** ≠ **在屏幕上**
3. **在屏幕上** ≠ **可交互**
4. **可交互** ≠ **启用状态**

必须综合检查：
- DOM 结构
- CSS 样式
- JavaScript 状态
- 浏览器渲染

### 最佳实践

✅ **推荐**：
- 多层验证，逐步过滤
- 使用 JavaScript evaluate 进行精确检查
- 记录调试日志，便于排查
- 考虑各种边界情况

❌ **避免**：
- 仅依赖单一检查（如 is_visible）
- 假设 get_by_role 找到的都是可用的
- 忽略父容器的影响
- 不考虑 CSS 样式的复杂性

## 后续改进

1. **性能优化**：viewport 和 parent 检查需要 JavaScript evaluate，可以考虑缓存结果
2. **更多检查**：可以考虑检查 pointer-events、z-index 等
3. **超时处理**：添加超时机制，避免长时间等待
4. **重试逻辑**：对于不稳定的页面，可以添加重试
