# 历史修复记录

本文档记录了各版本中的重要 bug 修复和技术改进。

## 可见性检测修复

### 问题描述
CLI 在非自己回合时也显示可用动作。

### 根因
Playwright `get_by_role` 找到了 DOM 中存在但视觉上隐藏的按钮（如 `.AwaitTurn` 容器内的按钮）。

### 修复方案
实现 5 层可见性检测：
1. `is_visible()` — Playwright 原生
2. 视口边界检查 — `getBoundingClientRect()` 是否在可见区域
3. 父元素隐藏检测 — `.AwaitTurn` 等容器
4. `disabled` 属性检测
5. `opacity` 阈值检测 — 低于 0.5 视为不可见

### 相关文件
- `src/platforms/browser/adapters/`

---

## Sit Out 状态修复

### 问题描述
`sit_in` 命令在 Sit Out 状态下失败。

### 根因
ReplayPoker 有两种"离开"状态：Stand（完全站起，有 Sit In 按钮）和 Sit Out（勾选了 "Sit Out Next Hand"，无 Sit In 按钮）。原代码只检测了 Sit In 按钮。

### 修复方案
`sit_in()` 方法按优先级尝试三种检测：
1. 基于 class 的 Sit In 按钮检测
2. 基于文本的 Sit In 按钮检测
3. 取消勾选 "Sit Out Next Hand" 复选框（`.Footer__settings--sittingOut .CheckBox.CheckBox--checked`）

### 相关文件
- `src/platforms/browser/adapters/`

---

## 状态检测修复

### 问题描述
CLI `state` 命令显示的多个字段不正确：公共牌、座位 ID、to_call、min_raise、is_my_turn。

### 根因
1. DOM 提取不完整 — CSS 选择器未适配 ReplayPoker
2. `is_acting` 状态未正确清理
3. 回合检测条件过于严格

### 修复方案
1. PlayManager 双向同步 `is_acting` 状态
2. 完整 DOM 状态提取（底牌从 CSS class、座位从 `.Seat--me`、金额从按钮文本）
3. 放松回合检测条件

### ReplayPoker 选择器映射

| 数据 | 旧选择器 | 正确选择器 |
|------|----------|------------|
| 底池 | `.Pot__value` | `.Stack__value span` |
| 公共牌 | `.CommunityCard` | `.Cards .Card--withValue` |
| 我的座位 | `.Seat--me` | `.Seat--currentUser` |
| 座位号 | `Seat--(\d+)` | `Position--(\d+)` |
| 动作按钮 | `.ActionButtons button` | `.BettingControls__actions button` |

### 相关文件
- `src/platforms/browser/adapters/`
- `src/bot/`

---

## 浏览器平台重构

### 变更内容
- `cli_ws_listener.py` → `websocket_listener.py`
- `dual_channel_manager.py` → `state_manager.py`
- 移除 CLI 特定前缀命名

### 设计原则
- 平台层组件不应包含 CLI 特定命名
- 通过 `BrowserInterface` 门面统一访问
- `src/bot/` 为遗留代码，`src/platforms/browser/` 为新架构
