# 测试体系指南 (Testing Guide)

你好，同学。本文档旨在帮助开发者快速了解系统的测试架构与核心逻辑。

---

## 1. 三层测试架构 (Three-Layer Architecture)

为了兼顾开发速度与实战可靠性，系统采用了分层测试策略：

### 🟢 Level 1: 单元测试 (Unit Tests)
- **目标**: 验证核心算法与业务逻辑（如筹码计算、策略分支、状态转换）。
- **特点**: 完全 Mock 浏览器与外部依赖，运行极快 (<1s)。
- **位置**: `tests/unit/`
- **运行**: `pytest tests/unit/ -v`

### 🟡 Level 2: 快照测试 (Snapshot Tests)
- **目标**: 验证 DOM 解析逻辑是否与真实页面匹配。
- **特点**: 使用从真实牌桌捕获的 HTML/JSON 快照，无需启动浏览器即可验证选择器（Selector）和文本解析器。
- **位置**: `tests/explore/` (含 `test_dom_parsing.py`)
- **运行**: `pytest tests/explore/test_dom_parsing.py -v`

### 🔴 Level 3: 集成测试 (Integration Tests)
- **目标**: 验证端到端（E2E）的完整对局流程。
- **特点**: 驱动真实浏览器，模拟自动模式下的入座、玩牌、止损及退出。
- **位置**: `tests/integration/`
- **运行**: `pytest tests/integration/ -v` (需要配置浏览器环境)

---

## 2. 目录结构概览

```text
tests/
├── unit/             # 逻辑单元测试
│   ├── brain/        # 决策大脑与策略测试 (Range, Balanced, etc.)
│   ├── bot/          # 浏览器管理与牌桌生命周期测试
│   └── arena/        # 仿真竞技场规则测试
├── integration/      # 真实浏览器端到端测试
│   └── helpers/      # 状态监控与报告生成工具
├── explore/          # 浏览器探索与 DOM 快照测试
│   └── data/         # 存储真实页面的 DOM 快照 (JSON)
└── tests.md          # 本指南
```

---

## 3. 核心测试逻辑流程

1. **逻辑验证**: 所有的 `Brain` 策略必须通过 `test_consistency.py` 验证，确保输出符合 `ActionPlan` 规范。
2. **解析验证**: 任何 UI 变动后，需重新捕获快照 (`capture_dom.py`) 并运行快照测试，防止解析逻辑失效。
3. **闭环验证**: 在 `Arena` 模式下运行轻量级集成测试，验证新策略在多玩家环境下的稳定性。

---

## 4. 维护工作流 (Maintenance Workflow)

- **修改代码后**: 优先运行单元测试，确保逻辑未退化。
- **UI 变化后**: 捕获新快照 -> 运行快照测试 -> 更新解析器选择器。
- **发布重大更新前**: 运行集成测试或竞技场（Arena）模式进行 100+ 手牌的压力测试。

---
> 保持测试套件的简洁与高覆盖是系统长期稳定运行的基石。
