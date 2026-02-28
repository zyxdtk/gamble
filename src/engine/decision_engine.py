import random
from dataclasses import dataclass
from typing import List, Optional
try:
    from treys import Card, Evaluator, Deck
except ImportError:
    print("Warning: treys not installed. Equity calculation disabled.")
    Card = None
    Evaluator = None
    Deck = None

import yaml
import os
from ..core.game_state import GameState

class DecisionEngine:
    def __init__(self):
        self.preflop_ranges = self.load_ranges()
        if Evaluator:
            self.evaluator = Evaluator()
        else:
            self.evaluator = None

    def load_ranges(self):
        """Loads preflop ranges from yaml config."""
        config_path = os.path.join(os.getcwd(), "config", "preflop_ranges.yaml")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    return data.get("ranges", {})
            except Exception as e:
                print(f"[RESOURCES] Error loading ranges from {config_path}: {e}")
        
        # Fallback to hardcoded tiered values
        print("[RESOURCES] Using fallback preflop charts.")
        return {
            "tier1": ["AA", "KK", "QQ", "JJ", "AKs"],
            "tier2": ["TT", "AQs", "AJs", "KQs", "AKo"],
            "tier3": ["99", "88", "AQo", "ATs", "KJs", "QJs", "JTs"]
        }

    def decide(self, state: GameState) -> dict:
        """
        Analyzes the current state and returns structured decision data.
        Returns a dict with my action, equity, and all players' information.
        """
        if not state.hole_cards:
            return {
                "my_action": "等待发牌...",
                "my_equity": 0,
                "my_hand_strength": "",
                "players": []
            }

        # Determine Position (simplified)
        # ReplayPoker counts seats 1-9. Button seat is state.current_dealer_seat.
        # We assume our seat is state.my_seat_id.
        pos_code = self.get_position_code(state)
        
        # Pre-flop
        if not state.community_cards:
            my_action = self.evaluate_preflop_v2(state.hole_cards, pos_code)
            my_equity = 0  # Preflop equity is complex, use range vs range later
            my_hand_strength = "翻牌前"
        else:
            # Post-flop
            my_action = self.evaluate_postflop(state.hole_cards, state.community_cards)
            equity_info = self.calculate_equity(state)
            my_hand_strength = my_action.split(":")[1].split("-")[0].strip() if ":" in my_action else ""
            
            # Extract equity percentage from equity_info
            import re
            equity_match = re.search(r'(\d+\.?\d*)%', equity_info)
            my_equity = float(equity_match.group(1)) if equity_match else 0
        
        # Analyze all players
        players_info = self.analyze_all_players(state)
        
        return {
            "my_action": my_action,
            "my_equity": my_equity,
            "my_hand_strength": my_hand_strength,
            "position": pos_code,
            "players": players_info
        }

    def get_position_code(self, state: GameState) -> str:
        """Returns position code: EP, MP, LP, SB, or ALL (unknown)."""
        if state.my_seat_id is None or state.current_dealer_seat is None:
             return "ALL"
             
        # Find relative position of our seat from button
        # seat_id starts at 1 usually?
        dealer = state.current_dealer_seat
        mine = state.my_seat_id
        num_players = len(state.players)
        if num_players < 2:
             return "ALL"
             
        # Dist = number of seats mine is *behind* dealer
        # e.g. dealer=1, mine=2 -> dist=1 (SB)
        # dealer=1, mine=9 -> dist=8 (LP/BTN)
        dist = (mine - dealer + num_players) % num_players
        
        # Mapping dist to label
        # 1: SB, 2: BB, 3: UTG (EP), ...
        # Simplified:
        if dist == 0:
             return "LP" # BTN
        elif dist == 1:
             return "SB" # SB
        elif dist == 2:
             return "EP" # BB/UTG earlyish
        elif dist <= num_players // 3:
             return "EP"
        elif dist <= 2 * num_players // 3:
             return "MP"
        else:
             return "LP"

    def evaluate_preflop_v2(self, hole_cards, pos_code):
        hand_str = self.get_hand_string(hole_cards)
        
        # Use provided positional range if available
        active_range = self.preflop_ranges.get(pos_code, self.preflop_ranges.get("ALL", []))
        
        # Check tier1 strong hands (universal)
        tier1 = ["AA", "KK", "QQ", "JJ", "AKs", "AKo"]
        if hand_str in tier1:
             return f"翻牌前 ({pos_code}): 顶级强牌 ({hand_str}) - 加注/加注/全下"
             
        if hand_str in active_range:
             return f"翻牌前 ({pos_code}): 入池范围内 ({hand_str}) - 加注/跟注"
        
        return f"翻牌前 ({pos_code}): 弱牌 ({hand_str}) - 弃牌"

    def get_hand_string(self, hole_cards):
        # Normalize cards: ['As', 'Kd'] -> 'AKo' or 'AKs'
        ranks = "23456789TJQKA"
        c1, c2 = hole_cards[0], hole_cards[1]
        
        r1_idx = ranks.index(c1[0])
        r2_idx = ranks.index(c2[0])
        
        if r1_idx < r2_idx:
            c1, c2 = c2, c1
            r1_idx, r2_idx = r2_idx, r1_idx

        is_suited = c1[1] == c2[1]
        suffix = "s" if is_suited else "o"
        
        if c1[0] == c2[0]:
            return c1[0] + c2[0]
        return c1[0] + c2[0] + suffix


    def calculate_equity(self, state: GameState, iterations=1000):
        """Calculates equity using Monte Carlo simulation with treys against all active opponents."""
        if not self.evaluator or not Card:
            return ""

        hole_cards = state.hole_cards
        community_cards = state.community_cards
        
        # Count active opponents (not folded)
        num_opponents = sum(1 for p in state.players.values() 
                           if p.is_active and p.status != "folded")
        # Subtract ourselves if we're in the players list
        if num_opponents > 0:
            num_opponents -= 1
        # Default to at least 1 opponent
        if num_opponents < 1:
            num_opponents = 1

        try:
            # Convert cards to treys format
            def to_treys(card_str):
                if len(card_str) == 2:
                    return Card.new(f"{card_str[0].upper()}{card_str[1].lower()}")
                return None

            hero_cards = [to_treys(c) for c in hole_cards]
            board_cards = [to_treys(c) for c in community_cards]
            
            if None in hero_cards or None in board_cards:
                return "胜率: 解析牌面错误"

            wins = 0
            ties = 0
            
            deck = Deck()
            
            # Remove known cards from deck
            known_cards = hero_cards + board_cards
            for card in known_cards:
                if card in deck.cards:
                    deck.cards.remove(card)
            
            # Simulation
            for _ in range(iterations):
                # Shuffle remaining deck
                current_deck = list(deck.cards)
                random.shuffle(current_deck)
                
                # Deal hands for all opponents
                villain_hands = []
                for _ in range(num_opponents):
                    if len(current_deck) < 2:
                        break  # Not enough cards
                    villain_cards = [current_deck.pop(), current_deck.pop()]
                    villain_hands.append(villain_cards)
                
                # Deal remaining board
                cards_needed = 5 - len(board_cards)
                if len(current_deck) < cards_needed:
                    continue  # Skip this iteration if not enough cards
                    
                sim_board = board_cards + [current_deck.pop() for _ in range(cards_needed)]
                
                # Evaluate hero hand
                hero_score = self.evaluator.evaluate(hero_cards, sim_board)
                
                # Evaluate all villain hands and find the best (lowest score)
                villain_scores = [self.evaluator.evaluate(vh, sim_board) for vh in villain_hands]
                best_villain_score = min(villain_scores) if villain_scores else float('inf')
                
                # Check if hero wins
                if hero_score < best_villain_score:  # Lower score is better in treys
                    wins += 1
                elif hero_score == best_villain_score:
                    ties += 1

            equity = (wins + (ties / 2)) / iterations * 100
            return f"胜率 (对 {num_opponents} 位对手): {equity:.1f}%"

        except Exception as e:
            return f"胜率计算错误: {e}"

    def evaluate_preflop(self, hole_cards):
        # Normalize cards: ['As', 'Kd'] -> 'AKo' or 'AKs'
        # 1. Sort by rank
        ranks = "23456789TJQKA"
        c1, c2 = hole_cards[0], hole_cards[1]
        
        # Convert to rank indices for sorting
        r1_idx = ranks.index(c1[0])
        r2_idx = ranks.index(c2[0])
        
        # Ensure c1 is the higher rank
        if r1_idx < r2_idx:
            c1, c2 = c2, c1
            r1_idx, r2_idx = r2_idx, r1_idx

        # Check suitedness
        is_suited = c1[1] == c2[1]
        suffix = "s" if is_suited else "o"
        
        # Handle pairs
        if c1[0] == c2[0]:
            hand_str = c1[0] + c2[0] # e.g., "AA", "KK"
        else:
            hand_str = c1[0] + c2[0] + suffix # e.g., "AKs", "JTo"

        # Check tiers
        if hand_str in self.preflop_charts["tier1"]:
             return f"翻牌前: 顶级牌 ({hand_str}) - 加注/全下"
        if hand_str in self.preflop_charts["tier2"]:
             return f"翻牌前: 强牌 ({hand_str}) - 加注/跟注"
        if hand_str in self.preflop_charts["tier3"] or (c1[0] == c2[0]): # Pocket pairs 22-99
             return f"翻牌前: 可玩 ({hand_str}) - 跟注/过牌"
        
        return f"翻牌前: 弱牌 ({hand_str}) - 弃牌"

    def analyze_opponent_ranges(self, state: GameState) -> str:
        """
        Analyzes active opponents based on their last action and street actions.
        """
        analysis = []
        for seat_id, player in state.players.items():
            if not player.is_active or player.status == "folded":
                continue
                
            # Skip ourselves if we knew our seat_id, but for now we just list everyone active
            # except maybe if we can identify ourselves.
            
            range_desc = "未知"
            
            # Simple Heuristics
            if "raise" in player.street_actions:
                 range_desc = "紧凶 (前15%) - 88+, ATs+, KJs+"
            elif "bet" in player.street_actions:
                 range_desc = "强牌 - 顶对+或诈唬"
            elif "call" in player.street_actions:
                 range_desc = "宽松/投机 - 对子, 同花连牌"
            elif "check" in player.street_actions:
                 range_desc = "弱牌 - 中对或更差"
            
            if range_desc != "未知":
                analysis.append(f"  - 座位 {seat_id} ({player.last_action}): {range_desc}")

        if not analysis:
            return ""
            
        return "【对手分析】\n" + "\n".join(analysis)

    def analyze_all_players(self, state: GameState) -> list:
        """
        Analyzes all players and returns structured information for each.
        """
        players_info = []
        
        for seat_id, player in sorted(state.players.items()):
            # Estimate hand range based on actions
            hand_range = self.estimate_hand_range(player)
            
            # Estimate equity (simplified - would need more complex calculation)
            equity = self.estimate_player_equity(player, state)
            
            # Check if we have visible cards for this player
            visible_cards = []
            # Note: Currently we don't track other players' visible cards
            # This would need to be added to GameState if cards are shown
            
            player_info = {
                "seat_id": seat_id,
                "name": player.name,
                "chips": player.chips,
                "status": player.status,
                "is_active": player.is_active,
                "hand_range": hand_range,
                "equity": equity,
                "visible_cards": visible_cards,
                "last_action": player.last_action or "无"
            }
            
            players_info.append(player_info)
        
        return players_info

    def estimate_hand_range(self, player) -> str:
        """Estimates a player's hand range based on their actions."""
        if player.status == "folded":
            return "已弃牌"
        
        if not player.street_actions:
            return "未知"
        
        # Simple heuristics based on actions
        actions = player.street_actions
        
        if "raise" in actions or "bet" in actions:
            return "强牌 (顶对+, 听牌)"
        elif "call" in actions:
            return "中等牌 (对子, 听牌)"
        elif "check" in actions:
            return "弱牌 (高牌, 小对)"
        else:
            return "未知"

    def estimate_player_equity(self, player, state: GameState) -> float:
        """
        Estimates a player's equity based on their perceived hand range.
        This is a simplified estimation - real equity would require range vs range calculation.
        """
        if player.status == "folded" or not player.is_active:
            return 0.0
        
        # Simple heuristic based on hand range estimation
        actions = player.street_actions
        
        if "raise" in actions or "bet" in actions:
            return 40.0  # Strong range
        elif "call" in actions:
            return 25.0  # Medium range
        elif "check" in actions:
            return 15.0  # Weak range
        else:
            return 20.0  # Unknown, assume average


    def evaluate_postflop(self, hole_cards, community_cards):
        # Very basic hit check (pair, two pair, etc.)
        all_cards = hole_cards + community_cards

        ranks = [c[0] for c in all_cards]
        suits = [c[1] for c in all_cards]
        
        # Count ranks
        rank_counts = {r: ranks.count(r) for r in ranks}
        pairs = [r for r, count in rank_counts.items() if count == 2]
        trips = [r for r, count in rank_counts.items() if count == 3]
        quads = [r for r, count in rank_counts.items() if count == 4]
        
        # Basic hand ranking
        hand_strength = "高牌"
        action = "过牌/弃牌"
        
        if quads:
            hand_strength = "四条"
            action = "加注/全下"
        elif trips:
            if pairs: # Full House
                hand_strength = "葫芦"
                action = "加注/全下"
            else:
                hand_strength = "三条"
                action = "加注"
        elif len(pairs) >= 2:
            hand_strength = "两对"
            action = "加注/跟注"
        elif len(pairs) == 1:
            # Check if pair is using hole card
            pair_rank = pairs[0]
            hole_ranks = [c[0] for c in hole_cards]
            if pair_rank in hole_ranks:
                 hand_strength = f"对 {pair_rank}"
                 action = "跟注/加注"
            else:
                 hand_strength = f"公共牌对 {pair_rank}"
                 action = "过牌/跟注"

        # Determine street name
        num_cards = len(community_cards)
        if num_cards == 3:
            street = "翻牌"
        elif num_cards == 4:
            street = "转牌"
        elif num_cards == 5:
            street = "河牌"
        else:
            street = "翻牌后"

        return f"{street}: {hand_strength} - {action}"
