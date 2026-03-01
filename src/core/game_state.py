from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class Player:
    seat_id: int
    name: str = "Unknown"
    chips: int = 0
    is_active: bool = False  # True if currently in the hand (not folded)
    is_acting: bool = False  # True if it's this player's turn
    status: str = "active" # active, folded, all_in, sit_out
    last_action: Optional[str] = None
    street_actions: List[str] = field(default_factory=list)
    perceived_range: str = "Unknown" # e.g. "Tight", "Wide", "Capped"
    
    # Statistics for profiling
    hands_played: int = 0
    vpip_actions: int = 0 # Voluntarily Put Money In Pot
    pfr_actions: int = 0  # Pre-Flop Raise
    
    @property
    def vpip(self) -> float:
        return (self.vpip_actions / self.hands_played * 100) if self.hands_played > 0 else 0
        
    @property
    def pfr(self) -> float:
        return (self.pfr_actions / self.hands_played * 100) if self.hands_played > 0 else 0

@dataclass
class GameState:
    hole_cards: List[str] = field(default_factory=list)
    community_cards: List[str] = field(default_factory=list)
    pot: int = 0
    current_dealer_seat: Optional[int] = None
    my_seat_id: Optional[int] = None
    active_seat: Optional[int] = None
    to_call: int = 0
    min_raise: int = 0
    max_raise: int = 0
    available_actions: List[str] = field(default_factory=list)
    players: Dict[int, Player] = field(default_factory=dict)
    my_initial_chips: int = 0
    total_chips: int = 0 # Current account balance (on-table + bank)
    
    @property
    def is_my_turn(self) -> bool:
        if self.my_seat_id is None:
            return False
        my_player = self.players.get(self.my_seat_id)
        return my_player.is_acting if my_player else False

    def reset_round(self):
        """Resets round-specific information."""
        self.hole_cards = []
        self.community_cards = []
        self.pot = 0
        self.to_call = 0
        self.active_seat = None
        for p in self.players.values():
            p.is_active = True # Assume active at start of hand
            p.is_acting = False

    def update_card(self, card: str, is_hole: bool):
        target = self.hole_cards if is_hole else self.community_cards
        if card not in target:
            target.append(card)

    def __str__(self):
        return (
            f"--- Game State ---\n"
            f"Hole Cards: {self.hole_cards}\n"
            f"Board: {self.community_cards}\n"
            f"Pot: {self.pot}\n"
            f"My Turn: {self.is_my_turn}\n"
            f"------------------"
        )
