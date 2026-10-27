MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}


class UploadValidationError(Exception):
    pass


def validate_upload(*, content_type: str, size_bytes: int) -> None:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise UploadValidationError(
            f"Unsupported file type '{content_type}'. Allowed: images (JPEG, PNG, WebP) or PDF."
        )
    if size_bytes > MAX_UPLOAD_SIZE_BYTES:
        raise UploadValidationError(
            f"File is too large. Maximum size is {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB."
        )
    if size_bytes <= 0:
        raise UploadValidationError("File is empty.")
