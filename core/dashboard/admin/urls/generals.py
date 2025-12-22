from django.urls import path
from ..views.home import AdminDashboardHomeView

app_name = "admin"

urlpatterns = [
    path("home/", AdminDashboardHomeView.as_view(), name="home"),
]