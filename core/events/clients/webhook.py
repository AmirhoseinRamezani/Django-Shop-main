# events/clients/webhook.py


import requests



class WebhookClient:
    """
    HTTP client for sending webhook events.

    Responsibilities:
    - Build request
    - Send request
    - Raise exceptions on failure
    - Log request failures

    It MUST NOT know anything about Django models.
    """

    DEFAULT_TIMEOUT = 5

    def __init__(self,endpoint ,timeout=None):
        # self.base_url = base_url or settings.WEBHOOK_URL
        # self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.endpoint = endpoint
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.session = requests.Session()

    @staticmethod
    def post(payload: dict,topic):

        # response = requests.post(
        #     settings.WEBHOOK_URL,
        #     json={
        #         "topic": topic,
        #         "payload": payload,
        #     },
        #     timeout=5,
        # )

        # response.raise_for_status()

        # return response
        return True