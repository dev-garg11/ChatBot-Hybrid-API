import fitz
import json
import httpx
import os
import re
from typing import List, Dict
from app.core.config import settings

OLLAMA_URL = settings.OLLAMA_URL
OLLAMA_MODEL = settings.OLLAMA_MODEL
OLLAMA_TIMEOUT = 120
IMAGE_SAVE_DIR = "app/data/extracted_images"


# ============================================================
# FORMAT DETECTION
# ============================================================

def has_qa_format(text: str) -> bool:
    matches = re.findall(r'\n\d+\.\d+\s+\w', text)
    return len(matches) >= 5


# ============================================================
# CHUNK PARSER — Manual/Documentation PDFs ke liye
# ============================================================

def parse_chunks(doc, chunk_size: int = 3) -> List[Dict]:
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
# MAIN EXTRACT FUNCTION — FIXED
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
        print("[FORMAT] Q&A format detected (1.1, 1.2...) -> parse_qa()")
        doc.close()
        return parse_qa(full_text)
    else:
        print("[FORMAT] Manual/Doc format detected -> parse_chunks()")
        result = parse_chunks(doc, chunk_size=3)
        doc.close()
        return result


# ============================================================
# ORIGINAL parse_qa — 1.1 format ke liye
# ============================================================

def parse_qa(text: str) -> List[Dict]:
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
            qa_pairs.append({"question": question, "answer": answer})

    print(f"Total Q&A parsed: {len(qa_pairs)}")
    return qa_pairs


# ============================================================
# CLEAN FUNCTION
# ============================================================

def clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


# ============================================================
# IMAGE EXTRACTOR
# ============================================================

def extract_images_from_page(doc, page_num: int, document_id: int) -> List[str]:
    os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)

    page = doc[page_num]
    image_list = page.get_images(full=True)
    saved_paths = []

    for img_index, img in enumerate(image_list):
        xref = img[0]
        try:
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]

            if len(image_bytes) < 5000:
                continue

            image_filename = f"doc_{document_id}_page{page_num + 1}_img{img_index + 1}.{image_ext}"
            image_path = os.path.join(IMAGE_SAVE_DIR, image_filename)

            with open(image_path, "wb") as f:
                f.write(image_bytes)

            saved_paths.append(image_path)
            print(f"    🖼️ Image saved: {image_filename}")

        except Exception as e:
            print(f"    ⚠️ Image error: {e}")
            continue

    return saved_paths


# ============================================================
# OLLAMA Q&A EXTRACTOR
# ============================================================

def extract_qa_from_chunk(chunk: str) -> List[Dict]:
    prompt = f"""Extract question-answer pairs from the following document text.

Return a JSON array where each item has "question" and "answer" keys.
Only return the JSON array, nothing else.

TEXT:
{chunk}

OUTPUT:
[{{"question": "...", "answer": "..."}}]"""

    try:
        response = httpx.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 1000
                }
            },
            timeout=OLLAMA_TIMEOUT
        )

        if response.status_code != 200:
            print(f"❌ Ollama error: {response.status_code}")
            return []

        raw = response.json().get("response", "").strip()

        start_idx = raw.find("[")
        end_idx = raw.rfind("]")
        if start_idx != -1 and end_idx != -1:
            raw = raw[start_idx:end_idx + 1]

        qa_pairs = json.loads(raw)

        valid = []
        for item in qa_pairs:
            q = item.get("question", "").strip()
            a = item.get("answer", "").strip()
            if len(q) > 10 and len(a) > 5:
                valid.append({"question": q, "answer": a})

        return valid

    except json.JSONDecodeError as e:
        print(f"⚠️ JSON parse error: {e}")
        return []
    except Exception as e:
        print(f"⚠️ Error: {e}")
        return []


# ============================================================
# FULL PDF Q&A EXTRACTOR (Ollama + Images)
# ============================================================

def extract_pdf_qa(file_path: str, document_id: int = 0) -> List[Dict]:
    print(f"📄 Reading PDF: {file_path}")
    os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)

    doc = fitz.open(file_path)
    total_pages = len(doc)
    print(f"📃 Total pages: {total_pages}")

    all_qa = []

    for page_num in range(total_pages):
        page = doc[page_num]
        page_text = page.get_text()
        page_text = " ".join(page_text.split())

        print(f"\n  📄 Page {page_num + 1}/{total_pages}")

        page_images = extract_images_from_page(doc, page_num, document_id)

        if not page_text.strip():
            print(f"  ⚠️ Empty page — skipping")
            continue

        print(f"  🤖 Extracting Q&A...")
        qa_pairs = extract_qa_from_chunk(page_text)
        print(f"  ✅ Q&A found: {len(qa_pairs)}")

        for qa in qa_pairs:
            qa["image_paths"] = page_images

        all_qa.extend(qa_pairs)

    doc.close()
    print(f"\n📊 Total Q&A: {len(all_qa)}")
    return all_qa