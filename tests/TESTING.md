# 测试规范 (Testing Protocol)

本文档描述 `tests/` 目录的职责划分、文件命名约定及运行方式。

---

## 1. 目录结构

```
tests/
├── TESTING.md                        # 本文件
├── __init__.py
│
├── unit/                             # 单元测试（无浏览器依赖，使用 mock）
│   ├── __init__.py
│   ├── bot/                          # Bot 模块单元测试
│   │   ├── test_browser_manager.py   # BrowserManager 逻辑
│   │   ├── test_table_manager.py     # TableManager 状态管理、离桌流程
│   │   └── test_lobby_manager.py     # LobbyManager URL 解析、选桌逻辑
│   ├── engine/                       # Engine 模块单元测试
│   │   ├── test_strategies.py        # 策略类行为测试
│   │   ├── test_engine_manager.py    # 引擎管理器测试
│   │   └── ...
│   └── core/                         # Core 模块单元测试
│       └── ...
│
├── integration/                      # 端到端集成测试（黑盒测试，真实浏览器）
│   ├── __init__.py
│   ├── helpers/                      # 集成测试辅助工具
│   │   ├── browser_monitor.py        # 浏览器状态监听
│   │   ├── log_collector.py          # 日志收集器
│   │   └── test_reporter.py          # 测试报告生成
│   ├── test_auto_mode.py             # Auto 模式集成测试
│   ├── test_two_cycle_run.py         # CheckOrFold 策略两周期测试
│   └── test_gto_two_cycle.py         # GTO 策略两周期测试
│
└── explore/                          # 浏览器探索工具（手动运行，非自动化测试）
    ├── __init__.py
    ├── explore_lobby.py              # 探索大厅页面元素结构
    └── explore_table.py              # 探索牌桌页面元素结构
```

---

## 2. 文件职责说明

### 2.1 单元测试 (`unit/`)

单元测试使用 mock 替代真实依赖，测试单个模块的逻辑。

| 文件 | 测试目标 | 依赖浏览器 |
|------|----------|-----------|
| `unit/bot/test_browser_manager.py` | Table ID 提取、去重逻辑、策略创建 | ❌（mock） |
| `unit/bot/test_table_manager.py` | 入座判断、满员退桌、止损触发、离桌流程 | ❌（mock） |
| `unit/bot/test_lobby_manager.py` | URL 构造、空位判断 | ❌（mock） |
| `unit/engine/test_strategies.py` | 各策略类 `make_decision()` 输出格式与行为边界 | ❌ |
| `unit/engine/test_engine_manager.py` | 引擎管理器生命周期、大脑创建/销毁 | ❌ |

### 2.2 集成测试 (`integration/`)

集成测试是**黑盒测试**，从 `main.py` 入口启动，在真实浏览器中运行，通过监听浏览器状态和日志来验证系统行为。

| 文件 | 测试目标 | 依赖浏览器 |
|------|----------|-----------|
| `integration/test_play_one_hand.py` | 玩1手牌：启动→入座→玩1手→退出→统计收益 | ✅ 真实浏览器 |
| `integration/test_auto_mode.py` | Auto 模式完整流程：启动→入座→玩牌→退出 | ✅ 真实浏览器 |
| `integration/test_two_cycle_run.py` | CheckOrFold 策略运行两个庄家周期 | ✅ 真实浏览器 |
| `integration/test_gto_two_cycle.py` | GTO 策略运行两个庄家周期 | ✅ 真实浏览器 |

**集成测试特点：**
- 不修改被测代码，纯黑盒测试
- 通过命令行参数控制被测程序（如 `--hands 1 --strategy checkorfold`）
- 通过 `subprocess` 启动 main.py，捕获输出进行验证
- 通过日志解析器监听应用状态和统计收益
- 自动生成 JSON 格式测试报告

### 2.3 浏览器探索工具 (`explore/`)

**不是自动化测试**，是开发辅助工具，在真实浏览器中探索页面结构。

| 文件 | 目标页面 | 输出 |
|------|----------|------|
| `explore/explore_lobby.py` | `casino.org/replaypoker/lobby/rings` | `data/lobby_explore.html` + 截图 |
| `explore/explore_table.py` | 任意 `/play/table/` URL | `data/table_explore.html` + 截图 |

---

## 3. 命名约定

| 类型 | 前缀/位置 | 示例 |
|------|-----------|------|
| 单元测试 | `unit/{module}/test_` | `unit/bot/test_table_manager.py` |
| 集成测试 | `integration/test_` | `integration/test_auto_mode.py` |
| 集成测试辅助 | `integration/helpers/` | `integration/helpers/browser_monitor.py` |
| 浏览器探索工具 | `explore/explore_` | `explore/explore_table.py` |

---

## 4. 运行方式

```bash
source .venv/bin/activate

# 运行全部单元测试（推荐，快速）
pytest tests/unit/ -v

# 运行全部集成测试（需要浏览器和登录 session）
pytest tests/integration/ -v -s --tb=short

# 运行特定集成测试
pytest tests/integration/test_auto_mode.py -v -s

# 运行浏览器探索工具（手动）
python tests/explore/explore_table.py https://www.casino.org/replaypoker/play/table/XXXXX
```

### 4.1 集成测试前置条件

运行集成测试前需要：

1. **有效的登录 session**：
   ```bash
   # 确保 data/browser_data/ 目录存在且包含有效的登录状态
   ls data/browser_data/
   ```

2. **配置正确**：
   ```bash
   # 检查 config/settings.yaml
   cat config/settings.yaml
   ```

3. **无其他 Chrome 实例占用**：
   ```bash
   # 关闭所有 Chrome 浏览器实例
   pkill -f "Google Chrome"
   ```

---

## 5. 编写新的集成测试

参考 `integration/test_auto_mode.py` 的 `AutoModeTestRunner` 类：

```python
class MyIntegrationTest:
    def __init__(self):
        self.monitor = BrowserMonitor()
        self.log_collector = LogCollector()
        self.reporter = TestReporter()

    async def setup(self):
        # 初始化 BrowserManager
        self.browser_manager = BrowserManager(auto_mode=True)
        await self.browser_manager.start()

    async def run_test(self):
        # 运行测试逻辑
        for _ in range(60):
            await self.browser_manager.run_tick()
            await asyncio.sleep(1)

    async def teardown(self):
        # 清理资源
        await self.browser_manager.stop()
```

---

## 6. 测试报告

集成测试会自动生成 JSON 格式的测试报告，保存在 `data/test_reports/` 目录：

```bash
# 查看最新的测试报告
ls -lt data/test_reports/ | head -5

# 查看报告内容
cat data/test_reports/auto_mode_basic_flow_20240301_120000.json
```

报告包含：
- 测试名称和运行时间
- 浏览器状态历史
- 动作日志
- 错误信息
- 测试摘要
