# events/dispatchers/router.py
from events.dispatchers.registry import ROUTES


def dispatch(event):

    for handler in ROUTES.get(event.topic, ()):
        handler(event)