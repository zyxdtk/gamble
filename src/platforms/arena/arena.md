# Arena 仿真竞技场核心逻辑

本文档记录 Arena 模块的运行机制与架构设计。

---

## 1. 核心架构：Brain-Bot-Arena 解耦

Arena 旨在提供一个纯净的扑克环境，用于快速测试 Brain 的策略效果。
- **GameEngine**: 核心规则引擎，负责洗牌、发牌、底池计算、胜率评估及对局日志记录。
- **ArenaAgent**: 策略适配层，将简单的竞技场状态转换为 `GameState`，并获取 `Brain` 的决策。
- **Competition**: 高层运行器，管理多手牌循环、玩家筹码持久化及最终统计报表（VPIP/PFR/Profit）。

---

## 2. 运行流程 (Execution Flow)

1.  **Hand Reset**: 每一手牌开始前，洗牌并重置所有玩家的活跃状态及该局投入。
2.  **Blinds**: 按照位置（庄家位、小盲位、大盲位）自动强制下注；支持 ante。
3.  **Betting Loop**: 每一条街道（Preflop, Flop, Turn, River）执行投注循环。
    - 询问玩家决策 -> 更新引擎注额 -> 广播动作日志。
4.  **Showdown / Settlement**: 到达河牌且多人存活，或中途仅剩一人时执行结算；支持边池分配并更新统计数据。

---

## 3. 比赛模式

### 3.1 Ring Game（常规桌对抗）

多策略在同一桌对抗固定手数，支持 Rebuy 和筹码锁定。

```bash
# 交互式配置
uv run python -m src.main arena

# 命令行直接运行
uv run python -m src.main arena --arena-hands 100 --arena-players 3
```

### 3.2 MTT 多桌锦标赛

完整的多桌锦标赛模拟，包括：多桌分配、淘汰检测、盲注升级、桌子平衡（拆短桌/并桌）、奖金分配。

```bash
# 交互式配置
uv run python -m src.main mtt

# 标准赛（18人，标准盲注）
uv run python -m src.main mtt --mtt-entries 18 --mtt-blinds standard

# 快速赛（45人，turbo 盲注）
uv run python -m src.main mtt --mtt-entries 45 --mtt-blinds turbo

# 深筹码赛（9人，deepstack 盲注）
uv run python -m src.main mtt --mtt-entries 9 --mtt-blinds deepstack --mtt-stack 3000

# 自定义奖金分配
uv run python -m src.main mtt --mtt-entries 18 --mtt-prize "50,30,20"
```

**MTT 参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--mtt-entries` | 18 | 参赛人数 |
| `--mtt-blinds` | standard | 盲注结构：standard / turbo / deepstack |
| `--mtt-stack` | 1000 | 起始筹码 |
| `--mtt-fee` | 100 | 买入费 |
| `--mtt-prize` | 自动 | 自定义奖金分配比例，逗号分隔（如 "50,30,20"） |

**盲注结构对比：**

| 结构 | 每级手数 | 升级速度 | 适用场景 |
|------|----------|----------|----------|
| standard | 10手/级 | 中等 | 常规 MTT |
| turbo | 6手/级 | 快速 | 快速赛 |
| deepstack | 15手/级 | 缓慢 | 深筹码赛 |

### 3.3 Sit & Go 单桌赛

固定人数、满员即开的单桌锦标赛。无需多桌平衡，节奏更快。

```bash
# 交互式配置
uv run python -m src.main sng

# 9人标准赛（默认）
uv run python -m src.main sng --sng-preset 9max

# 6人快速赛
uv run python -m src.main sng --sng-preset 6max --sng-blinds turbo

# Heads-Up 单挑赛
uv run python -m src.main sng --sng-preset hu

# 10人赛
uv run python -m src.main sng --sng-preset 10max
```

**SNG 预设类型：**

| 预设 | 人数 | 奖金分配 |
|------|------|----------|
| `hu` | 2人 | 66% / 34% |
| `6max` | 6人 | 50% / 30% / 20% |
| `9max` | 9人 | 40% / 25% / 18% / 10% / 7% |
| `10max` | 10人 | 40% / 25% / 18% / 10% / 7% |

**SNG 参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--sng-preset` | 9max | 赛事类型：hu / 6max / 9max / 10max |
| `--sng-blinds` | turbo | 盲注结构：standard / turbo |
| `--sng-stack` | 1500 | 起始筹码 |
| `--sng-fee` | 50 | 买入费 |

---

## 4. 并发与安全性分析 (Multi-Player Safety)

> [!IMPORTANT]
> **关于同策略多玩家的隔离性：**
> 在竞技场中，同一个策略（如 GTO）可以同时分配给多个玩家。系统通过以下机制确保**绝无内存干扰**：
> 1. **独立实例化**: `Competition`/`MTTManager`/`SitAndGo` 类在初始化时，会为每一个座位调用策略构造函数，生成**完全独立**的对象实例。
> 2. **实例级状态**: 各策略逻辑（如 `RangeBrain`）的所有临时变量均存储在 `self` 实例空间中，不使用 `static` 或 `global` 变量。
> 3. **无锁环境**: 模拟环境采用同步单线程循环，不存在多线程竞争问题。

---

## 5. 统计指标定义

- **VPIP (Voluntarily Put $ In Pot)**: 翻牌前主动投入筹码（Call/Raise）的比例。
- **PFR (Pre-Flop Raise)**: 翻牌前主动加注的比例。
- **Profit**: 最终筹码相对于初始筹码的增量。

---

## 6. MTT/SNG 专属特性

### 6.1 边池 (Side Pot)

当玩家 all-in 且投资额不同时，系统自动计算主池和边池：

- `calculate_side_pots()`: 按各玩家 `total_investment` 计算主池+边池
- `distribute_pots()`: 按边池分别评估赢家并分配奖金

### 6.2 盲注升级 (Blind Schedule)

- `BlindLevel`: 定义每个级别的 SB/BB/Ante/持续手数
- `BlindSchedule`: 管理盲注表，根据手数自动切换级别
- 支持 ante（从第4级起逐步引入）

### 6.3 ICM 策略

锦标赛感知策略（`ICMStrategy`），在标准策略基础上增加：

- **泡沫系数**: 接近奖励圈时自动保守，避免边缘 all-in
- **筹码压力感知**: 短筹紧迫（放宽全下范围）、大筹施压
- **盲注升级意识**: 即将涨盲时短筹更急

---

## 7. 模块结构

```
src/platforms/arena/
├── __init__.py          # 延迟导出所有类型
├── game.py              # GameEngine 核心规则引擎
├── agent.py             # ArenaAgent 策略适配层
├── competition.py       # Competition 对抗赛运行器（Ring Game）
├── platform.py          # ArenaPlatform 平台接口
├── blind_schedule.py    # 盲注结构定义与预设
├── side_pot.py          # 边池计算与分配
├── table.py             # TournamentTable 锦标赛桌
├── mtt.py               # MTTManager 多桌锦标赛管理器
└── sitngo.py            # SitAndGo 单桌赛管理器
```
