# DOM 探索工具

捕获牌桌 DOM 快照，用于测试和调试。

## 使用方法

```bash
# 自动连接浏览器，等待行动并捕获
python tests/explore/explore_table.py

# 手动模式：每5秒自动截图
python tests/explore/explore_table.py --manual

# 直接进入指定桌子
python tests/explore/explore_table.py https://www.casino.org/replaypoker/play/table/12345
```

## 功能

- 自动连接已有浏览器 (端口 9222)
- 自动打开大厅并找桌子坐下
- 等待行动按钮出现
- 捕获快照并保存

## 输出文件

每次捕获生成 3 个文件：

```
tests/explore/data/
├── {name}_{timestamp}.json    # 数据快照 (底池、筹码、按钮等)
├── {name}_{timestamp}.png     # 截图
└── {name}_{timestamp}.html    # 完整 DOM
```

例如：
- `initial_1772910180.json` / `.png` / `.html`
- `action_fold_1772910190.json` / `.png` / `.html`

## JSON 格式

```json
{
  "name": "action_fold",
  "timestamp": 1772910190.123,
  "url": "https://www.casino.org/replaypoker/play/table/12345",
  "data": {
    "pot": "150",
    "stakes": "1/2",
    "seats": [...],
    "community_cards": [],
    "buttons": {
      "fold": {"text": "Fold", "visible": true},
      "call": {"text": "Call 2", "visible": true}
    }
  }
}
```
