from order.models import OrderStatusType
from order.services.confirm_payment import confirm_order_payment


def test_confirm_order_payment_success(
    pending_order,
    successful_payment
):
    order = confirm_order_payment(pending_order.id)

    order.refresh_from_db()
    successful_payment.refresh_from_db()

    assert order.status == OrderStatusType.success
    assert successful_payment.is_consumed is True
