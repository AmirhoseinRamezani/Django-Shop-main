from shop.models import ProductModel, ProductStatusType
from .models import CartModel, CartItemModel

class CartSession:
    """
    Session-based cart handler.
    Handles both anonymous and authenticated users with DB sync.
    """

    SESSION_KEY = "cart"
    COUPON_KEY = "coupon_code"
    
    def __init__(self, session):
        self.session = session
        self._cart = self.session.setdefault(self.SESSION_KEY, {"items": []})

    # ---------- Coupon operations ----------
    def set_coupon(self, code: str):
        self.session[self.COUPON_KEY] = code
        self.save()

    def remove_coupon(self):
        self.session.pop(self.COUPON_KEY, None)
        self.save()

    def get_coupon_code(self):
        return self.session.get(self.COUPON_KEY)

    def get_coupon(self):
        from order.services.coupon import CouponService
        code = self.get_coupon_code()
        if not code:
            return None
        try:
            return CouponService.get_valid_coupon(code)
        except Exception:
            return None
    
    # ---------- Session operations ----------
    def add_product(self, product_id: int):
        product_id = int(product_id)
        for item in self._cart["items"]:
            if item["product_id"] == product_id:
                item["quantity"] += 1
                break
        else:
            self._cart["items"].append({"product_id": product_id, "quantity": 1})
        self.save()

    def remove_product(self, product_id: int):
        product_id = int(product_id)
        self._cart["items"] = [
            item for item in self._cart["items"] if item["product_id"] != product_id
        ]
        self.save()

    def update_product_quantity(self, product_id: int, quantity: int):
        product_id = int(product_id)
        quantity = max(1, int(quantity))
        for item in self._cart["items"]:
            if item["product_id"] == product_id:
                item["quantity"] = quantity
                break
        self.save()

    def clear(self):
        self.session[self.SESSION_KEY] = {"items": []}
        self.remove_coupon()
        self.save()

    # ---------- Read operations ----------
    def get_cart_items(self):
        product_ids = [item["product_id"] for item in self._cart["items"]]
        products = ProductModel.objects.filter(
            id__in=product_ids,
            status=ProductStatusType.PUBLISH.value
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
        total = sum(item["total_price"] for item in self.get_cart_items())
        coupon = self.get_coupon()
        if coupon:
            total = int(total * (100 - coupon.discount_percent) / 100)

        return total

    # ---------- DB Sync ----------
    def sync_cart_items_from_db(self, user):
        cart, _ = CartModel.objects.get_or_create(user=user)
        self.clear()
        for db_item in cart.cart_items.all():
            self._cart["items"].append({
                "product_id": db_item.product.id,
                "quantity": db_item.quantity
            })

        self.save()

    def merge_session_cart_in_db(self, user):
        cart, _ = CartModel.objects.get_or_create(user=user)
        session_ids = []
        for item in self._cart["items"]:
            product = ProductModel.objects.filter(
                id=item["product_id"],
                status=ProductStatusType.PUBLISH.value
            ).first()
            if not product:
                continue
            cart_item, _ = CartItemModel.objects.get_or_create(cart=cart, product=product)
            cart_item.quantity = item["quantity"]
            cart_item.save()
            session_ids.append(product.id)
        cart.cart_items.exclude(product__id__in=session_ids).delete()

    def save(self):
        self.session.modified = True
