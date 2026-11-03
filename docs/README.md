# 🛍️ Django Shop — Always-On Sale Platform

> A store that is **permanently on sale**.

Django Shop is a production-oriented e-commerce platform built around continuous sales, flash campaigns, gamified coupons, and always-on discounts. The entire stack — cart, order, payment, refund — is designed to stay **correct, consistent, and auditable** under campaign-level concurrency.

![Python](https://img.shields.io/badge/python-3.13-blue)
![Django](https://img.shields.io/badge/django-5.2.7-092E20)
![PostgreSQL](https://img.shields.io/badge/postgresql-15-336791)
![Docker](https://img.shields.io/badge/docker-compose-2496ED)
![License](https://img.shields.io/badge/license-MIT-green)
![Architecture](https://img.shields.io/badge/architecture-DDD%20%2B%20Clean-orange)

---

## 📑 Table of Contents

1. [Why This Project Exists](#-why-this-project-exists)
2. [Core Product Idea](#-core-product-idea)
3. [Tech Stack](#-tech-stack)
4. [High-Level Architecture](#-high-level-architecture)
5. [Payment Domain](#-payment-domain)
6. [Payment Resolution](#-payment-resolution-recovery-layer)
7. [Authentication & JWT](#-authentication--jwt)
8. [Project Structure](#-project-structure)
9. [Getting Started](#-getting-started)
10. [Testing](#-testing)
11. [Roadmap](#-roadmap)
12. [Contributing](#-contributing)
13. [License](#-license)

---

## 🎯 Why This Project Exists

Most e-commerce tutorials teach you how to build a cart. This project is about what happens **after** the cart works:

- What if two users buy the last item at the same millisecond?
- What if a coupon is redeemed twice because the network retried?
- What if the payment gateway responds, but the callback never arrives?
- What if the payment succeeded but the order got stuck in a conflicting state?
- What if a refund is retried and you must not refund twice?

This repository answers those questions with **explicit domain models, state machines, idempotency, optimistic locking, and reconciliation** — not with hope.

---

## 💡 Core Product Idea

The platform is designed around a **permanently-on-sale** shopping experience:

| Concept | Description |
|---|---|
| **Continuous Sales** | Products live inside long-running sale windows, not one-off events. |
| **Flash Campaigns** | Time-boxed campaigns with high-concurrency pressure. |
| **Coupons & Puzzles** | Discounts gated behind codes, quizzes, or gamified challenges. |
| **Always-On Discounts** | The default pricing model expects discounts, not exceptions. |
| **Fair Play** | Inventory reservation, idempotency, and throttling protect the shop from abuse during campaigns. |

The technical architecture follows the product: the domain must remain correct under marketing pressure.

---

## 🧱 Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13.7 |
| Framework | Django 5.2.7 |
| API Layer | Django REST Framework (external integrations only) |
| Auth | JWT (access + refresh) with OTP login |
| Database | PostgreSQL 15 (Alpine) |
| Cache / Throttle | Redis (optional / planned) |
| Containerization | Docker & Docker Compose |
| Mail Testing | SMTP4Dev v3 |
| Testing | Pytest + FactoryBoy |
| Architecture | DDD + Clean Architecture (pragmatic) |

> **Policy:** Session-First, not API-First. Django templates, CBVs, forms, and session auth are preferred. DRF is used only when a real external consumer exists (mobile app, public API, bot, n8n).

---

## 🏛️ High-Level Architecture
┌─────────────────────────────────────────────────────────────┐
│ Presentation │
│ Django Views (Session) │ DRF Endpoints (External) │
└────────────────────────────┼────────────────────────────────┘
│
┌────────────────────────────▼────────────────────────────────┐
│ Application Layer │
│ OrderService │ PaymentService │ RefundService │
│ CheckoutService│ ResolutionService │
└────────────────────────────┼────────────────────────────────┘
│
┌────────────────────────────▼────────────────────────────────┐
│ Domain Layer │
│ Order │ Payment (Aggregate Root) │ Refund │ Policy │
│ State Machines │ Invariants │ Domain Guards │
└────────────────────────────┼────────────────────────────────┘
│
┌────────────────────────────▼────────────────────────────────┐
│ Infrastructure Layer │
│ Repositories (Optimistic Lock) │ Gateways │ Outbox │
│ PostgreSQL │ Redis │ SMTP │ Provider Adapters │
└─────────────────────────────────────────────────────────────┘
---

## 💳 Payment Domain

`Payment` is a **pure Aggregate Root**. It owns the financial intent of an order and nothing else.
Order
│
└── 1:N ── Payment (Aggregate Root / Concurrency Boundary)
│
├── 1:N ── PaymentAttempt (gateway execution)
├── 0:N ── Refund (money return)
└── 0:N ── GatewayLog (immutable audit trail)
### Responsibilities

- Own the payment lifecycle and state transitions.
- Protect financial invariants (amount, currency, consumption, refundability).
- Coordinate `PaymentAttempt` and `Refund` ownership.
- Never store gateway execution state directly.

### Explicit Delegation

| Concern | Delegated To |
|---|---|
| Gateway execution | `PaymentAttempt` |
| Gateway communication | `GatewayLog` |
| Refund execution | `Refund` |
| Persistence | `PaymentRepository` |
| Retry decisions | `RetryPolicy` |
| Use-case orchestration | `PaymentService` |

### State API

```text
Payment
├── State API         state, is_pending, is_successful, is_failed,
│                     is_terminal, is_state(), in_state()
├── Capability API    can_succeed, can_fail, can_consume, can_refund
├── Commands          succeed(), fail(), consume(), refund()
├── Guards            _require(), _require_state(),
│                     require_pending(), require_success(),
│                     require_refundable(), ...
├── Internal          _transition_to()
├── Validation        clean()
└── Representation    __str__(), __repr__()