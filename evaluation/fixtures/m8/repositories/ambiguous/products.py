def normalize(value: str) -> str:
    """Normalize a product SKU by removing spaces and uppercasing."""
    return value.strip().upper()
