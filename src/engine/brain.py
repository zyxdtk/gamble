from treys import Card, Evaluator, Deck

class PokerBrain:
    def __init__(self):
        self.evaluator = Evaluator()

    def convert_card_to_treys(self, card_str):
        """
        Converts a card string (e.g., 'As', 'Th', '2d') to treys integer format.
        """
        if not card_str:
            return None
        
        # Treys expects 'As', 'Th', etc. Capital Rank, lowercase Suit.
        # Ensure format is correct.
        rank = card_str[0].upper()
        suit = card_str[1].lower()
        return Card.new(f"{rank}{suit}")

    def evaluate_hand(self, hole_cards, community_cards):
        """
        Evaluates the strength of the hand.
        Returns a score (lower is better, 1 is Royal Flush) and a class string.
        """
        if not hole_cards:
            return 8000, "Waiting for cards..."
            
        hand = [self.convert_card_to_treys(c) for c in hole_cards]
        board = [self.convert_card_to_treys(c) for c in community_cards]

        if not board:
             # Preflop evaluation (Basic storage of hand strength logic could go here)
             # For now, we return a simpler indicator or just the rank of the cards
             return 9000, "Preflop"

        score = self.evaluator.evaluate(board, hand)
        hand_class = self.evaluator.class_to_string(self.evaluator.get_rank_class(score))
        
        return score, hand_class

    def get_percentage_strength(self, score):
        """
        Converts the treys score (1-7462) to a percentile strength (0.0 - 1.0).
        1.0 is the best possible hand.
        """
        return 1.0 - (score / 7462.0)

if __name__ == "__main__":
    # Simple test
    brain = PokerBrain()
    print("Test 1: Royal Flush")
    score, class_str = brain.evaluate_hand(['As', 'Ks'], ['Qs', 'Js', 'Ts'])
    print(f"Score: {score}, Class: {class_str}")
    
    print("\nTest 2: Pair")
    score, class_str = brain.evaluate_hand(['Ah', '2d'], ['As', 'Jc', '8d'])
    print(f"Score: {score}, Class: {class_str}")
