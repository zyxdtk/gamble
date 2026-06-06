# Browser 平台统一接口使用指南

## 🎯 设计理念

所有上层调用方（CLI、src/core）都应该通过 **统一的 Browser 接口** 访问浏览器功能，而不是直接调用内部组件。

```
┌─────────────────────────────────────┐
│         上层应用层                   │
│                                     │
│  ┌──────────┐    ┌──────────────┐  │
│  │   CLI    │    │  src/core    │  │
│  │ (测试)   │    │  (生产)      │  │
│  └────┬─────┘    └──────┬───────┘  │
│       │                 │           │
│       └────────┬────────┘           │
│                ▼                     │
├─────────────────────────────────────┤
│  src/platforms/browser/__init__.py  │
│  (统一接口 - BrowserInterface)      │
│                                     │
│  • get_game_state()                 │
│  • get_available_actions()          │
│  • is_healthy()                     │
│  • get_channel_status()             │
│                                     │
│  内部实现细节（对外隐藏）：          │
│  • StateManager                     │
│  • WebSocketListener                │
│  • ReplayPokerAdapter               │
└─────────────────────────────────────┘
```

## 📦 核心优势

### 1. **隐藏实现细节**

上层调用方不需要知道：
- WebSocket 如何监听
- DOM 如何解析
- 状态如何合并

只需要调用简洁的 API。

### 2. **便于替换实现**

未来如果要更换 StateManager 策略或添加新的适配器，上层代码无需修改。

### 3. **统一的入口**

所有浏览器相关功能都通过 `BrowserInterface` 访问，避免散乱的导入。

## 📝 使用示例

### 1. CLI 人工模式

```python
# src/cli/main.py
from src.platforms.browser import BrowserInterface

class TestCLI:
    def __init__(self):
        self.browser = None
    
    async def connect_to_table(self, table_url: str):
        # 创建并初始化浏览器接口
        self.browser = BrowserInterface(self.page)
        await self.browser.initialize()
        
        print("✅ Browser interface initialized")
    
    async def cmd_state(self):
        """显示游戏状态"""
        if not self.browser:
            print("❌ Not connected to a table")
            return
        
        # 通过统一接口获取状态
        state = await self.browser.get_game_state()
        
        print(f"\n--- Game State ---")
        print(f"  Pot: {state['pot']}")
        print(f"  Community Cards: {state['community_cards']}")
        print(f"  My Seat: {state['my_seat_id']}")
        print(f"  My Turn: {state['is_my_turn']}")
        print(f"  Available Actions: {state['available_actions']}")
        print()
    
    async def cmd_channels(self):
        """显示通道状态"""
        if not self.browser:
            print("❌ Not connected")
            return
        
        status = self.browser.get_channel_status()
        print(f"\n--- Channel Status ---")
        print(f"  WebSocket: {'✅' if status['websocket'] else '❌'}")
        print(f"  DOM: {'✅' if status['dom'] else '❌'}")
        print()
```

### 2. src/core 生产代码（未来）

```python
# src/core/game_engine.py
from src.platforms.browser import BrowserInterface

class GameEngine:
    def __init__(self, page):
        # 完全相同的接口
        self.browser = BrowserInterface(page)
    
    async def start(self):
        await self.browser.initialize()
        
        while True:
            # 通过统一接口获取状态
            state = await self.browser.get_game_state()
            
            if state['is_my_turn']:
                action = self.make_decision(state)
                # ... 执行动作
```

### 3. 便捷函数用法

```python
from src.platforms.browser import create_browser_interface

# 一键创建并初始化
browser = await create_browser_interface(page)

# 直接使用
state = await browser.get_game_state()
```

## 🔌 提供的接口

### 状态获取

```python
# 获取完整游戏状态
state = await browser.get_game_state()
# Returns:
# {
#     "pot": 29,
#     "community_cards": ["4c", "8s", "2d"],
#     "hole_cards": ["Ah", "Ks"],
#     "my_seat_id": 4,
#     "is_my_turn": True,
#     "to_call": 0,
#     "min_raise": 10,
#     "available_actions": ["fold", "check", "bet"],
#     ...
# }

# 仅获取可用动作
actions = await browser.get_available_actions()
# Returns:
# {
#     "available": ["fold", "check", "bet"],
#     "to_call": 0,
#     "min_raise": 10,
#     "presets": {...}
# }
```

### 健康检查

```python
# 检查整体健康状态
if browser.is_healthy():
    print("Browser connection is healthy")

# 获取各通道详细状态
status = browser.get_channel_status()
print(f"WS: {status['websocket']}, DOM: {status['dom']}")
```

### 生命周期管理

```python
# 初始化（启动 WebSocket 监听等）
await browser.initialize()

# 关闭（停止监听，释放资源）
await browser.shutdown()
```

## ❌ 错误用法

### 不要直接导入内部组件

```python
# ❌ 错误：直接调用 StateManager
from src.platforms.browser.state_manager import StateManager
manager = StateManager(page)

# ✅ 正确：通过统一接口
from src.platforms.browser import BrowserInterface
browser = BrowserInterface(page)
```

### 不要依赖内部实现细节

```python
# ❌ 错误：访问内部组件
browser._state_manager.ws_listener._processed_hashes

# ✅ 正确：只使用公开接口
state = await browser.get_game_state()
```

## 🏗️ 架构层次

```
src/cli/main.py              # 人工模式（Human Mode）
    ↓ 调用
src/platforms/browser/         # 平台适配层
    ├── __init__.py            # ✅ 统一接口（BrowserInterface）
    ├── state_manager.py       # 内部实现（双通道管理器）
    ├── websocket_listener.py  # 内部实现（WS 监听器）
    └── adapters/              # 内部实现（DOM 适配器）
        └── replay_poker.py
```

**关键原则**：
- ✅ 上层只导入 `src/platforms/browser`（包级别）
- ✅ 不直接导入子模块（如 `state_manager`）
- ✅ 不使用私有属性（以下划线开头的）

## 🔄 未来扩展

### 添加新的平台适配器

如果要支持其他扑克网站，只需：

1. 创建新的适配器：`adapters/pokerstars.py`
2. 在 `BrowserInterface` 中添加平台检测逻辑
3. 上层代码无需修改

```python
class BrowserInterface:
    def __init__(self, page: Page):
        self.page = page
        
        # 自动检测平台
        url = page.url
        if "replaypoker" in url:
            self._adapter = ReplayPokerAdapter()
        elif "pokerstars" in url:
            self._adapter = PokerStarsAdapter()
        # ...
```

### 替换状态管理策略

如果未来要更换 StateManager 的实现：

```python
class BrowserInterface:
    async def initialize(self):
        # 可以轻松替换为新的实现
        self._state_manager = NewStateManager(self.page)
        await self._state_manager.initialize()
```

上层代码完全不受影响！

## 📋 总结

| 特性 | 直接调用内部组件 | 通过统一接口 |
|------|-----------------|------------|
| **耦合度** | ❌ 高耦合 | ✅ 低耦合 |
| **可维护性** | ❌ 难以维护 | ✅ 易于维护 |
| **可扩展性** | ❌ 难以扩展 | ✅ 易于扩展 |
| **测试性** | ❌ 难以测试 | ✅ 易于测试 |
| **符合设计原则** | ❌ 违反封装 | ✅ 良好封装 |

**记住**：始终通过 `src/platforms/browser` 的统一接口访问浏览器功能！
