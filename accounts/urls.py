from django.urls import path
from . import views

urlpatterns = [
    path('api/me/', views.CurrentUserAPIView.as_view(), name='api_current_user'),
    path('api/admin/only/', views.AdminOnlyAPIView.as_view(), name='api_admin_only'),
    path('api/engineer/only/', views.EngineerOnlyAPIView.as_view(), name='api_engineer_only'),
    path('api/supervisor/only/', views.SupervisorOnlyAPIView.as_view(), name='api_supervisor_only'),
]
