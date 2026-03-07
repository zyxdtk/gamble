from __future__ import annotations
from src.core.game_state import GameState


def get_position_code(state: GameState) -> str:
    if state.my_seat_id is None or state.current_dealer_seat is None:
        return "ALL"
    
    active_seats = sorted([s for s in state.players.keys()])
    num_players = len(active_seats)
    if num_players < 2:
        return "ALL"
    
    try:
        my_idx = active_seats.index(state.my_seat_id)
        dealer_idx = active_seats.index(state.current_dealer_seat)
    except ValueError:
        return "ALL"
    
    dist = (my_idx - dealer_idx + num_players) % num_players
    
    if dist == 0:
        return "LP"
    if dist == 1:
        return "SB"
    if dist == 2:
        return "BB"
    
    if num_players <= 3:
        return "LP" if dist == 0 else "EP"
    
    if dist <= num_players // 3:
        return "EP"
    if dist <= 2 * num_players // 3:
        return "MP"
    return "LP"


def normalize_hand_string(hole_cards: list[str]) -> str:
    if not hole_cards or len(hole_cards) < 2:
        return "XX"
    
    ranks = "23456789TJQKA"
    try:
        c1, c2 = hole_cards[0], hole_cards[1]
        if not c1 or not c2 or len(c1) < 2 or len(c2) < 2:
            return "XX"
        
        r1_idx = ranks.index(c1[0].upper())
        r2_idx = ranks.index(c2[0].upper())
        
        if r1_idx < r2_idx:
            c1, c2 = c2, c1
            r1_idx, r2_idx = r2_idx, r1_idx
        
        is_suited = c1[1].lower() == c2[1].lower()
        suffix = "s" if is_suited else "o"
        
        if c1[0].upper() == c2[0].upper():
            return c1[0].upper() + c2[0].upper()
        return c1[0].upper() + c2[0].upper() + suffix
    except (ValueError, IndexError):
        return "XX"


from src.engine.player_analysis import PlayerTag


# 玩家分析逻辑已迁移至 src/engine/utils/player_tags.py
