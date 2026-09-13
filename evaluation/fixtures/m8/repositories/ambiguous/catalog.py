from products import normalize


def catalog_key(sku: str) -> str:
    return normalize(sku)
