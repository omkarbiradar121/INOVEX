from django import forms
from .models import Product


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['product_id', 'name', 'model_version', 'classes', 'description', 'is_active']
        widgets = {
            'product_id': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g., P-PLATE01',
                    'style': 'text-transform: uppercase;',
                    'autofocus': True,
                }
            ),
            'name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g., Demonstration Metal Plate',
                }
            ),
            'model_version': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g., BIT-PLATE-CV-1.0',
                }
            ),
            'classes': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g., Normal, Defective',
                }
            ),
            'description': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': 'Manufacturing specifications, alloy composition, surface finish requirements...',
                }
            ),
            'is_active': forms.CheckboxInput(
                attrs={
                    'class': 'form-check-input',
                }
            ),
        }

    def clean_product_id(self):
        pid = self.cleaned_data.get('product_id', '').strip().upper()
        if not pid:
            raise forms.ValidationError("Product ID is required.")
        return pid

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError("Product name is required.")
        return name
