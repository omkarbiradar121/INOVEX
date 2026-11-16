from django.urls import path
from . import views

urlpatterns = [
    # Frontend Pages
    path('', views.index_redirect_view, name='index_redirect'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('assistant/', views.manufacturing_assistant_view, name='manufacturing_assistant'),
    path('admin-dashboard/', views.admin_dashboard_view, name='admin_dashboard'),
    path('engineer-dashboard/', views.engineer_dashboard_view, name='engineer_dashboard'),
    path('supervisor-dashboard/', views.supervisor_dashboard_view, name='manual_supervisor_dashboard'),
    path('manual-audit/', views.supervisor_dashboard_view, name='assistant_supervisor_dashboard'),

    # REST API Endpoints
    path('api/machines/', views.MachineListCreateAPIView.as_view(), name='api_machines'),
    path('api/manuals/', views.ManualListCreateAPIView.as_view(), name='api_manuals'),
    path('api/manuals/<int:pk>/index/', views.ManualIndexAPIView.as_view(), name='api_manual_index'),
    path('api/ask/', views.AskQuestionAPIView.as_view(), name='api_ask'),
    path('api/queries/', views.QueryHistoryAPIView.as_view(), name='api_queries'),
    path('api/queries/unanswered/', views.UnansweredQueriesAPIView.as_view(), name='api_queries_unanswered'),
    path('api/queries/<int:query_id>/download-pdf/', views.download_query_pdf_view, name='download_query_pdf'),
    path('queries/<int:query_id>/download-pdf/', views.download_query_pdf_view, name='download_query_pdf_alt'),
]
