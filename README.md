# Gamble - 德州扑克 AI 自动化系统

你好，同学。本项目是一个专门针对 [ReplayPoker.com](https://www.replaypoker.com/) 的德州扑克 AI 自动化系统。通过 Playwright 自动化技术和扑克决策引擎，实现自动入座、自动买入、自动决策以及动态盈亏离场。

## 🚀 核心特性

-   **智能浏览器管理**: 基于 Playwright 的多标签页管理，支持自动登录 session 复用。
-   **动态大盲注检测**: 实时从页面 DOM 中解析当前牌桌的大盲注 (BB) 金额。
-   **策略化风险管理**: 基于 BB 倍数的动态阈值（止损、止盈、低筹码自动离场）。
-   **庄家周期追踪**: 精确追踪庄家位的轮转（Dealer Cycles），确保在完成预设的游戏周期后安全撤离。
-   **多种运行模式**:
    -   **辅助模式** (Default): 提供终端决策建议。
    -   **学徒模式** (`--apprentice`): 观察并记录玩家操作，用于策略对齐。
    -   **全自动模式** (`--auto`): 自动入座、自动买入并执行 AI 策略。
-   **多策略支持**: 包含 CheckOrFold、GTO (简单版)、剥削性 (Exploitative) 等多种策略。

## 📂 项目结构

```text
gamble/
├── src/
│   ├── bot/                # 浏览器自动化与牌桌管理 (BrowserManager, TableManager, LobbyManager)
│   ├── core/               # 核心数据结构与扑克工具类 (GameState, Card parsing)
│   ├── engine/             # 决策引擎与具体的扑克策略 (DecisionEngine, Strategies)
│   ├── ui/                 # (可选) HUD 与前端显示相关
│   ├── main.py             # 系统入口程序
│   └── design_doc.md       # 系统设计文档
├── tests/
│   ├── bot/                # 机器人逻辑集成测试 (1M 周期测试, 离场逻辑等)
│   ├── unit/               # 核心算法单元测试 (策略回归, 解析逻辑等)
│   └── explore/            # 页面元素探索辅助工具
├── config/
│   └── settings.yaml       # 全局参数配置 (止损止盈、偏好盲注、策略选择)
├── data/                   # 运行报告、浏览器 Session 数据、网页快照
└── logs/                   # 详细运行日志
```

## 🛠️ 安装与运行

### 环境准备
项目使用 `uv` 管理依赖：
```bash
uv sync
playwright install chrome
```

### 运行程序
```bash
# 启动辅助模式（仅建议）
python -m src.main

# 启动全自动模式
python -m src.main --auto

# 启动学徒模式
python -m src.main --apprentice
```

## 🧪 测试说明

项目包含完善的测试套件，分为单元测试和集成测试。

### 运行单元测试
```bash
pytest tests/unit tests/bot/test_table_manager.py -v
```

### 运行集成测试 (End-to-End)
集成测试需要真实的浏览器环境和网络连接，用于验证长时稳定运行逻辑。
```bash
# 运行两个庄家周期稳定测试
pytest tests/bot/test_two_cycle_run.py -m integration -v -s
```

## ⚙️ 配置说明 (config/settings.yaml)

```yaml
game:
  preferred_stakes: "1/2"       # 偏好的盲注级别
  preferred_strategy: "apprentice" # 默认策略

exit_thresholds:
  stop_loss_bb: 100             # 亏损 100 BB 离场
  take_profit_bb: 300           # 盈利 300 BB 离场
  low_chips_bb: 10              # 桌上筹码低于 10 BB 离场
```

---
*注：本项目仅用于技术研究与学习测试目的。*
