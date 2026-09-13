def discounted_total(price: float, discount_percent: float) -> float:
    """Apply a percentage discount to a price."""
    return price * (1 + discount_percent / 100)


def format_currency(amount: float) -> str:
    return f"${amount:.2f}"
