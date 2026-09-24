"""Download assignment attachments from Google Drive.

WHAT: Takes the material list of an assignment and downloads every real
      file (driveFile) into data/downloads/ using the Drive API.
WHY:  To analyse an assignment our AI needs the actual content. Drive files
      are not handed to us as URLs we can just `requests.get()` — they
      require an authenticated Drive API call.
HOW:  Standard Drive flow:
        1. files().get(fileId, fields='mimeType,name')   -> metadata
        2. files().get_media(fileId) + MediaIoBaseDownload -> bytes
      Native Google files (Docs/Sheets) are NOT stored as normal files, so
      we EXPORT them (e.g. Google Docs -> text) instead of downloading.
      Links and YouTube videos have nothing to download, so we record them
      as notes to include in the AI prompt.
"""

import io
import re
from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from app.config import MAX_ATTACHMENT_BYTES

# Map Drive MIME types to a safe file extension.
MIME_EXTENSION = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "application/vnd.google-apps.document": ".txt",  # exported to text
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


def sanitize(name: str, max_len: int = 80) -> str:
    """Strip characters that Windows filesystem disallows."""
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip().strip(".")
    return (name[:max_len] or "file").strip()


def download_attachments(drive, materials: list, dest_dir: Path) -> list:
    """Download every file attachment; return a report list.

    Each report item looks like:
      {"name": str, "kind": "file"|"link"|"youtube", "path": Path|None,
       "note": str}
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    report = []

    for material in materials or []:
        if material.get("kind") == "drive_file":
            report.append(_download_drive_file(drive, material, dest_dir))
        elif material.get("kind") == "link":
            report.append(
                {"name": material["name"], "kind": "link", "path": None,
                 "note": material.get("url", "")}
            )
        elif material.get("kind") == "youtube":
            report.append(
                {"name": material["name"], "kind": "youtube", "path": None,
                 "note": material.get("url", "")}
            )
    return report


def _download_drive_file(drive, material: dict, dest_dir: Path) -> dict:
    """Download ONE Drive file (or export a native Google file)."""
    file_id = material["id"]
    base_name = sanitize(material.get("name", "attachment"))
    report = {"name": base_name, "kind": "file", "path": None, "note": ""}

    try:
        meta = drive.files().get(
            fileId=file_id, fields="mimeType,name,size"
        ).execute()
    except HttpError as exc:
        report["note"] = f"Could not access file (HTTP {exc.resp.status})"
        return report

    mime = meta.get("mimeType", "")
    size = int(meta.get("size") or 0)
    if size > MAX_ATTACHMENT_BYTES:
        report["note"] = f"Skipped: file is {size/1e6:.1f} MB (limit {MAX_ATTACHMENT_BYTES/1e6:.0f} MB)"
        return report

    try:
        if mime == "application/vnd.google-apps.document":
            content = drive.files().export(fileId=file_id, mimeType="text/plain").execute()
        else:
            content = _download_bytes(drive, file_id)
    except HttpError as exc:
        report["note"] = f"Download failed (HTTP {exc.resp.status})"
        return report

    extension = MIME_EXTENSION.get(mime, ".bin")
    target = dest_dir / _unique_name(dest_dir, base_name + extension)
    target.write_bytes(content)
    report["path"] = target
    report["note"] = f"HTTP MIME: {mime}"
    return report


def _download_bytes(drive, file_id: str) -> bytes:
    """Stream-download a normal file into memory."""
    request = drive.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request, chunksize=1024 * 1024)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    return buffer.getvalue()


def _unique_name(folder: Path, name: str) -> str:
    """Avoid overwriting files that already exist (adds _2, _3, ...)."""
    candidate = name
    index = 2
    stem = Path(name).stem
    suffix = Path(name).suffix
    while (folder / candidate).exists():
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    return candidate