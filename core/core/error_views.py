# core/error_views.py
from django.http import JsonResponse
from django.shortcuts import render


def wants_json(request):
    accept = request.headers.get("Accept", "")
    return (
        request.path.startswith("/api/")
        or "application/json" in accept
    )


def error_404(request, exception):
    if wants_json(request):
        return JsonResponse(
            {"detail": "Not found"},
            status=404
        )
    return render(request, "errors/404.html", status=404)


def error_403(request, exception):
    if wants_json(request):
        return JsonResponse(
            {"detail": "Permission denied"},
            status=403
        )
    return render(request, "errors/403.html", status=403)


def error_400(request, exception):
    if wants_json(request):
        return JsonResponse(
            {"detail": "Bad request"},
            status=400
        )
    return render(request, "errors/400.html", status=400)


def error_500(request):
    if wants_json(request):
        return JsonResponse(
            {"detail": "Internal server error"},
            status=500
        )
    return render(request, "errors/500.html", status=500)
