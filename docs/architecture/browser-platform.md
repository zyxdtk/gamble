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
