import asyncio
import os
import sys
import selectors

# Add project root path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.entites.faq_entities import FaqDocument, FaqQuestion, FaqAnswer
from app.utilis.pdf_extracter import extract_faq_from_pdf
from app.utilis.vector_service import get_vector

PDF_PATH = "http://10.147.8.83:70/faq.pdf"


async def load_faq():

    # ✅ Duplicate check
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("SELECT COUNT(*) FROM faq_documents WHERE file_name = 'faq.pdf'")
        )
        count = result.scalar()
        if count > 0:
            print("⚠️ FAQ already loaded — skipping")
            return

    print(f"PDF path: {PDF_PATH}")
    print("Step 1 — Extracting Q&A from PDF...")

    qa_pairs = extract_faq_from_pdf(PDF_PATH)

    if not qa_pairs:
        print("❌ No Q&A found — check the PDF format")
        return

    print(f"✅ Total Q&A found: {len(qa_pairs)}")

    async with AsyncSessionLocal() as db:

        # Document record
        document = FaqDocument(file_name=os.path.basename(PDF_PATH))
        db.add(document)
        await db.flush()
        print(f"✅ Document saved — ID: {document.id}")

        print("Step 2 — Creating vectors and saving them to the database...")

        for index, pair in enumerate(qa_pairs):

            print(f"  [{index + 1}/{len(qa_pairs)}] {pair['question'][:60]}...")

            # Question + vector
            question = FaqQuestion(
                document_id=document.id,
                question_text=pair["question"],
                question_vector=get_vector(pair["question"])
            )
            db.add(question)
            await db.flush()

            # Answer + vector
            answer = FaqAnswer(
                question_id=question.id,
                answer_text=pair["answer"],
                answer_vector=get_vector(pair["answer"])
            )
            db.add(answer)

        await db.commit()

    print(f"\n✅ Done! {len(qa_pairs)} Q&A saved in the database")


if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    loop.run_until_complete(load_faq())