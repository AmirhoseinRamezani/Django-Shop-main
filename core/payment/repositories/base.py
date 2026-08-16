# core/payment/repositories/base.py

from __future__ import annotations

from typing import Any, ClassVar, Generic, TypeVar

from django.db import models
from django.db.models import QuerySet

ModelT = TypeVar("ModelT", bound=models.Model)

class BaseRepository(Generic[ModelT]):
    """
    Minimal persistence base for Django repositories.

    Responsibilities
    ----------------
    - expose the repository model
    - provide a base QuerySet
    - provide basic retrieval
    - provide basic creation
    - provide row-level locking
    - provide persistence

    Non-responsibilities
    --------------------
    - transaction boundaries
    - business rules
    - state transitions
    - gateway communication
    - idempotency policy
    - concurrency policy
    - domain orchestration

    Transaction ownership belongs to the application/service layer.
    """

    model: ClassVar[type[ModelT]]

    @classmethod
    def queryset(cls) -> QuerySet[ModelT]:
        """
        Return the repository's base lazy QuerySet.

        No filtering or locking is applied here.

        The returned QuerySet remains lazy and can be further composed
        by concrete repositories.
        """
        return cls.model.objects.all()

    @classmethod
    def get(
        cls,
        pk: Any,
    ) -> ModelT:
        """
        Retrieve one model instance by primary key.

        Raises:
            cls.model.DoesNotExist:
                If no matching instance exists.
        """
        return cls.queryset().get(pk=pk)

    @classmethod
    def create(
        cls,
        **kwargs: Any,
    ) -> ModelT:
        """
        Create and persist one model instance.

        Business validation and transaction ownership belong to the
        calling application/service layer.

        Database constraints remain authoritative.
        """
        return cls.model.objects.create(**kwargs)

    @classmethod
    def lock(
        cls,
        pk: Any,
    ) -> ModelT:
        """
        Retrieve and lock one model row using SELECT ... FOR UPDATE.
        This method does not create a transaction boundary.
        The caller must execute it inside an active database transaction
        when using a database/backend that requires one for row locking.
        """
        return (
            cls.queryset()
            .select_for_update()
            .get(pk=pk)
        )

    @classmethod
    def save(
        cls,
        instance: ModelT,
        update_fields: list[str] | tuple[str, ...] | None = None,
    ) -> ModelT:
        """
        Persist an existing model instance.
        This is intentionally a thin persistence primitive.
        Concrete repositories may override this method when they need
        additional persistence semantics such as optimistic concurrency.
        No transaction boundary is created here.
        """
        instance.save(
            update_fields=update_fields,
        )

        return instance