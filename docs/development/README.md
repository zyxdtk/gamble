# 开发指南

## 环境搭建

```bash
# 克隆仓库
git clone <repo-url>
cd gamble

# 安装依赖（uv 包管理器）
uv sync

# 安装浏览器（仅浏览器模式）
playwright install chrome
```

## 项目规范

- **语言**：文档、注释、提交信息使用中文，代码标识符使用英文
- **包管理器**：`uv`（Python 3.12）
- **测试框架**：`pytest`，`asyncio_mode = "strict"`
- **集成测试**：`@pytest.mark.integration` 标记需要真实浏览器的测试
- **运行时数据**：`data/` 和 `logs/` 目录已 gitignore

## 代码结构

```
src/
├── core/                    # 核心接口层
│   ├── interfaces.py        # GamePlatform, PlayerAgent, GameRunner ABC
│   ├── events.py            # EventType, EventBus
│   └── messaging.py         # AsyncChannel 双工通信
├── strategies/              # 策略层（Brain）
│   ├── strategy_base.py     # Strategy ABC
│   ├── strategy_manager.py  # StrategyManager 单例
│   ├── action_plan.py       # ActionPlan 数据类
│   ├── game_state.py        # 策略层 GameState
│   ├── table_strategy.py    # TableStrategy 桌位策略
│   ├── hand_strategy.py     # HandStrategy 手牌策略
│   ├── strategies/          # 策略实现
│   ├── player_analysis/     # 对手画像系统
│   └── utils/               # equity, board_analyzer, position, preflop_range
├── platforms/               # 平台层
│   ├── arena/               # 本地模拟
│   │   ├── game.py          # GameEngine 规则引擎
│   │   ├── agent.py         # ArenaAgent 策略适配
│   │   ├── competition.py   # Competition 对抗赛
│   │   ├── ring.py          # Ring Game 现金桌
│   │   ├── ring_cli.py      # Ring Game CLI 交互
│   │   ├── mtt.py           # MTT 多桌锦标赛
│   │   ├── sitngo.py        # Sit & Go 单桌赛
│   │   ├── table.py         # TournamentTable
│   │   └── blind_schedule.py # 盲注递增
│   └── browser/             # 浏览器对战
│       ├── browser_platform.py  # BrowserPlatform
│       ├── websocket_listener.py # WebSocket 监听
│       ├── state_manager.py  # 双通道状态管理
│       └── adapters/         # ReplayPoker 适配器
├── bot/                     # 遗留代码（正在被 platforms/browser 替代）
└── main.py                  # 统一入口
```

## 运行测试

```bash
# 全部单元测试
uv run pytest tests/unit/ -v

# Arena 测试
uv run pytest tests/unit/arena/ -v

# Ring Game 测试
uv run pytest tests/unit/arena/test_ring.py -v

# 集成测试（需要真实浏览器）
uv run pytest -m integration -v
```

## 添加新策略

1. 在 `src/strategies/strategies/` 下创建新文件
2. 继承 `Strategy` 基类，实现 `make_decision(state) -> ActionPlan`
3. 策略会由 `StrategyManager` 自动发现

```python
from src.strategies.strategy_base import Strategy
from src.strategies.action_plan import ActionPlan, ActionType

class MyStrategy(Strategy):
    strategy_name = "my_strategy"

    def make_decision(self, state) -> ActionPlan:
        # 实现决策逻辑
        return ActionPlan(primary_action=ActionType.CHECK)
```

4. 在 Arena / Ring Game 中使用：通过策略名称引用

## 添加新平台

1. 继承 `GamePlatform` ABC，实现所有抽象方法
2. 在 `src/main.py` 中添加配置和运行函数

## 添加新桌位策略

1. 继承 `TableStrategy` ABC，实现 `decide(state) -> TableAction`
2. 在 `RingPlatform._create_table_strategy()` 中注册

## 添加新比赛模式

1. 在 `src/platforms/arena/` 下创建新模块
2. 参考 `Competition` 或 `RingPlatform` 的模式
3. 在 `__init__.py` 中添加延迟导入
4. 在 `src/main.py` 中添加 CLI 参数和运行函数

## 配置文件

| 文件 | 说明 |
|------|------|
| `config/settings.yaml` | 主配置：策略、买入、止盈止损、反检测延迟 |
| `config/preflop_ranges.yaml` | 翻牌前范围表（EP/MP/LP/SB） |
