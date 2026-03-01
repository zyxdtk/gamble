# Bot 模块设计文档

本文档覆盖 `src/bot/` 目录下各组件的设计决策与实现规划。

---

## 1. 自动模式 (Auto Mode)

> 对应实现：`browser_manager.py` / `table_manager.py`

### 目标
让 AI 不仅能给出建议，还能直接操作浏览器进行游戏（弃牌、跟注、加注）。

### 按钮识别策略
由于截图时可能不是轮到我方行动，需要在运行时动态查找按钮。

- **目标元素**：包含 "Fold", "Call", "Check", "Raise", "Bet", "All In" 文本的按钮。
- **定位方法**：
    - 使用 Playwright 的 `page.get_by_text(..., exact=True)` 或 `page.locator("button", has_text=...)`。
    - 结合 CSS 类名（如 `.Button`, `.ActionControls` 等，需实地观察）。
    - **安全机制**：点击前再次确认是否轮到自己行动 (`is_acting` 状态)。

### 自动操作逻辑
- **方法**：`execute_decision(decision: str)`
    - 解析 `decision` 字符串（例如 "RAISE/CALL"）。
    - 优先尝试执行主要建议（如 "RAISE"）。
    - 如果找不到主要按钮（如资金不足无法 Raise），则回退到次要建议（如 "CALL"）。
    - 如果所有建议都无法执行，则默认 "CHECK" 或 "FOLD"。

### 风险控制
- **确认对话框**：某些高额操作可能弹出确认框，需要处理。
- **随机延迟**：操作前增加 0.5s - 2s 随机延迟，模拟人类行为，防封号。

### 验证
- 在 Play Money 桌上测试。
- 观察日志确认动作是否被正确执行。

---

## 2. 牌桌筛选与进桌逻辑 (Table Selection)

> 对应实现：`lobby_manager.py`

### 背景
在百万筹码的征途上，**"决定打什么局"比"怎么打"更为重要**。

ReplayPoker 系统会自动记忆用户的 UI 选择（盲注级别、游戏类型等）。Bot 进入大厅后**不再执行任何主动的 UI 筛选点击**，而是：

1. 直接等待页面加载（挂起 3 秒，等待 WebSocket 数据渲染）。
2. 所有列表排序及满员过滤均依赖账号最后一次人工设定的偏好。

### 挑桌逻辑

1. **安全阈值检查**：
   - 读取 `config/settings.yaml` 中的 `max_small_blind`（如 10）。
   - 若排第一的桌子盲注超出阈值，直接停机并呼叫人工介入。

2. **入桌方案**（三选一）：

   | 方案 | 方式 | 推荐度 |
   |------|------|--------|
   | 方案 A | 从列表行解析 table ID，拼接 URL 后直接 `page.goto(url)` | 备用 |
   | 方案 B | 点击列表行内的 **"Open Now"** 按钮 | ✅ **推荐** |
   | 方案 C | 点击 **"Open Table"** 按钮，进入后还需繁琐的坐下操作 | ❌ 暂不实现 |

   > 当前实现采用**方案 B**：直接点击 `Open Now`，跳转后页面自动进入牌桌 URL。

3. **满员判断**：
   - 检测页面中是否出现 **"Join Waiting List"** 按钮。
   - 若出现，则说明牌桌已满员，调用 `leave_table` 退回大厅进行下一轮重试。

---

## 3. 入座与 Buy-in 逻辑 (Sit Down & Buy-in)

> 对应实现：`table_manager.py`

进入牌桌 URL 后，Bot 需要先判断自己是否已经入座，再决定后续操作。

### 3.1 判断自己是否已入座

- 遍历页面上所有玩家名称元素，检查是否有与配置文件中 `player.username` 完全匹配的名字。
- 若匹配到，则认为**已入座**，等待发牌（可能会被跳过若干轮）。
- 若未匹配到，则进入入座流程。

> **配置项**：在 `config/settings.yaml` 中新增：
> ```yaml
> player:
>   username: "你的账号名"
> ```

### 3.2 入座流程

1. **寻找空座**：
   - 优先点击页面上的 **"Seat Me Anywhere"** 按钮（系统自动分配）。
   - 若无该按钮，则扫描页面中的空座位元素并点击其中一个。

2. **Buy-in 弹窗**：
   - 弹出 Buy-in 对话框后，在筹码输入框中填入配置的 buy-in 金额。
   - 点击 **"OK"** / **"Confirm"** 完成入座。

3. **入座确认**：
   - 等待 2-3 秒后，再次运行"判断自己是否已入座"逻辑。
   - 若仍未入座（如弹窗未出现或点击失败），记录日志并重试一次。

> **配置项**：`config/settings.yaml`：
> ```yaml
> game:
>   buyin_amount: 1000   # 默认买入筹码数
> ```

---

## 4. 游戏状态与玩家状态维护 (State Management)

> 对应实现：`table_manager.py`

`TableManager` 是单个牌桌页面的控制中心，负责在整个局的生命周期内维护完整的游戏快照。

### 4.1 游戏状态 (GameState)

每个 Tick（`execute_turn` 调用）都应从页面刷新以下字段：

| 字段 | 说明 | 来源 |
|------|------|------|
| `stage` | 当前街：`preflop` / `flop` / `turn` / `river` / `showdown` | DOM / WebSocket |
| `pot` | 当前底池大小 | DOM |
| `community_cards` | 公共牌列表（0-5 张） | WebSocket |
| `to_call` | 跟注所需金额（0 = 可过牌） | DOM |
| `min_raise` | 最小加注额 | DOM |
| `is_acting` | 当前是否轮到自己行动 | DOM（按钮高亮状态） |
| `hole_cards` | 自己的底牌（2 张） | WebSocket |

### 4.2 玩家状态 (PlayerState)

每个座位维护一个 `Player` 对象，字段如下：

| 字段 | 说明 |
|------|------|
| `seat_id` | 座位编号 |
| `username` | 玩家名称 |
| `stack` | 当前筹码量 |
| `status` | `active` / `folded` / `all_in` / `sit_out` |
| `last_action` | 本街最后一次行动：`check` / `call` / `bet` / `raise` / `fold` |
| `is_dealer` | 是否为庄家 |
| `is_self` | 是否为 Bot 自身（通过 `username` 比对配置文件判断） |

### 4.3 状态刷新时机

```
每次 execute_turn() 调用
    ├── 刷新 GameState（读 DOM + WebSocket 缓存）
    ├── 刷新所有 PlayerState（遍历座位元素）
    ├── 检查 is_acting
    │       ├── True  → 调用 Strategy.make_decision(state)
    │       │             └── 执行行动（auto mode）/ 输出建议（assist mode）
    │       └── False → 仅记录日志，等待下一 Tick
    └── 检查桌面生命周期
            ├── 自己被淘汰（stack == 0） → 触发 re-buyin 或 leave_table
            └── 局结束（showdown 后牌收走） → 重置本局状态
```

### 4.4 状态重置

每一局结束（检测到新一轮发牌开始）时，需重置：
- `hole_cards` 清空
- `community_cards` 清空
- `stage` → `preflop`
- 所有玩家的 `last_action` 清空、`status` 重置为 `active`
