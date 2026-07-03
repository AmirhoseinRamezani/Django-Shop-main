
# tests/matchers/stock.py

def restored(product, old_stock):

    product.refresh_from_db()

    assert product.stock == old_stock


def decreased(
    product,
    old_stock,
    quantity,
):

    product.refresh_from_db()

    assert (
        product.stock
        ==
        old_stock - quantity
    )
