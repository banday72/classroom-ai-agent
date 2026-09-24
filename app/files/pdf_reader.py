"""Extract text from PDF files.

WHAT: Opens a PDF and pulls every piece of text it can find.
WHY:  Many assignments and readings are PDFs; PDF is a layout format, not
      a text format, so you cannot just read it as a string.
HOW:  PyMuPDF (modern import name `pymupdf`) opens the file and each page's
      get_text() returns the text layer. We join pages with blank lines.
NOTE: A SCANNED pdf (photos of pages) has no text layer -> we return a
      friendly message instead of pretending there is text.
"""

import pymupdf  # PyMuPDF


def extract_text(path: str) -> str:
    try:
        doc = pymupdf.open(path)
    except Exception:
        return f"[ERROR] Could not open PDF: {path}"

    pages = [page.get_text().strip() for page in doc]
    doc.close()

    joined = "\n\n".join(p for p in pages if p)
    if not joined:
        return ("[PDF has no selectable text — it is a scanned image document. "
                "OCR or a vision-capable AI model would be needed to read it.]")
    return joined