from django.conf import settings


class CorsMiddleware:
    """Minimal CORS for /api/, så mikkelbohnke.com kan kalde API'et fra browseren."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        origin = request.headers.get("Origin")
        if request.path.startswith("/api/") and origin in settings.CORS_ALLOWED_ORIGINS:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response["Vary"] = "Origin"
        return response
