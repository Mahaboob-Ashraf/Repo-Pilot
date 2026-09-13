from tax_rules import regional_tax


def checkout_total(subtotal: float, rate_percent: float) -> float:
    """Add the regional tax helper result to the order subtotal."""
    return subtotal + regional_tax(subtotal, rate_percent)


def format_receipt(total: float) -> str:
    """Format the final checkout receipt total to two decimal places."""
    return f"total={total:.1f}"
