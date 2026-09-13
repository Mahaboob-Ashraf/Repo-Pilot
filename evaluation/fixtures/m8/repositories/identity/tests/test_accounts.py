from accounts import register_account


def test_registration_normalizes_email() -> None:
    account = register_account("Ada", " ADA@EXAMPLE.COM ")
    assert account["email"] == "ada@example.com"
