"""Small pricing helpers for the RepoPilot toy fixture."""


def apply_discount(price: float, discount_percent: float) -> float:
    """Return a price after applying a percentage discount."""

    return price * (1 + discount_percent / 100)

