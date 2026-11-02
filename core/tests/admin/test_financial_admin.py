# core\tests\admin\test_financial_admin.py
import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import AnonymousUser

from order.admin import OrderAdmin
from order.models import OrderModel
from shop.admin import ProductAdmin
from shop.models import ProductModel
from payment.admin import PaymentModelAdmin, PaymentAttemptAdmin, RefundAdmin
from payment.models import PaymentAttempt, PaymentModel, Refund


@pytest.mark.parametrize(
    "admin_class, model",
    [
        (PaymentModelAdmin, PaymentModel),
        (PaymentAttemptAdmin, PaymentAttempt),
        (RefundAdmin, Refund),
        (OrderAdmin, OrderModel),
    ],
)
def test_financial_admin_models_are_read_only(admin_class, model, rf):
    admin_obj = admin_class(model, AdminSite())
    request = rf.get("/admin/")

    assert admin_obj.has_add_permission(request) is False
    assert admin_obj.has_change_permission(request) is False
    assert admin_obj.has_delete_permission(request) is False

    readonly = set(admin_obj.get_readonly_fields(request))
    assert {field.name for field in model._meta.fields} <= readonly


def test_product_admin_cannot_edit_stock_fields(rf):
    admin_obj = ProductAdmin(ProductModel, AdminSite())
    request = rf.get("/admin/shop/productmodel/")
    request.user = AnonymousUser()

    readonly = set(admin_obj.get_readonly_fields(request))
    form = admin_obj.get_form(request)

    assert {"stock", "reserved_stock"} <= readonly
    assert "stock" not in form.base_fields
    assert "reserved_stock" not in form.base_fields
    assert admin_obj.get_actions(request) == {}