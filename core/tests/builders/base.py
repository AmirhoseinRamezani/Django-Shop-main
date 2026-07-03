# tests/builders/base.py
class Builder:

    def __init__(self):
        self.kwargs = {}

    def with_data(self, **kwargs):
        self.kwargs.update(kwargs)
        return self

    def build(self):
        raise NotImplementedError