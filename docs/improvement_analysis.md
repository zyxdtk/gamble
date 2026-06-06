# 项目分析与改进建议

## 1. 项目现状

### 1.1 代码规模
- **Bot 模块**：2084 行代码，6 个核心文件
- **测试覆盖**：124 个测试用例，82 通过，1 失败，41 跳过

### 1.2 模块架构
```
browser_manager.py    (339行) - 浏览器生命周期管理
lifecycle_manager.py  (434行) - 入座/离场/买入逻辑
lobby_manager.py      (84行)  - 大厅管理
play_manager.py       (322行) - 游戏状态解析与动作执行
table_manager.py      (505行) - 牌桌协调器
task_manager.py       (400行) - 任务目标管理
```

### 1.3 测试状态
- ✅ 82 passed
- ❌ 1 failed (`test_create_checkorfold_brain_returns_correct_type`)
- ⏭️ 41 skipped (异步测试需要 pytest-asyncio)

---

## 2. 已识别的问题

### 2.1 高优先级问题

#### 问题 1: 空桌检测过于敏感
- **现象**：坐下后等待 20 秒无玩家即离开
- **根因**：`lifecycle_manager.py` 中 `_SITOUT_LEAVE_DELAY = 20` 秒
- **影响**：经常在只有 1-2 个玩家的桌子白等一场
- **建议**：增加等待时间到 60 秒，或增加"最少玩家数"判断

#### 问题 2: 椅子 ID 识别错误
- **现象**：日志显示 `Found my seat: ID=1` 但实际是 `seat=5`
- **根因**：`_find_my_seat()` 中座位 ID 提取逻辑有误
- **影响**：无法正确识别自己的座位，可能导致状态更新错误
- **建议**：修复座位 ID 提取逻辑，使用 WebSocket 中的 userId 匹配

#### 问题 3: 统计数据不准确
- **现象**：`Start Stack: 0` 但实际应该是买入金额 250
- **根因**：在桌子刚创建时 starting_stack 未正确设置
- **影响**：盈利统计不准确
- **建议**：在买入确认后立即设置 starting_stack

#### 问题 4: 测试失败
- **失败项**：`test_create_checkorfold_brain_returns_correct_type`
- **影响**：checkorfold 策略创建有问题
- **建议**：检查 brain 创建逻辑

### 2.2 中优先级问题

#### 问题 5: 异步测试跳过过多
- **现象**：41 个测试被跳过
- **根因**：缺少 pytest-asyncio 配置
- **建议**：安装并配置 pytest-asyncio

#### 问题 6: WebSocket 消息处理不完整
- **现象**：有时候没收到自己的手牌（`Hole: []`）
- **根因**：`dealHoleCards` 处理可能遗漏
- **建议**：增强 WebSocket 消息解析的健壮性

#### 问题 7: 日志显示问题
- **现象**：`[GTO THINKING]` 日志与实际动作不符
- **根因**：日志记录时预期动作与最终动作不一致
- **建议**：统一日志格式，区分"预期"和"实际"

### 2.3 低优先级问题

#### 问题 8: 代码注释不一致
- **现象**：部分注释是英文，部分是中文
- **建议**：统一使用中文注释

#### 问题 9: 异常处理不够健壮
- **现象**：某些异常被静默吞掉
- **建议**：增加更详细的错误日志

---

## 3. 改进建议

### 3.1 立即修复（高优先级）

| # | 问题 | 文件 | 建议修改 |
|---|------|------|----------|
| 1 | 空桌等待时间过短 | `lifecycle_manager.py` | `_SITOUT_LEAVE_DELAY = 20` → `60` |
| 2 | 座位 ID 识别错误 | `lifecycle_manager.py` | 修复 `_find_my_seat()` 逻辑 |
| 3 | 统计数据不准确 | `browser_manager.py` | 确保 starting_stack 在买入时设置 |
| 4 | 测试失败 | `test_engine_manager.py` | 修复 checkorfold brain 创建 |

### 3.2 短期改进（中优先级）

| # | 问题 | 文件 | 建议修改 |
|---|------|------|----------|
| 5 | 异步测试跳过 | `pyproject.toml` | 添加 pytest-asyncio 配置 |
| 6 | WebSocket 消息 | `table_manager.py` | 增强 dealHoleCards 处理 |
| 7 | GTO 日志不一致 | `range.py` | 统一日志格式 |

### 3.3 长期改进（低优先级）

| # | 问题 | 建议 |
|---|------|------|
| 8 | 代码注释统一 | 逐步将英文注释转为中文 |
| 9 | 异常处理 | 增加错误日志详细程度 |
| 10 | 新策略开发 | 添加更多策略类型 |

---

## 4. 行动清单

### 本次迭代
- [ ] 修复空桌等待时间
- [ ] 修复座位 ID 识别
- [ ] 修复统计数据
- [ ] 修复测试失败

### 下次迭代
- [ ] 配置 pytest-asyncio
- [ ] 增强 WebSocket 处理
- [ ] 统一日志格式
