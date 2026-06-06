# CLI 命令说明：state vs actions

## 问题

用户提问：`state` 和 `status` 这两个命令有什么区别？如果都是查询状态的话，是不是一个命令就可以了？

## 答案

### 1. 没有 `status` 命令

经过检查，CLI 中**只有 `state` 命令**，没有 `status` 命令。

可用的命令包括：
- `state` - 显示当前游戏状态
- `actions` - 显示可用动作
- 以及其他登录、桌子管理、配置等命令

### 2. `state` 和 `actions` 的区别

虽然两个命令都涉及"状态"，但它们的用途不同：

#### `state` 命令
**用途**：显示完整的游戏状态概览

**输出内容**：
```
--- Game State ---
  Pot: 46
  Community Cards: ['AS', 'KH']
  My Seat: 3
  To Call: 2
  Min Raise: 4
  My Turn: True
  Available Actions: fold, call, raise
```

**特点**：
- 综合性的状态快照
- 包含底池、公共牌、座位、金额等所有关键信息
- Available Actions 只是其中的一部分
- 用于快速了解当前整体局面

#### `actions` 命令
**用途**：详细显示可用的操作选项

**输出内容**：
```
=== Available Actions ===
Actions:
  • fold
  • call (2)
  • raise <amount>|min|half|pot|max
    (min: 4)

Presets: min, ½ Pot, Pot, Max

To Call: 2
```

**特点**：
- 专注于可执行的动作
- 显示每个动作的详细信息（如 call 的金额）
- 显示预设按钮（min, half, pot, max）
- 提供操作提示和格式说明
- 用于准备执行具体操作前的确认

### 3. 为什么需要两个命令？

**设计理由**：

1. **不同的使用场景**
   - `state`: 当你想了解"现在是什么情况"时使用
   - `actions`: 当你想确认"我能做什么操作"时使用

2. **信息密度不同**
   - `state`: 高密度概览，一行显示一个关键信息
   - `actions`: 详细展开，包含操作格式和预设选项

3. **工作流程中的位置**
   ```
   典型流程：
   1. 监控提示 "Your turn to act!"
   2. 输入 `state` 查看整体局面
   3. 输入 `actions` 确认可用操作和金额
   4. 执行具体操作（如 `call` 或 `raise 10`）
   ```

4. **调试目的**
   - `state`: 验证状态识别是否正确（My Turn, To Call 等）
   - `actions`: 验证动作按钮检测是否正确

### 4. 是否可以合并？

**理论上可以，但不建议**：

❌ **合并的问题**：
- 输出会变得很长，不够简洁
- 失去了"快速概览"的价值
- 不符合 Unix 哲学（每个工具做好一件事）

✅ **保持分离的优势**：
- 每个命令职责清晰
- 输出简洁易读
- 可以根据需要选择查看
- 便于脚本化和自动化

### 5. 最佳实践

**推荐的使用方式**：

```bash
# 场景1: 快速检查局面
test-cli> state

# 场景2: 准备行动前确认选项
test-cli> actions

# 场景3: 调试时两者结合
test-cli> state
test-cli> actions

# 场景4: 直接执行操作（不需要先查状态）
test-cli> call
```

### 6. 相关修复

在本次修复中，我们改进了 `state` 命令的 Available Actions 显示：

**修复前**：
- 使用 `get_available_actions()` - 受 `is_my_turn` 限制
- 如果不是你的回合，显示 "(waiting for turn)"
- 即使页面上有按钮也可能不显示

**修复后**：
- 使用 `get_all_visible_actions()` - 绕过 `is_my_turn` 检查
- 始终显示页面上可见的所有动作
- 如果没有按钮，显示 "(none)"
- 与 `actions` 命令保持一致

这样确保了 `state` 命令显示的 Available Actions 与实际页面上的按钮一致，提高了信息的准确性和一致性。

## 总结

- ❌ 没有 `status` 命令，只有 `state` 和 `actions`
- ✅ 两个命令有不同的用途和输出格式
- ✅ 建议保持分离，各司其职
- ✅ `state` = 全局概览，`actions` = 操作详情
- ✅ 本次修复确保了两者在 Available Actions 显示上的一致性
