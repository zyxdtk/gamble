# 对手手牌范围分析计划

## 目标
根据对手的行动估算其手牌范围，提供更好的决策支持。

## 1. 数据结构 (`src/game_state.py`)
- **修改 `Player` 类**：
    - 添加 `status`：`active`, `folded`, `all_in`, `sit_out`（活跃、弃牌、全下、离座）。
    - 添加 `last_action`：`check`, `call`, `bet`, `raise`（过牌、跟注、下注、加注）。
    - 添加 `street_actions`：当前街（Street）的行动列表。
    - 添加 `perceived_range`：字符串描述（例如："Top 20%", "Wide", "Capped"）。

## 2. 动作追踪 (`src/poker_client.py`)
- **在 `handle_game_update` 中**：
    - 当 `action` 为 `bet`, `call`, `raise`, `check`, `fold` 时：
        - 更新 `self.state.players` 中对应的 `Player` 对象。
        - 设置 `last_action` 并更新 `perceived_range`。

## 3. 范围逻辑 (`src/decision_engine.py`)
- **新方法**：`analyze_opponent_ranges(state: GameState)`
    - 遍历活跃对手。
    - 应用简单启发式规则：
        - **加注 (Raise, Pre-flop)**: "Tight (Top 15%) - 88+, ATs+, KJs+"（紧，前15%强牌）
        - **跟注 (Call, Pre-flop)**: "Wide/Speculative - Pairs, Suited Connectors, Broadways"（宽/投机，对子、同花连张）
        - **过牌 (Check, Post-flop)**: "Weak/Capped - Middle Pair or worse"（弱/有上限，中对或更差）
        - **下注/加注 (Bet/Raise, Post-flop)**: "Strong - Top Pair+, Strong Draw"（强，顶对+或强听牌）
- `decide()` 方法应将此分析附加到输出中。

## 4. 可视化
- `[ADVISOR]` 输出现在将包含：
    ```
    [ADVISOR] Opponent Analysis:
      - Seat 3 (Raise): Tight (Top 15%)
      - Seat 5 (Call): Speculative
    ```

## 验证
- 在 `assist mode` 中验证范围是否随着玩家行动更新。
