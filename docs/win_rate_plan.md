# 胜率计算功能 (Win Rate Calculation)

## 状态: ✅ 已完成

## 目标
计算当前手牌在面对所有未弃牌对手时的真实胜率 (Equity)。

## 实现概述

### 1. 依赖
- `treys`: 纯 Python 的扑克评估库,用于快速计算手牌强度

### 2. 实现位置
**文件**: `src/decision_engine.py`

**方法**: `calculate_equity(state: GameState, iterations=1000)`

### 3. 核心逻辑

#### A. 统计活跃对手
```python
num_opponents = sum(1 for p in state.players.values() 
                   if p.is_active and p.status != "folded")
if num_opponents > 0:
    num_opponents -= 1  # 减去自己
if num_opponents < 1:
    num_opponents = 1   # 默认至少1个对手
```

#### B. 蒙特卡洛模拟
- **模拟次数**: 1000 次 (可配置)
- **每次模拟**:
  1. 为每个对手发随机手牌
  2. 发完剩余公共牌
  3. 评估所有玩家的牌力
  4. 只有优于所有对手才算获胜

```python
# 为所有对手发牌
villain_hands = []
for _ in range(num_opponents):
    villain_cards = [current_deck.pop(), current_deck.pop()]
    villain_hands.append(villain_cards)

# 评估所有对手,找出最强的
villain_scores = [self.evaluator.evaluate(vh, sim_board) 
                 for vh in villain_hands]
best_villain_score = min(villain_scores)  # 越小越强

# 判断胜负
if hero_score < best_villain_score:
    wins += 1
elif hero_score == best_villain_score:
    ties += 1
```

#### C. 计算胜率
```python
equity = (wins + (ties / 2)) / iterations * 100
return f"胜率 (对 {num_opponents} 位对手): {equity:.1f}%"
```

### 4. 显示效果

- **6人桌,全员在场**: `胜率 (对 5 位对手): 45.2%`
- **3人弃牌后**: `胜率 (对 2 位对手): 68.5%`
- **单挑**: `胜率 (对 1 位对手): 82.1%`

### 5. 性能
- **计算时间**: < 0.5 秒 (1000次模拟)
- **实时性**: 满足游戏需求

## 集成

### HUD 显示
胜率信息会显示在 HUD 中,格式为:
```
翻牌后: 对 K - 跟注/加注
胜率 (对 3 位对手): 72.5%
【对手分析】
  - 座位 2 (call): 宽松/投机 - 对子, 同花连牌
  - 座位 4 (raise): 紧凶 (前15%) - 88+, ATs+, KJs+
```

### 决策参考
- **胜率 > 70%**: 强力推荐加注
- **胜率 40-70%**: 跟注或根据赔率决定
- **胜率 < 40%**: 考虑弃牌

## 测试

测试文件: `tests/test_equity.py`

运行测试:
```bash
python tests/test_equity.py
```

## 已知问题

- Python 3.8 与 `treys` 库存在兼容性问题 (`list[int]` 语法)
- 建议使用 Python 3.9+ 或通过 `uv` 管理的 Python 3.12
