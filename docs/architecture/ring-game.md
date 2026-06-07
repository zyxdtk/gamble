# Ring Game 架构设计

Ring Game 无限注现金桌的架构设计，与 Arena Competition 的核心差异是双工通信和双策略分离。

## 整体架构

```
                    ┌─────────────────────────────────────┐
                    │          RingPlatform                │
                    │  (管理 table、players、channels)      │
                    ├─────────────────────────────────────┤
                    │                                     │
                    │  ┌──────────┐    AsyncChannel       │
                    │  │RingPlayer│◄──────────────────►   │
                    │  │  (AI)    │   send_to_player()    │
                    │  │          │   receive_from_player()│
                    │  └──────────┘                        │
                    │                                     │
                    │  ┌──────────┐    AsyncChannel       │
                    │  │RingPlayer│◄──────────────────►   │
                    │  │  (AI)    │                        │
                    │  └──────────┘                        │
                    │                                     │
                    │  ┌──────────┐    AsyncChannel       │
                    │  │CLIRing   │◄──────────────────►   │
                    │  │ Player   │                        │
                    │  │ (Human)  │                        │
                    │  └──────────┘                        │
                    └─────────────────────────────────────┘
```

## 双工通信

### AsyncChannel (`src/core/messaging.py`)

基于 `asyncio.Queue` 的点对点消息通道：

```
Platform                              Player
   │                                    │
   │  ── send_to_player(msg) ──────►   │
   │                                    │
   │  ◄── receive_from_player() ─────   │
   │                                    │
   │  ── request_response(req) ────►   │
   │       (等待响应)                    │
   │  ◄────────── response ─────────   │
   │                                    │
```

`request_response()` 封装请求-响应配对：通过 `request_id` 将请求和响应配对，支持超时。

### MessageType

| 方向 | 类型 | 说明 |
|------|------|------|
| Platform → Player | `TABLE_STATE` | 桌位状态推送 |
| Platform → Player | `REQUEST_ACTION` | 请求手牌决策 |
| Platform → Player | `REQUEST_TABLE_ACTION` | 请求桌位决策 |
| Platform → Player | `HAND_RESULT` | 手牌结果 |
| Platform → Player | `GAME_OVER` | 游戏结束 |
| Player → Platform | `HAND_ACTION` | 手牌动作回复 |
| Player → Platform | `TABLE_ACTION` | 桌位动作回复 |

与 EventBus 的关系：EventBus 负责全局广播（日志、统计），AsyncChannel 负责 Platform 和特定 Player 之间的指令级通信。

## 双策略分离

### TableStrategy（桌位策略）

管理 sit in/sit out、补筹码、止盈止损等桌位级别决策：

```python
class TableStrategy(ABC):
    def decide(self, state: TableState) -> TableAction
```

`TableState` 包含：桌上筹码、银行余额、是否坐入/参与、盈亏、BB 阈值等。
`TableAction` 包含：动作类型（SIT_IN/SIT_OUT/ADD_CHIPS/LEAVE/NONE）+ 金额。

三种实现：
- `DefaultTableStrategy` — 短码补筹 / 筹码过厚 sit out / 止损止盈离场
- `ConservativeTableStrategy` — 更紧阈值，盈利后倾向 sit out
- `AggressiveTableStrategy` — 更松，频繁补筹，不止盈

### HandStrategy（手牌策略）

管理 fold/check/call/raise 等手牌级别决策：

```python
class HandStrategy(ABC):
    def make_decision(self, state: GameState) -> ActionPlan
```

`StrategyHandAdapter` 将现有 `Strategy` 包装为 `HandStrategy`，实现向后兼容。

## RingPlatform 主循环

```python
async def run(self) -> RingReport:
    await self._initial_buyin()           # 1. 初始买入

    for player in self.players:
        task = create_task(player.run())   # 2. 启动 Player 任务

    for hand_idx in range(1, max_rounds):
        await self._table_decision_phase() # 3. 桌位决策阶段
        await self._play_hand(hand_idx)    # 4. 执行一手牌
        if self._check_termination():      # 5. 检查终止条件
            break
```

### _play_hand 流程

```
1. 构建 players_info（仅 is_playing 且 chips > 0 的玩家）
2. 创建 GameEngine
3. 发牌、盲注
4. 翻牌前下注循环（通过 channel 请求决策）
5. 后续街道下注循环
6. 摊牌 / 结算
7. 同步筹码回 RingTable
8. 通知手牌结果
9. 更新盈亏统计和全局画像
10. 发布 EventBus 事件
```

### _betting_loop 异步下注

```
对于每个需要行动的玩家：
  1. 构建手牌状态 payload（复用 ArenaAgent._translate_state 逻辑）
  2. 通过 channel.request_response() 请求决策
  3. 转换为 ArenaActionType
  4. 执行 engine.execute_action()
  5. 通知其他玩家观察到的动作
  6. 超时则自动弃牌
```

## 为什么不修改 GameEngine

Ring Game 的 sit_in/sit_out 逻辑在 `RingPlatform._play_hand()` 中处理：构建 `players_info` 时只传入 `is_playing and chips > 0` 的玩家，与 TournamentTable 的做法一致。GameEngine 无需修改。

## 状态翻译在 Platform 侧

`RingPlatform._build_hand_state_payload()` 复用 `ArenaAgent._translate_state()` 的逻辑，将 GameEngine 状态翻译为可序列化的 payload，通过 Message 发给 RingPlayer。RingPlayer 从 payload 恢复 GameState 后调用 `hand_strategy.make_decision()`。

## 用户交互

CLIRingPlayer 不继承 RingPlayer，而是独立实现。参考 `BrowserTestCLI` 的 `run_in_executor + input()` 模式实现异步终端输入。
