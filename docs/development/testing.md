# 测试体系

## 三层测试架构

| 层级 | 类型 | 特点 | 位置 |
|------|------|------|------|
| Level 1 | 单元测试 | 纯逻辑，完全 mock，快速 | `tests/unit/` |
| Level 2 | 快照测试 | 真实 DOM 快照，无需浏览器 | `tests/explore/` |
| Level 3 | 集成测试 | 真实浏览器 E2E | `tests/integration/` |

## 目录结构

```
tests/
├── unit/                   # 单元测试
│   ├── arena/              # Arena 模块测试
│   │   ├── test_game.py    # GameEngine 核心规则测试
│   │   └── test_ring.py    # Ring Game 测试（28 个）
│   ├── bot/                # 遗留 bot 模块测试
│   ├── brain/              # 策略模块测试
│   ├── core/               # 核心模块测试
│   └── platforms/          # 平台模块测试
├── integration/            # 集成测试（需要真实浏览器）
│   └── BOT_TEST_DESIGN.md  # 集成测试设计文档
└── explore/                # DOM 探索工具
    └── explore_table.py    # DOM 快照采集工具
```

## 核心验证流程

```
逻辑验证 ──► 解析验证 ──► 闭环验证
(Brain 一致性)  (DOM 选择器)  (Arena 压力测试)
```

1. **逻辑验证**：Brain 决策在已知状态下输出预期动作
2. **解析验证**：DOM 选择器正确提取 ReplayPoker 页面数据
3. **闭环验证**：Arena 多策略对抗无崩溃、统计正确

## 运行测试

```bash
# 全部单元测试
uv run pytest tests/unit/ -v

# 特定模块
uv run pytest tests/unit/arena/test_ring.py -v
uv run pytest tests/unit/arena/test_game.py -v

# 集成测试
uv run pytest -m integration -v

# 带覆盖率
uv run pytest tests/unit/ --cov=src --cov-report=term-missing
```

## Ring Game 测试

`test_ring.py` 包含 28 个测试，覆盖：

| 组件 | 测试数 | 说明 |
|------|--------|------|
| `AsyncChannel` | 5 | 双工通信、请求-响应、超时、关闭 |
| `DefaultTableStrategy` | 6 | 无操作/止损/止盈/补筹/sit out/sit in |
| `ConservativeTableStrategy` | 1 | 盈利 sit out |
| `AggressiveTableStrategy` | 1 | 不止盈 |
| `StrategyHandAdapter` | 2 | 委托决策、保留名称 |
| `RingTable` | 6 | 入座/移除/sit in/out/补筹/满座 |
| `RingPlatform` | 3 | 初始化/短局/桌位策略 |
| `RingPlayer` | 2 | 手牌决策/桌位决策 |
| `MessageType` | 2 | 类型完整性/数据类 |

## 维护触发

| 场景 | 动作 |
|------|------|
| 修改策略逻辑 | 运行对应策略的单元测试 |
| 修改 DOM 选择器 | 运行快照测试，必要时重新采集 |
| 大版本发布前 | 运行全部测试 + Arena 压力测试 |

## DOM 探索工具

```bash
# 自动连接浏览器并采集快照
python tests/explore/explore_table.py

# 输出文件（JSON + PNG + HTML 三件套）
data/snapshots/snap_<timestamp>/
```
