# tests/builders/product_builder.py
from tests.factories.shop import ProductFactory

class ProductBuilder:

    def __init__(self):

        self.kwargs = {}

    # --------------------------

    def stock(self, value):

        self.kwargs["stock"] = value

        return self

    # --------------------------

    def draft(self):

        self.kwargs["status"] = 2

        return self

    # --------------------------

    def published(self):

        self.kwargs["status"] = 1

        return self

    # --------------------------

    def discounted(self, percent=20):

        self.kwargs["discount_percent"] = percent

        return self

    # --------------------------

    def price(self, value):

        self.kwargs["price"] = value

        return self

    # --------------------------

    def build(self):

        return ProductFactory(**self.kwargs)
