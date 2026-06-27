# Ring Game 无限注现金桌

Ring Game 是 No-Limit Hold'em Cash Game 模拟，与 Arena 的关键区别：

## 运行方式

```bash
# Arena Ring Game
uv run python -m src.main --platform arena --game ring                  # AI 全自主
uv run python -m src.main --platform arena --game ring --pilot assist   # 人类辅助

# Browser Ring Game（ReplayPoker）
uv run python -m src.main --platform browser --game ring                # AI 全自主
uv run python -m src.main --platform browser --game ring --pilot assist # 人类辅助
```

> 旧接口 `ring`、`--human` 已废弃，但仍可用：
> ```bash
> uv run python -m src.main ring            # → --platform arena --game ring
> uv run python -m src.main ring --human    # → --pilot assist
> ```

## 模式对比

| 特性 | Arena | Ring Game |
|------|-------|-----------|
| 筹码管理 | 自动 rebuy/锁利 | 玩家自行决策（TableStrategy） |
| sit in/sit out | 无 | 支持站起/坐入 |
| 止盈止损 | 无 | 按 BB 阈值自动离场 |
| 策略分离 | 无 | TableStrategy + HandStrategy |

## 桌位策略

桌位策略（TableStrategy）管理 sit in/sit out、补筹、止盈止损等桌位级别决策。

### DefaultTableStrategy（默认）

- 短码补筹：筹码 < 10 BB 时自动补至 100 BB
- 筹码过厚 sit out：筹码 > 800 BB 时 sit out 锁定利润
- 止损离场：亏损 > 250 BB
- 止盈离场：盈利 > 300 BB

### ConservativeTableStrategy（保守）

- 止损：亏损 150 BB 即离场
- 止盈：盈利 200 BB 即离场
- 盈利 100 BB 就 sit out
- 更低的补筹阈值（15 BB）

### AggressiveTableStrategy（激进）

- 止损：亏损 500 BB 才离场
- 不主动止盈
- 不因筹码过厚 sit out
- 更低的补筹阈值（20 BB）

## 人类玩家桌位交互

启用 `--pilot assist` 或 `--pilot managed` 后，每手牌开始前会询问桌位决策：

```
┌─────── 桌位状态 ───────┐
│ 桌上筹码: 180 (90 BB)  │
│ 银行: 1800  |  盈亏: -20 │
│ 状态: 参与中            │
└─────────────────────────┘

桌位决策 (输入 help 查看命令):
```

输入命令：`none` / `sit_in` / `sit_out` / `add 500` / `leave`

## 运行报告示例

```
┌──────────────────────────────────────────┐
│ 总手数: 100  |  持续时间: 12.3s           │
└──────────────────────────────────────────┘

         Ring Game 报告
┌────────┬───────┬──────────┬────────┬──────┬────────┬───────┬──────┬──────┐
│ 玩家   │ 手牌… │ 桌位策略 │ 桌上…  │ 银行 │ 总盈亏 │ VPIP% │ PFR% │ 胜手 │
├────────┼───────┼──────────┼────────┼──────┼────────┼───────┼──────┼──────┤
│ Alice  │ gto   │ default  │    208 │ 1800 │     +8 │  20.0 │  0.0 │    2 │
│ Bob    │ range │ default  │    196 │ 1800 │     -4 │  40.0 │  0.0 │    1 │
└────────┴───────┴──────────┴────────┴──────┴────────┴───────┴──────┴──────┘
```
