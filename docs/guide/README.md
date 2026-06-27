# 快速开始

德州扑克 AI 自动化与模拟系统。

## 环境准备

```bash
uv sync
playwright install chrome   # 仅浏览器模式需要
```

## 运行模式

### 新接口（推荐）

```bash
# 平台 + 游戏类型正交组合
uv run python -m src.main --platform arena --game competition  # Arena 本地模拟对抗
uv run python -m src.main --platform arena --game ring         # Ring Game 现金桌
uv run python -m src.main --platform arena --game mtt          # MTT 多桌锦标赛
uv run python -m src.main --platform arena --game sng          # SNG 单桌赛
uv run python -m src.main --platform browser --game ring       # ReplayPoker 浏览器在线
```

### 旧接口（已废弃，仍然可用）

```bash
uv run python -m src.main arena          # → --platform arena --game competition
uv run python -m src.main ring           # → --platform arena --game ring
uv run python -m src.main mtt            # → --platform arena --game mtt
uv run python -m src.main sng            # → --platform arena --game sng
uv run python -m src.main replaypoker    # → --platform browser --game ring
uv run python -m src.main auto           # → --platform browser --game ring --pilot auto
uv run python -m src.main cli            # → --platform browser --game ring --pilot assist
```

不带参数运行进入交互式菜单：

```bash
uv run python -m src.main
```

### 人类参与程度

所有模式都支持 `--pilot` 控制参与程度：

```bash
uv run python -m src.main --platform browser --game ring --pilot auto      # AI 全自主
uv run python -m src.main --platform browser --game ring --pilot managed   # AI 自主 + 人类可打断
uv run python -m src.main --platform browser --game ring --pilot assist    # AI 建议 + 人类确认
uv run python -m src.main --platform arena --game ring --pilot assist      # Ring 人类模式
uv run python -m src.main --platform arena --game mtt --pilot assist       # MTT 人类模式
```

## CLI 参数

```
uv run python -m src.main [--platform <p>] [--game <g>] [mode] [options]
```

### 核心参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--platform` | 平台选择：arena(本地模拟) / browser(浏览器在线) | 无 |
| `--game` | 游戏类型：ring / mtt / sng / competition | 无 |
| `--pilot` | 人类参与程度：auto(无人)/managed(托管)/assist(辅助) | `auto` |
| `--headless` | 浏览器无头模式 | `false` |
| `--log-level` | 控制台日志级别：DEBUG/INFO/WARNING/ERROR | `WARNING` |

> 旧位置参数 `mode` 已废弃，请使用 `--platform` + `--game`。旧参数 `--human` 和 `--cli` 等价于 `--pilot assist`。

### Arena

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--arena-hands` | 对抗手数 | `100` |
| `--arena-players` | 玩家数量 | `3` |

### Ring Game

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--ring-hands` | 手数 | `100` |
| `--ring-buyin` | 买入金额 | `200` |

### MTT

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mtt-entries` | 参赛人数 | `18` |
| `--mtt-blinds` | 盲注结构：standard/turbo/deepstack | `standard` |
| `--mtt-prize` | 奖金分配（如 `50,30,20`） | 自动 |
| `--mtt-stack` | 起始筹码 | `1000` |
| `--mtt-fee` | 买入费 | `100` |

### SNG

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--sng-preset` | 类型：hu/6max/9max/10max | 无 |
| `--sng-blinds` | 盲注结构：standard/turbo | `turbo` |
| `--sng-stack` | 起始筹码 | `1500` |
| `--sng-fee` | 买入费 | `50` |

### ReplayPoker（Browser Ring）

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--stakes` | 偏好盲注级别（如 1/2, 5/10） | 配置文件 |
| `--strategy` | 策略类型（gto/range/checkorfold 等）或桌子选择（fifo/most/least/random） | `gto` |
| `--buyin` | 买入量：min/max/default 或具体整数 | `min` |
| `--hands` | 限定手数（0=无限） | `0` |

## Pilot 模式

### 三种参与程度

| 模式 | `--pilot` 值 | 说明 | 等价旧参数 |
|------|-------------|------|-----------|
| 无人 | `auto` | AI 全自主，异常退出提示人类 | 无 flag |
| 托管 | `managed` | AI 自主运行，人类可随时打断/接管 | (新增) |
| 辅助 | `assist` | AI 建议动作，人类确认/覆盖 | `--human` |

### 通用手牌命令（所有模式、所有游戏）

| 命令 | 说明 |
|------|------|
| `fold` | 弃牌 |
| `check` | 过牌 |
| `call` | 跟注 |
| `raise <金额>` | 加注至金额 |
| `allin` | 全下 |
| `status` | 重新显示当前状态 |
| `help` | 显示帮助 |

按回车使用推荐默认动作（check > call > fold）。

### 托管模式控制命令（仅 managed/assist）

| 命令 | 说明 |
|------|------|
| `pause` | 暂停自动游戏 |
| `resume` | 恢复自动游戏 |
| `takeover` | 接管下一手决策 |
| `fold/check/call/raise/allin` | 覆盖当前决策 |

### Ring Game 桌位命令

| 命令 | 说明 |
|------|------|
| `none` | 无操作 |
| `sit_in` | 坐入参与 |
| `sit_out` | 站起观战（锁定利润） |
| `add <金额>` | 补充筹码 |
| `leave` | 离场 |

### ReplayPoker 浏览器命令（managed/assist）

| 命令 | 说明 |
|------|------|
| `login` | 确保已登录 |
| `lobby` | 导航到大厅 |
| `tables` | 列出可用桌子 |
| `best` | 显示最佳桌子 |
| `open [idx\|url]` | 打开桌子 |
| `sit` | 尝试坐下 |
| `buyin <金额>` | 设置买入金额并确认 |
| `leave` | 离场 |
| `screenshot [name]` | 截图 |
| `snap` | 快速截图 |
| `config` | 显示当前配置 |

## 可用策略

| 策略 | 说明 |
|------|------|
| `gto` / `balanced` | GTO 近似策略，手牌分级 + EV 驱动下注尺度 |
| `range` | 范围策略，EHS 评估 + 贝叶斯对手范围建模 |
| `exploitative` | 剥削策略，根据对手类型动态调整 |
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
