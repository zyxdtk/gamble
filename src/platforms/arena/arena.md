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
2.  **Blinds**: 按照位置（庄家位、小盲位、大盲位）自动强制下注。
3.  **Betting Loop**: 每一条街道（Preflop, Flop, Turn, River）执行投注循环。
    - 询问玩家决策 -> 更新引擎注额 -> 广播动作日志。
4.  **Showdown / Settlement**: 到达河牌且多人存活，或中途仅剩一人时执行结算，分配底池并更新统计数据。

---

## 3. 并发与安全性分析 (Multi-Player Safety)

> [!IMPORTANT]
> **关于同策略多玩家的隔离性：**
> 在竞技场中，同一个策略（如 GTO）可以同时分配给多个玩家。系统通过以下机制确保**绝无内存干扰**：
> 1. **独立实例化**: `Competition` 类在初始化时，会为每一个座位调用策略构造函数，生成**完全独立**的对象实例。
> 2. **实例级状态**: 各策略逻辑（如 `RangeBrain`）的所有临时变量均存储在 `self` 实例空间中，不使用 `static` 或 `global` 变量。
> 3. **无锁环境**: 模拟环境采用同步单线程循环，不存在多线程竞争问题。

---

## 4. 统计指标定义

- **VPIP (Voluntarily Put $ In Pot)**: 翻牌前主动投入筹码（Call/Raise）的比例。
- **PFR (Pre-Flop Raise)**: 翻牌前主动加注的比例。
- **Profit**: 最终筹码相对于初始筹码的增量。
