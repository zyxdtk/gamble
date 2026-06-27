# ReplayPoker 浏览器模式

通过 Playwright 自动化控制 ReplayPoker.com 进行在线对战。

## 前提条件

- 已安装 Chrome 浏览器
- 已运行 `playwright install chrome`
- 有 ReplayPoker.com 账号

## 运行模式

```bash
# AI 全自主模式（推荐）
uv run python -m src.main --platform browser --game ring --pilot auto

# 托管模式（AI 自主运行，人类可随时打断/接管）
uv run python -m src.main --platform browser --game ring --pilot managed

# 辅助模式（AI 建议 + 人类确认）
uv run python -m src.main --platform browser --game ring --pilot assist

# 无头模式
uv run python -m src.main --platform browser --game ring --headless
```

> 旧接口 `replaypoker`、`--human`、`--cli` 已废弃，但仍可用：
> ```bash
> uv run python -m src.main replaypoker        # → --platform browser --game ring
> uv run python -m src.main replaypoker --human # → --pilot assist
> uv run python -m src.main replaypoker --cli   # → --pilot assist
> ```

## 自动模式流程

1. 打开浏览器并登录
2. 导航到大厅，根据配置选择最佳桌子
3. 自动坐下并买入
4. 循环执行：清除弹窗 → 确保入座 → 检查 WS 连接 → 获取状态 → 策略决策 → 执行动作
5. 退出条件触发时离场（止损/止盈/筹码阈值）

## 退出阈值

`config/settings.yaml` 中的配置：

```yaml
game:
  exit_thresholds:
    stop_loss_bb: 250     # 亏损 250 BB 离桌
    take_profit_bb: 300   # 盈利 300 BB 离桌
    low_chips_bb: -1      # 桌上筹码不足 N BB 离桌（-1 关闭）
    max_chips_bb: 800     # 桌上筹码超过 N BB 离桌
```

## 桌子选择策略

```bash
uv run python -m src.main --platform browser --game ring --strategy most    # 选择玩家最多的桌子
uv run python -m src.main --platform browser --game ring --stakes 1/2       # 偏好盲注级别
```

| 策略 | 说明 |
|------|------|
| `fifo` | 先进先出 |
| `most` | 玩家最多 |
| `least` | 玩家最少 |
| `random` | 随机选择 |

## 截图与调试

| 命令 | 说明 |
|------|------|
| `screenshot [name]` | 手动截图 |
| `snap` | 快速截图（时间戳命名） |
| `autosnap on/off` | 开关自动截图 |

截图保存在 `data/snapshots/` 目录。
