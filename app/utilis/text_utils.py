import re

def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.lower()

    # 🔥 keep dot (for tech terms)
    text = re.sub(r'[^a-z0-9\s.]', '', text)

    text = re.sub(r'\s+', ' ', text)

    return text.strip()