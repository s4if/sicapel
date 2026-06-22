"""File-upload helpers (D8 / §12).

Shared by the warnings (signed-scan), amnesties (signed letter, T14) and
evidence-photo (T17) flows. Persisted paths follow the collision-proof
strategy::

    <UPLOAD_FOLDER>/<document_type>/<yyyy>/<mm>/<uuid>.<ext>

MIME is **sniffed from content** via ``python-magic`` (never trusts the
client-supplied extension). Full evidence-photo hardening (Pillow decode
test + thumbnail) lands in T17; the whitelist + size cap here are enough
for signed-scan uploads.

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


class UploadError(ValueError):
    """Raised when an uploaded file fails validation (empty / bad MIME)."""


def sniff_mime(data: bytes) -> str:
    """Content-based MIME detection (§12) — never trusts the extension."""
    return magic.from_buffer(data, mime=True)


def save_upload(
    file_storage,
    document_type,
    uploaded_by,
    *,
    warning_letter_id=None,
    violation_record_id=None,
) -> Document:
    """Persist ``file_storage`` and return a not-yet-committed ``Document``.

    Raises :class:`UploadError` on empty content or a non-whitelisted MIME.
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

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    abs_path = os.path.join(abs_dir, stored_name)
    with open(abs_path, "wb") as fh:
        fh.write(raw)

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
