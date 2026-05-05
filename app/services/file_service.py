import os
import uuid
import re
import asyncio
import logging

logger = logging.getLogger(__name__)

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
BASE_URL = os.getenv("BASE_URL", "http://localhost/files")

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


def sanitize_filename(filename: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)


async def write_file(path, contents):
    def _write():
        with open(path, "wb") as f:
            f.write(contents)
    await asyncio.to_thread(_write)


async def save_file(file, contents: bytes) -> str:

    os.makedirs(UPLOAD_DIR, exist_ok=True)

    original_name = os.path.basename(file.filename)
    safe_name = sanitize_filename(original_name)

    _, ext = os.path.splitext(safe_name)

    if ext.lower() != ".pdf":
        raise ValueError("Only PDF files allowed")

    # 🔥 SIZE CHECK
    if len(contents) > MAX_FILE_SIZE:
        raise ValueError("File too large")

    # 🔥 MIME CHECK
    if not contents.startswith(b"%PDF"):
        raise ValueError("Invalid PDF file")

    unique_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    try:
        await write_file(file_path, contents)
    except Exception as e:
        raise RuntimeError(f"File save failed: {str(e)}")

    file_url = f"{BASE_URL.rstrip('/')}/{unique_filename}"

    logger.info(f"📂 File saved: {file_path}")
    logger.info(f"🌐 URL: {file_url}")

    return file_url, file_path