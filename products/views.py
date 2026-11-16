from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from rest_framework import generics
from rest_framework.response import Response

from accounts.permissions import admin_required, IsAdministratorUser
from .models import Product
from .forms import ProductForm
from .serializers import ProductSerializer


@admin_required
def product_list_view(request):
    """
    Displays the catalog of registered products.
    Restricted to Administrator role.
    """
    products = Product.objects.all()
    context = {
        'products': products,
        'title': 'Registered Products',
    }
    return render(request, 'products/product_list.html', context)


@admin_required
def product_create_view(request):
    """
    Form to register a new manufacturing product line.
    Restricted to Administrator role.
    """
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save(commit=False)
            product.created_by = request.user
            product.save()
            messages.success(request, f"Product '{product.product_id}' ({product.name}) successfully registered.")
            return redirect('admin_dashboard')
        else:
            messages.error(request, "Please correct the errors below to register the product.")
    else:
        # Provide sensible defaults for the challenge target product
        initial_data = {}
        if not Product.objects.filter(product_id='P-PLATE01').exists():
            initial_data = {
                'product_id': 'P-PLATE01',
                'name': 'Demonstration Metal Plate',
                'model_version': 'BIT-PLATE-CV-1.0',
                'classes': 'Normal, Defective',
                'description': 'Demonstration metal bipolar plates for automated surface quality defect inspection.',
                'is_active': True,
            }
        form = ProductForm(initial=initial_data)

    context = {
        'form': form,
        'action_title': 'Register New Product',
        'is_edit': False,
    }
    return render(request, 'products/product_form.html', context)


@admin_required
def product_detail_view(request, pk):
    """
    View specifications and inspection parameters of a registered product.
    Restricted to Administrator role.
    """
    product = get_object_or_404(Product, pk=pk)
    context = {
        'product': product,
        'title': f"Product Detail: {product.product_id}",
    }
    return render(request, 'products/product_detail.html', context)


@admin_required
def product_edit_view(request, pk):
    """
    Update product details and vision model configurations.
    Restricted to Administrator role.
    """
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, f"Product '{product.product_id}' updated successfully.")
            return redirect('admin_dashboard')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = ProductForm(instance=product)

    context = {
        'form': form,
        'product': product,
        'action_title': f"Edit Product: {product.product_id}",
        'is_edit': True,
    }
    return render(request, 'products/product_form.html', context)


@admin_required
@require_POST
def product_toggle_view(request, pk):
    """
    Toggle active status of a product line.
    """
    product = get_object_or_404(Product, pk=pk)
    product.is_active = not product.is_active
    product.save()
    status_str = "activated" if product.is_active else "deactivated"
    messages.info(request, f"Product '{product.product_id}' {status_str}.")
    return redirect('admin_dashboard')


@admin_required
@require_POST
def product_delete_view(request, pk):
    """
    Delete a product from the registry.
    """
    product = get_object_or_404(Product, pk=pk)
    pid = product.product_id
    product.delete()
    messages.warning(request, f"Product '{pid}' removed from registration.")
    return redirect('admin_dashboard')


# REST API Endpoints (Admin Only)

class ProductListCreateAPIView(generics.ListCreateAPIView):
    """
    GET: List all registered products.
    POST: Register a new product.
    Restricted strictly to Administrator role.
    """
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAdministratorUser]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ProductDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET, PUT, PATCH, DELETE operations for specific product.
    Restricted strictly to Administrator role.
    """
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAdministratorUser]
