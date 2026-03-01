# Texas Hold'em AI 设计文档

## 1. 项目概述 (Project Overview)
本项目旨在开发一个针对 [ReplayPoker.com](https://www.replaypoker.com/) 的德州扑克 AI 自动化系统。该系统通过浏览器自动化工具 (Playwright) 与游戏交互，解析实时游戏状态，并执行自动下注决策。

## 2. 核心架构 (Core Architecture)

系统采用模块化设计，分为以下核心组件：

### 2.1 浏览器管理层 (Browser & Table Management)
-   **BrowserManager**: 负责启动 Playwright 实例，管理多个游戏标签页，并根据 URL 增量创建 `TableManager`。
-   **TableManager**: 针对单个牌桌的逻辑容器。
    -   **入座与买入**: 处理自动寻找空位、点击坐下并处理买入确认对话框。
    -   **状态更新**: 通过 DOM 解析底池、筹码量、可用按钮和大盲注金额。
    -   **离场策略**: 实现基于 BB 倍数的止损、止盈及孤单离桌（桌上仅剩一人时自动退出）逻辑。
    -   **周期追踪**: 通过观测 `DealerButton` 的位置变化，计算游戏运行的手数与圈数。
-   **LobbyManager**: 负责大厅导航、应用筛选条件并寻找符合要求的牌桌。

### 2.2 决策与策略层 (Decision & Strategy)
-   **DecisionEngine**: 连接 `GameState` 与具体策略逻辑的桥梁。
-   **Strategy Pattern**: 采用策略模式支持多种打法：
    -   `ApprenticeStrategy`: 学徒模式，仅观察并记录。
    -   `CheckOrFoldStrategy`: 保守策略，仅在能免费过牌时继续，否则弃牌，用于稳定性测试。
    -   `GTOStrategy`: 基于 GTO 逻辑的基础决策。
    -   `ExploitativeStrategy`: 剥削性策略，利用对手行为漏洞。

### 2.3 数据模型层 (Core Data Model)
-   **GameState**: 维护当前局势的单一事实来源。包含牌堆、公共牌、玩家信息、底池及当前行动权。

## 3. 核心流程与数据流 (Data Flow)

1.  **初始化**: `Main` 启动 `BrowserManager`。
2.  **大厅阶段**: `LobbyManager` 导航至 Lobby，根据配置查找最优 URL。
3.  **牌桌初始化**: `TableManager` 附加到新页面，探测大盲注，初始化 `initial_chips`。
4.  **运行循环**:
    -   `TableManager` 执行 `update_state_from_dom` 捕获最新数据。
    -   检查 `check_exit_conditions` 以确定是否需要离场。
    -   如果轮到自己行动，调用 `DecisionEngine` 获取建议。
    -   在自动模式下执行点击动作。
5.  **周期结束**: 满足 1M 盈利目标或完成预设的庄家周期后，执行 `leave_table` 安全退出。

## 4. 技术规范

-   **语言**: Python 3.12 (uv 管理)
-   **核心库**: Playwright (自动化), treys (扑克评估), PyYAML (配置管理)
-   **测试框架**: pytest + pytest-asyncio
-   **日志记录**: 使用标准 logging 模块输出至 console 和文件
