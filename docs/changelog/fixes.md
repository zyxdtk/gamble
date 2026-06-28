# 历史修复记录

本文档记录了各版本中的重要 bug 修复和技术改进。

## 2026-06-28 修复

### 策略别名机制 + gto 创建失败

**问题**：配置用 `gto`，但策略文件 `gto_solver.py` 注册键是 `gtosolver`，`create_strategy("gto")` 返回 None → 回退到 balanced，bot 实际打的是 balanced 而非 GTO。

**修复**：
- `Strategy` 基类新增 `strategy_aliases: list = []` 类属性
- `StrategyManager._register_strategy_class` 注册时同时注册所有别名（含版本化键）
- `GtoSolverStrategy.strategy_aliases = ["gto"]`

**相关文件**：`src/strategies/strategy_base.py`、`src/strategies/strategy_manager.py`、`src/strategies/strategies/gto_solver.py`

---

### 桌子满员卡住不换桌

**问题**：桌子满员时 `_check_and_sit_in` 返回 False，主循环只是 poll 等待，无卡住检测、无换桌逻辑，bot 一直卡着不动。

**修复**（`src/platforms/browser/auto_player.py`）：
- `__init__` 新增 `_stuck_counter` / `_stuck_threshold`(默认30) / `_consecutive_switches` / `_max_consecutive_switches`(默认5)
- `_game_loop` 捕获 `_check_and_sit_in` 返回值，未入座+无动作时计数，达到阈值调用 `_switch_table()`
- 新增 `_switch_table()`: leave_table → remove_strategy → 重置状态 → open_table → create_strategy → 重建 PilotDecider
- 连续换桌 5 次仍失败则等 60s；无可用桌子等 30s

**配置**（`config/settings.yaml`）：
```yaml
auto_mode:
  stuck_threshold: 30
  max_table_switches: 5
```

---

### Raise 金额超出筹码导致按钮置灰

**问题**：对手 all-in 金额大于自身筹码时，策略返回超出筹码的 raise 金额（如 `to_call*3`），ReplayPoker 把 Raise 按钮置灰，点击无效却 `return True` 静默失败。

**根因**：
1. `browser_state_to_payload` 缺 `my_chips` 字段 → 策略层 `state.total_chips=0`，不知道自己筹码量
2. 策略计算 raise 金额未钳制到自身筹码（`gto_solver.py` 用 `to_call*3` / `pot*0.75`）
3. 面对 `to_call >= my_chips` 时规则上不能 raise，但策略没有这个前置判断
4. 执行层只查 `is_visible()` 不查 `is_disabled()`

**修复**（诊断日志，3 处）：
- `src/core/payload.py`: payload 补 `my_chips` 字段（从 `players[my_seat].chips`）
- `src/platforms/browser/auto_player.py::_choice_to_game_action`: 检测情形 A（超额 all-in 仍 raise）和情形 B（amount > my_chips）打 WARNING
- `src/platforms/browser/adapters/replay_poker.py::execute_action`: raise 前检查 disabled/opacity，置灰时 return False

**后续可选根治**：在 `ActionPlan.get_action_for_bet` 或 `_choice_to_game_action` 加 `amount = min(amount, my_chips)`；`to_call >= my_chips` 时强制 CALL/ALL_IN 而非 RAISE。

---

## 可见性检测修复

### 问题描述
CLI 在非自己回合时也显示可用动作。

### 根因
Playwright `get_by_role` 找到了 DOM 中存在但视觉上隐藏的按钮（如 `.AwaitTurn` 容器内的按钮）。

### 修复方案
实现 5 层可见性检测：
1. `is_visible()` — Playwright 原生
2. 视口边界检查 — `getBoundingClientRect()` 是否在可见区域
3. 父元素隐藏检测 — `.AwaitTurn` 等容器
4. `disabled` 属性检测
5. `opacity` 阈值检测 — 低于 0.5 视为不可见

### 相关文件
- `src/platforms/browser/adapters/`

---

## Sit Out 状态修复

### 问题描述
`sit_in` 命令在 Sit Out 状态下失败。

### 根因
ReplayPoker 有两种"离开"状态：Stand（完全站起，有 Sit In 按钮）和 Sit Out（勾选了 "Sit Out Next Hand"，无 Sit In 按钮）。原代码只检测了 Sit In 按钮。

### 修复方案
`sit_in()` 方法按优先级尝试三种检测：
1. 基于 class 的 Sit In 按钮检测
2. 基于文本的 Sit In 按钮检测
3. 取消勾选 "Sit Out Next Hand" 复选框（`.Footer__settings--sittingOut .CheckBox.CheckBox--checked`）

### 相关文件
- `src/platforms/browser/adapters/`

---

## 状态检测修复

### 问题描述
CLI `state` 命令显示的多个字段不正确：公共牌、座位 ID、to_call、min_raise、is_my_turn。

### 根因
1. DOM 提取不完整 — CSS 选择器未适配 ReplayPoker
2. `is_acting` 状态未正确清理
3. 回合检测条件过于严格

### 修复方案
1. PlayManager 双向同步 `is_acting` 状态
2. 完整 DOM 状态提取（底牌从 CSS class、座位从 `.Seat--me`、金额从按钮文本）
3. 放松回合检测条件

### ReplayPoker 选择器映射

| 数据 | 旧选择器 | 正确选择器 |
|------|----------|------------|
| 底池 | `.Pot__value` | `.Stack__value span` |
| 公共牌 | `.CommunityCard` | `.Cards .Card--withValue` |
| 我的座位 | `.Seat--me` | `.Seat--currentUser` |
| 座位号 | `Seat--(\d+)` | `Position--(\d+)` |
| 动作按钮 | `.ActionButtons button` | `.BettingControls__actions button` |

### 相关文件
- `src/platforms/browser/adapters/`
- `src/bot/`

---

## 浏览器平台重构

### 变更内容
- `cli_ws_listener.py` → `websocket_listener.py`
- `dual_channel_manager.py` → `state_manager.py`
- 移除 CLI 特定前缀命名

### 设计原则
- 平台层组件不应包含 CLI 特定命名
- 通过 `BrowserInterface` 门面统一访问
- `src/bot/` 为遗留代码，`src/platforms/browser/` 为新架构
