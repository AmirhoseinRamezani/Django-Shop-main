# Transactional Outbox Contract

## Delivery semantics

- Delivery is **at least once**, never exactly once.
- A worker may complete an external side effect and crash before acknowledging it.
  The event can then be delivered again.
- Every consumer must deduplicate using the stable `event_id` value. For HTTP
  consumers, the webhook transport sends it as `Idempotency-Key`.
- Do not place irreversible external I/O inside a database transaction.

## Claim and recovery

- Workers claim rows in a short transaction using `SELECT ... FOR UPDATE SKIP LOCKED`
  on PostgreSQL.
- The claim token fences stale workers: only the worker holding the current token
  can acknowledge or release a claim.
- A `processing` row whose lease expires becomes eligible for reclamation.
- Failed attempts use bounded exponential backoff and eventually move to `failed`.
- The current registry activates email and HTTP webhook delivery. Telegram is
  intentionally not registered while its client remains a stub; it must not
  report success without sending a message.
- The default lease is 300 seconds. Keep handler timeouts materially below the
  lease duration. If a handler can legitimately run longer, add lease renewal
  before increasing the lease globally.

## Topic policy

- `ROUTES` contains topics with configured delivery handlers.
- `NOOP_TOPICS` contains intentionally persisted domain events with no outbound
  notification subscription in this deployment.
- A topic in neither collection is a configuration error and is retried; it is
  never silently acknowledged.
- When adding an `OrderEventType`, add its topic mapping and explicitly classify
  the resulting topic in `ROUTES` or `NOOP_TOPICS`.

## Adding a handler

1. Implement a transport that raises on every unsuccessful delivery.
2. Ensure the receiver supports idempotency using `event_id`; otherwise document
   the duplicate-side-effect risk.
3. Register the handler under a stable topic.
4. Add route-contract and failure/retry tests.
5. Keep network calls outside database transactions.

## Operations

Run `python manage.py process_outbox --batch-size 50 --max-retry 5 --lease-seconds 300`.
Monitor pending age, failed count, retry count, and expired processing claims.
Failed events require an explicit operator/reconciliation policy; do not blindly
reset them without checking whether the external side effect already happened.
