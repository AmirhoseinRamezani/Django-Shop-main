from django.db import models


class ProductStatusType(models.IntegerChoices):
    PUBLISH = 1, "نمایش"
    DRAFT = 2, "عدم نمایش"
