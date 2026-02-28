# 浏览器 HUD (Heads-Up Display) 实施计划

## 状态: ✅ 已完成

## 目标
在 ReplayPoker 游戏页面上直接显示 AI 的分析结果、胜率和决策建议。

## 实现概述

### 1. HUD 设计
- **位置**: 页面右上角,悬浮显示
- **样式**: 半透明黑色背景,绿色/黄色高亮文字
- **功能**: 
  - 可拖拽移动
  - 可关闭 (X 按钮)
  - 自动更新内容

### 2. 显示内容
- **标题**: "AI 顾问 ✥"
- **手牌分析**: 当前牌型和强度 (如 "对 K")
- **决策建议**: **加注/跟注** / 过牌/弃牌 (高亮显示)
- **胜率**: 对 N 位对手的胜率百分比
- **对手分析**: 关键对手的范围评估

### 3. 代码实现

#### A. 模块化设计
**文件**: `src/hud.py`

**类**: `HUD`
- `inject(page)`: 注入 HUD 到页面
- `update_content(page, suggestion)`: 更新 HUD 内容

#### B. 注入逻辑
在 `poker_client.py` 中:
- 检测到牌桌页面时自动注入
- 使用 `page.evaluate()` 执行 JavaScript
- 添加拖拽和关闭功能

```python
# 在 poker_client.py 中
self.hud = HUD()
await self.hud.inject(self.page)
```

#### C. 更新逻辑
每次收到游戏状态更新时:
```python
suggestion = self.engine.decide(self.state)
await self.hud.update_content(self.page, suggestion)
```

### 4. 内容格式化

HUD 会自动高亮关键信息:
- **行动建议** (加注/跟注等): 黄色,加粗,1.2倍字体
- **胜率**: 青色,加粗
- **换行**: 自动转换 `\n` 为 `<br/>`

### 5. 中文化

所有显示内容均为中文:
- 标题: "AI 顾问 ✥"
- 初始状态: "等待游戏状态..."
- 牌型: "对 K", "两对", "同花"等
- 行动: "加注/全下", "跟注/加注", "过牌/弃牌"
- 对手分析: "紧凶", "宽松/投机"等

## 验证

### 手动测试
1. 启动程序: `python -m src.poker_client`
2. 进入牌桌
3. 确认 HUD 显示在右上角
4. 确认内容随游戏进程实时更新
5. 测试拖拽功能
6. 测试关闭按钮

### 预期效果
```
┌─────────────────────────────┐
│ AI 顾问 ✥              × │
├─────────────────────────────┤
│ 翻牌后: 对 K - 跟注/加注    │
│ 胜率 (对 3 位对手): 72.5%  │
│ 【对手分析】                │
│   - 座位 2 (call): 宽松/投机│
│   - 座位 4 (raise): 紧凶    │
└─────────────────────────────┘
```

## 技术细节

### JavaScript 注入
- 使用 `document.createElement` 创建 HUD 元素
- 设置 `z-index: 2147483647` 确保在最上层
- 添加事件监听器实现拖拽
- 使用 `pointer-events: auto` 确保可交互

### 样式
```css
position: fixed;
top: 10px;
right: 10px;
background: rgba(0,0,0,0.85);
color: #0f0;
padding: 15px;
border-radius: 8px;
font-family: monospace;
```

## 已解决的问题

### 1. JavaScript 语法错误
**问题**: 重复的事件监听器代码导致 `SyntaxError: missing ) after argument list`

**解决**: 
- 将 HUD 逻辑提取到独立的 `src/hud.py` 模块
- 移除重复代码
- 添加防御性检查 (`if (document.getElementById('ai-hud')) return;`)

### 2. 内容更新失败
**问题**: 特殊字符导致 JavaScript 注入失败

**解决**:
- 转义反引号和 `${` 字符
- 使用模板字符串安全注入

## 相关文件

- [src/hud.py](file:///Users/ly/Workspace/gitee/gamble/src/hud.py) - HUD 实现
- [src/poker_client.py](file:///Users/ly/Workspace/gitee/gamble/src/poker_client.py) - HUD 集成
- [src/decision_engine.py](file:///Users/ly/Workspace/gitee/gamble/src/decision_engine.py) - 内容生成
