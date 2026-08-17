import random


def compute_backoff_delay(
    attempt: int,
    base: int = 2,
    max_backoff: int = 300,
    use_jitter: bool = False,
) -> float:
    """
    Computes exponential backoff delay in seconds.

    Formula:
        delay = base * (2 ** (attempt - 1))
        capped = min(max_backoff, delay)
        if use_jitter:
            delay = random.uniform(0, capped)

    :param attempt: 1-indexed attempt number (1, 2, 3...)
    :param base: Base multiplier in seconds (default: 2s)
    :param max_backoff: Upper bound ceiling in seconds (default: 300s)
    :param use_jitter: Whether to apply full jitter randomization (default: False)
    :return: Delay duration in seconds as float.
    """
    if attempt < 1:
        attempt = 1

    # Exponential calculation: base * 2^(attempt - 1)
    raw_delay = float(base * (2 ** (attempt - 1)))
    capped_delay = min(float(max_backoff), raw_delay)

    if use_jitter:
        # Full Jitter: uniform random value in [0, capped_delay]
        return random.uniform(0.0, capped_delay)

    return capped_delay
