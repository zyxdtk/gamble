# Texas Hold'em AI Design Document

## 1. 项目概述 (Project Overview)
本项目旨在开发一个针对 [ReplayPoker.com](https://www.replaypoker.com/) 的德州扑克 AI 助手。该系统将通过浏览器自动化工具 (Playwright) 与游戏交互，通过网络嗅探 (WebSocket) 获取实时游戏数据，并提供决策支持（辅助模式）或自动操作（自动模式）。

## 2. 系统架构 (System Architecture)

系统主要由以下四个层级组成：

1.  **浏览器层 (Browser Layer)**
    - 使用 **Playwright** 启动 Chrome 浏览器。
    - 负责加载游戏页面、维持会话、处理页面重载。
    - 提供 DOM 访问接口。

2.  **数据采集层 (Data Acquisition Layer)**
    - **WebSocket 监听**: 拦截浏览器与服务器之间的 WebSocket 通信帧，提取核心游戏状态（如手牌、公共牌）。
    - **DOM 解析**: 解析网页元素获取可见信息（如底池大小、当前行动玩家、按钮状态）。
    - **控制台监听**: 作为备用方案，利用浏览器的 `console.log` 信息。

3.  **决策层 (Decision Layer)**
    - **GameState**: 整合所有来源的数据，维护当前局势的完整状态。
    - **DecisionEngine**: 核心逻辑单元。接收 `GameState`，输出 `Action` (Fold, Check, Call, Raise)。
        - *初期策略*:基于手牌强度和位置的基础策略。
        - *后期策略*: 引入概率计算 (Pot Odds, EV) 和对手模型。

4.  **执行层 (Excution Layer)**
    - **Assist Mode**: 将决策建议输出到终端，供用户参考。
    - **Auto Mode**: 通过 Playwright 模拟点击操作，执行决策。

## 3. 模块设计 (Module Design)

### 3.1 `src/poker_client.py`
负责与浏览器交互的核心类 `ReplayPokerClient`。
- `start_browser()`: 启动和配置浏览器。
- `attach_network_listeners()`: 挂载 WebSocket 钩子。
- `get_game_state()`: 返回当前的 `GameState` 对象。
- `execute_action(action)`: 在页面上执行点击操作。

### 3.2 `src/decision_engine.py`
负责扑克逻辑的类 `DecisionEngine`。
- `evaluate_hand(hole_cards, community_cards)`: 评估手牌强度。
- `calculate_odds()`: 计算胜率和底池赔率。
- `decide_action(game_state)`: 返回最佳行动建议。

### 3.3 `src/utils.py`
通用工具函数。
- 扑克牌的解析与转换（如 `Ad` -> `Ace of Diamonds`）。
- 日志记录与调试工具。

## 4. 数据流 (Data Flow)

```mermaid
graph TD
    A[ReplayPoker Server] <-->|WebSocket| B[Browser (Playwright)]
    B -->|Network Frame| C[PokerClient Listener]
    B -->|DOM Elements| D[PokerClient Parser]
    C --> E[GameState]
    D --> E
    E --> F[DecisionEngine]
    F -->|Action Suggestion| G[User / AutoExec]
```

## 5. 开发路线图 (Roadmap)

1.  **Phase 1: 基础连接与数据获取** (Current)
    - 完成 Playwright 启动脚本。
    - 能够稳定解析 WebSocket 中的手牌数据。
    - 能够解析公共牌数据。

2.  **Phase 2: 完善状态解析**
    - 解析底池 (Pot) 大小。
    - 识别当前是否轮到自己行动 (Her Turn detection)。
    - 解析对手的筹码量和大致动作。

3.  **Phase 3: 基础决策引擎**
    - 实现 Pre-flop 手牌范围表 (Starting Hand Chart)。
    - 实现基础的 Post-flop 逻辑 (Hit or Fold)。

4.  **Phase 4: 自动化与优化**
    - 实现自动点击功能。
    - 优化延迟，提高稳定性。
    - 增加高级策略 (Pot Odds, Position awareness)。

## 6. 技术栈 (Tech Stack)
- **Language**: Python 3.10+
- **Browser Automation**: Playwright (Async API)
- **Dependency Management**: uv
- **Linting/Formatting**: ruff / black
