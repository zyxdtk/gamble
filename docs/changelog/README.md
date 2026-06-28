# 更新日志

## 2026-06-28 更新

### 🐛 Bug 修复（详见 `fixes.md`）

- **策略别名机制**: `Strategy` 基类新增 `strategy_aliases`，修复 `gto` 策略创建失败回退 balanced 的问题（`gto_solver.py` 注册键是 `gtosolver`，配置用 `gto` 对不上）
- **卡住检测 + 自动换桌**: 桌子满员时连续 30 轮无法入座自动换桌，连续 5 次失败冷却 60s
- **Raise 按钮置灰诊断**: payload 补 `my_chips` 字段；策略返回超额 raise 时打 `[筹码冲突]` WARNING；执行层检测 `disabled`/`opacity` 不再静默成功

### 📝 文档更新

- `CLAUDE.md`: 命令改为 `--platform/--game/--pilot` 新接口；策略列表从六种更新为九种，标注 `tag` 为默认
- `README.md`: 运行命令和特性描述同步新接口和九种策略
- `docs/architecture/strategy-engine.md`: 补充策略注册/别名机制说明、TAG 策略、`get_action_for_bet` 的不钳制 raise 金额注意事项
- `docs/architecture/browser-platform.md`: 新增 Raise 按钮置灰检测、卡住检测与自动换桌、筹码冲突诊断章节
- `docs/guide/browser-mode.md`: 新增策略选择章节、auto_mode 配置项
- `src/strategies/brain.md`: 补充 TAG 策略说明

## 2026-06-07 更新

### 🎰 Ring Game 无限注现金桌

新增完整的 Ring Game 模式，核心变化：

- **双工通信**：基于 `AsyncChannel`（`asyncio.Queue`）的点对点消息通道，Platform 推送状态给 Player，Player 异步返回决策
- **双策略分离**：TableStrategy（桌位策略：sit in/out/补筹/离场）+ HandStrategy（手牌策略：fold/check/call/raise）
- **三种桌位策略**：DefaultTableStrategy（短码补筹/筹码过厚 sit out/止损止盈）、ConservativeTableStrategy（更紧阈值）、AggressiveTableStrategy（频繁补筹，不止盈）
- **用户参与**：通过 CLI 交互做决策（`--ring-human`），Rich 格式化显示牌面

新增文件：
- `src/core/messaging.py` — AsyncChannel 双工通信核心
- `src/strategies/table_strategy.py` — 桌位策略
- `src/strategies/hand_strategy.py` — 手牌策略接口 + StrategyHandAdapter
- `src/platforms/arena/ring.py` — Ring Game 核心（RingPlatform/RingPlayer/RingTable）
- `src/platforms/arena/ring_cli.py` — CLI 用户交互（CLIRingPlayer）
- `tests/unit/arena/test_ring.py` — 28 个单元测试

修改文件：
- `src/core/events.py` — EventType 新增 TABLE_ACTION
- `src/main.py` — 新增 ring 模式 + `--ring-hands`/`--ring-buyin`/`--ring-human` 参数

### 📚 文档重组

将 `docs/` 目录重组为四个子目录：
- `docs/guide/` — 使用指南
- `docs/architecture/` — 架构设计
- `docs/development/` — 开发指南
- `docs/changelog/` — 更新历史

## 2026-03-08 更新

### 🧠 对手建模系统 (Player Analysis Module)
- **模块化重组**: 将玩家分析相关组件迁移至独立包 `src/engine/player_analysis/`，包含 `tags.py`、`database.py`、`manager.py` 和多种范围模型。
- **玩家标签体系**: 引入 `PlayerTag` 常量（`NIT`, `TAG`, `FISH`, `STATION`, `MANIAC`, `UNKNOWN`）并实现 `get_player_tag()` 分类函数。
- **SQLite 持久化**: 新增 `PlayerDatabase`，通过 `player.user_id` 跨 Session 记录每位对手的 VPIP/PFR 历史统计。
- **摊牌记录**: 扩展数据库新增 `player_showdowns` 表，记录对手在摊牌时展示的真实手牌，作为修正信号。
- **`PlayerManager` 融合管理**: 统一管理会话内统计、全局持久化数据，并维护每位对手与 Hero 各自的独立范围模型。

### 📊 多策略范围建模 (Multi-Strategy Range Modeling)
- **`BaseRangeModel`**: 引入抽象基类，统一范围模型接口。
- **`ActionBasedRangeModel`**: 基础动作驱动型贝叶斯更新模型。
- **`StatsAwareRangeModel`**: 结合 VPIP/PFR 历史数据修正贝叶斯衰减系数。
- **`ShowdownAwareRangeModel`**: 通过分析摊牌的"惊讶值"动态修正 `bias_factor`。
- **智能三级自动切换**: 根据样本量自动选择最优模型。

### ♟️ RangeBrain 策略升级
- 新增 `RangeBrain` 策略，整合 EHS、听牌潜力、SPR 与对手范围紧凑度进行多维决策。
- **对手紧凑度修正**: 动态调整跟注阈值：面对 Nit 更保守，面对 Maniac 更积极"抓诈"。

### 🚀 启动脚本升级
- 默认配置：自动模式 + Range 策略 + 盈利目标 2000
- 支持 `--interactive` 参数手动配置
- `nohup` 后台运行，日志按时间戳命名

### 🧪 测试覆盖
- 全量 139+ 项单元测试全部通过，零回归。

## 2026-02-28 更新

### 🏗️ 核心架构重构 (The 1M Project Refactoring)
- **目录重组**: 四个核心子目录：`src/bot/`、`src/engine/`、`src/core/`、`src/ui/`
- **入口统一**: `src/main.py` 支持 `--auto` 自动跑牌和 `--assist` 辅助模式

### 🧠 策略引擎升级 (Positional GTO)
- 引入 `config/preflop_ranges.yaml`：按座位定义翻牌前入局范围
- `GameState` 增加 VPIP 和 PFR 字段

### 🏆 盈利目标与自动离场
- 筹码跟踪和自动离场逻辑
- 支持 `to_call` 实时解析

### 🧪 稳定性与测试
- 回归测试和代码除错

### 🔄 Ralph Loop 自动化增强
- 大厅自动化、自动入座、状态自愈

## 2026-02-08 更新

### ✅ HUD 重构与修复
- 独立 `src/hud.py` 模块
- 修复 JavaScript 注入语法错误
- 拖拽和关闭功能

### ✅ 中文化
- HUD 界面完全中文化
- 决策引擎输出中文化

### ✅ 多对手胜率计算
- 改进胜率计算逻辑
- 蒙特卡洛模拟

### 📁 项目结构优化
- 测试文件移至 `tests/` 目录
- 文档更新至 `docs/` 目录
