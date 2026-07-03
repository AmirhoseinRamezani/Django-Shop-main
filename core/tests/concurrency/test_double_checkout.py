# tests/concurrency/test_double_checkout.py
import pytest

from tests.concurrency.base import (
    ConcurrentRunner,
)

from order.services.order import (
    OrderService,
)


pytestmark = pytest.mark.django_db(
    transaction=True,
)


def test_checkout_twice(
    order_builder,
):

    scenario = order_builder.build()

    runner = ConcurrentRunner()

    runner.run(

        lambda: OrderService.create_online_order(
            **scenario,
        ),

        lambda: OrderService.create_online_order(
            **scenario,
        ),
    )
