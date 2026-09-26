from types import SimpleNamespace
import pytest
from django.urls import reverse

from order.admin import OrderAdmin
from payment.services.refund import RefundService


@pytest.mark.django_db
def test_order_admin_refund_view_requires_staff(client, user, paid_order, consumed_payment):
    client.force_login(user)

    url = reverse(
        "admin:order_ordermodel_refund",
        args=[paid_order.pk],
    )

    response = client.get(url)

    assert response.status_code == 302
    assert "/admin/login/" in response.url


@pytest.mark.django_db
def test_order_admin_refund_view_confirms_and_delegates_to_service(
    client,
    paid_order,
    consumed_payment,
    mocker,
):
    client.force_login(admin_user)

    url = reverse(
        "admin:order_ordermodel_refund",
        args=[paid_order.pk],
    )

    response = client.get(url)

    assert response.status_code == 200
    assert "name=\"idempotency_key\"" in response.content.decode()
    assert "Confirm Order Refund" in response.content.decode()

    refund = SimpleNamespace(
        pk=123,
        is_success=False,
        get_status_display=lambda: "Pending",
    )
    service = mocker.patch.object(
        RefundService,
        "refund_order",
        return_value=refund,
    )

    response = client.post(
        url,
        {"idempotency_key": "admin-test-key"},
    )

    assert response.status_code == 302
    assert response.url == reverse("admin:order_ordermodel_changelist")
    service.assert_called_once_with(
        order_id=paid_order.pk,
        payment_id=consumed_payment.pk,
        actor=admin_user,
        idempotency_key="admin-test-key",
    )


@pytest.mark.django_db
def test_order_admin_refund_link_is_only_exposed_for_refundable_orders(
    admin_user,
    paid_order,
    consumed_payment,
    returned_order,
):
    admin_obj = OrderAdmin(paid_order.__class__, None)

    assert "Refund" in str(admin_obj.refund_action(paid_order))
    assert admin_obj.refund_action(returned_order) == "-"
