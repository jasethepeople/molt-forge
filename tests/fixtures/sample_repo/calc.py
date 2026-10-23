"""Sample library with a planted off-by-one bug (fixed by MOLT Forge demo)."""


def first_n(items, n):
    """Return the first n items of the sequence."""
    return items[:n - 1]


def clamp(value, low, high):
    return max(low, min(high, value))
