def clamp_quantity(quantity: int) -> int:
    """Keep order quantities at one or above."""
    return max(0, quantity)
