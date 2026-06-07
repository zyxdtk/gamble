# Arena 模拟引擎

Arena 是本地策略模拟系统，无需浏览器即可测试策略对抗。

## 核心组件

### GameEngine (`src/platforms/arena/game.py`)

德州扑克核心规则引擎，使用 `treys` 库进行牌力评估。

```python
engine = GameEngine(
    players_info=[{"name": "A", "stack": 1000}, {"name": "B", "stack": 1000}],
    small_blind=1, big_blind=2,
)
```

核心方法：
- `reset_hand(dealer_idx, hand_idx)` — 重置一手牌
- `deal_hole_cards()` — 发底牌
- `post_blinds(ante=0)` — 缴盲注，返回首个行动玩家索引
- `execute_action(player_idx, action_type, amount)` — 执行动作
- `next_street()` — 进入下一街（翻牌/转牌/河牌）
- `get_winners()` — 计算赢家（支持边池）

### ArenaAgent (`src/platforms/arena/agent.py`)

策略适配层，连接 GameEngine 与 Strategy：

```python
agent = ArenaAgent(seat_id=0, strategy=BalancedStrategy())
action, amount = agent.get_action(engine)  # -> (ArenaActionType, int)
```

核心逻辑：
1. `_translate_state(engine)` — 将 GameEngine 状态翻译为策略层 GameState
2. 调用 `strategy.make_decision(game_state)` 获取 ActionPlan
3. `plan.get_action_for_bet(to_call, pot)` 解析最终动作
4. `_translate_action()` — 策略 ActionType → Arena ActionType

### Competition (`src/platforms/arena/competition.py`)

对抗赛运行器，管理多手对抗：

- 筹码管理：低于 10 BB 自动 rebuy，超过 400 BB 锁定利润
- 下注循环：`_betting_loop(start_idx)` — 逐玩家请求决策
- 行为统计：VPIP（翻牌前自愿入池）、PFR（翻牌前加注）
- 摊牌观察：通知所有 Agent 对手摊牌

## 三种比赛模式

### Ring Game (`src/platforms/arena/ring.py`)

无限注现金桌，与 Competition 的关键区别：
- **双工通信**：通过 `AsyncChannel` 异步消息传递
- **双策略分离**：TableStrategy + HandStrategy
- **sit in/sit out**：玩家可站起/坐入
- **补筹码**：玩家可从银行补筹
- **止盈止损**：按 BB 阈值自动离场

### MTT (`src/platforms/arena/mtt.py`)

多桌锦标赛：
- `BlindSchedule` 盲注递增（standard/turbo/deepstack）
- `TournamentTable` 桌位管理，每手构建 players_info
- `_balance_tables()` 桌位平衡：淘汰出局、合并短桌、拆分过满
- `PrizePayout` 奖金分配
- `ICMStrategy` 泡沫期策略

### Sit & Go (`src/platforms/arena/sitngo.py`)

单桌锦标赛：
- 预设类型：HU (2人)、6max、9max、10max
- 固定奖金分配
- 无多桌平衡逻辑

## 统计指标

| 指标 | 定义 |
|------|------|
| VPIP | 翻牌前自愿入池率：CALL/RAISE/ALL_IN 占总手数比例 |
| PFR | 翻牌前加注率：RAISE/ALL_IN 占总手数比例 |
| Profit | 总盈亏 = (桌上筹码 + 银行 + 锁定利润) - 初始总资产 |

## 并发安全

Arena 是纯同步的，无锁环境：
- 每个 `ArenaAgent` 独立实例化 `Strategy`
- `GameEngine` 实例级状态，无共享可变数据
- `RingPlayer` 在独立 asyncio Task 中运行，通过 `AsyncChannel` 通信
