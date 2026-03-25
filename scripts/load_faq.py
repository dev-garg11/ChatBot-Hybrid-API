import asyncio
import os
import sys
import selectors
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text
from app.core.database import AsyncSessionLocal
from app.entites.faq_entities import FaqDocument, FaqQuestion, FaqAnswer
from app.utilis.pdf_extracter import extract_faq_from_pdf
from app.utilis.vector_service import get_vector

# ✅ Folder jaha saari PDFs hain
PDF_FOLDER = r"C:\chatbot_data\pdfs"

# ✅ Default type id (type_master table se)
TYPE_ID = 30


async def load_faq(pdf_path: str):
    print(f"\n📄 Processing PDF: {pdf_path}")

    async with AsyncSessionLocal() as db:
        # ✅ Duplicate check
        result = await db.execute(
            select(FaqDocument).where(FaqDocument.file_path == pdf_path)
        )
        existing_doc = result.scalar_one_or_none()
        if existing_doc:
            print("⚠️ FAQ already loaded — skipping")
            return

    print("Step 1 — Extracting Q&A from PDF...")
    qa_pairs = extract_faq_from_pdf(pdf_path)

    if not qa_pairs:
        print("❌ No Q&A found — check the PDF format")
        return

    print(f"✅ Total Q&A found: {len(qa_pairs)}")

    async with AsyncSessionLocal() as db:
        # ✅ Document save — sirf jo columns DB mein hain
        doc_result = await db.execute(text("""
            INSERT INTO faq_documents (file_name, file_path, type_id, is_active, status)
            VALUES (:name, :path, :type_id, true, true) RETURNING id
        """), {
            "name": os.path.basename(pdf_path),
            "path": pdf_path,
            "type_id": TYPE_ID
        })
        document_id = doc_result.scalar()
        print(f"✅ Document saved — ID: {document_id}")

        print("Step 2 — Creating vectors and saving them...")

        saved = 0
        skipped = 0

        for index, pair in enumerate(qa_pairs):
            question_text = pair["question"].strip()
            answer_text = pair["answer"].strip()

            if not question_text or not answer_text:
                skipped += 1
                continue

            print(f"[{index + 1}/{len(qa_pairs)}] {question_text[:60]}")

            # ✅ Duplicate question check
            existing_q = await db.execute(
                select(FaqQuestion).where(FaqQuestion.question_text == question_text)
            )
            if existing_q.scalar_one_or_none():
                print(f"⚠️ Duplicate question — skipping")
                skipped += 1
                continue

            # ✅ Question save
            q_result = await db.execute(text("""
                INSERT INTO faq_questions 
                    (document_id, type_master_id, question_text, question_vector, status)
                VALUES (:doc, :type, :question, :vector, true) RETURNING id
            """), {
                "doc": document_id,
                "type": TYPE_ID,
                "question": question_text,
                "vector": str(get_vector(question_text))
            })
            question_id = q_result.scalar()

            # ✅ Answer save
            await db.execute(text("""
                INSERT INTO faq_answers (question_id, answer_text, status)
                VALUES (:qid, :answer, true)
            """), {
                "qid": question_id,
                "answer": answer_text
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

