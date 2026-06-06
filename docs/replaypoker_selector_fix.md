# ReplayPoker DOM 选择器修复

## 问题描述

用户报告 CLI `state` 命令显示的所有字段都不正确：

```
test-cli> state

--- Game State ---
  Pot: 0                    # ❌ 应该是 29
  Community Cards: []       # ❌ 应该是 [4c, 8s, 2d]
  My Seat: None             # ❌ 应该是 4
  To Call: 0                # ❌ 应该根据按钮提取
  Min Raise: 0              # ❌ 应该根据按钮提取
  My Turn: False            # ❌ 应该是 True（有 Fold/Check/Bet 按钮）
  Available Actions: (none) # ❌ 应该有 fold/check/bet
```

但快照分析显示页面实际状态为：
- ✅ **底池值**：29（在 `.Stack__value span` 中）
- ✅ **社区牌**：4c 8s 2d（从聊天记录 "Dealt to board: [ 4c 8s 2d ]"）
- ✅ **我的座位**：Position--4（通过 `.Seat--currentUser` 和 `Position--4`）
- ✅ **动作按钮**：Fold、Check、Bet 10（在 `.BettingControls__actions button` 中）
- ✅ **当前行动者**：`Seat--currentPlayer Seat--currentUser`

## 根本原因

代码使用了错误的 CSS 选择器，这些选择器可能是针对其他平台设计的，但不适用于 ReplayPoker：

| 字段 | 错误的选择器 | 正确的选择器 |
|------|------------|------------|
| 底池值 | `.Pot__value` | `.Stack__value span` |
| 公共牌 | `.CommunityCard` | `.Cards .Card--withValue` 或聊天消息 |
| 我的座位 | `.Seat--me` | `.Seat--currentUser` |
| 座位ID | `Seat--(\d+)` | `Position--(\d+)` |
| 动作按钮 | `.ActionButtons button` | `.BettingControls__actions button` |
| 当前行动者检查 | `.Seat--me` + `active/turn` | `.Seat--currentUser` + `currentPlayer` |

## 修复方案

### 1. 底池值提取

**修复前**：
```python
pot_elem = page.locator(".Pot__value").first
```

**修复后**：
```python
# [FIX] ReplayPoker 使用 .Stack__value 而不是 .Pot__value
pot_elem = page.locator(".Stack__value span").first
```

**HTML 结构**：
```html
<div class="Stack__value">
  <span>29</span>
</div>
```

### 2. 公共牌提取

**修复前**：
```python
card_elems = page.locator(".CommunityCard")
```

**修复后**：
```python
# [FIX] ReplayPoker 的公共牌不在 .CommunityCard 中，需要从聊天消息或 Cards 区域提取
# 方法1: 从 Cards 区域提取可见的牌
card_elems = page.locator(".Cards .Card--withValue")
for i in range(await card_elems.count()):
    card_class = await card_elems.nth(i).get_attribute("class") or ""
    card_match = re.search(r'Card--([A-Z0-9]+)', card_class)
    if card_match:
        community_cards.append(card_match.group(1))

# 方法2: 如果上面没找到，从聊天消息中提取最新的 "Dealt to board"
if not community_cards:
    chat_messages = page.locator(".ChatMessage--dealer")
    last_board_msg = None
    for i in range(await chat_messages.count() - 1, -1, -1):
        msg = chat_messages.nth(i)
        msg_text = await msg.text_content()
        if msg_text and "Dealt to board:" in msg_text:
            last_board_msg = msg_text
            break
    
    if last_board_msg:
        # 提取方括号中的牌，如 "Dealt to board: [ 4c 8s 2d ]"
        board_match = re.search(r'\[\s*([^\]]+)\s*\]', last_board_msg)
        if board_match:
            cards_str = board_match.group(1)
            community_cards = cards_str.split()
```

**HTML 结构**：
```html
<!-- 方法1: Cards 区域 -->
<div class="Cards">
  <div class="Card Card--0 Position Position--4 Card--withValue enter-done">
    ...
  </div>
</div>

<!-- 方法2: 聊天消息 -->
<div class="ChatMessage ChatMessage--dealer">
  <strong class="ChatMessage__username">Dealer:</strong>
  <span class="ChatMessage__message">Dealt to board: [ 4c 8s 2d ]</span>
</div>
```

### 3. 我的座位ID提取

**修复前**：
```python
my_seat_elem = page.locator(".Seat--me").first
seat_id_match = re.search(r'Seat--(\d+)', seat_class)
```

**修复后**：
```python
# [FIX] ReplayPoker 使用 .Seat--currentUser 而不是 .Seat--me
my_seat_elem = page.locator(".Seat--currentUser").first
if await my_seat_elem.count() > 0:
    # 尝试从 class 中提取位置信息，例如 "Position Position--4"
    seat_class = await my_seat_elem.get_attribute("class") or ""
    position_match = re.search(r'Position--(\d+)', seat_class)
    if position_match:
        state["my_seat_id"] = int(position_match.group(1))
```

**HTML 结构**：
```html
<div class="Seat Seat--occupied Position Position--4 Seat--currentPlayer Seat--currentUser">
  ...
</div>
```

### 4. 动作按钮提取

**修复前**：
```python
action_buttons = page.locator(".ActionButtons button")
```

**修复后**：
```python
# [FIX] ReplayPoker 使用 .BettingControls__actions 而不是 .ActionButtons
action_buttons = page.locator(".BettingControls__actions button")
```

**HTML 结构**：
```html
<div class="Footer__actions">
  <div class="BettingControls BettingControls--undefinedLimit">
    <div class="BettingControls__actions">
      <button class="Button BettingControls__action BettingControls__action--defensive">
        <span class="Button__label">Fold</span>
      </button>
      <button class="Button BettingControls__action BettingControls__action--neutral">
        <span class="Button__label">Check</span>
      </button>
      <button class="Button BettingControls__action BettingControls__action--aggressive Button--withValue">
        <span class="Button__label">Bet<br><em>10</em></span>
      </button>
    </div>
  </div>
</div>
```

### 5. My Turn 检测

**修复前**：
```python
my_seat = page.locator(".Seat--me")
if class_name and ("active" in class_name or "turn" in class_name.lower()):
```

**修复后**：
```python
# 方法2: 检查自己座位是否有 "currentPlayer" 样式
my_seat = page.locator(".Seat--currentUser")
if await my_seat.count() > 0:
    class_name = await my_seat.first.get_attribute("class")
    if class_name and ("currentPlayer" in class_name or "active" in class_name or "turn" in class_name.lower()):
        turn_checks.append(True)
```

## 预期效果

修复后，CLI `state` 命令应该正确显示：

```
test-cli> state

--- Game State ---
  Pot: 29
  Community Cards: ['4c', '8s', '2d']
  My Seat: 4
  To Call: 0
  Min Raise: 10
  My Turn: True
  Available Actions: fold, check, bet
```

## 技术要点

### ReplayPoker 的特殊设计

1. **底池值**：使用 `.Stack__value` 而不是常见的 `.Pot__value`
2. **公共牌**：没有专门的 `.CommunityCard` 容器，需要从 `.Cards` 区域或聊天消息中提取
3. **座位标识**：使用 `.Seat--currentUser` 而不是 `.Seat--me`
4. **位置编号**：使用 `Position--N` 而不是 `Seat--N`
5. **动作按钮**：使用 `.BettingControls__actions` 而不是 `.ActionButtons`
6. **当前行动者**：使用 `Seat--currentPlayer` 类名标识

### 容错设计

对于公共牌提取，实现了双重回退机制：
1. **优先**：从 `.Cards .Card--withValue` 直接提取可见的牌
2. **回退**：从聊天消息中解析最新的 "Dealt to board" 记录

这种设计确保即使牌的渲染方式改变，仍然可以从聊天记录中提取。

## 修改文件清单

1. **src/platforms/browser/adapters/replay_poker.py** (第 470-600 行附近)
   - 修复底池值选择器：`.Pot__value` → `.Stack__value span`
   - 修复公共牌选择器：`.CommunityCard` → `.Cards .Card--withValue` + 聊天消息回退
   - 修复座位选择器：`.Seat--me` → `.Seat--currentUser`
   - 修复座位ID提取：`Seat--(\d+)` → `Position--(\d+)`
   - 修复动作按钮选择器：`.ActionButtons button` → `.BettingControls__actions button`
   - 修复 My Turn 检测：检查 `currentPlayer` 类名

## 测试建议

1. 重新启动 CLI
2. 运行 `state` 命令
3. 验证所有字段都正确显示：
   - Pot 应该显示实际底池金额
   - Community Cards 应该显示翻开的公共牌
   - My Seat 应该显示你的座位号（0-5）
   - To Call 和 Min Raise 应该根据按钮文本正确提取
   - My Turn 应该在轮到你时显示 True
   - Available Actions 应该显示真正可用的动作

## 相关文件

- [replay_poker.py](file:///Users/ly/Workspace/gitee/gamble/src/platforms/browser/adapters/replay_poker.py#L470-L600) - 浏览器适配器核心逻辑
- [docs/my_turn_fix.md](file:///Users/ly/Workspace/gitee/gamble/docs/my_turn_fix.md) - My Turn 状态修复历史
- [docs/available_actions_fix.md](file:///Users/ly/Workspace/gitee/gamble/docs/available_actions_fix.md) - Available Actions 修复历史
