from fastapi import APIRouter, BackgroundTasks, Depends, Query, UploadFile, File, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os
import logging
import hashlib
import uuid 

from app.services.rag_service import get_rag_answer
from app.core.database import get_db, AsyncSessionLocal
from app.services.file_service import save_file
from app.services.processing_service import process_single_document
from app.utilis.query_service import rewrite_query
from app.utilis.query_control import should_rewrite

router = APIRouter(prefix="/pdfs", tags=["PDF Documents"])
logger = logging.getLogger(__name__)


# ============================================================
# BACKGROUND WRAPPER
# ============================================================
async def process_single_document_bg(document_id: int, file_path: str):
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text("UPDATE faq_documents SET status = 'processing' WHERE id = :id"),
                {"id": document_id}
            )
            await db.commit()

            await process_single_document(db, document_id, file_path)

            await db.execute(
                text("UPDATE faq_documents SET status = 'completed' WHERE id = :id"),
                {"id": document_id}
            )
            await db.commit()

            logger.info(f"✅ Document {document_id} processed successfully.")

        except Exception as e:
            logger.error(f"❌ Background processing failed for document {document_id}: {str(e)}")
            await db.execute(
                text("UPDATE faq_documents SET status = 'failed' WHERE id = :id"),
                {"id": document_id}
            )
            await db.commit()


# ============================================================
# UPLOAD
# ============================================================
@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    type_id: int, 
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    unique_name = f"{uuid.uuid4().hex}_{os.path.basename(file.filename).replace(' ', '_')}"


    if not unique_name:
        raise HTTPException(400, "Invalid filename")

    if not unique_name.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files allowed")

    if file.content_type != "application/pdf":
        raise HTTPException(400, "Invalid content type")

    contents = await file.read()

    if len(contents) > 100 * 1024 * 1024:
        raise HTTPException(400, "File too large")

    if not contents.startswith(b"%PDF"):
        raise HTTPException(400, "Invalid PDF file")

    try:
        file_hash = hashlib.sha256(contents).hexdigest()

        result = await db.execute(
            text("SELECT id FROM faq_documents WHERE file_hash = :hash"),
            {"hash": file_hash}
        )
        existing = result.scalar()

        if existing:
            return {
                "message": "Duplicate PDF already exists",
                "document_id": existing
            }

        file_url, file_path = await save_file(file, contents)
        logger.info(f"📂 File stored at: {file_path}")

        result = await db.execute(text("""
            INSERT INTO faq_documents 
            (file_name, file_path, file_hash, type_id, is_active, status)
            VALUES (:name, :path, :hash, :type_id, true, 'pending')
            RETURNING id
        """), {
            "name": unique_name,
            "path": file_url,
            "hash": file_hash,
            "type_id": type_id
        })

        document_id = result.scalar()
        await db.commit()

        background_tasks.add_task(
            process_single_document_bg,
            document_id,
            file_path
        )

        return {
            "message": "PDF uploaded, processing started",
            "document_id": document_id,
            "status": "pending"
        }

    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Upload failed: {str(e)}")
        raise HTTPException(500, f"Upload failed: {str(e)}")


# ============================================================
# GET ALL DOCUMENTS
# ============================================================
@router.get("/documents")
async def get_all_pdf_documents(type_id: int = None, db: AsyncSession = Depends(get_db)):
    try:
        query = """
            SELECT id, file_name, file_path, status, type_id, is_active, total_chunks, uploaded_at
            FROM faq_documents
            WHERE is_active = true
        """
        params = {}

        if type_id:
            query += " AND type_id = :type_id"
            params["type_id"] = type_id

        query += " ORDER BY uploaded_at DESC"

        result = await db.execute(text(query), params)
        rows = result.fetchall()

        return {
            "success": True,
            "total": len(rows),
            "data": [
                {
                    "document_id": r.id,
                    "file_name": r.file_name,
                    "file_path": r.file_path,
                    "status": r.status,
                    "type_id": r.type_id,
                    "total_chunks": r.total_chunks,
                    "uploaded_at": str(r.uploaded_at)
                }
                for r in rows
            ]
        }

    except Exception as e:
        logger.error(f"❌ Get documents failed: {str(e)}")
        raise HTTPException(500, f"Failed to fetch documents: {str(e)}")

# ============================================================
# DELETE DOCUMENT
# ============================================================
@router.delete("/delete/{document_id}")
async def delete_pdf_document(document_id: int, db: AsyncSession = Depends(get_db)):
    try:
        # Document exist karta hai?
        result = await db.execute(
            text("SELECT file_name FROM faq_documents WHERE id = :id AND is_active = true"),
            {"id": document_id}
        )
        row = result.fetchone()

        if not row:
            raise HTTPException(404, "Document not found")

        # pdf_chunks delete karo
        await db.execute(
            text("DELETE FROM pdf_chunks WHERE document_id = :did"),
            {"did": document_id}
        )

        # Document delete karo
        await db.execute(
            text("DELETE FROM faq_documents WHERE id = :id"),
            {"id": document_id}
        )

        await db.commit()

        return {
            "success": True,
            "message": f"Document {document_id} deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Delete failed: {str(e)}")
        raise HTTPException(500, f"Delete failed: {str(e)}")


# ============================================================
# SEARCH
# ============================================================
@router.get("/search")
async def search_documents(
    query: str = Query(...),
    top_k: int = Query(5, ge=1, le=10),
    type_id: int = Query(None),
    db: AsyncSession = Depends(get_db)
):
    try:
        query = query.strip()

        if should_rewrite(query):
            query = await rewrite_query(query)

        rewritten_query = query

        result = await get_rag_answer(rewritten_query, db, top_k=top_k, type_id=type_id)

        return {
            "success": True,
            "query": query,
            "answer": result.get("answer"),
            "sources": result.get("sources", [])
        }

    except Exception as e:
        logger.error(f"Search failed: {str(e)}")
        raise HTTPException(500, f"Search failed: {str(e)}")