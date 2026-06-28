# 浏览器平台架构

## 双通道状态管理

Browser Platform 使用 WebSocket + DOM 双通道获取游戏状态：

```
┌─────────────────────────────────────────────┐
│              StateManager                    │
│         (智能合并双通道数据)                    │
├──────────────────┬──────────────────────────┤
│  WebSocket 通道   │       DOM 通道            │
│ (实时结构化数据)   │  (补充检测)               │
│                  │                          │
│  - 底牌/公共牌    │  - 可用动作按钮            │
│  - 玩家身份      │  - 下注金额提取             │
│  - 底池大小      │  - 按钮禁用状态             │
│  - 当前阶段      │  - 不透明度检测             │
└──────────────────┴──────────────────────────┘
```

### 合并策略

| 数据类型 | 主通道 | 备通道 | 说明 |
|----------|--------|--------|------|
| 底牌/公共牌 | WebSocket | DOM | WS 优先，DOM 兜底 |
| 玩家身份/座位 | WebSocket | DOM | WS 优先 |
| 底池 | WebSocket | DOM | 交叉验证，不匹配时告警 |
| 可用动作 | DOM | - | 仅 DOM |
| 下注金额 | DOM | - | 仅 DOM |
| 按钮禁用 | DOM | - | 仅 DOM |

### WebSocketListener

监听 ReplayPoker 的 WebSocket 消息，解析结构化游戏状态。

### ReplayPokerAdapter

通过 DOM 选择器与 ReplayPoker 交互：

| 操作 | 选择器 |
|------|--------|
| 底池 | `.Stack__value span` |
| 公共牌 | `.Cards .Card--withValue` |
| 我的座位 | `.Seat--currentUser` |
| 座位号 | `Position--(\d+)` |
| 动作按钮 | `.BettingControls__actions button` |
| Sit In 按钮 | `.SitIn__button` |
| 买入弹窗 | 金额输入 + OK 按钮 |

## 可见性检测

5 层可见性检测确保不误判隐藏按钮：

1. `is_visible()` — Playwright 原生
2. 视口边界检查 — 元素是否在可见区域
3. 父元素隐藏检测 — `.AwaitTurn` 等容器
4. `disabled` 属性检测
5. `opacity` 阈值检测 — 低于 0.5 视为不可见

## Raise 按钮置灰检测

执行 raise/bet 动作时，填入金额后额外检查 Raise 按钮的 `disabled` 属性和 `opacity`：

- 若 `disabled` 存在或 `opacity < 0.5` → 打 `[Raise 按钮置灰]` WARNING 并 `return False`（不再静默成功）
- 触发场景：raise 金额超出自身筹码、低于最小加注、面对超额 all-in 时仍尝试 raise

## 卡住检测与自动换桌

`BrowserAutoPlayer._game_loop` 中实现的健壮性机制：

### 卡住检测

每轮检查 `state.my_seat_id is None` 且 `actions` 为空 → `_stuck_counter++`。常见触发场景：桌子满员无空座、`_check_and_sit_in` 返回 False。

- 每 10 轮打 `[等待入座]` 日志
- 达到 `stuck_threshold`（默认 30 轮）→ 触发换桌

### 换桌流程 (`_switch_table`)

1. `leave_table` 离开旧桌（关闭页面）
2. `remove_strategy` 清理旧策略实例
3. 重置桌位级状态（初始筹码、手数追踪、街道日志）
4. `open_table` 打开新桌（`select_best_table` 自动过滤已访问的）
5. `create_strategy` + 重建 `PilotDecider`

### 防无限换桌

- 连续换桌 `max_table_switches` 次（默认 5）仍无法入座 → 等 60s 重试
- 换桌失败（无可用桌子）→ 等 30s 重试
- 成功入座后重置 `_consecutive_switches` 计数器

### 配置 (`config/settings.yaml`)

```yaml
auto_mode:
  stuck_threshold: 30        # 连续N轮无法入座触发换桌
  max_table_switches: 5      # 最大连续换桌次数
```

## 筹码冲突诊断

`_choice_to_game_action` 在决策后检测两种冲突情形并打 WARNING：

- **情形 A**: `to_call >= my_chips` 但策略返回 RAISE（面对超额 all-in 不该 raise，规则上只能 call/fold）
- **情形 B**: `amount > my_chips`（raise 金额本身超出自身筹码）

这两种情形下 ReplayPoker 会把 Raise 按钮置灰，动作无法执行。日志示例：

```
WARNING [筹码冲突#3] 面对超额 all-in: to_call=5000 >= my_chips=2000, 但策略返回 RAISE amount=15000 ...
WARNING [Raise 按钮置灰] amount=15000, disabled=True, opacity=0.30 ...
```

## BrowserInterface 统一接口

`src/platforms/browser/__init__.py` 提供 `BrowserInterface` 门面：

```python
# 正确：通过统一接口
from src.platforms.browser import BrowserInterface

# 错误：直接导入内部组件
from src.platforms.browser.state_manager import StateManager  # 禁止
```

所有上层代码（CLI、src/core）必须通过 `BrowserInterface` 访问浏览器功能，不直接依赖内部组件。

## 扩展新网站

继承 `WebsiteAdapter` 基类：

```python
class NewSiteAdapter(WebsiteAdapter):
    def get_name(self) -> str: ...
    def get_table_filter(self) -> TableFilter: ...
    def get_available_tables(self, page, filter) -> List[TableInfo]: ...
    # ... 实现其他抽象方法
```
