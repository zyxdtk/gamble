# 策略引擎设计

策略引擎（Brain）是决策核心，采用策略模式支持多种决策风格。

## 核心决策流程

```
GameState 输入
    │
    ▼
┌─────────────┐
│ 状态准备     │  翻译引擎状态，补充统计画像
└─────┬───────┘
      │
      ▼
┌─────────────┐
│ 计划生成     │  Strategy.make_decision(state) -> ActionPlan
└─────┬───────┘
      │
      ▼
┌─────────────┐
│ 实时裁决     │  ActionPlan.get_action_for_bet(to_call, pot) -> (ActionType, amount)
└─────────────┘
```

## 策略注册与别名

`StrategyManager` 通过文件系统扫描注册策略：

- **注册键** = 文件名去掉 `.py` 后小写并去下划线（如 `gto_solver.py` → `gtosolver`，`check_or_fold.py` → `checkorfold`）
- **版本化键**：`{base}_v{version}`（如 `tag_v1`），裸名键始终指向最新版本
- **别名机制**：策略类可通过 `strategy_aliases` 类属性注册别名（如 `GtoSolverStrategy.strategy_aliases = ["gto"]`）
- **默认策略**：`tag`（配置在 `config/settings.yaml` 的 `strategy.type`，代码默认值在 `browser_platform.py` 和 `main.py`）

当前已注册策略键：`tag` / `gto`(=gtosolver) / `balanced` / `range` / `exploitative` / `aggressive` / `checkorfold` / `neural` / `icm`，每个都有对应的 `_v1` 版本化键。

## 九种策略

### TAG 策略（默认）

紧凶型（Tight-Aggressive），代码实现在 `src/strategies/strategies/tag.py`。配置和文档中用 `tag` 引用。

- 翻前基于位置和手牌等级做 RFI / vs Open / 3bet 决策
- 翻后基于 equity bucket 和 SPR 调整下注尺度
- 介于 GTO 和 Exploitative 之间的平衡型打法

### Range 策略

基于 EHS（Effective Hand Strength）的数学化决策：

- **EHS 公式**：`EHS = HS + (1-HS)*PP - HS*NP`
  - HS = Hand Strength（当前胜率）
  - PP = Pot Potential（成牌潜力）
  - NP = Negative Potential（反超风险）
- 翻牌前使用范围表（`config/preflop_ranges.yaml`）按位置查表
- 翻牌后 EHS 评估 + SPR 下注尺度
- 对手范围建模：贝叶斯更新
- MDF 最小防守频率

### GTO / Balanced 策略

GTO 近似策略（`gto_solver.py`，配置用 `gto` 或 `gtosolver`）：

- 手牌分级：超强牌 / 强牌 / 中等牌 / 边缘牌 / 弱牌
- 混合策略：`secondary_action` + `secondary_probability` 实现概率化决策
- EV 驱动下注尺度：网格搜索最优 raise 金额
- 紧凑度修正：根据对手 VPIP/PFR 调整阈值

### Exploitative 策略

根据对手类型动态调整：

| 对手类型 | VPIP/PFR 特征 | 调整策略 |
|----------|---------------|----------|
| Nit | 极低 | 扩大偷盲，薄价值下注 |
| Maniac | 极高 | 减少诈唬，扩大价值范围 |
| Station | 高 VPIP 低 PFR | 不诈唬，只价值下注 |
| Fish | 异常模式 | 超池下注，利用错误 |

### Aggressive 策略

更宽的入池范围和更大的下注尺度，减少弃牌。

### CheckOrFold 策略

最保守策略，只看牌或弃牌。用于基线测试。

### Neural 策略

基于 DQN 深度学习，需要预训练模型。

### ICM 策略

锦标赛专用，考虑独立筹码模型（Independent Chip Model）进行泡沫期决策。

## ActionPlan 结构

```python
@dataclass
class ActionPlan:
    primary_action: ActionType       # 主动作
    primary_amount: int              # 主金额
    secondary_action: Optional[ActionType]  # 备选动作（混合策略）
    secondary_amount: int
    secondary_probability: float     # 执行备选动作概率
    bet_size_hint: Optional[str]     # "min"/"half_pot"/"pot"/"max"
    limit_amount: int                # 安全阈值
    fallback_action: ActionType      # 超过安全阈值后的退守动作
    confidence: float
    reasoning: str
    strategy_name: str
    my_equity: float
    pot_odds: float
    ev: float
```

`get_action_for_bet(to_call, pot)` 的裁决逻辑：
1. 安全检测：`to_call > limit_amount` → 退守
2. 混合策略：按概率随机选择主/备动作
3. 兜底：`CHECK` 但 `to_call > 0` → 退守

> **注意**：当前 `get_action_for_bet` 不钳制 raise 金额到自身筹码。当对手 all-in 金额 ≥ 自身筹码时，策略可能返回超出筹码的 raise 金额，导致 ReplayPoker 把 Raise 按钮置灰。`auto_player._choice_to_game_action` 会在这种情形打 WARNING 日志（`[筹码冲突]`），但不会自动降级到 CALL/ALL_IN。后续可在 `ActionPlan` 层加 `min(amount, my_chips)` 钳制根治。

## 对手画像系统 (`src/strategies/player_analysis/`)

| 组件 | 说明 |
|------|------|
| `manager.py` | `PlayerManager`：管理玩家统计，SQLite 持久化 |
| `model.py` | 玩家数据模型 |
| `showdown_model.py` | 摊牌记录建模 |
| `stats_model.py` | VPIP/PFR 等统计建模 |
| `tags.py` | 玩家标签（Nit/Maniac/Station/Fish） |
| `database.py` | SQLite 数据库访问层 |

## 事件处理

策略通过 `handle_event(event_type, data)` 接收事件：

| 事件类型 | 触发时机 | 数据 |
|----------|----------|------|
| `"action"` | 对手执行动作 | `user_id`, `action`, `pot_ratio` |
| `"showdown"` | 摊牌 | `user_id`, `hand_str`, `street` |

Exploitative 策略利用这些事件更新对手画像。
