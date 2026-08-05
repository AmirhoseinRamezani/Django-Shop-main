# tests/factories/payment.py
import factory

from tests.base import BaseFactory

from payment.models import (
    PaymentModel,
    PaymentStatusType,
)

from tests.factories.order import OrderFactory


class PaymentFactory(BaseFactory):

    class Meta:
        model = PaymentModel

    order = factory.SubFactory(OrderFactory)

    authority_id = factory.Sequence(
        lambda n: f"AUTH-{n}"
    )

    ref_id = factory.Sequence(
        lambda n: 100000 + n
    )

    amount = factory.SelfAttribute(
        "order.total_price"
    )

    status = PaymentStatusType.pending
    
    response_json = factory.LazyFunction(dict)

    is_consumed = False

    class Params:

        success = factory.Trait(
            status=PaymentStatusType.success,
            ref_id=factory.Sequence(
                lambda n: 100000 + n
            ),
        )

        failed = factory.Trait(
            status=PaymentStatusType.failed,
        )

        pending = factory.Trait(
            status=PaymentStatusType.pending,
        )
            
        consumed = factory.Trait(
            status=PaymentStatusType.success,
            is_consumed=True,
            ref_id=factory.Sequence(
                lambda n: 100000 + n
            ),
        )

# PaymentFactory