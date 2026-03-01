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


def get_player_tag(player) -> str:
    if player.hands_played < 5:
        return "样本不足"
    
    vpip = player.vpip
    pfr = player.pfr
    
    if vpip > 40 and pfr < 10:
        return "跟注站 (Calling Station)"
    if vpip > 50 and pfr > 30:
        return "疯子 (Maniac)"
    if vpip < 15:
        return "紧逼 (Nit/Tight)"
    if vpip < 25 and pfr > 15:
        return "紧凶 (TAG)"
    if vpip > 30 and pfr < 15:
        return "宽松被动 (Fish)"
    
    return "普通 (Average)"
