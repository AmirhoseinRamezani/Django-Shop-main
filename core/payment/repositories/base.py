# core/payment/repositories/base.py

from __future__ import annotations

from typing import Any, ClassVar, Generic, TypeVar

from django.db import models


ModelT = TypeVar(
    "ModelT",
    bound=models.Model,
)


class BaseRepository(
    Generic[ModelT],
):
    """
    Minimal ORM repository foundation.

    Responsibilities
    ----------------
    This class provides only low-level ORM primitives that are safe to
    reuse across payment repositories.

    It intentionally does not own:

        - transaction boundaries
        - domain policies
        - business validation
        - state transitions
        - authorization
        - idempotency rules
        - provider/gateway logic

    Concrete repositories remain responsible for domain-specific queries.

    Locking
    -------
    ``lock()`` uses ``select_for_update()`` but does not create a
    transaction. The caller is responsible for executing it inside an
    appropriate transaction.atomic() boundary.
    """

    model: ClassVar[type[ModelT]]

    # ============================
    # QUERYSET
    # ============================

    @classmethod
    def queryset(cls):
        """
        Return the base queryset for the repository model.
        """

        return cls.model.objects.all()

    # ============================
    # READ
    # ============================

    @classmethod
    def get(
        cls,
        pk: Any,
    ) -> ModelT:
        """
        Return one model instance by primary key.

        Django's DoesNotExist exception is intentionally preserved.

        Domain-specific repositories may translate that exception when
        their application contract requires a different error type.
        """

        return cls.queryset().get(
            pk=pk,
        )

    # ============================
    # CREATE
    # ============================

    @classmethod
    def create(
        cls,
        **kwargs: Any,
    ) -> ModelT:
        """
        Create and return one model instance.

        Database constraints remain authoritative.
        """

        return cls.model.objects.create(
            **kwargs,
        )

    # ============================
    # LOCK
    # ============================

    @classmethod
    def lock(
        cls,
        pk: Any,
    ) -> ModelT:
        """
        Lock one model row for update.

        IMPORTANT:

        This method does not create a transaction.

        The caller MUST execute this operation inside
        ``transaction.atomic()`` when row-level locking is required.

        The lock remains useful only for the lifetime of the surrounding
        database transaction.
        """

        return (
            cls.model.objects
            .select_for_update()
            .get(
                pk=pk,
            )
        )

    # ============================
    # SAVE
    # ============================

    @classmethod
    def save(
        cls,
        instance: ModelT,
        *,
        update_fields: tuple[str, ...] | list[str] | None = None,
    ) -> ModelT:
        """
        Persist an existing model instance.
        ``update_fields`` is forwarded directly to Django's model.save().

        Concrete repositories should prefer explicit update_fields for
        financial state transitions so unrelated model fields cannot be
        accidentally overwritten.
        """

        instance.save(
            update_fields=update_fields,
        )

        return instance