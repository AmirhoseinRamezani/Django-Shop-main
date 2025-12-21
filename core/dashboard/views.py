from django.views.generic import TemplateView

class DashboardHomeView(TemplateView):
    template_name = "dashboard/home.html"