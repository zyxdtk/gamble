根据今天的数据分析和代码改动，整理出下周可继续优化的点：

***

## 🔴 高优先级（直接影响盈利）

### 1. TAG翻后paired board规则

- **依据**：-350 JJ局，在 `2h 3d 2s 6h` paired board 上持续 raise → 对死胡同
- **改动**：在 [tag.py:530-580](file:///Users/ly/Workspace/gitee/gamble/src/strategies/strategies/tag.py#L530-L580) 翻后决策加规则：
  - `board_texture.is_paired` 且 `my_hand_strength` 是单对（非 set+）→ 关掉 value bet，改 check-call
  - paired board 上禁止主动 raise（除非是 set/两对/满堂等强成牌）

### 2. 河牌谨慎策略

- **依据**：6局打到river，总亏 -676（-112/局）
- **改动**：在 river 决策加限制：
  - 中等成牌（单对/两对）强制 check-call，禁止 raise
  - 只允许：(a) 强成牌 value bet、(b) 听牌破产点 bluff、(c) 0 EV 摊牌
  - 在 [tag.py:620-680](file:///Users/ly/Workspace/gitee/gamble/src/strategies/strategies/tag.py#L620-L680) river 决策逻辑加 `if equity < 0.6 and hand_strength < "two_pair": action = "check"`

### 3. 翻前raise选牌和尺寸优化

- **依据**：14局 raise 最终行动，亏 -723（-51.6/局）
- **改动**：
  - 调整 [preflop\_range.py:125-180](file:///Users/ly/Workspace/gitee/gamble/src/strategies/utils/preflop_range.py#L125-L180) 的 Tier 分布
  - Tier 3 手牌（88/77/AJs/QJs）禁止主动 raise（除非在后位且有隔离优势）
  - raise 尺寸从 3bb 调到 2.5bb（减少被 4bet 的风险）

### 4. 负EV桌自动离开

- **依据**：table 16986872: 30局 -693（-23/局）；table 16985618: 18局 -490（-27/局）
- **改动**：在 [auto\_player.py:484-520](file:///Users/ly/Workspace/gitee/gamble/src/platforms/browser/auto_player.py#L484-L520) 加桌台黑名单：
  - 记录每个 table\_id 的累计盈亏和局数
  - 如果某桌盈亏 < -15/局 且局数 > 10 → 自动换桌
  - 配置项：`--bad-table-threshold -15`（BB/局）

***

## 🟡 中优先级（提升数据质量和分析能力）

### 5. state.hole\_cards污染根因分析

- **依据**：warn.log 多次出现 `[fallback]` + reasoning 引用了错误牌型（T5s vs J8o）
- **现状**：已加 sanity check，但根因未知
- **调查**：
  - 看 [state\_manager.py:193-250](file:///Users/ly/Workspace/gitee/gamble/src/platforms/browser/state_manager.py#L193-L250) WS 帧解析逻辑
  - 看 [replay\_poker.py:380-420](file:///Users/ly/Workspace/gitee/gamble/src/platforms/browser/adapters/replay_poker.py#L380-L420) DOM 解析 hole\_cards 的时机
  - 怀疑：上一手牌残留 + SPA 页面未完全刷新

### 6. WS/DOM底池来源统一化

- **依据**：POT-MISMATCH 160次（虽然已降噪，但本质是来源不一致）
- **改动**：
  - 在 [state\_manager.py:435-461](file:///Users/ly/Workspace/gitee/gamble/src/platforms/browser/state_manager.py#L435-L461) 强制只用 DOM 的 pot（或只用 WS）
  - 或者加幂等校验：`dom_pot == ws_pot ± tolerance`，否则触发重新抓取

### 7. 手牌历史记录字段增强

- **依据**：分析时缺少关键信息（对手行为模式、牌桌动态）
- **改动**：在 [hand\_recorder.py:534-575](file:///Users/ly/Workspace/gitee/gamble/src/platforms/browser/hand_recorder.py#L534-L575) 加字段：
  - `pot_by_street`: 每个街道的底池大小变化
  - `opponents_actions`: 对手在本手的决策序列（简化版，只记关键动作）
  - `board_texture_final`: 最终公牌的纹理分类（paired/flush\_possible/straight\_possible）
  - `my_final_hand_strength`: 最终成牌强度（用于事后分析 EV）

***

## 🟢 低优先级（体验和性能）

### 8. 策略缓存优化

- **依据**：[cli\_player.py:187-189](file:///Users/ly/Workspace/gitee/gamble/src/utils/cli_player.py#L187-L189) 已加 `_strategy_singleton`，但未验证是否真正复用
- **验证**：加日志统计策略实例创建次数，确认每次决策是否真的复用缓存

### 9. 换桌策略优化

- **依据**：目前换桌是随机选，没有考虑桌台历史表现
- **改动**：在 [browser\_platform.py:380-420](file:///Users/ly/Workspace/gitee/gamble/src/platforms/browser/browser_platform.py#L380-L420) `open_table()` 加：
  - 优先选历史盈亏 > 0 的桌
  - 避开黑名单桌（见第4点）
  - 加 `--prefer-table` CLI 参数（手动指定偏好桌）

### 10. 长期追踪：EV计算准确性

- **依据**：strategy.equity 经常是 0.000（可能是状态污染导致）
- **调查**：看 equity 计算逻辑是否依赖完整的手牌信息
- **改动**：加 equity sanity check（如果 equity=0 且 hand\_strength≠垃圾 → 报错）

***

## 实施顺序建议

1. **第1周重点**：先做 1+2（paired board + 河牌谨慎），这两项可直接从历史数据估算收益（约 +300-500 chips/月）
2. **第2周**：做 3+4（翻前raise + 负EV桌离开），需要新跑 30局验证效果
3. **第3周**：做 5+6（根因分析），这两个是基础设施，不修会影响后续所有优化
4. **第4周**：做 7（数据增强），解锁更深度的分析能力（对手行为模式、牌桌动态）

***

需要我把这些整理成 GitHub Issues 或者看板吗？
