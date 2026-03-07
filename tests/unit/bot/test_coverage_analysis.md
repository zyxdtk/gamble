# tests/unit/bot 测试覆盖分析报告

## 当前测试文件列表

✅ 已有测试文件：
- test_browser_manager.py
- test_engine_manager.py
- test_lifecycle_manager.py
- test_lobby_manager.py
- test_table_manager.py
- test_task_manager.py

❌ 缺失测试文件：
- **test_play_manager.py** ⚠️

---

## 缺失的测试用例详细分析

### 1. PlayManager 测试 (高优先级)

**文件**: `src/bot/play_manager.py`
**测试文件**: ❌ 缺失 `test_play_manager.py`

**需要测试的方法**：

#### 1.1 状态更新相关
- [ ] `update_state_from_dom()` - 从 DOM 更新游戏状态
  - 测试底池解析
  - 测试筹码解析
  - 测试可用动作按钮检测
  - 测试 to_call 解析
  - 测试 min_raise 解析
  - 测试异常处理

- [ ] `_detect_big_blind()` - 检测盲注级别
  - 测试各种盲注格式解析
  - 测试多种选择器尝试
  - 测试已检测后的跳过逻辑

- [ ] `_parse_stakes_string()` - 解析盲注字符串
  - ✅ 已在 test_table_manager.py 中测试

- [ ] `_parse_amount_string()` - 解析金额字符串
  - 测试普通数字
  - 测试带 k/m 后缀
  - 测试非法输入

#### 1.2 庄家按钮追踪
- [ ] `_detect_dealer_seat()` - 检测庄家位置
  - 测试成功解析位置
  - 测试未找到返回 None
  - 测试异常处理

- [ ] `_update_dealer_cycle()` - 更新庄家周期
  - 测试新周期开始
  - 测试周期完成计数
  - 测试座位记录

#### 1.3 动作执行
- [ ] `find_action_buttons()` - 查找动作按钮
  - 测试找到所有按钮类型
  - 测试部分按钮可见
  - 测试无按钮情况

- [ ] `perform_click()` - 执行点击
  - 测试 FOLD 动作
  - 测试 CHECK/CALL 动作
  - 测试 RAISE/BET 动作
  - 测试 ALL-IN 动作
  - 测试带金额的加注
  - 测试使用下注比例提示
  - 测试动作失败

#### 1.4 Brain 管理
- [ ] `ensure_brain_exists()` - 创建 Brain
  - 测试首次创建
  - 测试已存在时跳过

- [ ] `update_brain_state()` - 更新 Brain 状态
  - 测试状态同步

- [ ] `request_decision()` - 请求决策
  - 测试获取决策数据

- [ ] `reset_brain()` - 重置 Brain
  - 测试重置状态

- [ ] `remove_brain()` - 移除 Brain
  - 测试清理

---

### 2. LifecycleManager 测试 (中优先级)

**文件**: `src/bot/lifecycle_manager.py`
**测试文件**: ✅ 存在 `test_lifecycle_manager.py`

**可能缺失的测试**：
- [ ] `check_overlays()` - 检查覆盖层（用户提到的方法）
  - 测试各种覆盖层检测
  - 测试弹窗处理

- [ ] `_find_my_seat()` - 查找自己的座位
  - 测试找到座位
  - 测试未找到座位
  - 测试多种座位标识

- [ ] `_confirm_buyin_dialog()` - 确认买入弹窗
  - 测试成功确认
  - 测试超时
  - 测试弹窗不存在

---

### 3. TableManager 测试 (中优先级)

**文件**: `src/bot/table_manager.py`
**测试文件**: ✅ 存在 `test_table_manager.py`

**可能缺失的测试**：
- [ ] `execute_turn()` - 执行回合
  - 测试策略决策流程
  - 测试动作执行
  - 测试日志输出

- [ ] `should_exit()` - 检查退出条件
  - ✅ 部分测试已存在
  - 测试 max_hands_limit
  - 测试 max_cycles
  - 测试 exit_requested

- [ ] `log_snapshot()` - 记录日志快照
  - 测试日志写入
  - 测试异常处理

---

### 4. LobbyManager 测试 (低优先级)

**文件**: `src/bot/lobby_manager.py`
**测试文件**: ✅ 存在 `test_lobby_manager.py`

**建议补充**：
- [ ] 找桌逻辑测试
- [ ] 过滤条件测试
- [ ] 页面导航测试

---

### 5. BrowserManager 测试 (低优先级)

**文件**: `src/bot/browser_manager.py`
**测试文件**: ✅ 存在 `test_browser_manager.py`

**建议补充**：
- [ ] 浏览器启动测试
- [ ] 页面管理测试
- [ ] Session 恢复测试

---

### 6. TaskManager 测试 (低优先级)

**文件**: `src/bot/task_manager.py`
**测试文件**: ✅ 存在 `test_task_manager.py`

**建议补充**：
- [ ] 任务状态管理
- [ ] 进度回调
- [ ] 多任务并发

---

## 优先级排序

### 🔴 高优先级（必须补充）
1. **test_play_manager.py** - PlayManager 是核心执行组件，完全无测试

### 🟡 中优先级（建议补充）
2. **LifecycleManager.check_overlays()** - 覆盖层处理很重要
3. **LifecycleManager._find_my_seat()** - 座位查找是关键功能
4. **TableManager.execute_turn()** - 回合执行逻辑

### 🟢 低优先级（可选补充）
5. 各 Manager 的异常处理测试
6. 边界条件测试
7. 集成测试

---

## 建议创建的测试文件清单

1. ✅ **test_play_manager.py** - 完整测试 PlayManager 所有方法
2. 🔄 **test_lifecycle_manager_extended.py** - 补充 LifecycleManager 未测试的方法
3. 🔄 **test_table_manager_extended.py** - 补充 TableManager 执行逻辑

---

## 测试覆盖率目标

建议达到以下覆盖率：
- PlayManager: 80%+ (目前 0%)
- LifecycleManager: 70%+ 
- TableManager: 70%+
- 其他 Manager: 60%+
