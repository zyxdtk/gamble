from src.decision_engine import DecisionEngine
from treys import Card, Evaluator, Deck

def test_equity():
    engine = DecisionEngine()
    
    # Test case 1: Preflop (should not reach equity calc usually but let's see)
    # The error happened "Post-flop: Pair of Ks".
    # So we have hole cards and community cards.
    
    # Case from log:
    # Post-flop: Pair of Ks
    # Hole cards? Board?
    # Log doesn't show exact cards in the error line, but "Pair of Ks" implies K in hand or board.
    
    hole_cards = ["Ks", "Qd"]
    community_cards = ["Kh", "7c", "2s"]
    
    print("Testing Equity Calculation...")
    try:
        result = engine.calculate_equity(hole_cards, community_cards, iterations=100)
        print(f"Result: {result}")
    except Exception as e:
        print(f"CRASHED: {e}")

if __name__ == "__main__":
    test_equity()
