from __future__ import annotations
import random

try:
    from treys import Card, Evaluator, Deck
except ImportError:
    Card = None
    Evaluator = None
    Deck = None


class EquityCalculator:
    _instance = None
    evaluator = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.evaluator = Evaluator() if Evaluator else None
        return cls._instance
    
    def calculate_equity(self, hole_cards: list[str], community_cards: list[str], 
                         num_opponents: int = 1, iterations: int = 500) -> float:
        if not self.evaluator or not Card:
            return self._estimate_preflop_equity(hole_cards)
        
        try:
            hero_cards = [self._to_treys(c) for c in hole_cards]
            board_cards = [self._to_treys(c) for c in community_cards]
            
            if None in hero_cards or None in board_cards:
                return 0.0
            
            wins = 0
            ties = 0
            
            deck = Deck()
            known_cards = hero_cards + board_cards
            for card in known_cards:
                if card in deck.cards:
                    deck.cards.remove(card)
            
            for _ in range(iterations):
                current_deck = list(deck.cards)
                random.shuffle(current_deck)
                
                villain_hands = []
                for _ in range(num_opponents):
                    if len(current_deck) < 2:
                        break
                    villain_cards = [current_deck.pop(), current_deck.pop()]
                    villain_hands.append(villain_cards)
                
                cards_needed = 5 - len(board_cards)
                if len(current_deck) < cards_needed:
                    continue
                
                sim_board = board_cards + [current_deck.pop() for _ in range(cards_needed)]
                
                hero_score = self.evaluator.evaluate(hero_cards, sim_board)
                villain_scores = [self.evaluator.evaluate(vh, sim_board) for vh in villain_hands]
                best_villain_score = min(villain_scores) if villain_scores else float('inf')
                
                if hero_score < best_villain_score:
                    wins += 1
                elif hero_score == best_villain_score:
                    ties += 1
            
            return (wins + (ties / 2)) / iterations
        
        except Exception:
            return self._estimate_preflop_equity(hole_cards)
    
    def _to_treys(self, card_str: str):
        if len(card_str) == 2:
            return Card.new(f"{card_str[0].upper()}{card_str[1].lower()}")
        return None
    
    def _estimate_preflop_equity(self, hole_cards: list[str]) -> float:
        if not hole_cards or len(hole_cards) < 2:
            return 0.0
        
        hand_str = self._normalize_hand(hole_cards)
        
        if hand_str[0] == hand_str[1]:
            rank = hand_str[0]
            if rank == 'A':
                return 0.85
            if rank == 'K':
                return 0.82
            if rank == 'Q':
                return 0.80
            if rank == 'J':
                return 0.77
            if rank == 'T':
                return 0.75
            if rank in '987':
                return 0.70
            return 0.65
        
        if 'A' in hand_str:
            if 'K' in hand_str:
                return 0.67 if 's' in hand_str else 0.65
            if 'Q' in hand_str:
                return 0.66 if 's' in hand_str else 0.64
            if 'J' in hand_str:
                return 0.65 if 's' in hand_str else 0.62
            return 0.60 if 's' in hand_str else 0.55
        
        if 'K' in hand_str:
            if 'Q' in hand_str:
                return 0.63 if 's' in hand_str else 0.60
            if 'J' in hand_str:
                return 0.60 if 's' in hand_str else 0.57
            return 0.55 if 's' in hand_str else 0.50
        
        return 0.35
    
    def _normalize_hand(self, hole_cards: list[str]) -> str:
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
