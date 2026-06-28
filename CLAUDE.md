# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Texas Hold'em Poker AI automation and simulation system. Uses Playwright browser automation to play on ReplayPoker.com, and includes a local simulation arena for offline strategy testing. Features a multi-strategy decision engine ("Brain") with nine strategies including a deep learning (DQN) option.

**Language**: Chinese for all docs, comments, commit messages, and agent communication. English for code identifiers.

## Commands

```bash
# Setup
uv sync
playwright install chrome

# Run modes (推荐使用 --platform/--game/--pilot)
uv run python -m src.main --platform browser --game ring --pilot auto      # 全自动 bot (ReplayPoker)
uv run python -m src.main --platform browser --game ring --pilot managed   # 托管模式
uv run python -m src.main --platform browser --game ring --pilot assist    # 辅助模式
uv run python -m src.main --platform arena  --game ring --arena-hands 100  # Arena 仿真

# 旧别名 (仍可用，会打印废弃提示)
uv run python -m src.main auto   # = --platform browser --game ring --pilot auto
uv run python -m src.main cli    # = --platform browser --game ring --pilot assist

# Tests
uv run pytest tests/ -v                # All tests
uv run pytest tests/unit/ -v           # Unit tests only
uv run pytest tests/unit/arena/ -v     # Arena tests only
uv run pytest -m integration -v        # Integration tests (requires real browser)

# Train neural model
uv run python scripts/train_nlh_model.py

# Interactive launcher
./start.sh --interactive
```

**常用参数**：`--headless` 无头模式 | `--stakes 1/2` 盲注级别 | `--strategy tag` 策略 | `--buyin min` 买入量 | `--log-level INFO` 日志级别

## Architecture

**Platform-Agent decoupled pattern**: Core abstractions define interfaces; platform and strategy layers implement them independently.

### Core Layer (`src/core/`)
- `GamePlatform` (ABC) — interface for any poker platform
- `PlayerAgent` (ABC) — interface for any decision agent
- `GameRunner` — orchestrates a session connecting an Agent to a Platform
- `EventBus` — pub/sub event system
- `StrategyToAgentAdapter` — adapts Strategy classes to PlayerAgent interface; converts between the two `GameState` types

### Strategy Layer (`src/strategies/`)
- `Strategy` (ABC) — defines `make_decision(state) -> ActionPlan` and `handle_event()`；支持 `strategy_aliases` 类属性注册别名
- `StrategyManager` (singleton) — auto-discovers strategy modules via filesystem scanning, registers (含别名) and creates per-table
- 九种策略: `TightAggressiveStrategy`(默认, 别名 `tag`), `GtoSolverStrategy`(别名 `gto`), `RangeStrategy`, `BalancedStrategy`, `ExploitativeStrategy`, `CheckOrFoldStrategy`, `AggressiveStrategy`, `NeuralStrategy`, `ICMStrategy`
- 策略名注册规则: 文件名去下划线小写 (如 `gto_solver.py` → `gtosolver`)；别名通过 `strategy_aliases` 注册 (如 `gto`)
- Utility submodules: `equity.py`, `board_analyzer.py`, `position.py`, `preflop_range.py`, `game_utils.py`
- Player analysis subpackage: `manager.py`, `model.py`, `showdown_model.py`, `stats_model.py`, `tags.py`, `database.py`

### Platform Layer (`src/platforms/`)
- `BrowserPlatform` — connects to ReplayPoker via Playwright; uses `WebSocketListener` for real-time state, `ReplayPokerAdapter` for DOM interaction, `StateManager` for state aggregation
- `ArenaPlatform` — wraps `GameEngine` for local simulation

### Arena Layer (`src/arena/`)
- `GameEngine` — poker rules engine (deck, dealing, betting, pot, showdown) using `treys` library
- `ArenaAgent` — translates `GameEngine` state into `GameState` for strategies
- `Competition` — multi-hand tournament runner with stats (VPIP, PFR, Profit)

## Key Data Flow

```
GameState (src/strategies/game_state.py)  --  strategy-specific, richer fields
   ├── Strategy.make_decision(state) -> ActionPlan
   │     └── ActionPlan.get_action_for_bet(to_call, pot) -> (ActionType, amount)
   ├── ArenaAgent._translate_state(arena) -> GameState
   └── StrategyToAgentAdapter._convert_to_strategy_state(core) -> GameState
```

**Two parallel `GameState` classes** exist:
- `src/core/interfaces.py` — platform-agnostic, used by core interfaces
- `src/strategies/game_state.py` — strategy-specific, richer fields

**Two parallel `ActionType` enums**:
- `src/strategies/action_plan.py` — FOLD, CHECK, CALL, RAISE, ALL_IN
- `src/core/interfaces.py` — same values plus BET

The `StrategyToAgentAdapter` bridges these two type systems.

## Configuration

- `config/settings.yaml` — bot name, headless mode, strategy type/style (默认 `tag`), buy-in, anti-ban delays, exit thresholds (stop_loss_bb, take_profit_bb), auto_mode (stuck_threshold, max_table_switches)
- `config/preflop_ranges.yaml` — preflop hand ranges by position (EP, MP, LP, SB)

## Auto Mode 健壮性机制

- **卡住检测**: 连续 `stuck_threshold` 轮（默认 30）无法入座 → 自动换桌（`_switch_table`）
- **换桌流程**: `leave_table` → `remove_strategy` → 重置桌位状态 → `open_table` → `create_strategy` → 重建 `PilotDecider`
- **防无限换桌**: 连续换桌 `max_table_switches` 次（默认 5）仍失败 → 等 60s 重试；无可用桌子等 30s
- **筹码冲突诊断**: 策略返回的 raise 金额超出自身筹码、或面对超额 all-in 仍 raise 时打 WARNING
- **Raise 按钮置灰检测**: 执行 raise 前检查 `disabled` 属性和 `opacity`，置灰时 return False 不再静默成功

## Key Conventions

- Package manager: `uv` (Python 3.12 per `.python-version`)
- Test framework: pytest with `asyncio_mode = "strict"`; `@pytest.mark.integration` for browser tests
- "Brain" in docs/loggers refers to `src/strategies/` (README references `src/brain/` but actual dir is `src/strategies/`)
- Runtime data goes to `data/` and `logs/` (both gitignored)
- `start.sh` runs bot with `nohup` in background, logging to `logs/poker_ai.log`
