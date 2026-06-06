# Browser Platform 通用浏览器平台

通用的浏览器自动化德州扑克平台，支持多个网站和配置化的策略。

## 📁 文件结构

```
src/platforms/browser/
├── __init__.py                 # 模块入口
├── browser_platform.py         # BrowserPlatform 核心类
├── test_cli.py                 # 交互式测试 CLI
├── README.md                   # 本文件
└── adapters/                   # 网站适配器
    ├── __init__.py
    ├── base.py                 # 抽象基类 WebsiteAdapter
    └── replay_poker.py         # ReplayPoker 具体实现
```

## 🚀 快速开始

```bash
# 启动测试 CLI
python src/main.py --mode test

# 或直接运行
python -m src/platforms/browser/test_cli --stakes 5/10 --strategy most
```

## 🎯 功能特性

### 1. 登录与会话保持
- 使用持久化浏览器数据目录 (`./data/browser_data`)
- 支持手动登录模式（默认）
- 自动检测登录状态

### 2. 配置化的牌桌筛选
- 盲注级别筛选 (`preferred_stakes`)
- 玩家数范围 (`min_players`/`max_players`)
- 最大小盲注限制

### 3. 多种牌桌选择策略
- `fifo` - 按大厅顺序（默认）
- `most` - 选择玩家最多的桌子
- `least` - 选择玩家最少的桌子
- `random` - 随机选择

### 4. 快照功能
- 手动快照和自动快照
- 包含截图、HTML源码、游戏状态

### 5. 完整的游戏操作
- 入座/离桌
- 买入金额设置
- 获取游戏状态
- 执行各类动作

## ⌨️ CLI 命令

### 登录与大厅操作
```
login              - 确保已登录（支持手动登录）
lobby              - 导航到大厅
tables [stakes]    - 列出可用桌子（可筛选盲注）
best               - 显示最佳可用桌子
open [idx|url]     - 打开桌子（索引/URL/最佳）
clearhistory       - 清除访问历史
```

### 牌桌管理
```
sit                - 尝试入座
buyin <amount>     - 设置买入金额并确认
buyin default      - 使用默认买入金额
buyin cancel       - 取消买入弹窗
leave              - 离桌
```

### 游戏操作
```
state              - 查看当前游戏状态
actions            - 查看可用操作
fold               - Fold
check              - Check
call               - Call
raise <amount>     - Raise 到指定金额
bet <amount>       - Bet 指定金额
allin              - All-in
```

### 快照功能
```
snapshot [name]    - 手动截图（仅图片）
snap               - 快速完整快照（包含所有数据）
autosnap on/off    - 开启/关闭自动快照
snaps              - 列出最近快照
snapdir            - 显示快照目录
```

### 配置与工具
```
config             - 显示当前配置
stakes <level>     - 设置优先盲注级别
strategy <type>    - 设置选桌策略（fifo/most/least/random）
url                - 显示当前 URL
help, ?            - 显示帮助
quit, q, exit      - 退出程序
```

## 📋 使用示例

```bash
test-cli> login          # 登录（手动）
test-cli> tables         # 列出可用桌子
test-cli> tables 1/2     # 筛选盲注级别
test-cli> strategy most  # 设置选桌策略
test-cli> best           # 显示最佳桌子
test-cli> open           # 打开最佳桌子
test-cli> sit            # 入座
test-cli> buyin 200      # 设置买入金额
test-cli> actions        # 查看可用操作
test-cli> check          # 执行 check
test-cli> snap           # 保存快照
test-cli> quit           # 退出
```

## 📁 快照目录结构

```
./data/snapshots/
├── snap_1717760000/
│   ├── lobby.png
│   ├── lobby.html
│   ├── table_xxx.png
│   ├── table_xxx.html
│   └── info.json
└── ...
```

## 📝 配置文件

配置文件位置：`config/settings.yaml`

```yaml
bot:
  name: "zyxdtk"
  headless: false

game:
  preferred_stakes: "5/10"
  max_tables: 1

strategy:
  type: "gto"
```

### 环境变量覆盖

- `POKER_STRATEGY` - 覆盖策略类型
- `POKER_MAX_HANDS` - 最大手数
- `POKER_MAX_CYCLES` - 最大圈数
- `POKER_MAX_DURATION_MIN` - 最长运行时间（分钟）
- `POKER_HEADLESS` - 是否无头模式

## 🔌 扩展新网站

1. 继承 `WebsiteAdapter` 基类
2. 实现所有抽象方法
3. 在 `adapters/__init__.py` 中注册

```python
from src.platforms.browser.adapters.base import WebsiteAdapter

class MyPokerSiteAdapter(WebsiteAdapter):
    def get_name(self) -> str:
        return "MyPokerSite"
    # 实现其它抽象方法...
```

## 📚 文件说明

- `browser_platform.py` - BrowserPlatform 核心类
- `adapters/base.py` - WebsiteAdapter 抽象基类
- `adapters/replay_poker.py` - ReplayPoker 网站适配器
- `test_cli.py` - 交互式测试 CLI
