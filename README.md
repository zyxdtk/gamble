# Gamble - 德州扑克 AI 自动化系统

本项目是一个专门针对 [ReplayPoker.com](https://www.replaypoker.com/) 的德州扑克 AI 自动化系统。通过 Playwright 自动化技术和多层次扑克决策引擎，实现自动入座、自动买入、自动决策以及动态盈亏离场。

## 🚀 核心特性

- **多策略决策引擎**: 支持 `range`（默认）、`gto`、`exploitative`、`checkorfold` 四种策略，由 `EngineManager` 动态加载。
- **深度对手建模**: 基于 VPIP/PFR 统计、摊牌记录（Showdown）和贝叶斯范围更新，为每位对手维护独立的动态范围模型。
- **范围感知决策（RangeBrain）**: 通过对手范围"紧凑度"动态修正跟注/加注阈值，面对 Nit 更保守，面对 Maniac 主动抓诈。
- **策略化风险管理**: 基于 BB 倍数的止损/止盈阈值，支持自定义盈利目标（`--profit`）、局数（`--hands`）、时间（`--duration`）等任务类型。
- **nohup 后台运行**: 改用 `nohup` 启动，关闭终端后进程继续运行，日志按时间戳自动保存至 `logs/` 目录。
- **多种运行模式**:
  - **自动模式** (`--mode auto`): 自动入座、买入并执行 AI 策略（默认）。
  - **辅助模式** (`--mode assist`): 在终端显示决策建议，不实际点击。
  - **学徒模式** (`--mode apprentice`): 观察并记录玩家操作。

## 📂 项目结构

```text
gamble/
├── src/
│   ├── bot/                     # 浏览器自动化与牌桌管理
│   │   ├── browser_manager.py   # 浏览器生命周期管理
│   │   ├── table_manager.py     # 牌桌协调器
│   │   ├── play_manager.py      # 游戏状态解析与动作执行
│   │   ├── lifecycle_manager.py # 入座/离场/买入逻辑
│   │   └── task_manager.py      # 任务目标管理（盈利/局数/时间）
│   ├── core/                    # 核心数据结构
│   │   ├── game_state.py        # GameState / Player 数据类
│   │   └── utils.py             # 通用工具函数
│   ├── engine/                  # 决策引擎
│   │   ├── brain_base.py        # Brain 抽象基类（集成 PlayerManager）
│   │   ├── engine_manager.py    # 策略动态加载工厂（单例）
│   │   ├── action_plan.py       # 决策结果数据类
│   │   ├── strategies/          # 具体策略实现
│   │   │   ├── range.py         # RangeBrain（默认策略，含对手紧凑度修正）
│   │   │   ├── gto.py           # GTOBrain
│   │   │   ├── exploitative.py  # ExploitativeBrain
│   │   │   └── checkorfold.py   # CheckOrFoldBrain
│   │   ├── player_analysis/     # 对手建模系统
│   │   │   ├── tags.py          # PlayerTag 分类（NIT/TAG/FISH/STATION/MANIAC）
│   │   │   ├── database.py      # SQLite 持久化（统计 + 摊牌记录）
│   │   │   ├── manager.py       # PlayerManager 融合管理器
│   │   │   ├── model.py         # BaseRangeModel / ActionBasedRangeModel
│   │   │   ├── stats_model.py   # StatsAwareRangeModel（VPIP/PFR 修正）
│   │   │   └── showdown_model.py# ShowdownAwareRangeModel（摊牌反馈修正）
│   │   └── utils/               # 引擎工具库
│   │       ├── equity_calculator.py  # 胜率计算（含听牌潜力）
│   │       ├── board_analyzer.py     # 牌面湿度分析
│   │       ├── preflop_range.py      # 翻牌前静态范围（PreflopRangeManager）
│   │       └── position.py           # 位置码计算 / 手牌规范化
│   └── main.py                  # 系统入口（argparse CLI）
├── tests/unit/                  # 单元测试（139+ 项，全部通过）
├── config/
│   └── settings.yaml            # 全局参数配置
├── data/                        # 运行数据（浏览器 Session、SQLite 数据库）
├── logs/                        # 运行日志（按时间戳命名）
└── start.sh                     # 一键启动脚本
```

## 🛠️ 安装与运行

### 环境准备

```bash
uv sync
playwright install chrome
```

### 快速启动（推荐）

```bash
./start.sh
```

默认配置：**自动模式 + Range 策略 + 盈利目标 2000**，按提示确认后以 `nohup` 后台启动。

```bash
# 手动配置模式
./start.sh --interactive

# 查看实时日志
tail -f logs/poker_ai.log
```

### 命令行直接启动

```bash
# 自动模式 + range 策略 + 盈利目标 1000
python -m src.main --mode auto --strategy range --profit 1000

# 自动模式 + GTO 策略 + 运行 50 手
python -m src.main --mode auto --strategy gto --hands 50

# 辅助模式（仅提供决策建议，不实际操作）
python -m src.main --mode assist --strategy range
```

## 🧪 测试说明

```bash
# 运行所有单元测试
pytest tests/unit/ -v

# 只运行策略测试
pytest tests/unit/engine/strategies/ -v

# 只运行对手建模测试
pytest tests/unit/engine/player_analysis/ -v
```

## ⚙️ 配置说明 (config/settings.yaml)

```yaml
game:
  preferred_stakes: "1/2"    # 偏好的盲注级别

exit_thresholds:
  stop_loss_bb: 100          # 亏损 100 BB 离场
  take_profit_bb: 300        # 盈利 300 BB 离场
  low_chips_bb: 10           # 桌上筹码低于 10 BB 离场

strategy:
  thinking_timeout: 2.0      # AI 思考超时时间（秒）
```

## 📖 策略说明

| 策略 | 说明 |
|------|------|
| `range` | **默认策略**。基于 EHS + 对手范围紧凑度的多维决策，智能区分 Nit/Maniac/诈唬者 |
| `gto` | 基于翻牌前范围表的近似 GTO 策略 |
| `exploitative` | 读取对手风格（PlayerTag）进行针对性剥削 |
| `checkorfold` | 最保守策略，仅在免费时过牌，否则弃牌 |

---
*注：本项目仅用于技术研究与学习测试目的。*
