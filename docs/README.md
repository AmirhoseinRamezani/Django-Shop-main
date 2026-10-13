# Payment Resolution patch v2

Patch paths are rooted at the repository root and use `core/...`, e.g. `diff --git a/core/payment/admin.py b/core/payment/admin.py`. The new service module is `core/payment/services/payment_resolution.py`.

## Key corrections

- Only the typed `OrderFinalizationConflict` emitted by canonical `confirm_order_payment()` is eligible for Resolution registration. Ordinary `ValidationError` (including financial snapshot validation), missing attempt evidence, multiple successful Payments, and unexpected exceptions propagate without creating a Resolution.
- Canonical finalization validates the immutable Payment/Order financial snapshot before classifying recognized Order lifecycle conflicts. Payment remains `SUCCESS`; Resolution does not consume Payment, mutate Order, refund, or call a gateway.
- Reconciliation still records successful provider inquiry evidence first, then delegates all order-side effects to `confirm_order_payment()` through the shared synchronization entrypoint.
- Django Admin requires an operator-entered resolution note.
- Result-page session hints are treated as untrusted presentation state; malformed, stale, foreign-owner, and closed-resolution hints are cleared without turning the result page into a 404.
- Recovery is keyset-paginated, makes no provider calls, continues past per-record errors, and can safely be rerun.
- Added service, reconciliation, recovery, concurrency, and result-view tests.

## Validation performed here

- `python -m compileall` for all changed Python modules: passed.
- Patch generation against a normalized copy of the uploaded `core.zip`: completed.
- The uploaded archive contains no `.git`, so the supplied Git baseline commit `ad7f0ba084ad7374c98c3dd2fc7afbf72884ee09` and local worktree status could not be verified.
- Django system checks, migration checks, pytest, and PostgreSQL concurrency tests were not run in this environment. Do not treat this patch as production-validated until those commands pass on the actual repository/database.
