# 快速开始

德州扑克 AI 自动化与模拟系统，支持 ReplayPoker 浏览器对战和本地 Arena 策略模拟。

## 环境准备

```bash
# 安装依赖
uv sync

# 安装浏览器（仅浏览器模式需要）
playwright install chrome
```

## 运行模式

### Arena 本地模拟

```bash
# 交互式配置
uv run python -m src.main arena

# 快速运行（3 玩家，100 手）
uv run python -m src.main arena --arena-hands 100 --arena-players 3
```

### Ring Game 无限注现金桌

```bash
# 纯 AI 对战
uv run python -m src.main ring --ring-hands 100

# 带人类玩家（CLI 交互）
uv run python -m src.main ring --ring-hands 50 --human

# 交互式配置
uv run python -m src.main
# 选择 "5. Ring (无限注现金桌)"
```

Ring Game 特性：
- 双策略分离：TableStrategy（sit in/out/补筹/离场）+ HandStrategy（fold/check/call/raise）
- 止盈止损：按 BB 阈值自动离场
- 短码补筹：筹码不足时自动补筹
- 筹码过厚 sit out：锁定利润

### MTT 多桌锦标赛

```bash
# 18 人标准赛
uv run python -m src.main mtt --mtt-entries 18

# 快速赛
uv run python -m src.main mtt --mtt-entries 18 --mtt-blinds turbo

# 深筹赛
uv run python -m src.main mtt --mtt-entries 9 --mtt-blinds deepstack --mtt-stack 5000

# 带人类玩家
uv run python -m src.main mtt --mtt-entries 9 --human
```

### SNG Sit & Go 单桌赛

```bash
# 9 人赛
uv run python -m src.main sng --sng-preset 9max

# 单挑赛
uv run python -m src.main sng --sng-preset hu

# 带人类玩家
uv run python -m src.main sng --sng-preset 6max --human
```

### 浏览器在线对战（ReplayPoker）

```bash
# AI 自动模式
uv run python -m src.main replaypoker

# 人类玩家模式
uv run python -m src.main replaypoker --human

# 完全手动浏览器控制
uv run python -m src.main replaypoker --cli

# 无头模式
uv run python -m src.main replaypoker --headless
```

## 交互式启动

不带参数运行进入交互式菜单：

```bash
uv run python -m src.main
```

```
┌────────────────────────────────────┐
│ 1. Arena       (本地模拟对抗)      │
│ 2. MTT         (多桌锦标赛)        │
│ 3. SNG         (Sit & Go 单桌赛)  │
│ 4. Ring        (无限注现金桌)      │
│ 5. ReplayPoker (浏览器在线对战)    │
└────────────────────────────────────┘
```

## 可用策略

| 策略 | 说明 |
|------|------|
| `gto` / `balanced` | GTO 近似策略，手牌分级 + EV 驱动下注尺度 |
| `range` | 范围策略，EHS 评估 + 贝叶斯对手范围建模 |
| `exploitative` | 剥削策略，根据对手类型（Nit/Maniac/Station/Fish）动态调整 |
| `aggressive` | 激进策略，更宽的入池范围和更大的下注尺度 |
| `checkorfold` | 保守策略，只看牌或弃牌 |
| `neural` | DQN 深度学习策略（需要训练模型） |
| `icm` | ICM 策略，锦标赛泡沫期专用 |

## 训练神经网络

```bash
uv run python scripts/train_nlh_model.py
```

## 交互式启动器

```bash
./start.sh --interactive
```
