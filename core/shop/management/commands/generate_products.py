import random
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from django.core.files import File

from faker import Faker

from shop.models import ProductModel, ProductCategoryModel
from shop.constants import ProductStatusType
from accounts.models import User, UserType


BASE_DIR = Path(__file__).resolve().parent


class Command(BaseCommand):
    help = "Generate fake products"

    @transaction.atomic
    def handle(self, *args, **options):
        fake = Faker("fa_IR")

        user = User.objects.filter(type=UserType.admin.value).first()
        if not user:
            self.stdout.write(self.style.ERROR("Admin user not found"))
            return

        categories = list(ProductCategoryModel.objects.all())
        if not categories:
            self.stdout.write(self.style.ERROR("No categories found"))
            return

        image_list = [
            "images/img1.jpg",
            "images/img2.jpg",
            "images/img3.jpg",
            "images/img4.jpg",
            "images/img5.jpg",
            "images/img6.jpg",
            "images/img7.jpg",
            "images/img8.jpg",
        ]

        for _ in range(10):
            title = " ".join(fake.words(2))
            base_slug = slugify(title, allow_unicode=True)
            slug = base_slug

            counter = 1
            while ProductModel.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            selected_categories = random.sample(
                categories,
                random.randint(1, min(4, len(categories)))
            )

            image_path = BASE_DIR / random.choice(image_list)

            with open(image_path, "rb") as img:
                product = ProductModel.objects.create(
                    user=user,
                    title=title,
                    slug=slug,
                    image=File(img, name=image_path.name),
                    description=fake.paragraph(nb_sentences=10),
                    brief_description=fake.paragraph(nb_sentences=1),
                    stock=fake.random_int(0, 10),
                    status=ProductStatusType.PUBLISH,
                    price=fake.random_int(10_000, 100_000),
                    discount_percent=fake.random_int(0, 50),
                )

            product.category.set(selected_categories)

        self.stdout.write(self.style.SUCCESS("Fake products generated successfully"))
