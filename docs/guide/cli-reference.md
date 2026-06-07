# CLI 命令参考

## 全局参数

```
uv run python -m src.main [mode] [options]
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `mode` | 运行模式：`arena`/`mtt`/`sng`/`ring`/`replaypoker` | 无（交互式选择） |
| `--headless` | 浏览器无头模式 | `false` |
| `--stakes` | 偏好盲注级别（如 `1/2`, `5/10`） | 配置文件 |
| `--strategy` | 桌子选择策略：`fifo`/`most`/`least`/`random` | `fifo` |

## 通用参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--human` | 启用人类玩家（CLI 交互），适用于所有模式 | `false` |
| `--cli` | ReplayPoker 完全手动浏览器控制 | `false` |

## Arena 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--arena-hands` | 对抗手数 | `100` |
| `--arena-players` | 玩家数量 | `3` |

## Ring Game 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--ring-hands` | 手数 | `100` |
| `--ring-buyin` | 买入金额 | `200` |

## MTT 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mtt-entries` | 参赛人数 | `18` |
| `--mtt-blinds` | 盲注结构：`standard`/`turbo`/`deepstack` | `standard` |
| `--mtt-prize` | 奖金分配（如 `50,30,20`） | 自动 |
| `--mtt-stack` | 起始筹码 | `1000` |
| `--mtt-fee` | 买入费 | `100` |

## SNG 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--sng-preset` | 类型：`hu`/`6max`/`9max`/`10max` | 无 |
| `--sng-blinds` | 盲注结构：`standard`/`turbo` | `turbo` |
| `--sng-stack` | 起始筹码 | `1500` |
| `--sng-fee` | 买入费 | `50` |

---

## 模式总览

所有模式都支持 `--human` 启用人类玩家：

| 命令 | 说明 |
|------|------|
| `uv run python -m src.main ring --human` | Ring Game 人类玩家 |
| `uv run python -m src.main mtt --human` | MTT 人类玩家 |
| `uv run python -m src.main sng --human` | SNG 人类玩家 |
| `uv run python -m src.main replaypoker --human` | ReplayPoker 人类玩家 |

---

## ReplayPoker CLI 命令

`replaypoker --cli` 模式下可用的交互式命令：

### 登录与大厅

| 命令 | 说明 |
|------|------|
| `login` | 确保已登录（支持手动登录） |
| `lobby` | 导航到大厅 |
| `tables [stakes]` | 列出可用桌子 |
| `best` | 显示最佳可用桌子 |
| `open [idx\|url]` | 打开桌子 |
| `join [min\|max\|amt]` | 快速加入：找桌子并坐下 |

### 桌子管理

| 命令 | 说明 |
|------|------|
| `sit` | 尝试坐下 |
| `buyin <amount>` | 设置买入金额并确认 |
| `leave` | 离开当前桌子 |

### 游戏动作

| 命令 | 说明 |
|------|------|
| `fold` | 弃牌 |
| `check` | 过牌 |
| `call` | 跟注 |
| `raise <amount>` | 加注至金额 |
| `allin` | 全下 |

### 状态查看

| 命令 | 说明 |
|------|------|
| `state` | 显示完整游戏状态（底池、公共牌、位置等） |
| `actions` | 显示可用动作详情（含金额和预设尺度） |

### 配置与工具

| 命令 | 说明 |
|------|------|
| `config` | 显示当前配置 |
| `stakes <level>` | 设置偏好盲注级别 |
| `screenshot [name]` | 手动截图 |
| `snap` | 快速截图 |
| `help` | 显示帮助 |
| `quit` | 退出 |

---

## Ring Game CLI 命令

Ring Game `--human` 模式下可用的交互式命令：

### 手牌命令（`ring>` 提示符）

| 命令 | 说明 |
|------|------|
| `fold` | 弃牌 |
| `check` | 过牌 |
| `call` | 跟注 |
| `raise <金额>` | 加注至金额 |
| `allin` | 全下 |
| `status` | 重新显示当前状态 |
| `help` | 显示帮助 |

### 桌位命令（`ring[table]>` 提示符）

| 命令 | 说明 |
|------|------|
| `none` | 无操作 |
| `sit_in` | 坐入参与 |
| `sit_out` | 站起观战（锁定利润） |
| `add <金额>` | 补充筹码 |
| `leave` | 离场 |
| `status` | 显示状态 |
| `help` | 显示帮助 |

---

## MTT/SNG CLI 命令

MTT/SNG `--human` 模式下可用的交互式命令：

### 手牌命令（`tourney>` 提示符）

| 命令 | 说明 |
|------|------|
| `fold` | 弃牌 |
| `check` | 过牌 |
| `call` | 跟注 |
| `raise <金额>` | 加注至金额 |
| `allin` | 全下 |
| `status` | 重新显示当前状态 |
| `help` | 显示帮助 |

---

## ReplayPoker 人类玩家命令

`replaypoker --human` 模式下可用的交互式命令：

### 手牌命令（`browser>` 提示符）

| 命令 | 说明 |
|------|------|
| `fold` | 弃牌 |
| `check` | 过牌 |
| `call` | 跟注 |
| `raise <金额>` | 加注至金额 |
| `bet <金额>` | 下注至金额 |
| `allin` | 全下 |
