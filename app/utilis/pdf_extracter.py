import fitz
import re
from typing import List, Dict


# ============================================================
# FORMAT DETECTION
# ============================================================

def has_qa_format(text: str) -> bool:
    """
    Check karo ki PDF mein 1.1, 1.2 Q&A format hai ya nahi.
    Agar 5+ numbered questions milein to Q&A format hai.
    """
    matches = re.findall(r'\n\d+\.\d+\s+\w', text)
    return len(matches) >= 5


# ============================================================
# CHUNK PARSER — Manual/Documentation PDFs ke liye
# ============================================================

def parse_chunks(doc, chunk_size: int = 3) -> List[Dict]:
    """
    Manual PDFs ke liye — har chunk_size pages ka ek Q&A pair banao.
    Question = page heading ya pehli line
    Answer = us chunk ka poora text
    """
    qa_pairs = []
    total = len(doc)
    pages = list(range(0, total))

    for i in range(0, len(pages), chunk_size):
        chunk_pages = pages[i:i + chunk_size]
        chunk_text = ""

        for p in chunk_pages:
            chunk_text += doc[p].get_text() + "\n"

        chunk_text = chunk_text.strip()
        if not chunk_text or len(chunk_text) < 20:
            continue

        lines = [l.strip() for l in chunk_text.split('\n') if l.strip()]
        if not lines:
            continue

        heading = ""
        for line in lines[:5]:
            if 5 < len(line) < 150:
                heading = line
                break

        if not heading:
            heading = f"Page {chunk_pages[0] + 1} Content"

        heading = re.sub(r'^Ver\.\d+\.\d+\s*\[\s*\d+\s*\]\s*', '', heading).strip()
        heading = re.sub(r'^\d+\s*$', '', heading).strip()

        if not heading:
            heading = f"Page {chunk_pages[0] + 1} Content"

        answer = clean(chunk_text)

        if len(answer) < 20:
            continue

        qa_pairs.append({
            "question": heading,
            "answer": answer
        })

    print(f"Total chunks parsed: {len(qa_pairs)}")
    return qa_pairs


# ============================================================
# MAIN EXTRACT FUNCTION
# ============================================================

def extract_faq_from_pdf(file_path: str) -> List[Dict]:
    """
    PDF se FAQ extract karo.
    - Agar 1.1 format hai: parse_qa() use hoga
    - Agar manual/doc format hai: parse_chunks() use hoga
    """
    doc = fitz.open(file_path)

    full_text = ""
    for page in doc:
        full_text += page.get_text()

    print("=== Extracted Text (first 500 chars) ===")
    print(full_text[:500])

    # Format detect karo
    if has_qa_format(full_text):
        print(f"\n[FORMAT] Q&A format detected (1.1, 1.2...) -> parse_qa()")
        doc.close()
        return parse_qa(full_text)
    else:
        print(f"\n[FORMAT] Manual/Doc format detected -> parse_chunks()")
        result = parse_chunks(doc, chunk_size=3)
        doc.close()
        return result


# ============================================================
# ORIGINAL parse_qa — 1.1 format ke liye
# ============================================================

def parse_qa(text: str) -> List[Dict]:
    """
    PDF format:
    1.1 Question text?
    Answer text here.

    1.2 Next question?
    Answer text here.
    """
    qa_pairs = []

    pattern = re.split(
        r'\n(?=\d+\.\d+\s)',
        text.strip()
    )

    for block in pattern:
        block = block.strip()
        if not block:
            continue

        lines = block.split('\n', 1)

        if len(lines) < 2:
            continue

        question = clean(lines[0])
        answer = clean(lines[1])

        if len(question) < 10 or len(answer) < 5:
            continue

        question = re.sub(r'^\d+\.\d+\s*', '', question).strip()

        if question and answer:
            qa_pairs.append({
                "question": question,
                "answer": answer
            })

    print(f"Total Q&A parsed: {len(qa_pairs)}")
    return qa_pairs


# ============================================================
# ORIGINAL clean function
# ============================================================

def clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()