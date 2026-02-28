import asyncio
import random
import numpy as np

async def human_delay(min_sec=1.5, max_sec=4.5):
    """
    Simulates a human-like delay using a Gaussian distribution.
    Parameters:
    - min_sec: Minimum possible delay.
    - max_sec: Maximum possible delay.
    """
    mean = (min_sec + max_sec) / 2
    # standard deviation to keep most values within [min_sec, max_sec]
    # about 99.7% are within 3 sigma, so 3 * sigma = (max_sec - min_sec) / 2
    sigma = (max_sec - min_sec) / 6
    
    delay = np.random.normal(mean, sigma)
    # Clip to absolute bounds
    delay = max(min_sec, min(max_sec, delay))
    
    print(f"[DELAY] Waiting {delay:.2f}s...", flush=True)
    await asyncio.sleep(delay)

def get_randomized_amount(amount, jitter=0.05):
    """
    Adds a small random jitter to an amount (e.g., 3BB becomes 2.9BB - 3.1BB).
    """
    return amount * (1 + random.uniform(-jitter, jitter))
