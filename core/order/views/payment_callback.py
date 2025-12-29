# order/views/payment_callback.py

from django.http import HttpResponse
from order.services.confirm_payment import confirm_order_payment


def payment_callback_view(request):
    order_id = request.GET.get("order_id")

    # اینجا verify پرداخت انجام می‌شود…

    confirm_order_payment(order_id)

    return HttpResponse("OK")
