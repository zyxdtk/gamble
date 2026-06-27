"""
payload 转换共享模块。

从 main.py 提取的浏览器状态 → 统一 payload schema 转换函数，
供 auto_player.py 和 PilotDecider 使用，避免循环依赖。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def browser_state_to_payload(state, actions: dict) -> dict:
    """将浏览器 (PokerGameState, actions) 转为统一 schema 的 payload"""
    pot = getattr(state, "pot", 0) if state else 0
    to_call = int(actions.get("to_call", 0) or 0)
    min_raise = int(actions.get("min_raise", 0) or (getattr(state, "min_raise", 0) if state else 0) or 0)
    max_raise = int(actions.get("max_raise", 0) or 0)
    hole = list(getattr(state, "hole_cards", []) or []) if state else []
    board = list(getattr(state, "community_cards", []) or []) if state else []
    my_seat = getattr(state, "my_seat_id", None) if state else None
    players = getattr(state, "players", {}) if state else {}

    # 当前阶段：浏览器用 prefs 标识，简化为 preflop/flop/turn/river
    board_n = len(board)
    if board_n == 0:
        stage = "preflop"
    elif board_n == 3:
        stage = "flop"
    elif board_n == 4:
        stage = "turn"
    else:
        stage = "river"

    available = list(actions.get("available", []) or [])
    # 浏览器侧 "bet" 跟 "raise" 在显示层等价，统一为 raise
    norm_available = []
    for a in available:
        if a == "bet":
            norm_available.append("RAISE")
        else:
            norm_available.append(a.upper())

    players_data = {}
    for sid, p in players.items():
        players_data[str(sid)] = {
            "user_id": str(sid),
            "name": getattr(p, "name", "") or f"Seat{sid}",
            "chips": getattr(p, "chips", 0),
            "is_active": getattr(p, "status", "active") not in ("folded", "sit_out"),
            "status": getattr(p, "status", "active"),
            "bet": getattr(p, "bet", 0),
            "is_acting": getattr(p, "is_acting", False),
        }

    return {
        "my_seat_id": my_seat,
        "hole_cards": hole,
        "community_cards": board,
        "pot": pot,
        "to_call": to_call,
        "min_raise": min_raise,
        "max_raise": max_raise,
        "available_actions": norm_available,
        "current_stage": stage,
        "players": players_data,
    }


def choice_to_game_action(choice) -> dict:
    """将 ActionChoice 转换回浏览器模式 {action, amount} 格式"""
    action = choice.action
    if action == "allin":
        return {"action": "raise", "amount": 0}  # max_raise 由调用方补充
    amount = choice.amount
    return {"action": action, "amount": amount}
