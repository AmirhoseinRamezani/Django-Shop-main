# tests/factories/common.py
import factory
from django.utils.text import slugify


class FakerMixin:

    title = factory.Faker("sentence", nb_words=3)

    description = factory.Faker("paragraph")

    brief_description = factory.Faker("sentence")

    slug = factory.LazyAttribute(
        lambda o: slugify(o.title)
    )


class TimestampMixin:

    class Meta:
        abstract = True