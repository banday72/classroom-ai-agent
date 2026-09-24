"""Dispatcher: figure out which reader to use for a downloaded file.

WHAT: One function, extract_text(path), that automatically picks the right
      reader based on the file extension.
WHY:  Callers (main.py) should not need to know how each format is parsed.
      This is the ONLY module that knows about all the file formats, so
      adding ".xlsx" support later means touching exactly one file.
HOW:  A simple dict maps extension -> reader function. Unknown extensions
      raise a clear error instead of silently returning nothing.
"""

from pathlib import Path

from . import docx_reader, image_reader, pdf_reader


class UnsupportedFileTypeError(Exception):
    """Raised when we neither know nor care about a file format."""


def _read_plain_text(path: str) -> str:
    """Plain .txt/.md files are just UTF-8 (or Latin-1) text."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return Path(path).read_text(encoding="latin-1")


READERS = {
    ".pdf": pdf_reader.extract_text,
    ".docx": docx_reader.extract_text,
    ".txt": _read_plain_text,
    ".md": _read_plain_text,
    ".png": image_reader.extract_text,
    ".jpg": image_reader.extract_text,
    ".jpeg": image_reader.extract_text,
}


def extract_text(path) -> str:
    """Return the text content of a downloaded attachment file."""
    file_path = Path(path)
    reader = READERS.get(file_path.suffix.lower())
    if reader is None:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{file_path.suffix}'. Supported: "
            + ", ".join(sorted(READERS))
        )
    return reader(str(file_path))