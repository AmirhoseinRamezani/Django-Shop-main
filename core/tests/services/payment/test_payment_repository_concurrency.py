# test_payment_repository_concurrency.py
import pytest

from payment.exceptions import (
    PaymentConcurrencyError,
)
from payment.repositories.payment_repository import (
    PaymentRepository,
)


@pytest.mark.django_db
class TestPaymentOptimisticConcurrency:

    def test_stale_payment_cannot_overwrite_newer_payment(
        self,
        payment,
    ):
        """
        Two application objects represent the same Payment.

        First object commits version N -> N+1.

        Second stale object still contains version N.

        Its update must fail.
        """

        first = PaymentRepository.model.objects.get(
            pk=payment.pk,
        )

        second = PaymentRepository.model.objects.get(
            pk=payment.pk,
        )

        assert first.version == second.version

        first.succeed()

        PaymentRepository.save(
            first,
            update_fields=[
                "status",
            ],
        )

        second.fail()

        with pytest.raises(
            PaymentConcurrencyError,
        ):
            PaymentRepository.save(
                second,
                update_fields=[
                    "status",
                ],
            )