from django.test import RequestFactory
import pytest

from accounts.models import UserType
from order.views.result import OrderCompletedView
from payment.enums import PaymentStatusType
from payment.models import PaymentResolutionStatus
from payment.services.payment_resolution import PaymentResolutionService
from tests.factories.accounts import UserFactory
from tests.factories.order import OrderFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory

pytestmark = pytest.mark.django_db


def _request(user, session):
    request = RequestFactory().get("/order/completed/")
    request.user = user
    request.session = session
    return request


def _open_resolution_for(user):
    order = OrderFactory(user=user, cancelled=True)
    payment = PaymentFactory(order=order, status=PaymentStatusType.SUCCESS, is_consumed=False)
    PaymentAttemptFactory(payment=payment, success=True)
    resolution = PaymentResolutionService.register(payment_id=payment.pk)
    return order, payment, resolution


def _response(user, session):
    response = OrderCompletedView.as_view()(_request(user, session))
    response.render()
    return response


def test_result_view_shows_open_resolution_and_repeated_request_is_stable():
    user = UserFactory(type=UserType.CUSTOMER)
    order, _, resolution = _open_resolution_for(user)
    session = {"payment_resolution_order_id": order.pk}

    first = _response(user, session)
    second = _response(user, session)

    assert first.context_data["payment_resolution_open"] is True
    assert second.context_data["payment_resolution_open"] is True
    assert session["payment_resolution_order_id"] == order.pk
    assert resolution.status == PaymentResolutionStatus.OPEN


def test_result_view_clears_session_hint_after_resolution_is_closed():
    user = UserFactory(type=UserType.CUSTOMER)
    order, _, resolution = _open_resolution_for(user)
    PaymentResolutionService.resolve(
        resolution_id=resolution.pk,
        actor=user,
        note="Reviewed provider evidence; no further customer action required.",
    )
    session = {"payment_resolution_order_id": order.pk}

    response = _response(user, session)

    assert response.context_data["payment_resolution_open"] is False
    assert "payment_resolution_order_id" not in session


def test_result_view_clears_stale_session_id_without_404():
    user = UserFactory(type=UserType.CUSTOMER)
    session = {"payment_resolution_order_id": 999999999}

    response = _response(user, session)

    assert response.status_code == 200
    assert response.context_data["payment_resolution_open"] is False
    assert "payment_resolution_order_id" not in session


def test_result_view_does_not_disclose_another_users_resolution():
    user = UserFactory(type=UserType.CUSTOMER)
    other_user = UserFactory(type=UserType.CUSTOMER)
    order, _, _ = _open_resolution_for(other_user)
    session = {"payment_resolution_order_id": order.pk}

    response = _response(user, session)

    assert response.status_code == 200
    assert response.context_data["payment_resolution_open"] is False
    assert "payment_resolution_order_id" not in session


def test_result_view_clears_malformed_session_id_without_error():
    user = UserFactory(type=UserType.CUSTOMER)
    session = {"payment_resolution_order_id": "not-a-valid-primary-key"}

    response = _response(user, session)

    assert response.status_code == 200
    assert response.context_data["payment_resolution_open"] is False
    assert "payment_resolution_order_id" not in session
