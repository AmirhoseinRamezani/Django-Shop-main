from django.urls import path, include
from . import views

app_name = "admin"

urlpatterns = [
    path("home/", views.AdminDashboardHomeView.as_view(), name="home"),
    path("", include("dashboard.admin.urls.generals")),
    path("", include("dashboard.admin.urls.products")),
    path("", include("dashboard.admin.urls.orders")),
    path("", include("dashboard.admin.urls.coupons")),
    path("", include("dashboard.admin.urls.reviews")),
    path("", include("dashboard.admin.urls.contacts")),
    path("", include("dashboard.admin.urls.users")),
    path("", include("dashboard.admin.urls.newsletters")),
    path("", include("dashboard.admin.urls.profiles")),
]
