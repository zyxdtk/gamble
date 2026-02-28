---
description: How to safely run and test the Texas Hold'em AI Bot in Ralph Loop mode
---

# Running the Poker Bot safely

This workflow outlines the standard procedures for running the bot, ensuring all safety and logging parameters are correctly set before starting a real session on ReplayPoker.

## 1. Local Evaluation / Unit Testing
Before putting the bot on a live table (even with play money), you MUST run the logical tests to ensure the math (Pot Odds, Equity) and GTO range logic is generating +EV decisions.

// turbo
```bash
python -m pytest tests/ -v
```

## 2. Dry Run/Observer Mode (Recommended)
If this is the first run after major modifications, run the bot in "Assist" mode without the `--auto` flag. The browser will open, and you can manually sit at a table. The bot will parse the game state and output its decisions to the terminal, but it **will not click any buttons**.

```bash
python -m src.main
```

Observe the terminal output tags (`[ADVISOR]`, `[GAME ACTION]`) to verify the state parsing matches what you see on the screen.

## 3. Full Auto (Ralph Loop)
When you are confident the bot is acting rationally, start the full autonomous loop. This will navigate to the lobby, locate an appropriate table, buy-in, and start playing strictly following the strategy rules.

```bash
python -m src.main --auto --log-level INFO
```

### Safety Checklist:
- 检查 `config/settings.yaml` 确保 `bankroll_management.stop_loss` 设置正确。
- 确认系统时间同步准确（对于随机数发生器和日志很重要）。
- 确保没有另一个 Chrome 实例在使用同样的 `data/browser_data`。

## 4. Emergency Stop
If the bot exhibits strange behavior (e.g., repeatedly raising all-in with weak hands), terminate the process immediately:
`Ctrl + C` in the terminal to trigger the graceful termination which closes the browser context.
