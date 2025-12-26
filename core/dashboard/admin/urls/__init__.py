from django.urls import path,include

app_name = "admin"

urlpatterns = [
    path("", include("dashboard.admin.urls.generals")),
    path("products/", include("dashboard.admin.urls.products")),
    path("orders/", include("dashboard.admin.urls.orders")),
    path("coupons/", include("dashboard.admin.urls.coupons")),
    path("users/", include("dashboard.admin.urls.users")),
    path("reviews/", include("dashboard.admin.urls.reviews")),
    path("contacts/", include("dashboard.admin.urls.contacts")),
    path("newsletters/", include("dashboard.admin.urls.newsletters")),
    path("profiles/", include("dashboard.admin.urls.profiles")),
]