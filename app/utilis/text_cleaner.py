import re

def clean_text(text: str):
    if not text:
        return ""

    # ✅ normalize whitespace
    text = re.sub(r"\s+", " ", text)

    # ✅ UNICODE flag add kiya - Punjabi/Hindi safe
    text = re.sub(r"[^\w\s.,]", "", text, flags=re.UNICODE)

    # ✅ fix repeated dots
    text = re.sub(r"\.{2,}", ".", text)

    return text.strip()