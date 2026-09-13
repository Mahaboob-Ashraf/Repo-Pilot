from normalization import normalize_email


def register_account(display_name: str, email: str) -> dict[str, str]:
    """Create the local account record with a canonical email."""
    return {"display_name": display_name, "email": normalize_email(email)}
