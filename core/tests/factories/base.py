# tests/factories/base.py
import factory

from factory.django import DjangoModelFactory


class BaseFactory(DjangoModelFactory):

    class Meta:
        abstract = True