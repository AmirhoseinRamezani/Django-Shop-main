# accounts/api/me.py
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
# from accounts.authentication import JWTAuthentication
from rest_framework.response import Response

class MeAPIView(APIView):
    # authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            "id": user.id,
            "email": user.email,
            "type": getattr(user, "type", None),
            "is_verified": user.is_verified,
        })
