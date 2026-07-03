# shop/constants.py
from django.db import models
from django.utils.translation import gettext_lazy as _


class ProductStatusType(models.IntegerChoices):
    PUBLISH = 1,_("Show")
    DRAFT = 2,_("Don't show")

class SiteSaleType(models.TextChoices):
    ONLINE = "ONLINE", _("Online")
    OFFLINE = "OFFLINE", _("Offline")