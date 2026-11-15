import pytest
from django.core.exceptions import PermissionDenied

from order.services.inventory import InventoryService
from order.models import OrderModel


@pytest.mark.django_db
class TestInventoryConsumeAuthorization:
    def test_consume_rejects_calls_without_canonical_capability(self):
        with pytest.raises(PermissionDenied):
            InventoryService.consume(order=OrderModel(pk=1))