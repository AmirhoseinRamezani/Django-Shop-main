Authentication & JWT Flow Documentation
1. Authentication Architecture Overview

The project implements a stateless JWT-based authentication system with OTP-based login flow.

Components:

Custom JWT service (access + refresh)

RefreshToken model persistence

JWTAuthentication (DRF)

JWT Middleware (API-level fallback)

OTP verification flow

Throttling layer for abuse prevention

2. Token Strategy

We use:

Access Token (15 min)

Refresh Token (7 days)

Access tokens are:

Not stored in DB

Verified cryptographically

Refresh tokens:

Persisted in DB

Expirable

Revoked on logout

3. Security Decisions

Separate secret for access and refresh tokens

Token type validation enforced

Invalid signature / expired token → AuthenticationFailed

authenticate_header implemented to enforce 401 responses

API paths isolated from HTML error handlers

4. 401 vs 403 Behavior (Important)

DRF returns:

401 only if authentication class implements authenticate_header
403 when user is anonymous but no auth challenge is defined

We explicitly added:

def authenticate_header(self, request):
    return "Bearer"


to guarantee correct HTTP semantics.

5. Middleware Policy

JWTMiddleware is only used to attach user context for API requests.
All permission validation is handled by DRF authentication + permission classes.

Global Django error handlers must not override API responses.

6. Testing Coverage

Covered flows:

OTP request

OTP verify

JWT creation

Access authentication

Refresh misuse

Invalid token handling

Middleware validation

Payment flow

Throttling

Total: 31 automated tests (pytest)

7. Future Improvements

Planned:

Token rotation

Refresh reuse detection

Token blacklist

Role-based permission

Audit logging

======
payments core :

Financial Aggregate Root.

    Payment represents only the financial intent of an order.

    Responsibilities
    ----------------
    • Own the payment lifecycle.
    • Protect financial invariants.
    • Control aggregate state transitions.
    • Coordinate PaymentAttempt ownership.
    • Determine refund and consume eligibility.

    Gateway execution is intentionally delegated to
    PaymentAttempt.

    Gateway communication is intentionally delegated to
    GatewayLog.

    Refund execution is intentionally delegated to Refund.

    This aggregate never stores gateway execution state.

    Payment (Aggregate Root ~>Domain Entity)

            │
            ├───────────────┐
            │               │
            ▼               ▼

    PaymentAttempt      Refund

            │               │
            │               │
            └──────┬────────┘
                ▼

            GatewayLog

                │
                ▼

            OutboxEvent

Payment Responsibility
A payment should only answer these questions:

What is the status of this payment?
Did you succeed?
Has it been used?
Is it possible to refund?
Is it possible to repeat?
Is the Aggregate exhausted?
Is state transfer allowed?

            Payment (Aggregate Root)
            │
            ├── Financial State
            │      status
            │      amount
            │      currency
            │      gateway
            │      version
            │      is_consumed
            │      is_refunded
            │
            ├── PaymentAttempt (1..N)
            │      authority
            │      ref_id
            │      transaction_id
            │      gateway_reference
            │      latency
            │      payload
            │      response
            │      ...
            │
            ├── Refund (0..N)
            │      refund lifecycle
            │
            └── GatewayLog (0..N)
                immutable request/response


            Payment
                │
                ├──────── Refund #1
                │
                ├──────── Refund #2
                │
                └──────── Refund #3


            Refund
                ├── idempotency_key       Application identity
                ├── gateway_ref           Gateway refund identity
                ├── gateway_transaction_id Gateway transaction identity
                └── GatewayLog
                    ├── request_payload
                    ├── response_payload
                    ├── callback payload
                    └── webhook payload
            

                 Application Service
                         │
                         ▼
                 Payment Repository
                         │
                ┌────────┴────────┐
                │                 │
         Load Aggregate     Persist Aggregate
                │                 │
                ▼                 ▼
          PaymentModel       Optimistic Lock
                │
                ▼
          Domain Methods
                │
       ┌────────┼────────┐
       │        │        │
   Validate   Apply   Invariants

payment/
│
├── enums.py
├── managers.py
│
├── models/
│   ├── payment.py
│   ├── payment_attempt.py
│   ├── refund.py
│   └── gateway_log.py
│
├── repositories/
│   ├── payment.py
│   ├── payment_attempt.py
│   └── refund.py
│
├── policies/
│   └── retry.py          # Phase بعد
│
├── services/
│   ├── payment.py
│   ├── verification.py
│   └── refund.py
│
└── exceptions.py

And responsibilities:
PaymentModel
    = Domain Rules + State Transition

PaymentAttempt
    = Attempt State Transition

Refund
    = Refund State Transition

PaymentRepository
    = Persistence + Optimistic Lock

PaymentAttemptRepository
    = Persistence + Optimistic Lock

RefundRepository
    = Persistence + Optimistic Lock

RetryPolicy
    = Retry Decision

PaymentService
    = Use Case Orchestration

RefundService
    = Refund Orchestration + Concurrency

GatewayLog
    = Immutable Audit Trail


PaymentModel
│
├── Identity
├── Financial Fields
├── Audit Fields
├── Meta
│
├── State API
│     ├── state
│     ├── is_pending
│     ├── is_successful
│     ├── is_failed
│     ├── is_terminal
│     ├── is_state()
│     ├── in_state()
│
├── Capability API
│     ├── can_succeed
│     ├── can_fail
│     ├── can_consume
│     └── can_refund
│
├── Commands
│     ├── succeed()
│     ├── fail()
│     ├── consume()
│     └── refund()
│
├── Guards
│     ├── _require()
│     ├── _require_state()
│     ├── _require_not_state()
│     ├── require_pending()
│     ├── require_success()
│     ├── require_failed()
│     ├── require_consumed()
│     ├── require_not_consumed()
│     ├── require_not_refunded()
│     └── require_refundable()
│
├── Internal
│     └── _transition_to()
│
├── Validation
│     └── clean()
│
└── Representation
      ├── __str__()
      └── __repr__()

feat(paymentmodel): refactor payment aggregate root for enterprise architecture

- Refactor Payment into a pure Aggregate Root
- Remove persistence logic from domain commands
- Remove PaymentAttempt query responsibilities
- Eliminate save() side effects from domain methods
- Simplify aggregate state model
- Introduce explicit state transition API
- Add domain guard methods
- Centralize aggregate invariant validation
- Decouple domain from repository implementation
- Remove infrastructure concerns from entity
- Improve DDD and Clean Architecture compliance
- Prepare payment aggregate for repository pattern
- Prepare payment core for PaymentAttempt redesign

                     PAYMENT CORE
                          │
             ┌────────────┴────────────┐
             │                         │
             ▼                         ▼
       PaymentModel             PaymentAttempt
             │                         │
             │                         │
       State Machine             State Machine
             │                         │
             ▼                         ▼
       Financial                 Gateway Identity
       Invariants                Attempt Lifecycle
             │                         │
             └────────────┬────────────┘
                          │
                          ▼
                     Repository
                          │
              ┌───────────┴───────────┐
              │                       │
              ▼                       ▼
       Pessimistic Lock        Optimistic Version
       select_for_update       compare-and-swap
              │                       │
              └───────────┬───────────┘
                          ▼
                      PostgreSQL

            Gateway
            │
            ▼
            Gateway Adapter
            │
            ▼
            Application Service
            │
            ├── Policy
            ├── Payment
            ├── Attempt
            └── Repository

        
                     Payment Core
                          │
             ┌────────────┴────────────┐
             │                         │
        exceptions.py             policies.py
             │                         │
       Error Contract           Business Decisions
             │                         │
             └────────────┬────────────┘
                          │
                   Application
                     Services
                          │
              ┌───────────┼───────────┐
              │           │           │
          Repository   Gateway    Event Bus
              │           │           │
              ▼           ▼           ▼
           Database    External     Events


Refund V1:
Order
  │
  └── Payment  ← Aggregate Root / Concurrency Boundary
        │
        ├── PaymentAttempt
        │
        └── Refund
              │
              └── one refund lifecycle

Payment.amount
Payment.currency
Payment.gateway
Payment.status
        │
        └──── immutable financial/payment snapshot
                         │
                         ▼
                     Refund

    target architecture :
                            ┌────────────────────┐
                            │       Order        │
                            └─────────┬──────────┘
                                      │
                                      ▼
                            ┌────────────────────┐
                            │      Payment       │
                            │  Aggregate Root    │
                            │                    │
                            │ amount             │
                            │ currency           │
                            │ gateway            │
                            │ status             │
                            │ version            │
                            │ is_consumed        │
                            │ is_refunded        │
                            └──────┬───────┬─────┘
                                   │       │
                      ┌────────────┘       └────────────┐
                      ▼                                 ▼
              ┌────────────────┐                ┌────────────────┐
              │ PaymentAttempt │                │     Refund     │
              │                │                │                │
              │ gateway attempt│                │ amount         │
              │ status         │                │ currency       │
              │ authority      │                │ idempotency    │
              │ response       │                │ status         │
              │ latency        │                │ gateway IDs    │
              └────────────────┘                │ evidence       │
                                                └────────────────┘

                                Application Service
                                    │
                        ┌─────────────┼──────────────┐
                        ▼             ▼              ▼
                    Repository     Gateway          Outbox
                        │             │              │
                        ▼             ▼              ▼
                    Database      Provider       Events


                VERSION 1
            ────────────────────
            IRR
            Decimal
            Payment
            PaymentAttempt
            Refund
            Idempotency
            Concurrency
            Repository
            Gateway abstraction
            Transaction boundary
            Outbox
            Audit
            Tests
            ────────────────────
                    DONE

            &

                VERSION 2
            ────────────────────
            Money
            Fractional currencies
            Multi-currency
            FX
            Quote
            Crypto assets
            Blockchain networks
            Crypto gateway
            Exchange-rate snapshots
            ────────────────────
                    ↓
                EXTENSION