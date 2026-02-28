# 德州扑克 AI 助手 - 更新日志

## 2026-02-28 更新

### 🏗️ 核心架构重构 (The 1M Project Refactoring)
- **目录重组**: 将所有源码从平铺的 `src/` 分散重构至四个核心子目录：
  - `src/bot/`: 存放浏览器自动化脚本 (`poker_client.py`, `explore_lobby.py`)
  - `src/engine/`: 存放决策相关逻辑 (`decision_engine.py`, `brain.py`)
  - `src/core/`: 存放公共状态和工具类 (`game_state.py`, `utils.py`)
  - `src/ui/`: 存放 HUD 显示相关 (`hud.py`)
- **入口统一**: 修改 `src/main.py` 以天然支持 `--auto` 参数自动跑牌和 `--assist` 辅助模式。

### 🧠 策略引擎升级 (Positional GTO)
- 引入 `config/preflop_ranges.yaml`：基于当前座位（EP, MP, LP, SB）定义不同宽严程度的翻牌前入局范围。
- `GameState` 增加 VPIP (入池率) 和 PFR (翻前加注率) 字段，为后续对手剥削策略铺路。

### 🛡️ 防封禁与资金管理
- 在 `src/core/utils.py` 引入高斯分布的随机延迟函数，模拟真人思考点击节奏。
- 生成明确的百万路程规划 (`1m_chip_strategy.md`) 和 `run_bot.md` 工作流。

### 🔄 Ralph Loop 自动化增强
- **大厅自动化**: 实现 `navigate_to_lobby` 和 `apply_lobby_filters`，支持自动寻找 Texas Hold'em 常规桌。
- **自动入座**: 实现 `sit_and_buyin` 逻辑，自动寻找空位并处理买入弹窗。
- **状态自愈**: 增加 “I'm Back” 按钮检测，防止因超时被踢出。
- **统一 Pulse**: 建立 `run_automation_tick` 机制，整合大厅、坐下、打牌的闭环逻辑。

## 2026-02-08 更新

### ✅ HUD 重构与修复
- 创建独立的 `src/hud.py` 模块
- 修复 JavaScript 注入语法错误 (重复代码)
- 添加拖拽和关闭功能
- 提升 z-index 确保显示在最上层

### ✅ 中文化
- HUD 界面完全中文化
- 决策引擎输出中文化:
  - 翻牌前: 顶级牌/强牌/可玩/弱牌
  - 翻牌后: 四条/葫芦/三条/两对/同花/对X/高牌
  - 行动: 加注/全下, 跟注/加注, 过牌/弃牌
  - 对手分析: 紧凶/强牌/宽松/投机/弱牌

### ✅ 多对手胜率计算
- 改进胜率计算逻辑,针对所有未弃牌对手
- 自动统计活跃对手数量
- 蒙特卡洛模拟为每个对手发随机手牌
- 显示格式: `胜率 (对 N 位对手): XX%`
- 胜率随对手弃牌动态变化

### 📁 项目结构优化
- 测试文件移至 `tests/` 目录
- 文档更新至 `docs/` 目录

## 当前功能

### 核心功能
- ✅ WebSocket 数据捕获
- ✅ 手牌和公共牌识别
- ✅ 底池大小追踪
- ✅ 玩家状态追踪
- ✅ 翻牌前决策 (基于手牌强度)
- ✅ 翻牌后决策 (基于牌型)
- ✅ 多对手胜率计算
- ✅ 对手范围分析
- ✅ 浏览器 HUD 显示
- ✅ 中文界面

### 运行模式
- **辅助模式** (默认): 显示建议,不自动操作
- **自动模式**: 自动点击按钮执行决策

## 待完成功能

### 高优先级
- [ ] 修复 Equity Error (日志中的数字错误码)
- [ ] 识别自己的座位号
- [ ] 底池赔率计算
- [ ] 位置感知决策

### 中优先级
- [ ] 对手建模 (基于历史行动)
- [ ] 诈唬检测
- [ ] 更复杂的翻牌后策略

### 低优先级
- [ ] 记录和回放功能
- [ ] 统计分析
- [ ] 多桌支持

## 技术栈

- **语言**: Python 3.12
- **浏览器自动化**: Playwright
- **扑克评估**: treys
- **依赖管理**: uv
- **测试**: pytest (计划中)

## 文件结构

```
gamble/
├── src/
│   ├── brain.py              # 大脑模块 (未使用)
│   ├── decision_engine.py    # 决策引擎
│   ├── game_state.py         # 游戏状态
│   ├── hud.py                # HUD 显示
│   ├── main.py               # 主入口
│   └── poker_client.py       # 浏览器客户端
├── tests/
│   ├── __init__.py
│   ├── test_equity.py        # 胜率计算测试
│   └── reproduce_equity_error.py
├── docs/
│   ├── design_doc.md         # 设计文档
│   ├── hud_plan.md           # HUD 实施计划
│   ├── win_rate_plan.md      # 胜率计算计划
│   ├── opponent_analysis_plan.md
│   ├── auto_mode_plan.md
│   └── changelog.md          # 本文件
└── data/                     # 浏览器数据和调试文件
```

## 运行说明

### 启动程序
```bash
python -m src.poker_client
```

### 切换模式
编辑 `src/poker_client.py`:
```python
# 辅助模式
client = ReplayPokerClient(headless=False, auto_mode=False)

# 自动模式
client = ReplayPokerClient(headless=False, auto_mode=True)
```

### 运行测试
```bash
python tests/test_equity.py
```

## 已知问题

1. **Equity Error**: 日志中偶尔出现 `胜率计算错误: 86469` 等数字错误码
   - 可能是 treys 库返回的错误码
   - 需要进一步调查

2. **Python 版本兼容性**: 
   - treys 库在 Python 3.8 下有类型注解问题
   - 建议使用 Python 3.9+

3. **座位识别**: 
   - 当前无法准确识别自己的座位号
   - 导致对手数量统计可能包含自己

## 参考资料

- [ReplayPoker](https://www.replaypoker.com/)
- [Playwright 文档](https://playwright.dev/python/)
- [treys 库](https://github.com/ihendley/treys)
