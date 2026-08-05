# # payment/tests/test_verify_payment.py
# import pytest
# from payment.services.verify import verify_payment
# from payment.models import PaymentStatusType

# @pytest.mark.django_db
# def test_verify_payment_success(payment):
#     result = verify_payment(
#         authority=payment.authority_id,
#         ref_id=123456789,
#     )

#     result.refresh_from_db()

#     assert result.status == PaymentStatusType.success
#     assert result.ref_id == 123456789
#     assert result.is_consumed is True
