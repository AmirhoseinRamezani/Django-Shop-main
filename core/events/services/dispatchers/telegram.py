# events/services/dispatchers/telegram.py

def send_telegram_event(event):
    topic = event.topic
    payload = event.payload

    if topic == "product.published":
        _send_product(payload)

    elif topic == "order.paid":
        _send_order_paid(payload)


def _send_product(payload):
    message = (
        f"🛒 {payload['name']}\n"
        f"{payload.get('price', '')}\n\n"
        f"{payload.get('caption', '')}\n"
        f"🔗 {payload['url']}"
    )

    # call telegram bot client here
    # telegram_client.send_photo(...)


def _send_order_paid(payload):
    """
    Send Telegram notification.
    Real implementation later.
    """
    message = (
        f"✅ سفارش جدید ثبت شد\n"
        f"شماره سفارش: {payload['order_id']}\n"
        f"مبلغ: {payload['amount']}"
    )

    # telegram_client.send_message(...)

