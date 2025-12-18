from django.core.management.base import BaseCommand
from django.db import transaction
from faker import Faker
from django.utils.text import slugify
from shop.models import ProductCategoryModel


class Command(BaseCommand):
    help = "Generate fake categories"

    @transaction.atomic
    def handle(self, *args, **kwargs):
        fake = Faker("fa_IR")
        for _ in range(10):
            title = fake.word()
            ProductCategoryModel.objects.get_or_create(
                slug=slugify(title, allow_unicode=True),
                defaults={"title": title},
            )
        self.stdout.write(self.style.SUCCESS("Categories generated"))
