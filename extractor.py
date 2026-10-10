import tempfile
from pathlib import Path
import httpx
from bs4 import BeautifulSoup

_ocr_reader = None


def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(["ru", "en"], gpu=False)
    return _ocr_reader


async def extract_from_url(url: str) -> str:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    return text[:5000]


def extract_from_image(image_bytes: bytes) -> str:
    reader = _get_ocr_reader()

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(image_bytes)
        path = f.name

    try:
        result = reader.readtext(path, detail=0, paragraph=True)
        return " ".join(result)
    finally:
        Path(path).unlink(missing_ok=True)