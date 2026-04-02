import asyncio
import os
import sys
import selectors
import httpx
import tempfile
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import AsyncSessionLocal
from app.entites.faq_entities import PdfQuestion, PdfAnswer
from app.utilis.pdf_extracter import extract_pdf_qa
from app.utilis.vector_service import get_vector

PDF_TYPE_ID = 30


def download_pdf(url: str) -> str:
    response = httpx.get(url, timeout=60)
    if response.status_code != 200:
        raise Exception(f"Download failed: {response.status_code}")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(response.content)
    tmp.close()
    return tmp.name


async def load_pdfs():

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("""
                SELECT fd.id, fd.file_path 
                FROM faq_documents fd
                WHERE fd.is_active = true 
                AND fd.type_id = :type_id
                AND NOT EXISTS (
                    SELECT 1 FROM pdf_questions pq 
                    WHERE pq.document_id = fd.id
                )
            """),
            {"type_id": PDF_TYPE_ID}
        )
        files = result.fetchall()

    if not files:
        print("⚠️ No new PDF files to process")
        return

    print(f"📂 Total PDF files to process: {len(files)}")

    for row in files:
        document_id = row[0]
        file_path = row[1]

        print(f"\n{'='*50}")
        print(f"📄 Processing: {file_path}")
        print(f"{'='*50}")

        temp_path = None

        try:
            # ✅ HTTP se download karo
            temp_path = await asyncio.to_thread(download_pdf, file_path)
            print(f"  ✅ Downloaded to temp: {temp_path}")

            # ✅ temp_path use karo file_path nahi
            extracted = await asyncio.to_thread(
                extract_pdf_qa, temp_path, document_id
            )

            qa_pairs = extracted["qa_pairs"]
            image_paths = extracted["image_paths"]

            print(f"✅ Q&A found: {len(qa_pairs)}")
            print(f"✅ Images found: {len(image_paths)}")

            if not qa_pairs:
                print("❌ No Q&A found — skipping")
                continue

            async with AsyncSessionLocal() as db:

                for index, pair in enumerate(qa_pairs):
                    print(f"  [{index + 1}/{len(qa_pairs)}] {pair['question'][:60]}...")

                    q_vector = await asyncio.to_thread(get_vector, pair["question"])
                    a_vector = await asyncio.to_thread(get_vector, pair["answer"])

                    question = PdfQuestion(
                        document_id=document_id,
                        question_text=pair["question"],
                        question_vector=q_vector
                    )
                    db.add(question)
                    await db.flush()

                    # ✅ image_paths bhi save karo
                    image_paths_json = json.dumps(pair.get("image_paths", []))

                    answer = PdfAnswer(
                        question_id=question.id,
                        answer_text=pair["answer"],
                        answer_vector=a_vector,
                        image_paths=image_paths_json
                    )
                    db.add(answer)

                await db.commit()
                print(f"✅ Saved {len(qa_pairs)} Q&A for: {file_path}")

        except Exception as e:
            print(f"💥 Error: {e}")
            continue

        finally:
            # ✅ Temp file delete karo
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    print(f"\n✅ PDF Ingestion completed!")


if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    loop.run_until_complete(load_pdfs())
