# tests/builders/accounts_builder.py
"""
Account scenario builders.

This module composes existing account factories into meaningful
authentication/account scenarios.

It does not implement authentication business logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from accounts.models import (
    DeviceSession,
    Profile,
    RefreshToken,
    User,
)

from tests.builders.base import BaseBuilder
from tests.factories.accounts import (
    DeviceSessionFactory,
    ProfileFactory,
    RefreshTokenFactory,
    UserFactory,
)


@dataclass(frozen=True)
class AccountScenario:
    """
    Result of an account scenario.

    Concrete domain objects are exposed explicitly so tests can
    assert against actual persisted model state.
    """

    user: User
    profile: Optional[Profile] = None
    sessions: tuple[DeviceSession, ...] = ()
    tokens: tuple[RefreshToken, ...] = ()


class AccountScenarioBuilder(BaseBuilder[AccountScenario]):
    """
    Builder for common account/authentication test scenarios.
    """

    __slots__ = (
        "_user",
        "_admin",
        "_superuser",
        "_unverified",
        "_create_session",
        "_create_token",
    )

    def __init__(self) -> None:
        super().__init__()

        self._user: Optional[User] = None
        self._admin = False
        self._superuser = False
        self._unverified = False
        self._create_session = False
        self._create_token = False

    def with_user(self, user: User) -> AccountScenarioBuilder:
        """
        Use an externally-created user.

        The supplied user is reused exactly as provided.
        """
        self._user = user
        return self

    def as_admin(self) -> AccountScenarioBuilder:
        """Create an administrative user."""
        self._admin = True
        return self

    def as_superuser(self) -> AccountScenarioBuilder:
        """Create a superuser."""
        self._superuser = True
        return self

    def unverified(self) -> AccountScenarioBuilder:
        """Create an unverified user."""
        self._unverified = True
        return self

    def with_device_session(self) -> AccountScenarioBuilder:
        """Create one device session for the user."""
        self._create_session = True
        return self

    def with_refresh_token(self) -> AccountScenarioBuilder:
        """
        Create one device session and one refresh token bound to it.
        """
        self._create_session = True
        self._create_token = True
        return self

    def build(self) -> AccountScenario:
        self._mark_built()

        user = self._build_user()
        profile = self._build_profile(user)

        sessions: list[DeviceSession] = []
        tokens: list[RefreshToken] = []

        if self._create_session:
            session = DeviceSessionFactory.create(user=user)
            sessions.append(session)

            if self._create_token:
                token = RefreshTokenFactory.create(
                    user=user,
                    session=session,
                )
                tokens.append(token)

        return AccountScenario(
            user=user,
            profile=profile,
            sessions=tuple(sessions),
            tokens=tuple(tokens),
        )

    def _build_user(self) -> User:
        if self._user is not None:
            return self._user

        kwargs: dict[str, object] = {}

        if self._admin:
            kwargs["admin"] = True

        if self._superuser:
            kwargs["superuser"] = True

        if self._unverified:
            kwargs["unverified"] = True

        return UserFactory.create(**kwargs)

    @staticmethod
    def _build_profile(user: User) -> Optional[Profile]:
        """
        Reuse an existing profile when the supplied user already owns one.

        This is important because UserFactory already creates the profile
        in the finalized factory layer.
        """
        profile = getattr(user, "profile", None)

        if profile is not None:
            return profile

        return ProfileFactory.create(user=user)