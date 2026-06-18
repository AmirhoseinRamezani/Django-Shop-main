# # accounts/api/login.py
# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework.permissions import AllowAny
# from accounts.models import EmailOTP, OTPPurpose
# import random


# class LoginAPIView(APIView):
#     permission_classes = [AllowAny]

#     def post(self, request):
#         email = request.data.get("email", "").lower()

#         if not email:
#             return Response({"detail": "Invalid email"}, status=400)

#         code = str(random.randint(1000, 9999))

#         EmailOTP.objects.create(
#             email=email,
#             purpose=OTPPurpose.SIGNUP,
#             code=code,
#         )

#         return Response({"detail": "OTP sent"}, status=200)
