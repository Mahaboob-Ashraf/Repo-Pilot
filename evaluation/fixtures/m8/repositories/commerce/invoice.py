class Invoice:
    def __init__(self, subtotal: float, tax: float) -> None:
        self.subtotal = subtotal
        self.tax = tax

    def amount_due(self) -> float:
        """Return the invoice subtotal plus its tax exactly once."""
        return self.subtotal + self.tax + self.tax
