# core/payment/gateways/registry.py
from __future__ import annotations

from types import MappingProxyType
from typing import Any, TypeAlias

from payment.enums import PaymentGateway
from payment.exceptions import (
    PaymentGatewayNotSupportedError,
)

GatewayClient: TypeAlias = type[Any]
class GatewayRegistry:
    """
    Runtime registry for concrete payment gateway clients.

    The registry maps a stable PaymentGateway identifier to its concrete
    gateway client implementation.

    Responsibilities
    -----------------
    - register a concrete gateway client
    - resolve a gateway client
    - determine whether a gateway is implemented
    - expose the registered gateway identifiers

    Non-responsibilities
    --------------------
    - database access
    - transactions
    - Payment persistence
    - Refund persistence
    - gateway communication
    - business policy
    - payment state transitions
    - refund authorization
    - retry orchestration
    - logging
    - event publishing

    Architecture
    ------------
        PaymentGateway
              |
              v
        GatewayRegistry
              |
              v
        Concrete Gateway Client

    Example
    -------
        GatewayRegistry.register(
            PaymentGateway.ZARINPAL,
            ZarinPalSandbox,
        )

        client_class = GatewayRegistry.resolve(
            PaymentGateway.ZARINPAL,
        )

        client = client_class()
    """

    _clients: dict[PaymentGateway, GatewayClient] = {}

    # ------------------------------------
    # Registration
    # ------------------------------------

    @classmethod
    def register(
        cls,
        gateway: PaymentGateway,
        client: GatewayClient,
    ) -> None:
        """
        Register a concrete gateway client.

        Registration is intentionally explicit.

        The registry rejects:
            - non-PaymentGateway identifiers
            - non-class clients
            - duplicate gateway registrations

        Duplicate registration is treated as a configuration/programming
        error rather than silently replacing the existing implementation.

        This prevents import order from changing financial behavior.
        """

        if not isinstance(gateway, PaymentGateway):
            raise TypeError(
                "gateway must be an instance of PaymentGateway."
            )

        if not isinstance(client, type):
            raise TypeError(
                "client must be a gateway client class."
            )

        if gateway in cls._clients:
            raise ValueError(
                (
                    "Payment gateway is already registered: "
                    f"{gateway.value}"
                )
            )

        cls._clients[gateway] = client

    # ------------------------------------
    # Resolution
    # ------------------------------------

    @classmethod
    def resolve(
        cls,
        gateway: PaymentGateway | str,
    ) -> GatewayClient:
        """
        Resolve a registered gateway client class.

        The registry returns the class, not an instance.

        Client construction remains explicit at the application/gateway
        boundary and is therefore not hidden inside the registry.
        """

        normalized_gateway = cls._normalize_gateway(gateway)

        client = cls._clients.get(
            normalized_gateway,
        )

        if client is None:
            raise PaymentGatewayNotSupportedError(
                "Payment gateway is not currently implemented.",
                details={
                    "gateway": normalized_gateway.value,
                },
            )

        return client

    # ------------------------------------
    # Capability / availability
    # ------------------------------------

    @classmethod
    def is_registered(
        cls,
        gateway: PaymentGateway | str,
    ) -> bool:
        """
        Return whether a concrete implementation is registered.

        This answers:

            "Do we have an implementation?"

        It does NOT answer:

            "Is this gateway operational right now?"

        Operational health belongs to the gateway/application layer.
        """

        normalized_gateway = cls._normalize_gateway(
            gateway,
        )

        return normalized_gateway in cls._clients

    # ------------------------------------
    # Inspection
    # ------------------------------------

    @classmethod
    def gateways(cls) -> tuple[PaymentGateway, ...]:
        """
        Return all currently registered gateway identifiers.

        A tuple is returned so callers cannot mutate registry state
        through the returned collection.
        """

        return tuple(cls._clients.keys())

    @classmethod
    def snapshot(
        cls,
    ) -> MappingProxyType:
        """
        Return a read-only snapshot of the current registry.

        The returned mapping cannot be mutated by consumers.

        This is useful for:
            - diagnostics
            - startup checks
            - tests
            - observability

        It intentionally exposes implementation classes because this is
        infrastructure metadata, not financial/domain data.
        """

        return MappingProxyType(
            dict(cls._clients),
        )

    # ------------------------------------
    # Normalization
    # ------------------------------------

    @staticmethod
    def _normalize_gateway(
        gateway: PaymentGateway | str,
    ) -> PaymentGateway:
        """
        Normalize a gateway identifier.

        Enum members are returned unchanged.

        String values are resolved through the enum value.

        Unknown values are rejected at the registry boundary rather than
        being allowed to silently behave like an unsupported client.
        """

        if isinstance(gateway, PaymentGateway):
            return gateway

        try:
            return PaymentGateway(str(gateway))
        except ValueError as exc:
            raise PaymentGatewayNotSupportedError(
                "Unknown payment gateway.",
                details={
                    "gateway": str(gateway),
                },
            ) from exc