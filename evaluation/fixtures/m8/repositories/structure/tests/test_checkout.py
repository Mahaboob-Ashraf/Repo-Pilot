from checkout import checkout_total


def test_checkout_total_includes_tax() -> None:
    assert checkout_total(100.0, 5.0) == 105.0
