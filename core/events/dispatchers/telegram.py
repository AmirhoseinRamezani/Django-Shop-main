from events.clients.telegram import TelegramClient


def send_telegram_event(event):

    handlers = {
        "product.published": send_product,
        "order.paid": send_order_paid,
    }

    handler = handlers.get(event.topic)

    if handler:
        handler(event.payload)


def send_product(payload):

    TelegramClient.send_photo(
        photo=payload["url"],
        caption=payload.get("caption", ""),
    )


def send_order_paid(payload):

    TelegramClient.send_message(

        f"Order #{payload['order_id']} paid."
    )