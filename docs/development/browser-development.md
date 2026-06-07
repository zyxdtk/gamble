# 浏览器平台开发指南

## 架构层次

```
BrowserInterface (门面，统一入口)
    │
    ├── BrowserPlatform (GamePlatform 实现)
    │     ├── ReplayPokerAdapter (DOM 交互)
    │     └── TableSelectionStrategy (桌子选择)
    │
    └── StateManager (双通道状态管理)
          ├── WebSocketListener (WebSocket 实时数据)
          └── ReplayPokerAdapter (DOM 补充检测)
```

## BrowserInterface 使用规范

**必须**通过统一接口访问浏览器功能：

```python
# ✓ 正确
from src.platforms.browser import BrowserInterface

# ✗ 错误：直接导入内部组件
from src.platforms.browser.state_manager import StateManager
from src.platforms.browser.websocket_listener import WebSocketListener
```

## ReplayPoker 选择器

| 数据 | 选择器 | 备注 |
|------|--------|------|
| 底池 | `.Stack__value span` | |
| 公共牌 | `.Cards .Card--withValue` | 备选：聊天消息 |
| 我的座位 | `.Seat--currentUser` | |
| 座位号 | `Position--(\d+)` | 正则匹配 |
| 动作按钮 | `.BettingControls__actions button` | |
| Sit In | `.SitIn__button` | |
| Sit Out 复选框 | `.Footer__settings--sittingOut .CheckBox.CheckBox--checked` | |
| 买入金额输入 | 金额输入框 + OK 按钮 | |

## 可见性检测

5 层检测避免误判隐藏按钮：

1. `is_visible()` — Playwright 原生
2. 视口边界 — `getBoundingClientRect()` 是否在可见区域
3. 父元素隐藏 — `.AwaitTurn` 容器检测
4. `disabled` 属性
5. `opacity` — 低于 0.5 视为不可见

## Sit Out 处理

ReplayPoker 有两种"离开"状态：

| 状态 | 表现 | 处理 |
|------|------|------|
| Stand | 完全站起 | 点击 "Sit In" 按钮 |
| Sit Out | 勾选了 "Sit Out Next Hand" | 取消勾选复选框 |

`sit_in()` 方法按优先级尝试三种检测方式。

## 扩展新网站

1. 继承 `WebsiteAdapter` 基类
2. 实现所有抽象方法
3. 在 `BrowserPlatform` 中注册

```python
class MySiteAdapter(WebsiteAdapter):
    def get_name(self) -> str:
        return "MyPokerSite"

    def get_available_tables(self, page, filter) -> List[TableInfo]:
        # 实现桌子发现逻辑
        ...

    def get_game_state(self, page) -> GameState:
        # 实现状态提取逻辑
        ...
```

## 调试技巧

### 截图

```python
# CLI 模式下
test-cli> screenshot debug1
test-cli> snap              # 快速截图

# 自动截图
test-cli> autosnap on
```

### DOM 探索

```bash
# 采集当前页面 DOM 快照
python tests/explore/explore_table.py
```

输出三件套：
- `snap_<ts>/lobby.png` — 截图
- `snap_<ts>/lobby.html` — 完整 HTML
- `snap_<ts>/info.json` — 解析后的状态 + 动作

### 网络请求

在 BrowserPlatform 中可以监听 WebSocket 消息来调试状态同步问题。
