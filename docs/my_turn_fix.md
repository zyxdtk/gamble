# My Turn 状态识别修复说明

## 问题描述

在 CLI 中执行 `state` 命令时，发现多个字段显示不正确：

```
test-cli> actions

=== Available Actions ===
Actions:
  • fold
  • call (2)
  • raise <amount>|min|half|pot|max
    (min: 4)

test-cli> state

--- Game State ---
  Pot: 46
  Community Cards: []          # <-- 应该是实际的公共牌，如 ['AS', 'KH']
  My Seat: None                # <-- 应该显示座位ID，如 3
  To Call: 0                   # <-- 应该是 2
  Min Raise: 0                 # <-- 应该是 4
  My Turn: False               # <-- 应该是 True
  Available Actions: (waiting for turn)  # <-- 明明有可用动作！
```

**问题**：多个关键字段都显示不正确或为空。

## 根本原因分析

### 核心问题：数据源不一致

CLI 使用的是 `BrowserPlatform.get_game_state()`，它从浏览器适配器的 DOM 解析获取数据。
但是浏览器适配器的 `get_game_state()` 方法只提取了很少的字段（主要是 pot 和 is_my_turn）。

其他关键字段如 `community_cards`、`my_seat_id`、`to_call`、`min_raise` 都没有从 DOM 中提取，
导致这些字段始终显示为默认值（空列表、None、0）。

### 问题点 1: PlayManager 状态更新不完整

在 `src/bot/play_manager.py` 的 `update_state_from_dom()` 方法中：

**修复前**：
```python
buttons = await self.find_action_buttons()
self.tm.state.available_actions = list(buttons.keys())

# 如果找到操作按钮，说明轮到我行动
if buttons and self.tm.state.my_seat_id is not None:
    my_player = self.tm.state.players.get(self.tm.state.my_seat_id)
    if my_player:
        my_player.is_acting = True  # ✓ 设置为 True
        self.tm.state.active_seat = self.tm.state.my_seat_id
# ❌ 缺少：当没有按钮时，应该清除 is_acting
```

**问题**：只在检测到按钮时设置 `is_acting = True`，但没有在按钮消失时清除该标志。这导致状态可能保持为 `True` 即使已经不在玩家的回合。

### 问题点 2: 浏览器适配器状态提取不完整

在 `src/platforms/browser/adapters/replay_poker.py` 的 `get_game_state()` 方法中：

**修复前**：
```python
async def get_game_state(self, page: Page) -> Dict[str, Any]:
    state = {
        "pot": 0,
        "community_cards": [],      # ❌ 没有从 DOM 提取
        "my_seat_id": None,         # ❌ 没有从 DOM 提取
        "is_my_turn": False,
        "to_call": 0,               # ❌ 没有从 DOM 提取
        "min_raise": 0,             # ❌ 没有从 DOM 提取
        "players": {}
    }
    try:
        pot_elem = page.locator(".Pot__value").first
        # ... 只提取了 pot
        # ... 只检测了 is_my_turn
        # 其他字段都没有提取！
```

**问题**：只提取了 `pot` 和 `is_my_turn`，其他关键字段都是默认值。

## 解决方案

### 修复 1: PlayManager 双向同步

在 `src/bot/play_manager.py` 中添加逻辑，确保 `is_acting` 与按钮存在性保持同步：

```python
buttons = await self.find_action_buttons()
self.tm.state.available_actions = list(buttons.keys())

# [FIX] 如果找到操作按钮，说明轮到我行动
if buttons and self.tm.state.my_seat_id is not None:
    my_player = self.tm.state.players.get(self.tm.state.my_seat_id)
    if my_player:
        my_player.is_acting = True
        self.tm.state.active_seat = self.tm.state.my_seat_id
elif not buttons:
    # [FIX] 如果没有可用按钮，确保清除 acting 状态
    if self.tm.state.my_seat_id is not None:
        my_player = self.tm.state.players.get(self.tm.state.my_seat_id)
        if my_player:
            my_player.is_acting = False
```

**效果**：
- 有按钮 → `is_acting = True` → `is_my_turn = True`
- 无按钮 → `is_acting = False` → `is_my_turn = False`

### 修复 2: 浏览器适配器完整状态提取

在 `src/platforms/browser/adapters/replay_poker.py` 中添加完整的 DOM 提取逻辑：

```python
async def get_game_state(self, page: Page) -> Dict[str, Any]:
    state = {
        "pot": 0,
        "community_cards": [],
        "my_seat_id": None,
        "is_my_turn": False,
        "to_call": 0,
        "min_raise": 0,
        "players": {}
    }
    try:
        # 1. 提取底池
        pot_elem = page.locator(".Pot__value").first
        if await pot_elem.count() > 0:
            pot_text = await pot_elem.text_content(timeout=500)
            if pot_text:
                val = re.sub(r"[^\d]", "", pot_text)
                if val:
                    state["pot"] = int(val)
        
        # 2. 提取公共牌
        community_cards = []
        card_elems = page.locator(".CommunityCard")
        for i in range(await card_elems.count()):
            card_class = await card_elems.nth(i).get_attribute("class") or ""
            # 从 class 中提取牌面信息，例如 "Card Card--AS" -> "AS"
            card_match = re.search(r'Card--([A-Z0-9]+)', card_class)
            if card_match:
                community_cards.append(card_match.group(1))
        state["community_cards"] = community_cards
        
        # 3. 提取我的座位ID
        my_seat_elem = page.locator(".Seat--me").first
        if await my_seat_elem.count() > 0:
            seat_class = await my_seat_elem.get_attribute("class") or ""
            seat_id_match = re.search(r'Seat--(\d+)', seat_class)
            if seat_id_match:
                state["my_seat_id"] = int(seat_id_match.group(1))
        
        # 4. 提取 to_call 和 min_raise
        action_buttons = page.locator(".ActionButtons button")
        for i in range(await action_buttons.count()):
            btn = action_buttons.nth(i)
            if not await btn.is_visible():
                continue
            
            btn_text = await btn.text_content()
            if not btn_text:
                continue
            
            # 提取 Call 按钮的金额
            if re.search(r'\bCall\b', btn_text, re.IGNORECASE):
                digits = re.sub(r"[^\d]", "", btn_text)
                if digits:
                    state["to_call"] = int(digits)
            
            # 提取 Raise/Bet 按钮的最小金额
            if re.search(r'\b(Raise|Bet)\b', btn_text, re.IGNORECASE):
                digits = re.sub(r"[^\d]", "", btn_text)
                if digits:
                    state["min_raise"] = int(digits)
```

**效果**：现在可以从 DOM 中提取所有关键字段。

### 修复 3: 放宽浏览器适配器的判断条件

在 `src/platforms/browser/adapters/replay_poker.py` 中放宽判断条件：

```python
# 需要至少2个条件满足才认为是用户的回合
if len(turn_checks) >= 2:
    state["is_my_turn"] = True
elif len(turn_checks) == 1 and await page.locator(".ActionButtons button").count() > 0:
    # [FIX] 如果只有一个turn检查通过，但有可用的操作按钮，也认为是用户回合
    action_buttons = page.locator(".ActionButtons button")
    for i in range(await action_buttons.count()):
        btn = action_buttons.nth(i)
        disabled = await btn.get_attribute("disabled")
        if disabled is None:  # 有可点击的按钮
            state["is_my_turn"] = True
            break
```

**效果**：即使只检测到 1 个回合指示器，只要有可用的操作按钮，也判定为玩家回合。

## 验证测试

运行验证脚本确认修复效果：

```bash
python tests/unit/bot/verify_my_turn_fix.py
```

输出示例：
```
=== Testing is_my_turn Logic ===

Test 1: No player info
  is_my_turn: False
  ✓ PASS

Test 2: Player exists but is_acting = False
  is_acting: False
  is_my_turn: False
  ✓ PASS

Test 3: Player exists and is_acting = True
  is_acting: True
  is_my_turn: True
  ✓ PASS

All tests passed! ✓

Scenario Simulation:
  Initial: is_acting=False, is_my_turn=False

  [Action buttons appear]
  -> Result: is_acting=True, is_my_turn=True

  [Action buttons disappear]
  -> Result: is_acting=False, is_my_turn=False

✓ State synchronization fixed!
```

## 修改文件清单

1. **src/bot/play_manager.py** (第 69-80 行附近)
   - 添加了清除 `is_acting` 的逻辑
   - 确保状态双向同步

2. **src/platforms/browser/adapters/replay_poker.py** (第 470-600 行附近)
   - 添加了完整的 DOM 状态提取逻辑
   - 提取社区牌、座位ID、to_call、min_raise 等字段
   - 放宽了回合检测条件

3. **src/platforms/browser/adapters/replay_poker.py** (第 619-675 行附近)
   - [FIX] 添加按钮禁用状态检测
   - 检查 `disabled` 属性
   - 检查 `opacity` 样式（< 0.5 视为禁用）
   - 确保只将真正可用的按钮添加到 available 列表

4. **src/platforms/browser/adapters/replay_poker.py** (第 619-675 行附近)
   - [FIX] 添加多重可见性检查（5层验证）
   - 检查 is_visible()
   - 检查是否在 viewport 内
   - 检查父元素是否隐藏（如 .AwaitTurn 容器）
   - 检查 disabled 属性
   - 检查 opacity 样式
   - 解决 "Please wait for next hand" 时仍显示动作的问题

5. **src/platforms/browser/adapters/replay_poker.py** (第 749-775 行附近)
   - [FIX] sit_in 方法增加对 "Sit Out" 状态的处理
   - 检测并取消勾选 "Sit Out Next Hand" 复选框
   - 支持从 Sit Out 状态恢复到 Sit In 状态

6. **src/platforms/browser/test_cli.py** (第 519-536 行附近)
   - [FIX] state 命令改用 `get_all_visible_actions()` 而不是 `get_available_actions()`
   - 确保 Available Actions 始终显示页面上可见的动作，不受 is_my_turn 限制
   - 修改提示文本从 "(waiting for turn)" 改为 "(none)"

## 预期效果

修复后，CLI 中的状态显示应该全部正确：

### 场景1: 轮到你行动时
```
test-cli> state

--- Game State ---
  Pot: 46
  Community Cards: ['AS', 'KH']   # ✓ 现在正确显示公共牌
  My Seat: 3                      # ✓ 现在正确显示座位ID
  To Call: 2                      # ✓ 现在正确显示跟注金额
  Min Raise: 4                    # ✓ 现在正确显示最小加注
  My Turn: True                   # ✓ 现在正确显示轮次状态
  Available Actions: fold, call, raise  # ✓ 显示真正可用的动作
```

### 场景2: 不轮到你行动时
```
test-cli> state

--- Game State ---
  Pot: 30
  Community Cards: []
  My Seat: None
  To Call: 0
  Min Raise: 0
  My Turn: False                  # ✓ 正确显示不是你的回合
  Available Actions: (none)       # ✓ 正确显示没有可用动作（之前错误显示 raise）
```

## 技术要点

- **状态同步**：`is_acting` 标志必须与实际的 UI 状态（按钮存在性）保持同步
- **双向更新**：不仅要设置状态为 True，还要在条件不满足时清除状态
- **DOM 提取**：从 HTML 元素的 class、text 等属性中提取游戏状态信息
- **正则解析**：使用正则表达式从 CSS class 和按钮文本中提取结构化数据
- **按钮状态检测**：
  - 检查 `disabled` 属性判断是否禁用
  - 检查 `opacity` 样式判断是否灰色（< 0.5 视为禁用）
  - 确保只将真正可用的按钮添加到 available 列表
- **容错处理**：放宽判断条件以提高鲁棒性，避免因单一检测失败导致状态错误
