"""Extract text from images (optional OCR).

WHAT: Tries to read text written inside an image. There is no real text
      "inside" a PNG — we need OCR (optical character recognition).
WHY:  Some teachers upload screenshots of the assignment instead of text.
HOW:  We use Tesseract via pytesseract. It is OPTIONAL by design:
      pytesseract is not in requirements.txt because Tesseract is a separate
      program you must install. Without it we clearly say so and return a
      message the AI can understand instead of crashing.
NOTE: If you do not want to install Tesseract, a vision-capable AI model
      (e.g. one that accepts images) is the modern alternative.
"""

try:
    import pytesseract
    from PIL import Image

    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


def extract_text(path: str) -> str:
    if not OCR_AVAILABLE:
        return ("[Image attachment present but not readable here: OCR is not "
                "installed. Add 'pytesseract' to requirements and install "
                "Tesseract (https://github.com/tesseract-ocr/tesseract), or "
                "use a vision-capable AI model to analyse this image.]")
    try:
        return pytesseract.image_to_string(Image.open(path)).strip()
    except Exception as exc:
        return f"[Could not OCR image: {exc}]"