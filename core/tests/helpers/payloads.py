def otp_payload():

    return {
        "email": "user@test.com",
        "code": "123456",
    }


def order_paid_payload(order):

    return {
        "order_id": order.id,
        "email": order.email,
        "amount": str(order.get_price()),
    }


def coupon_payload(coupon):

    return {
        "code": coupon.code,
        "discount": coupon.discount_percent,
    }


def product_payload(product):

    return {
        "name": product.title,
        "price": str(product.final_price),
        "url": "https://example.com",
    }