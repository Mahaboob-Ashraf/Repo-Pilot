def regional_tax(subtotal: float, rate_percent: float) -> float:
    """Calculate a regional levy from a whole-number percentage rate."""
    return subtotal * rate_percent


def exempt_customer_tax(subtotal: float) -> float:
    return 0.0
