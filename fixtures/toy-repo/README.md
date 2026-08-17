# RepoPilot Toy Repository

This deliberately small Python repository is the first controlled target for
future RepoPilot parsing, retrieval, patching, and regression work.

## Intended bug

`pricing.apply_discount()` should reduce a price by the supplied percentage.
For example, a 20% discount on `100.0` must return `80.0`.

The current implementation is intentionally wrong: it increases the price
instead. Do not fix the bug in this fixture until a later RepoPilot workflow is
explicitly testing the repair path.

## Expected baseline

Run from this directory with pytest available:

```text
pytest -q
```

Exactly one test should pass and exactly one should fail. The failing test is
intentional fixture evidence; it is not a RepoPilot application test failure.

