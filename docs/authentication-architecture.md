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