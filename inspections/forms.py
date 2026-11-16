from django import forms
from products.models import Product
from .models import Inspection, SupervisorDecision, InspectionClass
from .services import ImageValidationService


class SingleInspectionForm(forms.ModelForm):
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label=None
    )
    image = forms.ImageField(
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/jpeg, image/png',
        }),
        error_messages={
            'invalid_image': "Corrupted or invalid image file. Actual content could not be decoded.",
        },
        help_text="JPEG or PNG, maximum 5 MiB, dimensions 64x64 to 4096x4096 px."
    )

    class Meta:
        model = Inspection
        fields = ['product', 'image']

    def clean_image(self):
        img_file = self.cleaned_data.get('image')
        if not img_file:
            raise forms.ValidationError("Please choose an image to inspect.")

        # Phase 9 validation
        is_valid, error_msg, metadata = ImageValidationService.validate_file(img_file)
        if not is_valid:
            raise forms.ValidationError(error_msg)

        # Attach validated metadata to the file object for the view
        img_file.validated_metadata = metadata
        return img_file


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={
            'class': 'form-control',
            'accept': 'image/jpeg, image/png',
            'multiple': True,
        }))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = [single_file_clean(data, initial)]
        return result


class BatchInspectionForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label=None
    )
    images = MultipleFileField(
        help_text="Select 1 to 10 images (JPEG or PNG, up to 5 MiB each)."
    )

    def clean_images(self):
        files = self.cleaned_data.get('images', [])
        if not files:
            raise forms.ValidationError("Please select at least 1 image.")
        if len(files) > 10:
            raise forms.ValidationError(f"Maximum 10 images allowed per batch. You selected {len(files)}.")
        return files


class SupervisorReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=SupervisorDecision.choices,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        initial=SupervisorDecision.CONFIRMED,
        help_text="Confirm the AI prediction or select an override."
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Add optional quality review notes, observations, or defect descriptions...',
        }),
        help_text="Optional remarks for quality audit tracking."
    )
