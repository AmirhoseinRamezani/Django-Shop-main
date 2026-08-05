<!-- Test execution policy prompt AI -->
# Django Testing Architecture Policy

## Development Policy

This project is **Session-First**, not API-First.

Follow these principles strictly:

* Prefer Django Templates, Class-Based Views, Forms and Session Authentication.
* Use Django REST Framework only when external integrations require it (Mobile App, Public API, Telegram Bot, n8n, third-party services).
* Prefer Django built-in capabilities over custom abstractions.
* Follow KISS, DRY and SRP.
* Avoid over-engineering and premature optimization.
* Every layer must have a clear responsibility.
* Every solution must remain understandable by a single developer after several months.
* Before introducing a new pattern, explain why it is necessary and which problem it solves.
* Prioritize maintainability, readability and long-term scalability over clever implementations.

---

# Testing Architecture Policy

You are the Lead Test Architect for this project.

Your responsibility is to build a scalable testing architecture that will remain maintainable as the project grows.

Always think in terms of business behavior instead of implementation details.

---

# Testing Pyramid

Prefer tests in this order:

1. Model Tests
2. Policy Tests
3. Service Tests
4. View Tests
5. Integration Tests
6. End-to-End Tests (only when necessary)

Never test the same business rule in multiple layers unless it provides additional value.

---

# Fixture Classification

Before creating any fixture, classify it first.

There are only two categories.

## 1. Shared Data

Shared data contains reusable objects that have no business meaning.

Examples:

* User
* Admin User
* Category
* Product
* Coupon
* Address

Shared data must never:

* execute services
* execute workflows
* change state
* create completed scenarios

Location:

tests/
fixtures/

---

## 2. Domain Scenario

Domain fixtures represent business situations.

Examples:

* pending_order
* paid_order
* refunded_order
* expired_order
* pending_payment
* successful_payment
* failed_payment
* cart_with_items
* order_with_coupon

These fixtures belong only to their own application.

Location:

app/tests/conftest.py

---

Always explain why a fixture belongs to one category before generating code.

---

# Factory Architecture

Every reusable object must be created by FactoryBoy.

Never create reusable ORM objects directly inside fixtures.

Architecture:

Factory
↓
UserFactory
↓
Fixture
↓
user
↓
Test

Factories generate data.

Fixtures compose scenarios.

Tests verify behavior.

---

# Fixture Rules

General fixtures:

* small
* reusable
* deterministic
* independent

Domain fixtures may:

* compose multiple factories
* represent business scenarios

General fixtures must never:

* call services
* call state machines
* create payments
* complete orders
* verify OTP
* consume coupons

Those belong to domain fixtures.

---

# Test Rules

Every test should verify exactly one business behavior.

Prefer descriptive names.

Example:

test_user_can_start_payment()

instead of

test_payment()

Arrange
Act
Assert sections should be clearly separated.

Avoid unnecessary mocking.

Mock only external systems:

* Payment Gateway
* Email
* SMS
* Redis
* Celery
* Third-party APIs

Do not mock your own services unless isolation is required.

---

# Assertions

Always assert observable business outcomes.

Good examples:

* database state
* returned value
* emitted event
* created outbox message
* stock updated
* coupon consumed

Avoid asserting internal implementation details.

---

# Directory Structure

tests/
factories/
accounts.py
shop.py
order.py
payment.py

```
fixtures/
    users.py
    shop.py
    cart.py
```

accounts/
tests/
conftest.py
test_models.py
test_services.py
test_views.py

order/
tests/
conftest.py
test_models.py
test_policy.py
test_services.py
test_state_machine.py

payment/
tests/
conftest.py
test_models.py
test_policy.py
test_services.py
test_gateway.py

---

# Long-Term Principles

Business logic belongs inside:

* Models
* Policies
* Services
* State Machines

Fixtures only prepare data.

Factories only build objects.

Tests only verify business behavior.

Never move business logic into fixtures.

Never hide business behavior inside factories.

Never introduce abstractions unless they clearly reduce duplication while improving readability.

Keep the testing architecture simple, explicit and easy to extend.

# ===================================
Chapter 2

My goal is for the test infrastructure to have these features:

Single source of truth
Completely lazy Builders
Factories are just model constructors
Scenarios are composable
Zero duplicate code
Fluent API
Scalable to thousands of tests

tests/

    base.py

    assertions.py

    helpers/

    fixtures/

    factories/

        accounts.py
        shop.py
        cart.py
        order.py
        payment.py
        events.py

    builders/

        base.py

        checkout_builder.py

        order_builder.py

        payment_builder.py

        cart_builder.py

        outbox_builder.py

        event_builder.py

    scenarios/

        checkout.py

        payment.py

        order.py

        events.py
