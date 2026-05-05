import fitz
import os
import uuid
import httpx
import logging
import asyncio
from PIL import Image
import io
import pytesseract

# ✅ Windows path
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

logger = logging.getLogger(__name__)


def extract_with_tesseract(page) -> str:
    try:
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        text = pytesseract.image_to_string(img)
        return " ".join(text.split())
    except Exception as e:
        logger.error(f"Tesseract error: {e}")
        return ""


async def extract_text_and_images(pdf_path: str):
    temp_file = None

    if pdf_path.startswith("http"):
        async with httpx.AsyncClient(timeout=15) as client_http:
            response = await client_http.get(pdf_path)
        if response.status_code != 200:
            return []
        temp_file = f"temp_{uuid.uuid4().hex}.pdf"
        with open(temp_file, "wb") as f:
            f.write(response.content)
        pdf_path = temp_file

    if not os.path.exists(pdf_path):
        return []

    pages_data = []

    try:
        doc = fitz.open(pdf_path)
        logger.info(f"📖 Total pages: {len(doc)}")

        for page_index in range(len(doc)):
            page = doc[page_index]

            # ✅ Step 1: fitz se try karo
            text = " ".join(page.get_text().split())

            # ✅ Step 2: Tesseract fallback
            if len(text.strip()) < 20:
                logger.info(f"🔄 Page {page_index+1}: No text, using Tesseract...")
                text = extract_with_tesseract(page)
                logger.info(f"✅ Tesseract Page {page_index+1} text length: {len(text)}")

            if len(text.strip()) >= 20:
                pages_data.append({"text": text, "images": []})
            else:
                logger.info(f"⚠️ Page {page_index+1}: No text found, skipping")

        doc.close()

    except Exception as e:
        logger.error(f"❌ PDF extraction error: {e}")

    finally:
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)

    logger.info(f"✅ Total pages with text: {len(pages_data)}")
    return pages_data