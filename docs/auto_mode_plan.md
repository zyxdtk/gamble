# 自动模式 (Auto Mode) 实施计划

## 目标
让 AI 不仅能给出建议，还能直接操作浏览器进行游戏（弃牌、跟注、加注）。

## 1. 按钮识别策略 (`src/poker_client.py`)
由于 `debug_state.html` 中没有捕捉到行动按钮（因为截图时可能不是轮到我方行动），我们需要能够在运行时动态查找按钮。

- **目标元素**: 包含 "Fold", "Call", "Check", "Raise", "Bet", "All In" 文本的按钮。
- **定位方法**:
    - 使用 Playwright 的 `page.get_by_text(..., exact=True)` 或 `page.locator("button", has_text=...)`。
    - 结合 CSS 类名（如 `.Button`, `.ActionControls` 等，需实地观察）。
    - **安全机制**: 点击前再次确认是否轮到自己行动 (`is_acting` 状态)。

## 2. 自动操作逻辑
- **新建方法**: `execute_decision(decision: str)`
    - 解析 `decision` 字符串（例如 "RAISE/CALL"）。
    - 优先尝试执行主要建议（如 "RAISE"）。
    - 如果找不到主要按钮（如因为资金不足无法 Raise），则回退到次要建议（如 "CALL"）。
    - 如果所有建议都无法执行，则默认 "CHECK" 或 "FOLD"。

## 3. 代码变更计划

### `src/poker_client.py`
- [NEW] `find_action_buttons()`: 返回当前可见的操作按钮字典 `{ "fold": locator, "call": locator ... }`。
- [NEW] `click_button(action_name)`: 封装点击逻辑，包含重试和错误处理。
- [MODIFY] `main()` 循环:
    - 检查 `client.state.is_acting`。
    - 如果为 `True` 且 `auto_mode_enabled` 为 `True`:
        - 调用 `decision_engine.decide(state)`。
        - 调用 `execute_decision(decision)`。

## 4. 风险控制
- **确认对话框**: 某些高额操作可能会弹出确认框，需要处理。
- **延迟**: 在操作前增加随机延迟（0.5s - 2s），模拟人类行为，防封号。

## 验证
- 在 Play Money 桌上测试。
- 观察日志确动作是否被正确执行。
