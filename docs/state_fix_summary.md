# 状态识别修复总结

## 问题概述

在 CLI 中执行 `state` 命令时，多个关键字段显示不正确：
- Community Cards: [] (应该是实际的公共牌)
- My Seat: None (应该显示座位ID)
- To Call: 0 (应该是实际跟注金额)
- Min Raise: 0 (应该是最小加注金额)
- My Turn: False (应该是 True，因为有可用动作)
- **Available Actions: raise** (❌ 错误！即使不轮到你，也显示了禁用的 raise 按钮)

## 根本原因

1. **数据源不一致**：CLI 使用浏览器适配器的 DOM 解析，但该适配器只提取了很少的字段
2. **状态同步缺失**：`is_acting` 标志没有与按钮存在性保持双向同步
3. **DOM 提取不完整**：缺少对社区牌、座位ID、to_call、min_raise 等字段的提取逻辑
4. **按钮状态检测缺失**：没有检查按钮是否被禁用（disabled 属性或 opacity 样式），导致禁用的按钮也被视为可用

## 修复方案

### 1. PlayManager 双向同步 (src/bot/play_manager.py)

```python
# 当检测到按钮时设置 is_acting = True
if buttons and self.tm.state.my_seat_id is not None:
    my_player = self.tm.state.players.get(self.tm.state.my_seat_id)
    if my_player:
        my_player.is_acting = True
        
# [新增] 当没有按钮时清除 is_acting = False  
elif not buttons:
    if self.tm.state.my_seat_id is not None:
        my_player = self.tm.state.players.get(self.tm.state.my_seat_id)
        if my_player:
            my_player.is_acting = False
```

### 2. 浏览器适配器完整状态提取 (src/platforms/browser/adapters/replay_poker.py)

添加了以下 DOM 提取逻辑：

#### a) 公共牌提取
```python
# 从 .CommunityCard 元素提取牌面信息
card_elems = page.locator(".CommunityCard")
for i in range(await card_elems.count()):
    card_class = await card_elems.nth(i).get_attribute("class") or ""
    # 从 "Card Card--AS" 中提取 "AS"
    card_match = re.search(r'Card--([A-Z0-9]+)', card_class)
    if card_match:
        community_cards.append(card_match.group(1))
```

#### b) 座位ID提取
```python
# 从 .Seat--me 元素提取座位ID
my_seat_elem = page.locator(".Seat--me").first
if await my_seat_elem.count() > 0:
    seat_class = await my_seat_elem.get_attribute("class") or ""
    # 从 "Seat Seat--me Seat--3" 中提取 3
    seat_id_match = re.search(r'Seat--(\d+)', seat_class)
    if seat_id_match:
        state["my_seat_id"] = int(seat_id_match.group(1))
```

#### c) to_call 和 min_raise 提取
```python
# 从按钮文本中提取金额
action_buttons = page.locator(".ActionButtons button")
for i in range(await action_buttons.count()):
    btn_text = await btn.text_content()
    
    # 提取 Call 金额："Call 2" -> 2
    if re.search(r'\bCall\b', btn_text, re.IGNORECASE):
        digits = re.sub(r"[^\d]", "", btn_text)
        if digits:
            state["to_call"] = int(digits)
    
    # 提取 Raise/Bet 金额："Raise 4" -> 4
    if re.search(r'\b(Raise|Bet)\b', btn_text, re.IGNORECASE):
        digits = re.sub(r"[^\d]", "", btn_text)
        if digits:
            state["min_raise"] = int(digits)
```

### 3. 放宽回合检测条件 (src/platforms/browser/adapters/replay_poker.py)

```python
# 原来需要至少2个条件满足
if len(turn_checks) >= 2:
    state["is_my_turn"] = True
# [新增] 现在1个条件 + 可用按钮也可以
elif len(turn_checks) == 1 and has_available_buttons:
    state["is_my_turn"] = True
```

### 4. 按钮禁用状态检测 (src/platforms/browser/adapters/replay_poker.py)

```python
for action_name, button_regex in targets.items():
    btn = page.get_by_role("button", name=re.compile(button_regex, re.IGNORECASE))
    if await btn.count() > 0:
        first_btn = btn.first
        if await first_btn.is_visible():
            # [FIX] 检查按钮是否被禁用（灰色状态）
            disabled = await first_btn.get_attribute("disabled")
            if disabled is None:  # None 表示没有 disabled 属性，即可用
                # 再检查样式中的 opacity，如果太低说明是禁用状态
                style = await first_btn.get_attribute("style") or ""
                opacity_match = re.search(r'opacity:\s*([\d.]+)', style)
                if opacity_match:
                    opacity = float(opacity_match.group(1))
                    if opacity < 0.5:  # 透明度过低，视为禁用
                        continue
                actions["available"].append(action_name)
```

**效果**：现在能正确过滤掉禁用的按钮，只显示真正可用的动作。

## 修改的文件

1. **src/bot/play_manager.py** (第 69-80 行)
   - 添加 is_acting 清除逻辑

2. **src/platforms/browser/adapters/replay_poker.py** (第 470-600 行)
   - 添加完整的 DOM 状态提取
   - 放宽回合检测条件

3. **src/platforms/browser/adapters/replay_poker.py** (第 619-635 行)
   - [FIX] 添加按钮禁用状态检测
   - 检查 disabled 属性和 opacity 样式

4. **src/platforms/browser/test_cli.py** (第 519-536 行)
   - [FIX] state 命令改用 `get_all_visible_actions()`
   - 确保 Available Actions 始终显示可见动作

5. **docs/my_turn_fix.md**
   - 详细的问题分析和修复说明文档

6. **docs/cli_commands_explanation.md**
   - 解释 state 和 actions 命令的区别

## 验证测试

运行验证脚本：
```bash
python tests/unit/bot/verify_my_turn_fix.py
python tests/unit/platforms/test_state_extraction.py
python tests/unit/platforms/test_button_disabled.py  # [新增] 按钮禁用检测测试
```

所有测试通过 ✓

## 预期效果

修复后，CLI 状态显示将完全正确：

```
--- Game State ---
  Pot: 46
  Community Cards: ['AS', 'KH']   ✓
  My Seat: 3                      ✓
  To Call: 2                      ✓
  Min Raise: 4                    ✓
  My Turn: True                   ✓
  Available Actions: fold, call, raise  ✓
```

## 技术亮点

1. **正则表达式解析**：从 CSS class 和按钮文本中提取结构化数据
2. **DOM 遍历**：使用 Playwright 的定位器遍历页面元素
3. **状态同步**：确保内部状态与 UI 状态保持一致
4. **容错设计**：多种提取方法回退，提高鲁棒性
5. **按钮状态检测**：
   - 检查 `disabled` HTML 属性
   - 检查 `opacity` CSS 样式
   - 双重验证确保准确识别禁用状态

## 后续改进建议

1. 考虑添加 WebSocket 支持，获取更准确的状态更新
2. 增加更多的 DOM 选择器回退方案
3. 添加状态变化的日志记录，便于调试
4. 考虑缓存提取结果，提高性能
