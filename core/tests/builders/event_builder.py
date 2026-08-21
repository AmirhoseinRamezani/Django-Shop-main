# # tests/builders/event_builder.py

from events.models import OutboxEvent

class OutboxEventBuilder:
    """
    Fluent builder for event scenarios.

    Usage:

    OutboxEventBuilder()

        .topic("order.created")

        .payload({...})

        .pending()

        .build()

    """


    def __init__(self):

        self.data = {

            "topic":
                "test.event",

            "payload":
                {},

        }


    def topic(self,value):

        self.data["topic"] = value

        return self



    def payload(self,value):

        self.data["payload"] = value

        return self



    def pending(self):

        self.data["status"] = "pending"

        return self



    def processed(self):

        self.data["status"] = "processed"

        return self



    def failed(self,error="failed"):

        self.data["status"]="failed"

        self.data["last_error"]=error

        return self



    def build(self):

        return OutboxEvent.objects.create(
            **self.data
        )