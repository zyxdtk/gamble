import random

def get_randomized_amount(amount, jitter=0.05):
    """
    Adds a small random jitter to an amount (e.g., 3BB becomes 2.9BB - 3.1BB).
    """
    return int(amount * (1 + random.uniform(-jitter, jitter)))
