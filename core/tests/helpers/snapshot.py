# tests/helpers/snapshot.py
from copy import deepcopy


def snapshot(instance):
    """
    Save current object state.

    before = snapshot(product)

    ...
    product.refresh_from_db()

    assert before.stock == 10
    """

    return deepcopy(instance)
