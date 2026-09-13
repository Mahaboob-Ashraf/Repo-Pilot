def retry_delay(attempt: int, base_seconds: float = 1.0) -> float:
    """Return an exponential delay between repeated delivery attempts."""
    return base_seconds * attempt
