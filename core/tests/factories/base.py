# # tests/factories/base.py
# import factory

# from factory.django import DjangoModelFactory


# class BaseFactory(factory.django.DjangoModelFactory):

#     class Meta:
#         abstract = True
#         skip_postgeneration_save=True 

import factory

from tests.base import BaseFactory


class DomainFactory(BaseFactory):
    """
    Root factory for every domain factory.

    Provides common traits.

    UserFactory
    ProductFactory
    CouponFactory
    OrderFactory

    all inherit this class.
    """

    class Meta:
        abstract = True

    @classmethod
    def create_batch_for(cls, size, **kwargs):
        return cls.create_batch(size=size, **kwargs)

    @classmethod
    def one(cls, **kwargs):
        return cls.create(**kwargs)

    @classmethod
    def build_one(cls, **kwargs):
        return cls.build(**kwargs)
        
        
        