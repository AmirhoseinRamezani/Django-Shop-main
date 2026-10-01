# tests/services/payment/test_payment_flow.py
import pytest

from payment.services.payment_flow import (
    handle_successful_payment,
)
from unittest.mock import patch

pytestmark = pytest.mark.django_db


class DummySession(dict):

    modified = False


class TestPaymentFlow:

    @patch(
        "payment.services.payment_flow.verify_payment",
    )
    def test_returns_order(
        self,
        mock_verify,
        payment,
    ):
        session = DummySession()
        mock_verify.return_value = payment
    
        order = handle_successful_payment(
            payment_id=payment.pk,
            ref_id="REF-TEST",
            response={"status": "ok"},
            session=session,
        )
        assert order == payment.order
        mock_verify.assert_called_once_with(
            payment_id=payment.pk,
            ref_id="REF-TEST",
            response={"status": "ok"},
        )

    def test_clears_coupon_session(self, payment, monkeypatch):
        
        session = DummySession()
        session["coupon_id"] = 123
        
        monkeypatch.setattr(
            "payment.services.payment_flow.verify_payment",
            lambda *args, **kwargs: payment,
        )
        
        handle_successful_payment(
            payment_id=payment.id,
            ref_id="111",
            response={},
            session=session,
        )
        
        assert "coupon_id" not in session
        assert session.modified is True

    def test_clear_cart(self, payment, monkeypatch):
        session = DummySession()

        def mock_verify(*args, **kwargs):
            return payment

        monkeypatch.setattr("payment.services.payment_flow.verify_payment", mock_verify)

        cleared = []
        monkeypatch.setattr("payment.services.payment_flow.CartSession.clear", lambda self: cleared.append(True))

        handle_successful_payment(
            payment_id=payment.id,
            ref_id="1",
            response={},
            session=session,
        )

        assert len(cleared) == 1