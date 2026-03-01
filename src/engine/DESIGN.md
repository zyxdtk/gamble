# Engine 模块设计文档

该目录包含了德州扑克 AI 自动化系统的核心"大脑"。它负责接收 `GameState`（牌桌通用状态），并返回清晰的动作指令（包含 Action 类型与数额）。

## 架构概览

```
src/engine/
├── __init__.py              # 模块导出
├── engine_manager.py        # 决策引擎管理器（单例）
├── brain_base.py            # 大脑基类
├── action_plan.py           # 行动方案数据结构
├── strategies/              # 策略实现（每个策略一个文件）
│   ├── __init__.py
│   ├── check_or_fold.py     # Check or Fold 策略
│   ├── gto.py               # GTO 策略
│   └── exploitative.py      # 剥削性策略
└── utils/                   # 公共工具
    ├── __init__.py
    ├── equity.py            # 胜率计算
    ├── ranges.py            # 起手牌范围管理
    └── position.py          # 位置计算、玩家标签
```

## 核心组件

### 1. EngineManager（决策引擎管理器）

单例模式，负责管理所有牌桌的大脑实例。

**主要功能：**
- 自动发现并注册 `strategies/` 目录下的策略
- 创建、获取、移除大脑实例
- 实时更新大脑状态
- 请求决策

**使用示例：**
```python
from src.engine import EngineManager

mgr = EngineManager(thinking_timeout=2.0)

# 进入play模式时创建大脑
mgr.create_brain(table_id="table_1", strategy_type="gto")

# 实时传递table信息
mgr.update_brain("table_1", game_state)

# 请求决策
decision = mgr.get_decision("table_1", game_state)

# 离开牌桌时移除大脑
mgr.remove_brain("table_1")
```

### 2. Brain（大脑基类）

所有策略的抽象基类，支持：
- **预设行动方案**：在收到新信息时预先计算行动范围
- **限时思考**：在配置的时间内进行深度思考，超时则使用现有方案
- **实时更新**：随着牌局进展更新行动方案

**核心方法：**
```python
class Brain(ABC):
    def create_initial_plan(self, state: GameState) -> ActionPlan:
        """创建初始行动方案"""
        
    def update_plan(self, state: GameState) -> ActionPlan:
        """更新行动方案（轻量级）"""
        
    def deep_think(self, state: GameState) -> ActionPlan:
        """深度思考（重量级，可能超时）"""
        
    def receive_table_update(self, state: GameState) -> None:
        """接收牌桌更新"""
        
    def make_decision(self, state: GameState) -> dict:
        """做出决策（限时思考 + 行动方案）"""
```

### 3. ActionPlan（行动方案）

预设的行动方案数据结构，支持根据对手押注自动选择行动。

**字段说明：**
```python
@dataclass
class ActionPlan:
    primary_action: ActionType      # 主要行动
    primary_amount: int             # 主要行动金额
    fallback_action: ActionType     # 备选行动
    fallback_amount: int            # 备选行动金额
    call_range_min: int             # 跟注范围下限
    call_range_max: int             # 跟注范围上限
    raise_range_min: int            # 加注范围下限
    raise_range_max: int            # 加注范围上限
    fold_threshold: int             # 弃牌阈值
    confidence: float               # 置信度
    reasoning: str                  # 决策理由
```

**自动决策逻辑：**
```python
def get_action_for_bet(self, to_call: int, pot: int) -> tuple[ActionType, int]:
    """
    根据对手押注自动选择行动：
    - 如果可以免费看牌 -> CHECK
    - 如果押注超过弃牌阈值 -> FOLD
    - 如果押注在跟注范围内 -> CALL
    - 如果押注低于加注范围下限 -> RAISE
    - 否则 -> 使用备选行动
    """
```

## 策略实现

### CheckOrFoldBrain
最简单的策略：能过则过，不能过就弃牌。适合测试和挂机。

### GTOBrain

基于博弈论最优策略，追求长期不可被剥削的决策。

#### 手牌分级系统

| Tier | 手牌 | 说明 |
|------|------|------|
| **Tier 1** | AA, KK, QQ, JJ, AKs, AKo | 顶级强牌 |
| **Tier 2** | TT, 99, AQs, AQo, AJs, KQs | 强牌 |
| **Tier 3** | 88, 77, ATs, KJs, QJs, JTs, T9s | 中等牌 |
| **Tier 4** | 其他 | 弱牌/边缘牌 |

#### 翻牌前策略

**核心逻辑：**
```python
def _create_preflop_plan(state, hand_str, pos_code):
    # Tier 1: 总是加注 75% 底池
    if tier == 1:
        return RAISE(pot * 0.75)
    
    # Tier 2: 根据位置和跟注金额决定
    if tier == 2:
        if to_call <= 2 or position in [LP, MP]:
            return RAISE(pot * 0.66) if no_raise else CALL
        return CALL(fold_threshold=6)
    
    # Tier 3: 位置好且便宜时跟注
    if tier == 3:
        if position in [LP, MP] and to_call <= 4:
            return CALL(max=4)
        return CALL(max=2, fallback=FOLD)
    
    # 其他: 在范围内则跟注，否则弃牌
    if in_range:
        return CALL(max=4, fallback=FOLD)
    return CHECK/FOLD
```

**位置代码：**
- `EP` - 早期位置 (Early Position)
- `MP` - 中期位置 (Middle Position)
- `LP` - 晚期位置 (Late Position)
- `SB` - 小盲注
- `BB` - 大盲注

#### 翻牌后策略

**核心逻辑：**
```python
def _create_postflop_plan(state, hand_str):
    equity = calculate_equity(hole_cards, community_cards, num_opponents)
    pot_odds = to_call / (pot + to_call)
    
    # 超强牌 (>70% equity): 大额价值下注
    if equity > 0.70:
        return RAISE(pot * 0.75)
    
    # 强牌 (> pot_odds + 15%): 标准价值下注
    if equity > raise_threshold:
        return RAISE(pot * 0.66, call_range_max=pot*0.5)
    
    # 中等牌 (> pot_odds): 跟注
    if equity > call_threshold:
        return CALL(max=pot*0.5, fallback=CHECK)
    
    # 弱牌: 过牌/弃牌
    return CHECK/FOLD(fold_threshold=pot*0.3)
```

**对手类型调整（在 GTO 基础上）：**
- 对抗 Nit: `call_threshold += 0.10`, `raise_threshold += 0.15`
- 对抗 Maniac: `call_threshold -= 0.05`

---

### ExploitativeBrain

在 GTO 基础上，根据对手类型进行针对性剥削。通过分析对手的 VPIP/PFR 数据，给对手打标签并调整策略。

#### 玩家标签系统

| 标签 | VPIP | PFR | 特征 |
|------|------|-----|------|
| **紧逼 (Nit)** | <15% | - | 只玩超强牌，容易弃牌 |
| **疯子 (Maniac)** | >50% | >30% | 频繁加注诈唬 |
| **跟注站 (Calling Station)** | >40% | <10% | 跟注很宽，很少加注 |
| **宽松被动 (Fish)** | >30% | <15% | 玩太多牌，被动跟注 |
| **紧凶 (TAG)** | <25% | >15% | 标准优秀玩家 |
| **普通 (Average)** | - | - | 无明显特征 |

#### 翻牌前剥削策略

**对抗紧逼型 (Nit):**
```python
if opp_types["nit"] > 0:
    # 更激进的偷盲
    if plan == CHECK and to_call == 0:
        plan = RAISE(pot * 0.5)  # 对Nit偷盲
    elif plan == RAISE:
        plan.amount *= 1.3  # 对Nit施压
```

**对抗疯子 (Maniac):**
```python
if opp_types["maniac"] > 0:
    # 收紧范围，减少诈唬
    if plan == RAISE and equity < 0.55:
        plan = CALL(max=pot*0.3)  # 对Maniac收紧
    elif plan == CALL:
        plan.call_range_max *= 1.5  # 对Maniac抓诈
```

**对抗跟注站 (Calling Station):**
```python
if opp_types["station"] > 0:
    if plan == RAISE:
        if equity > 0.60:
            plan.amount *= 1.4  # 强牌加大注
        else:
            plan = CHECK  # 弱牌不诈唬
```

**对抗鱼 (Fish):**
```python
if opp_types["fish"] > 0:
    if plan == RAISE and equity > 0.50:
        plan.amount *= 1.5  # 对Fish压榨
    elif plan == CALL:
        plan.call_range_max *= 1.3  # 对Fish宽跟注
```

#### 翻牌后剥削策略

**对抗紧逼型:**
- 价值下注加大 30% (equity > 60%)
- 诈唬减少注码 30% (equity < 40%)

**对抗疯子:**
- 用更宽的范围抓诈唬 (equity > 30% 就 CALL)
- 绝不诈唬加注

**对抗跟注站:**
- 纯价值策略：强牌下重注 (equity > 55% 加注 50%)
- 绝不诈唬
- 边缘牌直接弃牌 (equity < 35%)

**对抗鱼:**
- 更宽的价值下注范围 (equity > 45%)
- 更宽的跟注范围 (1.4x)

#### 策略对比

| 场景 | GTO | Exploitative |
|------|-----|--------------|
| 对抗 Nit | 标准加注 | 更大加注，频繁偷盲 |
| 对抗 Maniac | 标准范围 | 收紧范围，抓诈唬 |
| 对抗 Station | 混合策略 | 纯价值，绝不诈唬 |
| 对抗 Fish | 标准下注 | 极端价值压榨 |

**使用建议：**
- **GTO**: 对手未知或对手水平较高时使用
- **Exploitative**: 对手有明显漏洞时使用，收益更高但可能被反剥削

## 公共工具

### EquityCalculator
胜率计算器（单例）：
- 使用 treys 库进行蒙特卡洛模拟
- 支持翻牌前快速估算
- 支持多对手场景

### RangeManager
起手牌范围管理器（单例）：
- 从 `config/preflop_ranges.yaml` 加载范围表
- 提供默认回退范围
- 支持手牌分级（tier1/tier2/tier3）

### 位置和玩家标签工具
- `get_position_code(state)` - 计算位置代码（EP/MP/LP/SB/BB）
- `normalize_hand_string(hole_cards)` - 标准化手牌表示
- `get_player_tag(player)` - 根据VPIP/PFR给玩家打标签

## 配置项

在 `config/settings.yaml` 中：

```yaml
strategy:
  type: "gto"              # 策略类型: gto, exploitative, checkorfold
  thinking_timeout: 2.0    # 思考时间限制（秒）
```

## 工作流程

1. **进入Play模式**：
   - `TableManager.initialize()` 调用 `EngineManager.create_brain()`
   - 根据配置的策略类型创建对应的大脑实例

2. **实时更新**：
   - WebSocket 收到消息时，调用 `EngineManager.update_brain()`
   - 大脑更新预设行动方案

3. **请求决策**：
   - 需要玩家行动时，调用 `EngineManager.get_decision()`
   - 大脑尝试在限时内进行深度思考
   - 超时则使用现有行动方案

4. **执行行动**：
   - 根据行动方案和当前押注情况选择具体行动
   - 执行点击操作

5. **离开牌桌**：
   - `TableManager.on_close()` 调用 `EngineManager.remove_brain()`
   - 清理大脑实例
