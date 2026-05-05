import hashlib
from app.utilis.text_utils import normalize_text


def generate_hash(text) -> str:
    """
    Generate consistent hash for duplicate detection
    """

    # 🔥 handle bytes safely
    if isinstance(text, bytes):
        text = text.decode(errors="ignore")

    if not text:
        return ""

    normalized = normalize_text(text)

    # 🔥 use SHA256 (safe)
    return hashlib.sha256(normalized.encode()).hexdigest()