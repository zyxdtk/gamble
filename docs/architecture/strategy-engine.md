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

## 六种策略

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

GTO 近似策略：

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
