# 系统架构设计

## 核心设计模式：Platform-Agent 解耦

系统采用 Platform-Agent 解耦模式：核心层定义接口，平台层和策略层各自独立实现。

```
┌──────────────────────────────────────────────┐
│                  App Layer                    │
│               (src/main.py)                  │
├──────────────────────────────────────────────┤
│               GameRunner                      │
│         (连接 Agent 与 Platform)              │
├────────────────────┬─────────────────────────┤
│    PlayerAgent     │      GamePlatform        │
│   (决策接口)        │     (平台接口)            │
├────────────────────┼─────────────────────────┤
│   Strategy 层      │      Platform 层          │
│  - Range           │  - BrowserPlatform       │
│  - Balanced/GTO    │  - ArenaPlatform         │
│  - Exploitative    │  - RingPlatform          │
│  - Aggressive      │                          │
│  - CheckOrFold     │                          │
│  - Neural (DQN)    │                          │
│  - ICM             │                          │
└────────────────────┴─────────────────────────┘
```

## 三层架构

### 核心层 (`src/core/`)

| 组件 | 说明 |
|------|------|
| `interfaces.py` | `GamePlatform` ABC、`PlayerAgent` ABC、`GameRunner`、`GameState`/`ActionType`/`GameAction`/`Player` |
| `events.py` | `EventType` 枚举、`GameEvent` 数据类、`EventBus` 全局发布订阅 |
| `messaging.py` | `AsyncChannel` 双工通信通道、`MessageType` 枚举、`Message` 数据类 |
| `StrategyToAgentAdapter` | 适配 Strategy 到 PlayerAgent，桥接两套 `GameState`/`ActionType` |

### 策略层 (`src/strategies/`)

| 组件 | 说明 |
|------|------|
| `strategy_base.py` | `Strategy` ABC：`make_decision(state) -> ActionPlan`、`handle_event()` |
| `strategy_manager.py` | `StrategyManager` 单例：自动发现、注册、创建策略 |
| `action_plan.py` | `ActionPlan`：主/备动作、混合策略、尺度建议、安全限制 |
| `game_state.py` | 策略层 `GameState`（比核心层更丰富） |
| `table_strategy.py` | `TableStrategy` ABC + 默认/保守/激进桌位策略 |
| `hand_strategy.py` | `HandStrategy` ABC + `StrategyHandAdapter` 适配器 |
| `strategies/` | 六种策略实现 + ICM 策略 |
| `utils/` | `equity.py`、`board_analyzer.py`、`position.py`、`preflop_range.py` |

### 平台层 (`src/platforms/`)

| 组件 | 说明 |
|------|------|
| `browser/` | `BrowserPlatform`：连接 ReplayPoker，WebSocket + DOM 双通道状态管理 |
| `arena/` | `ArenaPlatform`/`RingPlatform`：本地模拟 |

## 两套平行类型系统

系统存在两套 `GameState` 和 `ActionType`：

| | 核心层 (`src/core/interfaces.py`) | 策略层 (`src/strategies/`) |
|---|---|---|
| `ActionType` 值 | 小写 (`"fold"`) + `BET` | 大写 (`"FOLD"`)，无 `BET` |
| `GameState` | 平台无关，`available_actions: List[ActionType]` | 更丰富，`available_actions: List[str]`，含 `hand_strength` 等 |
| `Player` | 基础字段 | 额外 `last_action`、`street_actions`、`perceived_range` |

`StrategyToAgentAdapter` 桥接这两套类型系统。

## 核心数据流

```
GameState (src/strategies/game_state.py)  --  策略专用，更丰富
   ├── Strategy.make_decision(state) -> ActionPlan
   │     └── ActionPlan.get_action_for_bet(to_call, pot) -> (ActionType, amount)
   ├── ArenaAgent._translate_state(arena) -> GameState
   └── StrategyToAgentAdapter._convert_to_strategy_state(core) -> GameState
```

## EventBus 与 AsyncChannel

| | EventBus | AsyncChannel |
|---|---|---|
| 用途 | 全局广播（日志、统计） | Platform 与特定 Player 之间的指令级通信 |
| 模式 | 发布-订阅，一对多 | 点对点，请求-响应 |
| 使用场景 | 所有模式 | Ring Game |
| 实现 | `subscribe()` / `publish()` | `send_to_player()` / `request_response()` |
