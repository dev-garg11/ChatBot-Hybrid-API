import fitz
import re
from typing import List, Dict


def extract_faq_from_pdf(file_path: str) -> List[Dict]:
    doc = fitz.open(file_path)

    full_text = ""
    for page in doc:
        full_text += page.get_text()

    doc.close()

    print("=== Extracted Text (first 500 chars) ===")
    print(full_text[:500])

    return parse_qa(full_text)


def parse_qa(text: str) -> List[Dict]:
    """
    PDF format:
    1.1 Question text?
    Answer text here.

    1.2 Next question?
    Answer text here.
    """
    qa_pairs = []

    # ✅ Pattern — numbered like 1.1, 1.2, 2.1, 2.2 etc.
    # Question = line starting with number like 1.1
    # Answer = text after it until next numbered question
    pattern = re.split(
        r'\n(?=\d+\.\d+\s)',  # split at newline followed by number like "1.1 "
        text.strip()
    )

    for block in pattern:
        block = block.strip()
        if not block:
            continue

        # First line = question, rest = answer
        lines = block.split('\n', 1)

        if len(lines) < 2:
            continue

        question = clean(lines[0])
        answer = clean(lines[1])

        # Skip if too short
        if len(question) < 10 or len(answer) < 5:
            continue

        # Remove leading number like "1.1 " from question
        question = re.sub(r'^\d+\.\d+\s*', '', question).strip()

        if question and answer:
            qa_pairs.append({
                "question": question,
                "answer": answer
            })

    print(f"Total Q&A parsed: {len(qa_pairs)}")
    return qa_pairs


def clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()