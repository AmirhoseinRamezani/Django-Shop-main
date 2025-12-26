from django.urls import path, include
from dashboard.admin.views.coupons import AdminCouponListView ,AdminCouponCreateView ,AdminCouponUpdateView ,AdminCouponDeleteView


urlpatterns = [
    path("coupon/list/", AdminCouponListView.as_view(),name="coupon-list"),
    path("coupon/create/", AdminCouponCreateView.as_view(),name="coupon-create"),
    path("coupon/<int:pk>/edit/", AdminCouponUpdateView.as_view(),name="coupon-edit"),
    path("coupon/<int:pk>/delete/", AdminCouponDeleteView.as_view(),name="coupon-delete"),
]
