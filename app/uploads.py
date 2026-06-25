"""File-upload helpers (D8 / §12).

Shared by the warnings (signed-scan), amnesties (signed letter, T14) and
evidence-photo (T17) flows. Persisted paths follow the collision-proof
strategy::

    <UPLOAD_FOLDER>/<document_type>/<yyyy>/<mm>/<uuid>.<ext>

MIME is **sniffed from content** via ``python-magic`` (never trusts the
client-supplied extension). For ``evidence_photo`` uploads, Pillow verifies
the image is valid and generates a JPEG thumbnail (T17).

The caller commits the session (D10) — :func:`save_upload` only ``add`` +
``flush`` so the returned ``Document`` has an ``id``.
"""

import os
import uuid
from datetime import date

import magic
from flask import current_app
from werkzeug.utils import secure_filename

from . import db
from .models import Document

_MIME_WHITELIST = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "video/mp4",
}

_EXT_BY_MIME = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "video/mp4": "mp4",
}

# Thumbnail dimensions for evidence photos (T17).
_THUMB_MAX_WIDTH = 300
_THUMB_QUALITY = 75


class UploadError(ValueError):
    """Raised when an uploaded file fails validation (empty / bad MIME / bad image)."""


def sniff_mime(data: bytes) -> str:
    """Content-based MIME detection (§12) — never trusts the extension."""
    return magic.from_buffer(data, mime=True)


def _make_thumb(raw: bytes, abs_dir: str, stem: str) -> str | None:
    """Decode-test an image and write a JPEG thumbnail.

    Returns the absolute path of the thumbnail (``thumb_<stem>.jpg``), or
    ``None`` if ``raw`` is not a valid image. Raises :class:`UploadError`
    only when the image file is corrupt (partial write, truncated header).
    """
    try:
        from PIL import Image

        img = Image.open(__import__("io").BytesIO(raw))
        img.verify()
        # Re-open after verify() since verify() closes the file.
        img = Image.open(__import__("io").BytesIO(raw))
    except Exception as exc:
        raise UploadError(f"Gagal memproses gambar: {exc}") from exc

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    w, h = img.size
    if w > _THUMB_MAX_WIDTH:
        ratio = _THUMB_MAX_WIDTH / w
        new_w = _THUMB_MAX_WIDTH
        new_h = max(1, int(h * ratio))
        img = img.resize((new_w, new_h), Image.LANCZOS)

    thumb_path = os.path.join(abs_dir, f"thumb_{stem}.jpg")
    img.save(thumb_path, "JPEG", quality=_THUMB_QUALITY)
    return thumb_path


def save_upload(
    file_storage,
    document_type,
    uploaded_by,
    *,
    warning_letter_id=None,
    violation_record_id=None,
) -> Document:
    """Persist ``file_storage`` and return a not-yet-committed ``Document``.

    For ``evidence_photo`` document types, Pillow decode-test and JPEG
    thumbnail generation are performed (T17). Raises :class:`UploadError`
    on empty content, bad MIME, or a corrupt image.
    """
    raw = file_storage.read()
    if not raw:
        raise UploadError("File kosong atau tidak terbaca.")

    mime = sniff_mime(raw)
    if mime not in _MIME_WHITELIST:
        raise UploadError(f"Tipe file tidak diizinkan ({mime}).")

    ext = _EXT_BY_MIME.get(mime, "bin")
    today = date.today()
    rel_dir = os.path.join(
        document_type, str(today.year), f"{today.month:02d}"
    )
    abs_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    stem = uuid.uuid4().hex
    stored_name = f"{stem}.{ext}"
    abs_path = os.path.join(abs_dir, stored_name)
    with open(abs_path, "wb") as fh:
        fh.write(raw)

    # T17: Pillow decode-test + thumbnail for evidence photos.
    if document_type == "evidence_photo" and mime.startswith("image/"):
        _make_thumb(raw, abs_dir, stem)

    original = secure_filename(
        getattr(file_storage, "filename", "") or stored_name
    )
    doc = Document(
        violation_record_id=violation_record_id,
        warning_letter_id=warning_letter_id,
        file_name=original or stored_name,
        file_path=abs_path,
        mime_type=mime,
        file_size=len(raw),
        document_type=document_type,
        uploaded_by=uploaded_by,
    )
    db.session.add(doc)
    db.session.flush()
    return doc
