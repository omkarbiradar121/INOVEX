from django.urls import path
from . import views

urlpatterns = [
    # Web UI Product Management Views
    path('', views.product_list_view, name='product_list'),
    path('add/', views.product_create_view, name='product_create'),
    path('<int:pk>/', views.product_detail_view, name='product_detail'),
    path('<int:pk>/edit/', views.product_edit_view, name='product_edit'),
    path('<int:pk>/toggle/', views.product_toggle_view, name='product_toggle'),
    path('<int:pk>/delete/', views.product_delete_view, name='product_delete'),

    # REST APIs (Administrator only)
    path('api/', views.ProductListCreateAPIView.as_view(), name='api_product_list_create'),
    path('api/<int:pk>/', views.ProductDetailAPIView.as_view(), name='api_product_detail'),
]
