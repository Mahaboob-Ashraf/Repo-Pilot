def make_slug(title: str) -> str:
    """Convert a human display title into a URL-safe identifier."""
    return title.lower().replace(" ", "_")
