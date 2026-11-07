# Refund Recovery Runbook (V1)

## Automated recovery

Run one bounded batch:

```bash
docker compose exec backend python manage.py recover_pending_refunds
```

Tune the batch and stale threshold explicitly when required:

```bash
docker compose exec backend python manage.py recover_pending_refunds \
  --batch-size 100 \
  --older-than-minutes 30
```

The command performs provider **inquiry only**. It never invokes the Refund
execution endpoint. A `PENDING` result, timeout, unknown result, invalid
identity, or financial mismatch does not release the refund reservation and
does not produce a terminal state.

The default stale policy is `requested_at` older than 30 minutes. Each command
invocation examines at most one batch (maximum 1,000 records). Run it again for
subsequent batches. PostgreSQL `SKIP LOCKED` distributes candidate selection;
a per-Refund PostgreSQL session advisory lock prevents concurrent workers from
inquiring the same Refund. No row lock or transaction is held during provider
HTTP communication.

## Provider limitation: ZarinPal

The current ZarinPal adapter explicitly declares both `refund=False` and
`refund_inquiry=False`. The application must not infer either capability.
Pending refunds associated with this provider remain unresolved and the
command reports them as `unsupported` with a non-zero exit status.

## Manual reconciliation

For an unsupported provider:

1. Keep the Refund in `PENDING`; its amount continues to reserve refundable
   capacity.
2. Identify the Refund, Payment, amount, currency, request timestamp, and
   provider reference from the application records.
3. Reconcile against authoritative provider/merchant-portal records and, when
   necessary, obtain written confirmation from the provider.
4. Preserve the external evidence and escalation/audit trail.
5. Do not retry the Refund execution endpoint, release the reservation, update
   financial rows directly, or mark the Refund terminal through an ad hoc
   script.

Refund V1 does not currently provide a generic operator evidence-ingestion
workflow for providers without Refund Inquiry. Therefore manual review can
establish the external facts, but local financial finalization remains blocked
until an approved evidence-ingestion path is implemented. This limitation is
intentional; it is safer than fabricating provider capability or financial
success.
