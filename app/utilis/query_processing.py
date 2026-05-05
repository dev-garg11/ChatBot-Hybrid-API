import re

def process_query(text: str) -> str:
    if not text or not text.strip():
        return ""

    text = text.strip()

    # ✅ Extra spaces hatao
    text = re.sub(r"\s+", " ", text)

    # ✅ Sirf trailing/leading punctuation hatao
    text = re.sub(r"^[^\w]+|[^\w]+$", "", text)

    # ✅ Noisy characters hatao but dot sirf numbers ke beech rakho
    # e.g. "v2.0" rakhega, "hello...world" fix karega
    text = re.sub(r"\.{2,}", " ", text)          # multiple dots → space
    text = re.sub(r"(?<!\d)\.(?!\d)", " ", text) # dot jo numbers ke beech nahi → space
    text = re.sub(r"[^\w\s.]", " ", text)        # baaki noise → space

    # ✅ Double spaces clean karo jo upar se aa sakti hain
    text = re.sub(r"\s+", " ", text)

    return text.strip()