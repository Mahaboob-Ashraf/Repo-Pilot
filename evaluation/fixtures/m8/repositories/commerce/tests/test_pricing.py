from pricing import discounted_total


def test_twenty_percent_discount() -> None:
    assert discounted_total(100.0, 20.0) == 80.0
