# Brain 模块核心逻辑 (Brain Core Logic)

本文档记录 Brain 模块的决策核心，用于检查 AI 逻辑是否符合预期。

---

## 1. 核心决策流程 (Decision Flow)

1.  **State Prep**: 接收 `GameState`，识别当前位置（SB/BB/EP/MP/LP）。
2.  **Plan Generation**: 生成 `ActionPlan`（包含主动作、加注额、跟注上限 `limit_amount`、退守动作 `fallback`）。
3.  **Real-time Adaptation**: 执行时对比对手真实注额。若 `to_call <= limit_amount` 则执行主动作；否则执行 `fallback`（通常是 FOLD）。

---

## 2. 策略逻辑细节

### 2.0 TAG (紧凶型) - *默认策略*
- **定位**: 介于 GTO 和 Exploitative 之间的平衡型紧凶打法，代码在 `strategies/tag.py`。
- **翻前**: 基于位置（EP/MP/LP/SB/BB）和手牌等级做 RFI / vs Open / 3bet 决策，使用 `preflop_ranges.yaml` 范围表。
- **翻后**: 基于 equity bucket 和 SPR 调整下注尺度，价值与诈唬的混合频率参考 GTO 表。
- **配置**: `config/settings.yaml` 的 `strategy.type: tag`（也是代码默认值）。

### 2.1 Range (范围策略) - *稳健基石*
- **核心标准**: 基于 **EHS (Effective Hand Strength)**。
- **翻牌前**: 严格遵守 `preflop_ranges.yaml`。
- **翻牌后**:
  - `EHS > 0.75`: 强价值加注（0.75 Pot）。
  - `EHS > PotOdds + 0.1`: 赔率领先，执行 CALL/CHECK。
  - `SPR < 2`: 自动进入套池模式，降低跟注/全下阈值。

### 2.2 GTO (博弈论最优) - *不可剥削*
- **手牌分级**: AA/KK/AKs (Tier 1) ->...-> 垃圾牌 (Tier 4)。
- **混合策略**: 对边缘强牌进行概率加注/跟注，增加对手读牌难度。
- **EV 驱动**: 翻牌后通过网格搜索 (Grid Search) 寻找预估 EV 最大的加注尺度（如 1/3 Pot, 1/2 Pot, Pot）。

### 2.3 Exploitative (剥削策略) - *利润最大化*
基于对手的行为特征（VPIP/PFR）动态调整权重：
- **对抗 Nit (紧逼)**: 扩大偷盲范围，面对其加注时极度谨慎。
- **对抗 Maniac (疯子)**: 减少诈唬，放宽抓诈 (Bluff Catch) 的胜率门槛。
- **对抗 Station (跟注站)**: **绝不诈唬**。仅进行大尺度的价值下注。
- **对抗 Fish (鱼)**: 进行极端尺度的价值榨取（Overbet）。

---

## 3. 风险控制逻辑 (Risk Control)

- **危险牌面感知**: 自动识别公牌成双、三同花等高风险局面，自动调低非 Nuts 牌的 `limit_amount`。
- **止损墙**: 记录每手牌投入，若本局投入超过总筹码定值且非顶级强牌，强制触发 FOLD。
- **响应即时性**: 所有计算均在本地完成，无任何人为延迟，确保不超时。
