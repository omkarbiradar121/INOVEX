from django.urls import path
from . import views

urlpatterns = [
    # Phase 5: Single Image Inspection (Engineer)
    path('single/', views.single_inspection_view, name='single_inspection'),
    path('result/<int:pk>/', views.inspection_result_view, name='inspection_result'),

    # Phase 6: Batch Image Inspection (Engineer)
    path('batch/upload/', views.batch_upload_view, name='batch_upload'),
    path('batch/<str:batch_id>/', views.batch_detail_view, name='batch_detail'),
    path('batch/<str:batch_id>/status/', views.batch_status_api, name='api_batch_status'),

    # Phase 7: Personal Inspection History (Engineer)
    path('history/', views.engineer_history_view, name='engineer_history'),

    # Phase 8: Supervisor Dashboard and Review
    path('supervisor/', views.supervisor_dashboard_view, name='supervisor_dashboard'),
    path('review/<int:pk>/', views.supervisor_review_view, name='supervisor_review'),

    # Phase 10: Model Evaluation
    path('evaluation/', views.model_evaluation_view, name='model_evaluation'),
    path('evaluation/run/', views.execute_model_evaluation_view, name='execute_model_evaluation'),

    # REST APIs
    path('api/', views.InspectionListAPIView.as_view(), name='api_inspection_list'),
    path('api/<int:pk>/', views.InspectionDetailAPIView.as_view(), name='api_inspection_detail'),
    path('api/single/', views.SingleInspectionAPIView.as_view(), name='api_single_inspection'),
    path('api/review/<int:pk>/', views.SupervisorReviewAPIView.as_view(), name='api_supervisor_review'),
]
