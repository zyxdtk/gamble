# 拆分 TableManager 架构实现计划

为了让 AI 机器人在德州扑克自动打牌时逻辑更加清晰、职责更加分明，我们将 [TableManager](file:///Users/ly/Workspace/gitee/gamble/src/bot/table_manager.py#9-521) 拆分为专门负责入座及宏观生命周期的 `LifecycleManager`，以及专门负责牌局内动作收集与执行的 `PlayManager`。同时优化 WebSocket 的重连机制和数据收集流程。

## User Review Required

> [!IMPORTANT]
> - 本次重构涉及核心调度逻辑的拆分，请确认分离为 `LifecycleManager` 与 `PlayManager` 的思路是否符合您的期望。
> - [poker_client.py](file:///Users/ly/Workspace/gitee/gamble/src/bot/poker_client.py) 经检查是一个带有废弃注释的纯空文件，可以直接安全删除。
> - 关于 WebSocket 检测，我们将引入在 [TableManager](file:///Users/ly/Workspace/gitee/gamble/src/bot/table_manager.py#9-521) 入口处先确保 WS 钩子挂载成功，否则不往下流转的机制，这比直接粗暴的 `reload` 更安全优雅。

## Proposed Changes

---

### src/bot/
将把杂乱的 [TableManager](file:///Users/ly/Workspace/gitee/gamble/src/bot/table_manager.py#9-521) 根据状态职责分离出新的管理器组件。

#### [NEW] [lifecycle_manager.py](file:///Users/ly/Workspace/gitee/gamble/src/bot/lifecycle_manager.py)
用于管理“玩牌前”和“离桌”的宏观状态机（Lifecycle）。
- [try_sit_and_buyin()](file:///Users/ly/Workspace/gitee/gamble/src/bot/table_manager.py#331-369)：找空座、点击入座、处理买入弹窗。
- [check_overlays()](file:///Users/ly/Workspace/gitee/gamble/src/bot/table_manager.py#440-449)：检测并处理偶尔出现的 `Sit in`、`I'm back` 蒙层。
- [check_exit_conditions()](file:///Users/ly/Workspace/gitee/gamble/src/bot/table_manager.py#217-253) 和 [leave_table()](file:///Users/ly/Workspace/gitee/gamble/src/bot/table_manager.py#469-503)：包含止损、止盈、筹码过低、以及“桌上仅剩自己一人”的自动离座判断。

#### [NEW] [play_manager.py](file:///Users/ly/Workspace/gitee/gamble/src/bot/play_manager.py)
用于管理“正在玩牌”时的核心数据搜集与策略调用（Play State）。
- [update_state_from_dom()](file:///Users/ly/Workspace/gitee/gamble/src/bot/table_manager.py#120-152)：读取底池、读取盲注。
- 大量数据的分析与汇总将被同步或移交给 [DecisionEngine](file:///Users/ly/Workspace/gitee/gamble/src/engine/decision_engine.py#16-540) 进行维护与判断。
- [find_action_buttons()](file:///Users/ly/Workspace/gitee/gamble/src/bot/table_manager.py#205-216) & [perform_click()](file:///Users/ly/Workspace/gitee/gamble/src/bot/table_manager.py#450-468)：识别当前是否轮到自己行动，并将决策引擎的 [decision](file:///Users/ly/Workspace/gitee/gamble/src/engine/strategies.py#37-45) 指令转化为对界面按钮的点击。

#### [MODIFY] [table_manager.py](file:///Users/ly/Workspace/gitee/gamble/src/bot/table_manager.py)
降级为“协调者”（Coordinator）的角色。
- 保留 WebSocket 的监听与解析，随时维护更新公共共享的 [GameState](file:///Users/ly/Workspace/gitee/gamble/src/core/game_state.py#29-77)。
- 新增 `ensure_websocket_hook` 逻辑：如果监控不到 WS 流量则触发重连/Reload。
- 它的 [execute_turn](file:///Users/ly/Workspace/gitee/gamble/src/bot/table_manager.py#387-439) 主循环现在变成：检查 `LifecycleManager` 是否已稳定处于“正在玩”状态；如果尚未入座/触发了离席条件则交由生命周期接管；如果正在游戏中且轮到自己，则将其交给 `PlayManager` 和 [DecisionEngine](file:///Users/ly/Workspace/gitee/gamble/src/engine/decision_engine.py#16-540) 去发号施令。

#### [DELETE] [poker_client.py](file:///Users/ly/Workspace/gitee/gamble/src/bot/poker_client.py)
- 删除此遗留废弃文件。

---

### WebSocket & Reliability Improvements
为了解决偶尔出现的 WebSocket 钩子挂载失败导致数据无法同步的问题：
- **Hook Detection**: 在 `TableManager.initialize()` 中，检测当前 URL 是否包含 `/table/`。如果是，则强制执行一次 `page.reload()`，确保 Playwright 的 `page.on("websocket")` 监听器在流量产生前已就绪。
- **Heartbeat & Watchdog**: `TableManager` 将记录最后一次收到有效 WS 数据帧的时间。如果超过 30 秒无数据且 `PlayManager` 检测到游戏正在进行，则触发自动重连逻辑。

## Implementation Roadmap

### Phase 1: Infrastructure & Component Extraction
- [ ] 创建 `LifecycleManager` 和 `PlayManager` 类定义。
- [ ] 将 `TableManager` 中对应的逻辑块（入座、离座检测、DOM 解析、动作点击）平移至新组件。
- [ ] 确保 `TableManager` 作为唯一数据持有者，通过 `self` 引用传递给子管理器。

### Phase 2: Refactoring TableManager Loop
- [ ] 重构 `TableManager.execute_turn()`，逻辑改为：
  1. `LifecycleManager.check_overlays()` (处理弹窗)
  2. `LifecycleManager.try_sit_and_buyin()` (确保入座)
  3. `LifecycleManager.check_exit_conditions()` (止损止盈检查)
  4. `PlayManager.update_state_from_dom()` (同步 DOM 数据)
  5. 若轮到自己，则调用 `PlayManager.perform_click()` 执行决策。

### Phase 3: WebSocket Reliability
- [ ] 实现 `initialize()` 中的强制重载逻辑。
- [ ] 在 `handle_ws_frame` 中添加数据有效性校验，避免脏数据污染 `GameState`。

### Phase 4: Integration & Testing
- [ ] 运行 `tests/bot/test_gto_two_cycle.py` 验证完整链路。
- [ ] 手动模拟“断线”和“空桌”场景，测试 `LifecycleManager` 的自动离场逻辑。

## Risks & Mitigations
- **DOM Selector Fragility**: 网页结构变化可能导致 `PlayManager` 解析失败。
  - *Mitigation*: 优先使用 WebSocket 数据，DOM 解析仅作为补充（如检测庄家位、底池校对）。
- **State Sync Issues**: 拆分后可能存在数据同步延迟。
  - *Mitigation*: `GameState` 保持单例或由 `TableManager` 统一维护，子组件只读或通过方法更新。

## Verification Plan

### Automated Tests
1. **单元验证**：代码重构后，运行 `pytest tests/bot/test_gto_two_cycle.py -m integration -v -s`，测试应当能够顺利启动进入大厅并找到座位坐下（LifecycleManager 负责）。
2. **状态机过渡**：日志将严格打印出通过 LifecycleManager 成功 `buy-in` 后，再进入等待发牌、最后切换至 `PlayManager` 接管执行下注动作的无缝转换。
3. **安全离场**：若同局只剩自己一人，`LifecycleManager` 将成功触发 [Leave](file:///Users/ly/Workspace/gitee/gamble/tests/bot/test_table_manager.py#274-348) 逻辑。
