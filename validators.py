import os
from werkzeug.utils import secure_filename

ALLOWED_PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def parse_optional_float(value, field_label, errors):
    """Convert a possibly-blank value to float, or record an error."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(f"{field_label} must be a number.")
        return None


def parse_optional_int(value, field_label, errors):
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"{field_label} must be a whole number.")
        return None


def parse_required_float(value, field_label, errors):
    result = parse_optional_float(value, field_label, errors)
    if result is None and not errors:
        errors.append(f"{field_label} is required.")
    return result


def parse_required_int(value, field_label, errors):
    result = parse_optional_int(value, field_label, errors)
    if result is None and not errors:
        errors.append(f"{field_label} is required.")
    return result


def allowed_photo(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_PHOTO_EXTENSIONS
    )


def save_photo(file_storage, upload_folder):
    """Validate and save an uploaded photo. Returns the stored filename, or
    None if no file was given. Raises ValueError on an invalid file type.
    """
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_photo(file_storage.filename):
        raise ValueError("Photo must be a PNG, JPG, GIF, or WEBP file.")
    filename = secure_filename(file_storage.filename)
    file_storage.save(os.path.join(upload_folder, filename))
    return filename
