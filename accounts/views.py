from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .permissions import IsAdministratorUser, IsEngineerUser, IsSupervisorUser


class CurrentUserAPIView(APIView):
    """
    Returns authenticated user information and role metadata.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            'username': user.username,
            'role': user.role,
            'role_display': user.get_role_display() if hasattr(user, 'get_role_display') else str(user.role),
            'employee_id': getattr(user, 'employee_id', '') or '',
            'is_administrator': user.is_administrator,
            'is_engineer': user.is_engineer,
            'is_supervisor': user.is_supervisor,
        })


class AdminOnlyAPIView(APIView):
    permission_classes = [IsAdministratorUser]

    def get(self, request):
        return Response({
            'status': 'authorized',
            'role_authorized': 'Administrator',
            'message': 'Administrator access verified.',
        })


class EngineerOnlyAPIView(APIView):
    permission_classes = [IsEngineerUser]

    def get(self, request):
        return Response({
            'status': 'authorized',
            'role_authorized': 'Engineer',
            'message': 'Engineer access verified.',
        })


class SupervisorOnlyAPIView(APIView):
    permission_classes = [IsSupervisorUser]

    def get(self, request):
        return Response({
            'status': 'authorized',
            'role_authorized': 'Supervisor',
            'message': 'Supervisor access verified.',
        })
