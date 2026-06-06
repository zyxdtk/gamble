# Gamble - 德州扑克 AI 自动化系统

本项目是一个德州扑克 AI 自动化与仿真测试系统。通过 Playwright 自动化技术和多层次扑克决策引擎，实现全自动对局及离线仿真对抗。

---

## 🚀 核心特性

- **Brain (大脑) 决策系统**:
  - 支持 `range`、`balanced` (原 `gto`)、`exploitative`、`checkorfold` 四种启发式策略。
  - **[NEW]** 支持 `neural`: 基于 RLCard 与核心深度学习 (DQN) 的自进化模型。
  - 完全逻辑解耦，通过 `BrainManager` 集成所有策略。
- **Arena (竞技场) 仿真模式**:
  - **离线模拟**: 无需浏览器即可运行万级对手的模拟赛。
  - **AI 推理**: `neural` 策略支持加载真正的 `.pth` 模型权重进行对抗。
  - **策略对抗**: 支持多策略、多玩家（如 Neural vs Balanced）的同台对抗与统计分析。
- **深度对手建模**: 基于 VPIP/PFR 统计、摊牌记录（Showdown）为每位对手维护独立的动态模型。
- **多种运行模式**:
  - **仿真竞技场** (`--mode arena`): 进行本地仿真测试（最新功能）。
  - **自动模式** (`--mode auto`): 在真实牌局中执行 AI 策略。
  - **辅助模式** (`--mode assist`): 提供实时对局决策报告。
  - **学徒模式** (`--mode apprentice`): 观察并记录玩家操作以供学习。

---

## 📂 项目结构

```text
gamble/
├── src/
│   ├── brain/                   # 纯决策逻辑（原 engine）
│   │   ├── brain_manager.py     # 策略管理与动态加载
│   │   ├── strategies/          # 具体策略实现（GTO, Range, 等）
│   │   └── player_analysis/     # 对手建模系统
│   ├── bot/                     # 浏览器自动化与牌桌管理
│   ├── arena/                   # 仿真系统（模拟牌桌、发牌、结算）
│   └── main.py                  # 系统入口
├── docs/                        # 全局设计方案、任务列表及核心逻辑 (brain.md)
├── tests/                       # 单元测试与集成测试
│   ├── unit/                    # 核心组件测试
│   └── arena/                   # 竞技场规则测试
├── config/                      # 策略与游戏参数配置
├── data/                        # 统计数据库与 Session 数据
└── logs/                        # 运行日志
```

---

## 🛠️ 安装与运行

### 1. 环境准备
```bash
uv sync
playwright install chrome
```

### 2. 运行仿真竞技场 (Arena)
用于测试策略强度，查看 P/L 和 VPIP 等数据：
```bash
# 运行 100 手牌，默认策略对抗
uv run python src/main.py --mode arena --arena-hands 100

# 自定义玩家策略对抗 (Neural vs Balanced)
uv run python src/main.py --mode arena --arena-players neural,balanced,range,exploitative --arena-hands 100

### 3. 训练神经网络模型 (Offline Training)
如果你想训练自己的 `neural` 策略模型：
```bash
# 运行 DQN 强化学习训练循环 (默认 1000 回合)
uv run python scripts/train_nlh_model.py
```
训练完成后，权重将自动保存至 `data/models/nlh_dqn.pth`，`neural` 策略在下次运行时会自动加载。
```

### 3. 运行自动/辅助模式
```bash
# 自动模式
uv run python src/main.py --mode auto --strategy aggressive --profit 100

# 辅助模式
uv run python src/main.py --mode assist --strategy aggressive
```

---

## 🧪 测试说明
```bash
# 运行所有验证测试
uv run pytest tests/ -v

# 运行竞技场专用测试
uv run pytest tests/arena/ -v
```

---

## 📖 核心文档
- [**Brain 核心逻辑**](src/brain/brain.md): 详细记录了各策略的思考分支与阀值定义。
- [**项目规则 (Rules)**](.agents/rules/global.md): 本项目的代码与文档规范说明。

---
*注：本项目仅用于技术研究与学习测试目的。*
