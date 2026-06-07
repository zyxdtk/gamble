# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Texas Hold'em Poker AI automation and simulation system. Uses Playwright browser automation to play on ReplayPoker.com, and includes a local simulation arena for offline strategy testing. Features a multi-strategy decision engine ("Brain") with six strategies including a deep learning (DQN) option.

**Language**: Chinese for all docs, comments, commit messages, and agent communication. English for code identifiers.

## Commands

```bash
# Setup
uv sync
playwright install chrome

# Run modes
uv run python -m src.main cli          # Interactive CLI (manual browser control)
uv run python -m src.main auto         # Auto-play bot
uv run python -m src.main --mode arena --arena-hands 100  # Arena simulation

# Tests
uv run pytest tests/ -v                # All tests
uv run pytest tests/arena/ -v          # Arena tests only
uv run pytest -m integration -v        # Integration tests (requires real browser)

# Train neural model
uv run python scripts/train_nlh_model.py

# Interactive launcher
./start.sh --interactive
```

## Architecture

**Platform-Agent decoupled pattern**: Core abstractions define interfaces; platform and strategy layers implement them independently.

### Core Layer (`src/core/`)
- `GamePlatform` (ABC) — interface for any poker platform
- `PlayerAgent` (ABC) — interface for any decision agent
- `GameRunner` — orchestrates a session connecting an Agent to a Platform
- `EventBus` — pub/sub event system
- `StrategyToAgentAdapter` — adapts Strategy classes to PlayerAgent interface; converts between the two `GameState` types

### Strategy Layer (`src/strategies/`)
- `Strategy` (ABC) — defines `make_decision(state) -> ActionPlan` and `handle_event()`
- `StrategyManager` (singleton) — auto-discovers strategy modules via filesystem scanning, registers and creates per-table
- Six strategies: `RangeStrategy`, `BalancedStrategy`, `ExploitativeStrategy`, `CheckOrFoldStrategy`, `AggressiveStrategy`, `NeuralStrategy`
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

- `config/settings.yaml` — bot name, headless mode, strategy type/style, buy-in, anti-ban delays, exit thresholds (stop_loss_bb, take_profit_bb)
- `config/preflop_ranges.yaml` — preflop hand ranges by position (EP, MP, LP, SB)

## Key Conventions

- Package manager: `uv` (Python 3.12 per `.python-version`)
- Test framework: pytest with `asyncio_mode = "strict"`; `@pytest.mark.integration` for browser tests
- "Brain" in docs/loggers refers to `src/strategies/` (README references `src/brain/` but actual dir is `src/strategies/`)
- Runtime data goes to `data/` and `logs/` (both gitignored)
- `start.sh` runs bot with `nohup` in background, logging to `logs/poker_ai.log`
