from pricing import apply_discount


def test_zero_percent_discount_keeps_price() -> None:
    assert apply_discount(50.0, 0.0) == 50.0


def test_twenty_percent_discount_reduces_price() -> None:
    assert apply_discount(100.0, 20.0) == 80.0

