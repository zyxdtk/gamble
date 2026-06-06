# src/platforms/browser 双通道状态管理架构

## 🎯 设计理念

在 `src/platforms/browser` 中构建 **WebSocket + DOM** 双通道机制，相互校验提高可靠性：

```
┌─────────────────────────────────────────┐
│     StateManager (双通道状态管理器)      │
│                                         │
│  ┌──────────────┐   ┌───────────────┐  │
│  │  WebSocket   │   │     DOM       │  │
│  │   Listener   │   │   Adapter     │  │
│  │              │   │               │  │
│  │ • 实时推送   │   │ • 按钮检测    │  │
│  │ • 结构化数据 │   │ • 金额提取    │  │
│  │ • 身份识别   │   │ • 底池校验    │  │
│  └──────┬───────┘   └───────┬───────┘  │
│         │                   │           │
│         └───────┬───────────┘           │
│                 ▼                       │
│        Smart Merge Engine               │
│        (智能合并引擎)                    │
│                                         │
│  • WS 优先: community_cards,            │
│             hole_cards, my_seat_id      │
│  • DOM 补充: available_actions,         │
│              to_call, min_raise         │
│  • 交叉校验: pot 值对比                  │
└─────────────────────────────────────────┘

上层调用方：
- CLI 测试工具（当前）
- src/core 核心逻辑（未来）
```

## 📦 核心组件

### 1. WebSocketListener (`websocket_listener.py`)

轻量级 WebSocket 监听器，作为 `src/platforms/browser` 的标准组件：

```python
from src.platforms.browser.websocket_listener import WebSocketListener

# 创建监听器
ws = WebSocketListener(page)

# 启动监听
await ws.start_listening()

# 获取状态
state = ws.get_state()
# {
#   "pot": 29,
#   "community_cards": ["4c", "8s", "2d"],
#   "hole_cards": ["Ah", "Ks"],
#   "my_seat_id": 4,
#   "is_my_turn": True,
#   ...
# }

# 检查健康状态
if ws.is_healthy():
    print("WebSocket is active")
```

**关键特性**：
- ✅ **自动身份识别**：通过非 'X' 底牌自动识别自己的座位
- ✅ **全量哈希去重**：避免 ReplayPoker 多包共用 ID 的问题
- ✅ **优先级排序**：确保 startHand 先于 dealHoleCards 处理
- ✅ **健康检查**：45秒无消息视为不健康

### 2. StateManager (`state_manager.py`)

双通道状态管理器，智能合并 WS 和 DOM 数据：

```python
from src.platforms.browser.state_manager import StateManager

# 创建管理器
manager = StateManager(page)

# 初始化（启动 WS 监听）
await manager.initialize()

# 更新并获取合并状态
state = await manager.update_state()
print(f"Pot: {state['pot']}")
print(f"My Seat: {state['my_seat_id']}")
print(f"Available Actions: {state['available_actions']}")

# 检查通道状态
status = manager.get_channel_status()
print(f"WS: {'✅' if status['websocket'] else '❌'}")
print(f"DOM: {'✅' if status['dom'] else '❌'}")

# 关闭
await manager.shutdown()
```

**合并策略**：

| 字段 | 优先级 | 说明 |
|------|--------|------|
| `community_cards` | WebSocket | WS 提供完整列表 |
| `hole_cards` | WebSocket | WS 直接来自服务器 |
| `my_seat_id` | WebSocket | WS 通过底牌自动识别 |
| `is_my_turn` | WebSocket | WS 从 tick 消息获取 |
| `pot` | WebSocket | WS 为主，DOM 校验 |
| `available_actions` | DOM | DOM 从按钮检测更准确 |
| `to_call` | DOM | DOM 从 Call 按钮文本提取 |
| `min_raise` | DOM | DOM 从 Bet/Raise 按钮提取 |

**校验机制**：
```python
# 如果 WS 和 DOM 的 pot 差异超过 10%，记录警告
if abs(pot_ws - pot_dom) > max(pot_ws, pot_dom) * 0.1:
    bot_logger.warning(f"⚠️ Pot mismatch: WS={pot_ws}, DOM={pot_dom}")

# 如果 WS 没有判断出 is_my_turn，但有可用按钮，则推断为 True
if not merged["is_my_turn"] and merged["available_actions"]:
    merged["is_my_turn"] = True
```

## 🔧 在 test_cli.py 中集成（测试用途）

> **注意**：CLI 只是测试工具，用于验证 `src/platforms/browser` 的功能。
> 未来的生产代码会通过 `src/core` 直接调用 `StateManager`。

### 步骤 1: 初始化双通道管理器

```python
class TestCLI(Cmd):
    def __init__(self):
        super().__init__()
        self.state_manager = None  # 新增
    
    async def connect_to_table(self, table_url: str):
        """连接到牌桌并初始化双通道"""
        # ... 现有代码 ...
        
        # 初始化双通道状态管理器（来自 src/platforms/browser）
        from src.platforms.browser.state_manager import StateManager
        self.state_manager = StateManager(self.page)
        await self.state_manager.initialize()
        
        print("✅ State manager initialized")
```

### 步骤 2: 修改 state 命令

```python
async def cmd_game_state(self):
    """Show game state using dual-channel."""
    if not self.state_manager:
        print("❌ State manager not initialized. Connect to a table first.")
        return
    
    # 更新并获取合并状态
    state = await self.state_manager.update_state()
    
    print(f"\n--- Game State (Dual-Channel) ---")
    print(f"  Channels: WS={'✅' if self.state_manager.is_healthy() else '❌'}, DOM=✅")
    print(f"  Pot: {state['pot']}")
    print(f"  Community Cards: {state['community_cards']}")
    print(f"  Hole Cards: {state['hole_cards'] or 'Unknown'}")
    print(f"  My Seat: {state['my_seat_id']}")
    print(f"  To Call: {state['to_call']}")
    print(f"  Min Raise: {state['min_raise']}")
    print(f"  My Turn: {state['is_my_turn']}")
    
    if state['available_actions']:
        print(f"  Available Actions: {', '.join(state['available_actions'])}")
    else:
        print(f"  Available Actions: (none)")
    
    if state.get('current_stage'):
        print(f"  Stage: {state['current_stage'].upper()}")
    
    print()
```

### 步骤 3: 添加通道状态诊断命令

```python
async def cmd_channels(self):
    """Show channel health status."""
    if not self.state_manager:
        print("❌ State manager not initialized.")
        return
    
    status = self.state_manager.get_channel_status()
    ws_state = self.state_manager.ws_listener.get_state()
    
    print(f"\n--- Channel Status ---")
    print(f"  WebSocket: {'✅ Healthy' if status['websocket'] else '❌ Unhealthy'}")
    print(f"  DOM: {'✅ Available' if status['dom'] else '❌ Error'}")
    print(f"\n--- WebSocket Data ---")
    print(f"  My Seat ID: {ws_state.get('my_seat_id')}")
    print(f"  My User ID: {ws_state.get('my_user_id')}")
    print(f"  Hand ID: {ws_state.get('hand_id')}")
    print(f"  Big Blind: {ws_state.get('big_blind')}")
    print(f"  Players: {len(ws_state.get('players', {}))}")
    print()
```

## 🎨 优势对比

### 单通道（仅 DOM）vs 双通道

| 特性 | 仅 DOM | 双通道 |
|------|--------|--------|
| **准确性** | ⚠️ 依赖选择器，易出错 | ✅ WS 提供结构化数据 |
| **实时性** | ❌ 需要轮询 | ✅ WS 实时推送 |
| **身份识别** | ❌ 需要查找 `.Seat--me` | ✅ WS 通过底牌自动识别 |
| **公共牌** | ❌ 需要从聊天解析 | ✅ WS 直接提供 |
| **按钮检测** | ✅ DOM 擅长 | ✅ DOM 补充 |
| **容错性** | ❌ 单一故障点 | ✅ 双通道互为备份 |
| **校验能力** | ❌ 无法自我验证 | ✅ WS/DOM 交叉校验 |

## 📊 实际效果示例

### 场景 1: 正常游戏

```
test-cli> state

--- Game State (Dual-Channel) ---
  Channels: WS=✅, DOM=✅
  Pot: 29
  Community Cards: ['4c', '8s', '2d']
  Hole Cards: ['Ah', 'Ks']
  My Seat: 4
  To Call: 0
  Min Raise: 10
  My Turn: True
  Available Actions: fold, check, bet
  Stage: FLOP
```

### 场景 2: WebSocket 断开

```
test-cli> channels

--- Channel Status ---
  WebSocket: ❌ Unhealthy
  DOM: ✅ Available

test-cli> state

--- Game State (Dual-Channel) ---
  Channels: WS=❌, DOM=✅
  Pot: 29  (from DOM)
  Community Cards: []  (WS unavailable)
  My Seat: None  (WS unavailable)
  To Call: 0
  Min Raise: 10
  My Turn: False
  Available Actions: fold, check, bet
```

**注意**：即使 WS 断开，DOM 仍能提供部分信息（按钮、金额等）。

### 场景 3: 数据不一致告警

```
[bot] WARNING - ⚠️ Pot mismatch: WS=29, DOM=35, diff=6
```

这种情况下，系统仍然使用 WS 的值（更可靠），但记录了警告供调试。

## 🚀 未来扩展：src/core 对接

当 CLI 测试完成后，`src/core` 可以直接使用 `StateManager`：

```python
# src/core/game_engine.py
from src.platforms.browser.state_manager import StateManager

class GameEngine:
    def __init__(self, page):
        # 直接使用 src/platforms/browser 的组件
        self.state_mgr = StateManager(page)
    
    async def start(self):
        await self.state_mgr.initialize()
        
        while True:
            # 获取合并后的状态
            state = await self.state_mgr.update_state()
            
            # 基于状态做决策
            if state['is_my_turn']:
                action = self.make_decision(state)
                await self.execute_action(action)
```

这种设计使得：
- ✅ CLI 和 src/core 共用同一套底层实现
- ✅ 测试通过的代码可以直接用于生产
- ✅ 避免了重复开发和代码不一致问题

### 1. 添加更多校验规则

```python
def _validate_state(self, ws_state, dom_state):
    """验证状态一致性"""
    issues = []
    
    # 校验 my_seat_id
    if ws_state.get('my_seat_id') and dom_state.get('my_seat_id'):
        if ws_state['my_seat_id'] != dom_state['my_seat_id']:
            issues.append(f"Seat ID mismatch: WS={ws_state['my_seat_id']}, DOM={dom_state['my_seat_id']}")
    
    # 校验社区牌数量
    ws_count = len(ws_state.get('community_cards', []))
    dom_count = len(dom_state.get('community_cards', []))
    if ws_count != dom_count:
        issues.append(f"Community cards count mismatch: WS={ws_count}, DOM={dom_count}")
    
    return issues
```

### 2. 自动切换主通道

```python
if not self.ws_listener.is_healthy():
    bot_logger.warning("WebSocket unhealthy, switching to DOM-only mode")
    # 临时切换到纯 DOM 模式
```

### 3. 状态历史记录

```python
self.state_history = []  # 记录历史状态

async def update_state(self):
    state = await self._merge_states(...)
    self.state_history.append({
        "timestamp": time.time(),
        "state": state.copy()
    })
    # 保留最近 100 条
    if len(self.state_history) > 100:
        self.state_history = self.state_history[-100:]
```

## 📝 总结

双通道架构的核心价值：

1. **可靠性**：WS 提供准确的服务器数据，DOM 作为补充和校验
2. **容错性**：一个通道失效时，另一个仍能提供部分信息
3. **可观测性**：可以实时监控两个通道的健康状态
4. **可扩展性**：可以轻松添加新的校验规则和融合策略

这种设计借鉴了 `src/bot` 的双通道思想，但完全独立实现，避免了代码耦合。
