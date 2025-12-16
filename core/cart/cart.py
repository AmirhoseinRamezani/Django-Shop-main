from shop.models import ProductModel, ProductStatusType
from cart.models import CartModel, CartItemModel
from django.db.models import Q


class CartSession:
    """
    Session-based cart handler.
    Keeps cart usable for anonymous users and synced for authenticated users.
    """

    SESSION_KEY = "cart"

    def __init__(self, session):
        self.session = session
        self._cart = self.session.setdefault(self.SESSION_KEY, {"items": []})

    # ---------- Session operations ----------

    def add_product(self, product_id: int):
        product_id = int(product_id)

        for item in self._cart["items"]:
            if item["product_id"] == product_id:
                item["quantity"] += 1
                break
        else:
            self._cart["items"].append(
                {"product_id": product_id, "quantity": 1}
            )
        self.save()

    def remove_product(self, product_id: int):
        product_id = int(product_id)
        self._cart["items"] = [
            item for item in self._cart["items"]
            if item["product_id"] != product_id
        ]
        self.save()

    def update_product_quantity(self, product_id: int, quantity: int):
        product_id = int(product_id)
        quantity = max(1, int(quantity))  # prevent zero/negative values

        for item in self._cart["items"]:
            if item["product_id"] == product_id:
                item["quantity"] = quantity
                break
        self.save()

    def clear(self):
        self.session[self.SESSION_KEY] = {"items": []}
        self.save()

    # ---------- Read operations ----------

    def get_cart_items(self):
        """
        Returns cart items enriched with product objects.
        Safely ignores deleted/unpublished products.
        """

        product_ids = [item["product_id"] for item in self._cart["items"]]

        products = ProductModel.objects.filter(
            id__in=product_ids,
            status=ProductStatusType.publish.value
        )

        product_map = {p.id: p for p in products}
        valid_items = []

        for item in self._cart["items"]:
            product = product_map.get(item["product_id"])
            if not product:
                continue

            total_price = item["quantity"] * product.get_price()
            valid_items.append({
                "product": product,
                "quantity": item["quantity"],
                "total_price": total_price
            })

        return valid_items

    def get_total_quantity(self):
        return sum(item["quantity"] for item in self._cart["items"])

    def get_total_payment_amount(self):
        return sum(
            item["quantity"] * item["product"].get_price()
            for item in self.get_cart_items()
        )

    # ---------- DB Sync ----------

    def sync_cart_items_from_db(self, user):
        cart, _ = CartModel.objects.get_or_create(user=user)
        db_items = cart.cart_items.all()

        for db_item in db_items:
            self.add_product(db_item.product.id)
            self.update_product_quantity(
                db_item.product.id,
                db_item.quantity
            )

    def merge_session_cart_in_db(self, user):
        cart, _ = CartModel.objects.get_or_create(user=user)

        session_ids = []

        for item in self._cart["items"]:
            product = ProductModel.objects.filter(
                id=item["product_id"],
                status=ProductStatusType.publish.value
            ).first()

            if not product:
                continue

            cart_item, _ = CartItemModel.objects.get_or_create(
                cart=cart,
                product=product
            )
            cart_item.quantity = item["quantity"]
            cart_item.save()

            session_ids.append(product.id)

        cart.cart_items.exclude(product__id__in=session_ids).delete()

    def save(self):
        self.session.modified = True
