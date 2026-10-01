# core/tests/builders/base.py
"""
Base infrastructure for test scenario builders.

Builders are test-only composition tools built on top of Factory Boy.

Responsibilities:
    - hold builder state
    - enforce single-use construction
    - provide a small common contract

Builders must NOT:
    - contain production business logic
    - replace Factory Boy
    - manage transactions
    - access production services
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar


TScenario = TypeVar("TScenario")


class BaseBuilder(ABC, Generic[TScenario]):
    """
    Minimal base class for domain scenario builders.

    Lifecycle:
        configure
            ↓
        build()
            ↓
        scenario

    A builder instance is intentionally single-use.
    """

    __slots__ = ("_is_built",)

    def __init__(self) -> None:
        self._is_built = False

    def _mark_built(self) -> None:
        """
        Mark this builder as consumed.

        Builders are intentionally single-use so a partially configured
        builder cannot accidentally be reused for another scenario.
        """
        if self._is_built:
            raise RuntimeError(
                f"{self.__class__.__name__} instances are single-use. "
                "Create a new builder instance for another scenario."
            )

        self._is_built = True

    @property
    def is_built(self) -> bool:
        """Return whether this builder has already been built."""
        return self._is_built

    @abstractmethod
    def build(self) -> TScenario:
        """Construct and return the configured scenario."""
        raise NotImplementedError