import io
from typing import Tuple, Dict, Any, Optional
from PIL import Image, UnidentifiedImageError

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MiB
MIN_DIMENSION = 64
MAX_DIMENSION = 4096
ALLOWED_FORMATS = {'JPEG', 'PNG'}


class ImageValidationError(Exception):
    """Raised when an uploaded image fails validation."""
    pass


class ImageValidationService:
    """
    Enforces Phase 9 strict image validation rules:
    - JPEG and PNG only
    - Maximum file size: 5 MiB
    - Dimensions between 64x64 and 4096x4096
    - Verifies actual image content bytes (detects corrupt, empty, truncated files)
    """

    @classmethod
    def validate_file(cls, uploaded_file) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Validates an uploaded file (InMemoryUploadedFile or TemporaryUploadedFile or file path).

        Returns:
            (is_valid, error_message, metadata_dict)
        """
        # 1. Size check
        file_size = getattr(uploaded_file, 'size', None)
        if file_size is None:
            # Maybe path or bytes
            if hasattr(uploaded_file, 'seek') and hasattr(uploaded_file, 'tell'):
                pos = uploaded_file.tell()
                uploaded_file.seek(0, io.SEEK_END)
                file_size = uploaded_file.tell()
                uploaded_file.seek(pos)
            else:
                file_size = len(uploaded_file)

        if file_size == 0:
            return False, "Image file is empty (0 bytes).", {}

        if file_size > MAX_FILE_SIZE_BYTES:
            size_mb = file_size / (1024 * 1024)
            return False, f"File size ({size_mb:.2f} MiB) exceeds the maximum allowed limit of 5.00 MiB.", {}

        # 2. Content & format validation using Pillow
        try:
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)

            # Open image
            img = Image.open(uploaded_file)
            img_format = (img.format or '').upper()

            # Verify format is JPEG or PNG
            if img_format not in ALLOWED_FORMATS:
                return False, f"Unsupported image format: '{img_format or 'Unknown'}'. Only JPEG and PNG are allowed.", {}

            # Strict verification of image integrity (detects truncated/corrupt streams)
            img.verify()

            # Re-open to read dimensions (verify() closes or invalidates state in Pillow)
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)
            img = Image.open(uploaded_file)
            width, height = img.size

            # Verify image pixel data can actually be loaded (catches corrupt payloads)
            img.load()

        except (UnidentifiedImageError, OSError, SyntaxError) as err:
            return False, f"Corrupted or invalid image file. Actual content could not be decoded: {str(err)}", {}
        except Exception as general_err:
            return False, f"Image validation failed: {str(general_err)}", {}
        finally:
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)

        # 3. Dimension limits check (64x64 to 4096x4096)
        if width < MIN_DIMENSION or height < MIN_DIMENSION:
            return False, (
                f"Image dimensions ({width}x{height} px) are below the minimum required "
                f"resolution of {MIN_DIMENSION}x{MIN_DIMENSION} px."
            ), {}

        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            return False, (
                f"Image dimensions ({width}x{height} px) exceed the maximum allowed "
                f"resolution of {MAX_DIMENSION}x{MAX_DIMENSION} px."
            ), {}

        metadata = {
            'file_size_bytes': file_size,
            'image_width': width,
            'image_height': height,
            'image_format': img_format,
        }
        return True, None, metadata
