import asyncio
import logging
import traceback
from sqlalchemy import text

from app.services.pdf_service import extract_text_and_images
from app.services.chunk_service import chunk_text, vector_to_str
from app.utilis.text_cleaner import clean_text
from app.utilis.vector_service import get_vector

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


async def process_single_document(db, document_id, file_path):

    try:
        # -----------------------------
        # 🔥 SET STATUS = PROCESSING
        # -----------------------------
        await db.execute(
            text("UPDATE faq_documents SET status = 'processing' WHERE id = :doc_id"),
            {"doc_id": document_id}
        )
        await db.commit()

        # -----------------------------
        # 🔥 EXTRACT PDF
        # -----------------------------

        logger.info(f"📄 Extracting PDF: {file_path}")
        pages = await extract_text_and_images(file_path)
        logger.info(f"📄 Pages extracted: {len(pages) if pages else 0}")


        if not pages:
            logger.warning(f"⚠️ No pages extracted for doc {document_id}")
            await db.execute(
                text("UPDATE faq_documents SET status = 'failed' WHERE id = :doc_id"),
                {"doc_id": document_id}
            )
            await db.commit()
            return

        total_chunks = 0
        batch = []

        # -----------------------------
        # 🔥 PROCESS EACH PAGE
        # -----------------------------
        for page in pages:
            raw_text = page.get("text", "")
            logger.info(f"📝 Raw text length: {len(raw_text)}")

            if not raw_text or len(raw_text.strip()) < 20:
                continue

            cleaned_text = clean_text(raw_text)
            logger.info(f"🧹 Cleaned text length: {len(cleaned_text) if cleaned_text else 0}")

            if not cleaned_text or len(cleaned_text.strip()) < 20:
                continue

            chunks = chunk_text(cleaned_text)
            logger.info(f"✂️ Chunks created: {len(chunks) if chunks else 0}")

            if not chunks:
                continue

            # -----------------------------
            # 🔥 PARALLEL EMBEDDINGS
            # -----------------------------
            tasks = [
                asyncio.to_thread(get_vector, chunk)
                for chunk in chunks if chunk.strip()
            ]

            embeddings = await asyncio.gather(*tasks, return_exceptions=True)

            for chunk, emb in zip(chunks, embeddings):

                if isinstance(emb, Exception) or not emb:
                    logger.warning(f"⚠️ Embedding failed: {emb}")
                    continue

                batch.append({
                    "doc_id": document_id,
                    "chunk": chunk,
                    "embedding": vector_to_str(emb)
                })

                total_chunks += 1

                # -----------------------------
                # 🔥 BATCH INSERT
                # -----------------------------
                if len(batch) >= BATCH_SIZE:
                    await db.execute(
                        text("""
                            INSERT INTO pdf_chunks 
                            (document_id, chunk_text, embedding)
                            VALUES (:doc_id, :chunk, CAST(:embedding AS vector))
                        """),
                        batch
                    )
                    await db.commit()
                    batch = []

        # -----------------------------
        # 🔥 FINAL FLUSH
        # -----------------------------
        if batch:
            await db.execute(
                text("""
                    INSERT INTO pdf_chunks 
                    (document_id, chunk_text, embedding)
                    VALUES (:doc_id, :chunk, CAST(:embedding AS vector))
                """),
                batch
            )
            await db.commit()


        # -----------------------------
        # 🔥 UPDATE STATUS
        # -----------------------------
        await db.execute(
            text("""
                UPDATE faq_documents 
                SET status = 'completed', total_chunks = :count 
                WHERE id = :doc_id
            """),
            {"count": total_chunks, "doc_id": document_id}
        )
        await db.commit()

        logger.info(f"✅ Document {document_id} processed | Chunks: {total_chunks}")

    except Exception as e:
        logger.error(f"❌ Processing failed for doc {document_id}: {str(e)}")
        logger.error(traceback.format_exc())  
        await db.rollback()

        await db.execute(
            text("UPDATE faq_documents SET status = 'failed' WHERE id = :doc_id"),
            {"doc_id": document_id}
        )
        await db.commit()