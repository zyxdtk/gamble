# ReplayPoker 使用指南

通过 Playwright 自动化控制 ReplayPoker.com 进行在线对战。

## 前提条件

- 已安装 Chrome 浏览器
- 已运行 `playwright install chrome`
- 有 ReplayPoker.com 账号

## 快速开始

### AI 自动模式

```bash
uv run python -m src.main replaypoker
```

自动模式流程：
1. 打开浏览器并登录
2. 导航到大厅
3. 根据配置选择最佳桌子
4. 自动坐下并买入
5. 循环执行：等待轮次 -> 获取状态 -> 策略决策 -> 执行动作

### 人类玩家模式

```bash
uv run python -m src.main replaypoker --human
```

自动管理登录、找桌、坐下，但手牌决策由你在终端输入。收到决策请求时显示牌面和可用动作：

```
┌─────── 你的回合 (浏览器) ───────┐
│ 底池: 120  |  需跟注: 20       │
└─────────────────────────────────┘

可用动作: fold | call | raise
回车 = call (20)

browser> [call (20)]:
```

输入命令：`fold` / `check` / `call` / `raise 100` / `allin`

### 完全手动模式

```bash
uv run python -m src.main replaypoker --cli
```

启动后进入交互式 REPL，可逐步操作：

```
test-cli> login          # 登录
test-cli> lobby          # 进入大厅
test-cli> tables         # 查看可用桌子
test-cli> open 1         # 打开第一个桌子
test-cli> sit            # 坐下
test-cli> buyin 200      # 买入 200 筹码
test-cli> state          # 查看当前状态
test-cli> actions        # 查看可用动作
test-cli> fold           # 弃牌
test-cli> quit           # 退出
```

### 配置

`config/settings.yaml` 中的关键配置：

```yaml
game:
  preferred_stakes: "5/10"    # 偏好盲注级别
  max_small_blind: 50         # 不加入小盲超过此值的桌子
  max_tables: 1               # 同时参与的桌数
  exit_thresholds:
    stop_loss_bb: 250         # 亏损 250 BB 离桌
    take_profit_bb: 300       # 盈利 300 BB 离桌
    low_chips_bb: -1          # 桌上筹码不足 N BB 离桌（-1 关闭）
    max_chips_bb: 800         # 桌上筹码超过 N BB 离桌
```

## 桌子选择策略

| 策略 | 说明 |
|------|------|
| `fifo` | 先进先出，最早找到的桌子优先 |
| `most` | 选择玩家最多的桌子 |
| `least` | 选择玩家最少的桌子 |
| `random` | 随机选择 |

```bash
uv run python -m src.main replaypoker --strategy most
uv run python -m src.main replaypoker --stakes 1/2
uv run python -m src.main replaypoker --headless
```

## 截图与调试

| 命令 | 说明 |
|------|------|
| `screenshot [name]` | 手动截图 |
| `snap` | 快速截图（时间戳命名） |
| `autosnap on/off` | 开关自动截图 |

截图保存在 `data/snapshots/` 目录。

## 交互式启动器

```bash
./start.sh --interactive
```

使用 `nohup` 在后台运行，日志输出到 `logs/poker_ai.log`。
