# tests/factories/payment.py
import factory

from tests.base import BaseFactory

from payment.models import (
    PaymentModel,
)
from payment.enums import (
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

    status = PaymentStatusType.PENDING
    
    response_json = factory.LazyFunction(dict)

    is_consumed = False

    class Params:

        success = factory.Trait(
            status=PaymentStatusType.SUCCESS,
            ref_id=factory.Sequence(
                lambda n: 100000 + n
            ),
        )

        failed = factory.Trait(
            status=PaymentStatusType.FAILED,
        )

        pending = factory.Trait(
            status=PaymentStatusType.PENDING,
        )
            
        consumed = factory.Trait(
            status=PaymentStatusType.SUCCESS,
            is_consumed=True,
            ref_id=factory.Sequence(
                lambda n: 100000 + n
            ),
        )

# PaymentFactory