# MTT/SNG 锦标赛模式

MTT（多桌锦标赛）和 SNG（Sit & Go 单桌赛）是锦标赛淘汰模式。

## 运行方式

```bash
# MTT
uv run python -m src.main --platform arena --game mtt                  # AI 全自主
uv run python -m src.main --platform arena --game mtt --pilot assist   # 人类辅助

# SNG
uv run python -m src.main --platform arena --game sng                  # AI 全自主
uv run python -m src.main --platform arena --game sng --pilot assist   # 人类辅助
```

> 旧接口 `mtt`、`sng` 已废弃，但仍可用：
> ```bash
> uv run python -m src.main mtt            # → --platform arena --game mtt
> uv run python -m src.main sng            # → --platform arena --game sng
> uv run python -m src.main mtt --human    # → --pilot assist
> ```

## 模式对比

| 特性 | Arena | Ring | MTT | SNG |
|------|-------|------|-----|-----|
| 桌数 | 单桌 | 单桌 | 多桌（自动平衡） | 单桌 |
| 盲注 | 固定 | 固定 | 递增 | 递增 |
| 淘汰制 | 否 | 否 | 是 | 是 |
| 奖金分配 | 无 | 无 | 按名次 | 按名次 |

## 盲注结构

### MTT

| 类型 | 说明 |
|------|------|
| `standard` | 每 10 手升一级 |
| `turbo` | 每 5 手升一级 |
| `deepstack` | 起始筹码更多，升级更慢 |

### SNG

| 类型 | 说明 |
|------|------|
| `standard` | 标准升级 |
| `turbo` | 快速升级（默认） |

## SNG 预设类型

| 预设 | 人数 | 奖金分配 |
|------|------|----------|
| `hu` | 2 人 | 冠军 66% / 亚军 34% |
| `6max` | 6 人 | 1-3 名 |
| `9max` | 9 人 | 1-5 名 |
| `10max` | 10 人 | 1-5 名 |

## 运行报告示例

```
┌──────────────────────────────────────────────────────────────┐
│ 参赛: 9 人  |  奖池: 900  |  总手数: 42  |  耗时: 3.2s      │
└──────────────────────────────────────────────────────────────┘

         MTT 锦标赛报告
┌──────┬──────────┬──────────────┬──────────┬────────┐
│ 名次 │ 玩家     │ 策略         │    奖金  │ 淘汰手 │
├──────┼──────────┼──────────────┼──────────┼────────┤
│    1 │ Player3  │ exploitative │      360 │ 冠军!  │
│    2 │ Player1  │ gto          │      225 │ #42    │
└──────┴──────────┴──────────────┴──────────┴────────┘
```
