import asyncio
import os
import sys
import selectors
import re

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text
from app.core.database import AsyncSessionLocal
from app.entites.faq_entities import FaqDocument
from app.utilis.pdf_extracter import extract_faq_from_pdf
from app.utilis.vector_service import get_vector
from dotenv import load_dotenv
load_dotenv()

# ==============================
# CONFIG — .env se load hoga
# ==============================
BASE_URL   = os.getenv("BASE_URL", "http://10.147.8.83:70/")
PDF_FOLDER = os.getenv("PDF_FOLDER", r"C:\chatbot_data\pdfs")
TYPE_ID    = int(os.getenv("TYPE_ID", 30))


# ==============================
# INDEX FILTER FUNCTION
# ==============================
def is_index_question(question: str):
    pattern = r'^\d+(\.\d+)*\s+[A-Za-z ]+$'
    return bool(re.match(pattern, question.strip()))


# ==============================
# SAFE VECTOR FUNCTION
# ==============================
def safe_vector(text):
    try:
        vector = get_vector(text)

        if vector is None or len(vector) == 0:
            return None

        vector = "[" + ",".join(map(str, vector)) + "]"
        return vector

    except Exception as e:
        print("⚠️ Vector error:", e)
        return None


async def load_faq(pdf_path: str):

    print(f"\n📄 Processing PDF: {pdf_path}")

    async with AsyncSessionLocal() as db:

        result = await db.execute(
            select(FaqDocument).where(FaqDocument.file_path == pdf_path)
        )

        existing_doc = result.scalar_one_or_none()

        if existing_doc:
            print("⚠️ FAQ already loaded — reusing existing document")
            document_id = existing_doc.id

        else:
            doc_result = await db.execute(text("""
                INSERT INTO faq_documents
                (file_name, file_path, type_id, is_active, status)
                VALUES (:name, :path, :type_id, true, true)
                RETURNING id
            """), {
                "name": os.path.basename(pdf_path),
                "path": BASE_URL + os.path.basename(pdf_path),
                "type_id": TYPE_ID
            })

            document_id = doc_result.scalar()
            await db.commit()

            print(f"✅ Document saved — ID: {document_id}")

    print("Step 1 — Extracting Q&A from PDF...")

    qa_pairs = extract_faq_from_pdf(pdf_path)

    if not qa_pairs:
        print("❌ No Q&A found — check PDF format")
        return

    print(f"✅ Total Q&A found: {len(qa_pairs)}")

    async with AsyncSessionLocal() as db:

        print("Step 2 — Creating vectors and saving...")

        saved = 0
        skipped = 0

        for index, pair in enumerate(qa_pairs):

            question_text = pair["question"].strip()
            answer_text   = pair["answer"].strip()

            if not question_text or not answer_text:
                skipped += 1
                continue

            if is_index_question(question_text):
                print("⚠️ Index skipped")
                skipped += 1
                continue

            print(f"[{index+1}/{len(qa_pairs)}] {question_text[:60]}")

            existing_q = await db.execute(
                text("""
                    SELECT id FROM faq_questions
                    WHERE question_text=:q AND document_id=:doc
                """),
                {"q": question_text, "doc": document_id}
            )

            if existing_q.first():
                print("⚠️ Duplicate — skipping")
                skipped += 1
                continue

            question_vector = safe_vector(question_text)
            answer_vector   = safe_vector(answer_text)

            if question_vector is None or answer_vector is None:
                print("⚠️ Vector generation failed — skipping")
                skipped += 1
                continue

            q_result = await db.execute(text("""
                INSERT INTO faq_questions
                (document_id, type_master_id, question_text, question_vector, status)
                VALUES (:doc, :type, :question, :vector, true)
                RETURNING id
            """), {
                "doc":      document_id,
                "type":     TYPE_ID,
                "question": question_text,
                "vector":   question_vector
            })

            question_id = q_result.scalar()

            await db.execute(text("""
                INSERT INTO faq_answers
                (question_id, answer_text, answer_vector, status)
                VALUES (:qid, :answer, :vector, true)
            """), {
                "qid":    question_id,
                "answer": answer_text,
                "vector": answer_vector
            })

            saved += 1

        await db.commit()

    print(f"✅ Done! Saved: {saved} | Skipped: {skipped}")


async def load_all_pdfs():
    for file in os.listdir(PDF_FOLDER):
        if file.endswith(".pdf"):
            pdf_path = os.path.join(PDF_FOLDER, file)
            await load_faq(pdf_path)


if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    loop.run_until_complete(load_all_pdfs())