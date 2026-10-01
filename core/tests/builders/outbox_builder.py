# tests/builders/outbox_builder.py
from tests.builders.base import BaseBuilder

from tests.factories.events import (
    OutboxEventFactory,
)


class OutboxBuilder(BaseBuilder):

    def topic(self, topic):

        self.kwargs["topic"] = topic

        return self

    def payload(self, payload):

        self.kwargs["payload"] = payload

        return self

    def processed(self):

        self.kwargs["processed"] = True

        return self

    def failed(self):

        self.kwargs["failed"] = True

        return self

    def build(self):

        return OutboxEventFactory(
            **self.kwargs
        )