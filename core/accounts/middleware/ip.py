# accounts/middleware/ip.py
class IPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            request.ip_address = forwarded.split(",")[0].strip()
        else:
            request.ip_address = request.META.get("REMOTE_ADDR")

        return self.get_response(request)
