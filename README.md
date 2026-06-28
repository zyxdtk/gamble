# Gamble - 德州扑克 AI 自动化系统

本项目是一个德州扑克 AI 自动化与仿真测试系统。通过 Playwright 自动化技术和多层次扑克决策引擎，实现全自动对局及离线仿真对抗。

---

## 🚀 核心特性

- **Brain 决策系统**:
  - 支持 `tag`（默认，紧凶型）、`gto`、`balanced`、`range`、`exploitative`、`aggressive`、`checkorfold` 七种启发式策略
  - 支持 `neural`：基于 RLCard 与 DQN 的深度学习策略
  - 支持 `icm`：锦标赛泡沫期专用策略
  - 完全逻辑解耦，通过 `StrategyManager` 集成所有策略；支持策略别名（如 `gto` → `GtoSolverStrategy`）
- **Arena 仿真模式**:
  - **离线模拟**: 无需浏览器即可运行策略对抗
  - **Ring Game**: 无限注现金桌，支持 sit in/out、补筹、止盈止损
  - **MTT**: 多桌锦标赛，盲注递增、桌位平衡、奖金分配
  - **SNG**: Sit & Go 单桌赛（HU/6max/9max/10max）
- **深度对手建模**: 基于 VPIP/PFR 统计、摊牌记录为每位对手维护独立的动态模型
- **Auto 模式健壮性**: 卡住检测 + 自动换桌 + 筹码冲突诊断 + Raise 按钮置灰检测
- **多种运行模式**:
  - **浏览器全自动** (`--platform browser --game ring --pilot auto`): ReplayPoker 全自动 bot
  - **托管/辅助** (`--pilot managed`/`assist`): AI 决策 + 人类可打断/确认
  - **Arena** (`--platform arena --game ring|mtt|sng|competition`): 本地策略对抗
  - 旧别名 `auto`/`cli`/`replaypoker` 仍可用（打印废弃提示）

---

## 🛠️ 安装与运行

```bash
# 环境准备
uv sync
playwright install chrome

# ReplayPoker 全自动 bot（推荐）
uv run python -m src.main --platform browser --game ring --pilot auto

# 托管模式（AI 自主 + 人类可接管）
uv run python -m src.main --platform browser --game ring --pilot managed

# 辅助模式（AI 建议 + 人类确认）
uv run python -m src.main --platform browser --game ring --pilot assist

# Arena 策略对抗
uv run python -m src.main --platform arena --game ring --arena-hands 100
uv run python -m src.main --platform arena --game mtt --mtt-entries 18
uv run python -m src.main --platform arena --game sng --sng-preset 9max

# 旧别名（仍可用）
uv run python -m src.main auto    # = --platform browser --game ring --pilot auto
uv run python -m src.main cli     # = --platform browser --game ring --pilot assist
uv run python -m src.main arena   # = --platform arena --game competition
```

---

## 🧪 测试

```bash
uv run pytest tests/unit/ -v          # 全部单元测试
uv run pytest tests/unit/arena/ -v    # Arena 测试
uv run pytest -m integration -v       # 集成测试
```

---

## 📖 文档

| 目录 | 说明 |
|------|------|
| [docs/guide/](docs/guide/) | 使用指南 |
| [docs/architecture/](docs/architecture/) | 架构设计 |
| [docs/development/](docs/development/) | 开发指南 |
| [docs/changelog/](docs/changelog/) | 更新历史 |

---
*注：本项目仅用于技术研究与学习测试目的。*
