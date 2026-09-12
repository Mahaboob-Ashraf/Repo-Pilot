from service import checkout


def test_checkout_uses_calculation() -> None:
    assert checkout() == 10.0
