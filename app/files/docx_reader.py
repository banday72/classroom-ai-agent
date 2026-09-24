"""Extract text from Word (.docx) files.

WHAT: Reads a .docx and returns all its text, including text inside tables.
WHY:  Assignments are often written up in Word documents. A .docx is a ZIP
      folder of XML files, so reading it needs a library (python-docx).
HOW:  python-docx gives us `doc.paragraphs` (normal text) and
      `doc.tables`. We take every non-empty paragraph, then each table row
      as a pipe-separated line, so the AI sees the same content in order.
"""

from docx import Document


def extract_text(path: str) -> str:
    doc = Document(path)
    parts = []

    # Normal paragraphs
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)

    # Tables (common in templates & rubrics)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))

    return "\n\n".join(parts)