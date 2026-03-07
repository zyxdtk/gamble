# 德州扑克 AI 助手 - 更新日志

## 2026-03-08 更新

### 🧠 对手建模系统 (Player Analysis Module)
- **模块化重组**: 将玩家分析相关组件迁移至独立包 `src/engine/player_analysis/`，包含 `tags.py`、`database.py`、`manager.py` 和多种范围模型。
- **玩家标签体系**: 引入 `PlayerTag` 常量（`NIT`, `TAG`, `FISH`, `STATION`, `MANIAC`, `UNKNOWN`）并实现 `get_player_tag()` 分类函数。
- **SQLite 持久化**: 新增 `PlayerDatabase`，通过 `player.user_id` 跨 Session 记录每位对手的 VPIP/PFR 历史统计。
- **摊牌记录**: 扩展数据库新增 `player_showdowns` 表，记录对手在摊牌时展示的真实手牌，作为修正信号。
- **`PlayerManager` 融合管理**: 统一管理会话内统计、全局持久化数据，并维护每位对手与 Hero 各自的独立范围模型。

### 📊 多策略范围建模 (Multi-Strategy Range Modeling)
- **`BaseRangeModel`**: 引入抽象基类，统一范围模型接口。
- **`ActionBasedRangeModel`**: 基础动作驱动型贝叶斯更新模型（原 `RangeModel`，保持兼容）。
- **`StatsAwareRangeModel`**: 结合 VPIP/PFR 历史数据修正贝叶斯衰减系数。Nit（紧手）的下注导致更剧烈的范围收缩，Maniac 的收缩则更缓慢。
- **`ShowdownAwareRangeModel`**: 通过分析摊牌的"惊讶值"（实际牌力 vs 预期牌力的偏差）动态修正 `bias_factor`——经常诈唬的对手其 `bias_factor < 1.0`，让 AI 对其加注更宽容。
- **智能三级自动切换**: `PlayerManager.get_range_model()` 根据样本量和是否有摊牌记录自动选择最优模型（ActionBased → StatsAware → ShowdownAware）。

### ♟️ RangeBrain 策略升级 (Strategy Integration)
- 新增 `RangeBrain` 策略，整合 EHS、听牌潜力、SPR 与对手范围紧凑度（Tightness Score）进行多维决策。
- **对手紧凑度修正**: `_get_opponent_tightness()` 将范围活跃组合数转化为安全余量（Safety Margin），动态调整跟注阈值：面对 Nit 更保守，面对 Maniac 更积极"抓诈"。
- **决策场景**: 价值提取（EHS>0.75）、半诈唬（强听牌+深筹）、防守弃牌（超池+紧型对手）、赔率跟注（修正阈值）。

### 🚀 启动脚本升级 (start.sh)
- 默认配置更新为：**自动模式 + Range 策略 + 盈利目标 2000**，直接 `./start.sh` 即可无交互启动。
- 支持 `--interactive` (`-i`) 参数手动进入配置菜单。
- 改用 `nohup` 后台运行，日志按时间戳命名（`logs/poker_ai_YYYYMMDD_HHMMSS.log`），`logs/poker_ai.log` 软链接始终指向最新日志，关闭终端后进程继续运行。

### 🧪 测试覆盖
- 全量 139+ 项单元测试全部通过，零回归。
- 新增 `TestRangeBrainOpponentModeling` 测试类，覆盖 Nit/Maniac 差异化决策与摊牌诈唬者识别场景。

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

### 🏆 盈利目标与自动离场 (The 1M Goal)
- **筹码跟踪**: 实时抓取并记录初始筹码量与当前余额，自动计算盈利状况。
- **自动离场**: 实现 `leave_table` 逻辑。当 Session 累计盈利达到 1,000,000 筹码时，Bot 将自动安全离开牌桌。
- **UI 对接**: 支持从“Call”按钮文本中实时解析最新的 `to_call` 数额，极大提升了赔率计算的准确性。

### 🧪 稳定性与测试
- **回归测试**: 新增 `tests/test_decision_regression.py`。涵盖了不同对手风格（NIT, MANIAC）下的决策一致性校验。
- **代码除错**: 修复了 `analyze_all_players` 中的变量定义错误，确保全模式运行无中断。

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
