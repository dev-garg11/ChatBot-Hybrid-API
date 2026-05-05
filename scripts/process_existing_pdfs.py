import os
import asyncio
import logging
from sqlalchemy import text
from app.core.database import AsyncSessionLocal
from app.services.processing_service import process_single_document

logger = logging.getLogger(__name__)

CONCURRENCY = 3


async def process_doc(doc):
    try:
        if not doc.file_path.startswith(("http://", "https://")) and not os.path.exists(doc.file_path):
            logger.warning(f"Skipping {doc.id} — file not found")

            async with AsyncSessionLocal() as db:
                await db.execute(
                    text("UPDATE faq_documents SET status = 'failed' WHERE id = :doc_id"),
                    {"doc_id": doc.id}
                )
                await db.commit()

            return "skipped"

        async with AsyncSessionLocal() as db:

            # 🔥 mark processing
            await db.execute(
                text("UPDATE faq_documents SET status = 'processing' WHERE id = :doc_id"),
                {"doc_id": doc.id}
            )
            await db.commit()

            await process_single_document(db, doc.id, doc.file_path)

        return "success"

    except Exception as e:
        logger.exception(f"Document {doc.id} failed")

        async with AsyncSessionLocal() as db:
            await db.execute(
                text("UPDATE faq_documents SET status = 'failed' WHERE id = :doc_id"),
                {"doc_id": doc.id}
            )
            await db.commit()

        return "failed"


async def process_all_documents(reprocess: bool = False):
    async with AsyncSessionLocal() as db:

        query = """
            SELECT id, file_path, file_name FROM faq_documents
            WHERE is_active = true
        """ if reprocess else """
            SELECT id, file_path, file_name FROM faq_documents
            WHERE is_active = true
            AND (status IN ('pending', 'failed') OR status IS NULL)
        """

        result = await db.execute(text(query))
        documents = result.fetchall()

    if not documents:
        logger.info("No documents to process")
        return

    logger.info(f"Found {len(documents)} documents")

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def limited(doc):
        async with semaphore:
            return await process_doc(doc)

    tasks = [limited(doc) for doc in documents]
    results = await asyncio.gather(*tasks)

    logger.info(f"""
    =============================
    Processing Complete
    =============================
    Total:    {len(documents)}
    Success:  {results.count("success")}
    Failed:   {results.count("failed")}
    Skipped:  {results.count("skipped")}
    =============================
    """)


if __name__ == "__main__":
    import sys
    reprocess = "--reprocess" in sys.argv
    asyncio.run(process_all_documents(reprocess))