# src/platforms/browser 架构重构总结

## 🎯 重构目标

将原本命名为 "CLI 专用" 的组件重构为 `src/platforms/browser` 的标准组件，使其能够被：
1. **CLI 测试工具**调用（当前用途）
2. **src/core 核心逻辑**直接对接（未来用途）

## 📦 重构内容

### 文件重命名

| 原文件名 | 新文件名 | 说明 |
|---------|---------|------|
| `cli_ws_listener.py` | `websocket_listener.py` | WebSocket 监听器 |
| `dual_channel_manager.py` | `state_manager.py` | 双通道状态管理器 |

### 类名重命名

| 原类名 | 新类名 | 说明 |
|-------|-------|------|
| `CLIWebSocketListener` | `WebSocketListener` | 移除 CLI 前缀 |
| `DualChannelStateManager` | `StateManager` | 简化命名 |

### 导入路径更新

```python
# 重构前（错误）
from src.platforms.browser.cli_ws_listener import CLIWebSocketListener
from src.platforms.browser.dual_channel_manager import DualChannelStateManager

# 重构后（正确）
from src.platforms.browser.websocket_listener import WebSocketListener
from src.platforms.browser.state_manager import StateManager
```

## 🏗️ 正确的架构层次

```
┌─────────────────────────────────────┐
│         上层应用层                   │
│                                     │
│  ┌──────────────────────┐  ┌──────────────┐  │
│  │ tests/integration/   │  │  src/core    │  │
│  │ browser/test_cli.py  │  │  (生产)      │  │
│  │ (集成测试)           │  │              │  │
│  └──────────┬───────────┘  └──────┬───────┘  │
│             │                     │           │
│             └────────┬────────────┘           │
│                      ▼                        │
├─────────────────────────────────────┤
│     src/platforms/browser           │
│     (浏览器平台适配器层)             │
│                                     │
│  ┌──────────────────────────────┐  │
│  │   StateManager               │  │
│  │   (双通道状态管理器)          │  │
│  │                              │  │
│  │  ┌──────────┐  ┌──────────┐ │  │
│  │  │WebSocket │  │   DOM    │ │  │
│  │  │Listener  │  │ Adapter  │ │  │
│  │  └──────────┘  └──────────┘ │  │
│  └──────────────────────────────┘  │
└─────────────────────────────────────┘
```

**关键原则**：
- ✅ `src/platforms/browser` 是独立的平台适配层
- ✅ 不依赖上层调用方（无论是 CLI 还是 src/core）
- ✅ 提供标准化的接口供上层调用

## 📝 使用示例

### 1. CLI 集成测试使用

```python
# tests/integration/browser/test_cli.py
from src.platforms.browser import BrowserInterface

class TestCLI:
    async def connect_to_table(self, table_url: str):
        # 初始化浏览器接口（来自 src/platforms/browser）
        self.browser = BrowserInterface(self.page)
        await self.browser.initialize()
        
        print("✅ Browser interface initialized")
        
    async def cmd_state(self):
        # 通过统一接口获取状态
        state = await self.browser.get_game_state()
        print(f"Pot: {state['pot']}")
        print(f"My Seat: {state['my_seat_id']}")
```

### 2. src/core 生产代码使用（未来）

```python
# src/core/game_engine.py
from src.platforms.browser.state_manager import StateManager

class GameEngine:
    def __init__(self, page):
        # 直接使用相同的组件
        self.state_mgr = StateManager(page)
    
    async def start(self):
        await self.state_mgr.initialize()
        
        while True:
            state = await self.state_mgr.update_state()
            if state['is_my_turn']:
                action = self.make_decision(state)
                await self.execute_action(action)
```

## ✅ 重构优势

### 1. **清晰的职责分离**

- `src/platforms/browser`：负责与浏览器交互，提取游戏状态
- `CLI`：仅用于测试验证
- `src/core`：核心业务逻辑

### 2. **代码复用**

CLI 测试通过的代码可以直接用于 src/core，避免重复开发。

### 3. **易于维护**

所有浏览器相关的逻辑集中在 `src/platforms/browser`，修改一处即可影响所有调用方。

### 4. **符合设计原则**

- **单一职责**：每个模块只做一件事
- **开闭原则**：对扩展开放，对修改封闭
- **依赖倒置**：上层依赖下层抽象，而非具体实现

## 🔍 对比旧架构（src/bot）

| 特性 | src/bot (废弃) | src/platforms/browser (新) |
|------|---------------|---------------------------|
| **定位** | 紧耦合的单体 | 独立的平台适配层 |
| **可复用性** | ❌ 难以复用 | ✅ 可被多方调用 |
| **测试性** | ❌ 难以单独测试 | ✅ CLI 专门用于测试 |
| **扩展性** | ❌ 修改影响全局 | ✅ 新增调用方无需修改底层 |

## 📋 下一步工作

### 1. 在 CLI 中集成 StateManager

修改 `test_cli.py`，使用新的 `StateManager` 替代原有的 DOM -only 方案。

### 2. 验证双通道功能

- 测试 WebSocket 连接和消息处理
- 测试 DOM 按钮检测
- 验证智能合并逻辑
- 检查交叉校验告警

### 3. 为 src/core 准备接口

确保 `StateManager` 的接口足够清晰和稳定，方便未来 src/core 直接调用。

## 💡 设计反思

### 为什么不用 src/bot？

1. **历史包袱**：src/bot 包含大量过时的逻辑
2. **紧耦合**：TableManager、PlayManager、LifecycleManager 互相依赖
3. **难以测试**：没有专门的测试入口
4. **不符合分层**：混合了平台适配和业务逻辑

### 为什么选择现在的架构？

1. **清晰的分层**：platforms/browser 只负责浏览器交互
2. **独立可测**：CLI 作为专门的测试工具
3. **易于扩展**：新增调用方无需修改底层
4. **面向未来**：为 src/core 预留了干净的接口

## 🎓 经验教训

1. **命名很重要**：避免在底层组件名称中包含上层概念（如 "CLI"）
2. **职责要清晰**：platforms 层不应该知道谁在调用它
3. **测试先行**：先通过 CLI 验证功能，再集成到核心逻辑
4. **文档同步**：重构时及时更新文档中的引用和示例

---

**相关文件**：
- [websocket_listener.py](file:///Users/ly/Workspace/gitee/gamble/src/platforms/browser/websocket_listener.py)
- [state_manager.py](file:///Users/ly/Workspace/gitee/gamble/src/platforms/browser/state_manager.py)
- [docs/cli_dual_channel_architecture.md](file:///Users/ly/Workspace/gitee/gamble/docs/cli_dual_channel_architecture.md)
