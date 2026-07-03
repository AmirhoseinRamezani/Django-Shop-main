# tests/helpers/session.py

class DummySession(dict):
    """
    Session replacement for service tests.
    """

    modified = False

    def save(self):
        self.modified = True

    def cycle_key(self):
        pass

    def flush(self):
        self.clear()
        self.modified = True