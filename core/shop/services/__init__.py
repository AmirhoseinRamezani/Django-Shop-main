"""Shop application services."""
from shop.services.inventory_adjustment import InventoryAdjustmentService
from shop.services.wishlist import toggle_wishlist

__all__ = (
    "InventoryAdjustmentService",
    "toggle_wishlist",
)