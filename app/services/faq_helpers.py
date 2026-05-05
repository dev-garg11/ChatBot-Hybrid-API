import re
from typing import List


# ============================================================
# 🔥 QUERY CLEANING (SAFE + MINIMAL)
# ============================================================
def preprocess_query(text_input: str) -> str:
    """
    Clean query without breaking meaning.
    Designed for RAG + LLM usage.
    """

    if not text_input or not text_input.strip():
        return ""

    # lowercase
    text_input = text_input.lower()

    # 🔥 remove punctuation (safe for embeddings)
    text_input = re.sub(r"[^\w\s]", "", text_input)

    # remove extra spaces
    text_input = re.sub(r"\s+", " ", text_input)

    return text_input.strip()


# ============================================================
# 🔥 OPTIONAL SPELL FIX (SAFE + STRICT)
# ============================================================
def safe_spell_fix(query: str, vocab: List[str]) -> str:
    """
    Very conservative spell correction.
    Only fixes if match confidence is very high.
    """

    if not vocab:
        return query

    try:
        from rapidfuzz import process
    except ImportError:
        return query  # skip if library not available

    corrected_words = []

    for word in query.split():

        # skip very short words
        if len(word) < 3:
            corrected_words.append(word)
            continue

        match = process.extractOne(word, vocab)

        # 🔥 strict threshold (avoid wrong corrections)
        if match and match[1] >= 90:
            corrected_words.append(match[0])
        else:
            corrected_words.append(word)

    return " ".join(corrected_words)


# ============================================================
# 🔥 MAIN PIPELINE
# ============================================================
def process_query(query: str, vocab: List[str] = None) -> str:
    """
    Final query processing pipeline.
    """

    # safety
    if vocab is None:
        vocab = []

    # step 1: basic clean
    query = preprocess_query(query)

    if not query:
        return ""

    # step 2: optional spell fix
    if vocab:
        query = safe_spell_fix(query, vocab)

    return query