# 快速开始

德州扑克 AI 自动化与模拟系统。

## 环境准备

```bash
uv sync
playwright install chrome   # 仅浏览器模式需要
```

## 运行模式

```bash
# 平台 + 游戏类型正交组合
uv run python -m src.main --platform arena --game competition  # Arena 本地模拟对抗
uv run python -m src.main --platform arena --game ring         # Ring Game 现金桌
uv run python -m src.main --platform arena --game mtt          # MTT 多桌锦标赛
uv run python -m src.main --platform arena --game sng          # SNG 单桌赛
uv run python -m src.main --platform browser --game ring       # ReplayPoker 浏览器在线
```

不带参数运行进入交互式菜单。旧位置参数 `arena/ring/mtt/sng/replaypoker/auto/cli` 仍可用但已废弃。

## CLI 参数

### 核心参数（所有模式通用）

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--platform` | arena(本地) / browser(浏览器) | 无 |
| `--game` | ring / mtt / sng / competition | 无 |
| `--pilot` | auto(无人) / managed(托管) / assist(辅助) | `auto` |
| `--hands` | 游戏手数 | `100` |
| `--buyin` | 买入量：min/max/default 或整数 | 按模式 |
| `--players` | 玩家/参赛人数 | 按模式 |
| `--stack` | 起始筹码：short/medium/deep 或整数 | 按模式 |
| `--blinds` | 盲注结构：standard/turbo/deepstack | 按模式 |
| `--headless` | 浏览器无头模式 | `false` |
| `--strategy` | tag/gto/range/exploitative/checkorfold/aggressive/neural | `tag` |
| `--log-level` | DEBUG/INFO/WARNING/ERROR | `INFO` |

### 模式专属参数

| 参数 | 适用模式 | 说明 | 默认值 |
|------|---------|------|--------|
| `--preset` | sng | SNG 类型：hu/6max/9max/10max | 无 |
| `--prize` | mtt | 奖金分配（如 `50,30,20`） | 自动 |
| `--stakes` | browser | 偏好盲注级别（如 1/2） | 配置文件 |

### 参数默认值按模式

| 参数 | arena competition | arena ring | mtt | sng | browser |
|------|------------------|-----------|-----|-----|---------|
| `--buyin` | - | 200 | 100 | 50 | min |
| `--players` | 7 | - | 18 | - | - |
| `--stack` | - | - | 1000 | 1500 | - |
| `--blinds` | - | - | standard | turbo | - |

## Browser 模式自动流程

1. 打开浏览器并登录
2. 导航到大厅，根据配置选择最佳桌子
3. 自动坐下并买入
4. 循环：清弹窗 → 确保入座 → 检查 WS → 获取状态 → 策略决策 → 执行动作
5. 卡住检测：连续 30 轮无法入座 → 自动换桌（连续 5 次仍失败等 60s）
6. 退出条件触发时离场（止损/止盈/筹码阈值）

退出阈值在 `config/settings.yaml` 的 `game.exit_thresholds` 和 `auto_mode` 中配置。

## Ring Game 桌位策略

桌位策略（TableStrategy）管理 sit in/sit out、补筹、止盈止损：

| 策略 | 止损 | 止盈 | sit out | 补筹阈值 |
|------|------|------|---------|---------|
| default | -250 BB | +300 BB | >800 BB | <10 BB |
| conservative | -150 BB | +200 BB | >100 BB | <15 BB |
| aggressive | -500 BB | 不止盈 | 不 sit out | <20 BB |

## MTT/SNG 盲注结构

| 类型 | MTT | SNG |
|------|-----|-----|
| standard | 每 10 手升一级 | 标准升级 |
| turbo | 每 5 手升一级 | 快速升级（默认） |
| deepstack | 起始筹码更多，升级更慢 | - |

SNG 预设：`hu`(2人) / `6max`(6人) / `9max`(9人) / `10max`(10人)

## Pilot 模式

| 模式 | `--pilot` | 说明 |
|------|----------|------|
| 无人 | `auto` | AI 全自主，异常退出提示人类 |
| 托管 | `managed` | AI 自主，人类可随时打断/接管 |
| 辅助 | `assist` | AI 建议，人类确认/覆盖 |

### 手牌命令

`fold` / `check` / `call` / `raise <金额>` / `allin` / `status` / `help`

按回车使用推荐默认动作。

### 桌位命令（Ring Game）

`none` / `sit_in` / `sit_out` / `add <金额>` / `leave`

### 浏览器命令（managed/assist）

`login` / `lobby` / `tables` / `best` / `open [idx|url]` / `sit` / `buyin <金额>` / `leave` / `screenshot` / `snap` / `config`

## 可用策略

| 策略 | 说明 |
|------|------|
| `tag` | 紧凶策略（默认） |
| `gto` / `balanced` | GTO 近似，手牌分级 + EV 驱动 |
| `range` | 范围策略，贝叶斯对手建模 |
| `exploitative` | 剥削策略，根据对手类型调整 |
| `aggressive` | 激进策略，宽入池大下注 |
| `checkorfold` | 保守策略 |
| `neural` | DQN 深度学习（需训练模型） |
| `icm` | ICM 锦标赛泡沫期专用 |

## 训练与启动

```bash
uv run python scripts/train_nlh_model.py   # 训练神经网络
./start.sh --interactive                    # 交互式启动器
```
