from django.urls import path, include
from dashboard.admin.views.generals import AdminDashboardHomeView


urlpatterns = [

    path("home/", AdminDashboardHomeView.as_view(), name="home"),
]