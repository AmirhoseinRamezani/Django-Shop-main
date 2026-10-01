# tests/factories/base.py
import factory
from factory.django import DjangoModelFactory

class BaseFactory(DjangoModelFactory):
    """
    Root factory for every domain factory.
    Provides common helpers and uniform factory behavior.

    UserFactory, ProductFactory, CouponFactory, OrderFactory, PaymentFactory, etc.
    all inherit from this class.
    """

    class Meta:
        abstract = True

    @classmethod
    def create_batch_for(cls, size, **kwargs):
        """Creates a batch of saved model instances."""
        return cls.create_batch(size=size, **kwargs)

    @classmethod
    def one(cls, **kwargs):
        """Convenience single instance builder (persisted)."""
        return cls.create(**kwargs)

    @classmethod
    def build_one(cls, **kwargs):
        """Convenience single instance builder (in-memory)."""
        return cls.build(**kwargs)
        