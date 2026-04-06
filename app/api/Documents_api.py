from fastapi import APIRouter, Depends, Body, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from typing import Optional
import os
import re

from app.core.database import get_db
from app.utilis.vector_service import get_vector
from app.utilis.response import ApiResponse
from app.utilis.pdf_extracter import extract_faq_from_pdf
from app.entites.faq_entities import FaqQuestion
from dotenv import load_dotenv

load_dotenv()

# ----------------------------
# ROUTER
# ----------------------------
document_router = APIRouter(prefix="/faq", tags=["Document"])

# ----------------------------
# CONFIG
# ----------------------------
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "data")
BACKUP_DIR_PDFS = os.getenv("PDF_FOLDER", r"C:\chatbot_data\pdfs")
BACKUP_DIR_FAQ  = os.getenv("FAQ_FOLDER",  r"C:\chatbot_data\faq")
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000")

os.makedirs(UPLOAD_DIR,      exist_ok=True)
os.makedirs(BACKUP_DIR_PDFS, exist_ok=True)
os.makedirs(BACKUP_DIR_FAQ,  exist_ok=True)


# ----------------------------
# HELPER
# ----------------------------
def normalize_text(input_text: str) -> str:
    input_text = input_text.lower()
    input_text = re.sub(r"[^a-z0-9\s]", "", input_text)
    return input_text.strip()


# ============================================================
# DOCUMENT ENDPOINTS
# ============================================================

@document_router.post("/add-document", response_model=ApiResponse, summary="Upload PDF & Save Q&A")
async def add_document(
    type_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    try:
        if not file.filename.endswith(".pdf"):
            return ApiResponse(success=False, status_code=400, message="Only PDF files are allowed")

        file_bytes = await file.read()

        # Backup location pe save karo
        server_file_path = os.path.join(BACKUP_DIR_PDFS, file.filename)
        with open(server_file_path, "wb") as f:
            f.write(file_bytes)

        # Local save karo
        local_file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(local_file_path, "wb") as f:
            f.write(file_bytes)

        public_url = f"{SERVER_BASE_URL}/pdfs/{file.filename}"

        # DB mein document record insert karo
        doc_result = await db.execute(text("""
            INSERT INTO faq_documents (file_name, file_path, type_id, is_active, status)
            VALUES (:name, :file_path, :type_id, true, true) RETURNING id
        """), {"name": file.filename, "file_path": public_url, "type_id": type_id})
        document_id = doc_result.scalar()
        await db.commit()

        # PDF se Q&A extract karo
        qa_pairs = extract_faq_from_pdf(local_file_path)
        if not qa_pairs:
            return ApiResponse(
                success=False, status_code=404, message="No Q&A found in PDF",
                data={"document_id": document_id, "file_url": public_url}
            )

        saved, skipped = 0, 0
        for qa in qa_pairs:
            clean_question = normalize_text(qa["question"])
            answer_text    = qa["answer"].strip()

            if not clean_question or not answer_text:
                skipped += 1
                continue

            existing = await db.execute(select(FaqQuestion).where(FaqQuestion.question_text == clean_question))
            if existing.scalar_one_or_none():
                skipped += 1
                continue

            vector = get_vector(clean_question)
            q_result = await db.execute(text("""
                INSERT INTO faq_questions (document_id, type_master_id, question_text, question_vector)
                VALUES (:doc, :type, :question, :vector) RETURNING id
            """), {"doc": document_id, "type": type_id, "question": clean_question, "vector": str(vector)})
            question_id = q_result.scalar()

            await db.execute(
                text("INSERT INTO faq_answers (question_id, answer_text) VALUES (:qid, :answer)"),
                {"qid": question_id, "answer": answer_text}
            )
            saved += 1

        await db.commit()

        return ApiResponse(
            success=True, status_code=201, message="Document uploaded and Q&A saved successfully",
            data={
                "document_id":     document_id,
                "document_name":   file.filename,
                "file_path":       server_file_path,
                "file_url":        public_url,
                "type_id":         type_id,
                "total_extracted": len(qa_pairs),
                "saved":           saved,
                "skipped":         skipped
            }
        )
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@document_router.get("/documents", response_model=ApiResponse, summary="Get All Documents")
async def get_all_documents(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("""
            SELECT id AS document_id, file_name AS document_name,
                   file_path, type_id, uploaded_at AS created_at
            FROM faq_documents
            WHERE status = true
        """))
        rows = result.fetchall()

        return ApiResponse(
            success=True, status_code=200, message="Documents fetched",
            data=[
                {
                    "document_id":   r.document_id,
                    "document_name": r.document_name,
                    "file_path":     r.file_path,
                    "file_url":      f"{SERVER_BASE_URL}/pdfs/{r.document_name}",
                    "type_id":       r.type_id,
                    "created_at":    str(r.created_at)
                }
                for r in rows
            ]
        )
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@document_router.get("/document/{document_id}", response_model=ApiResponse, summary="Get Document by ID")
async def get_document_by_id(document_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("""
            SELECT id AS document_id, file_name AS document_name,
                   file_path, type_id, uploaded_at AS created_at
            FROM faq_documents
            WHERE id = :did AND status = true
        """), {"did": document_id})
        row = result.fetchone()

        if not row:
            return ApiResponse(success=False, status_code=404, message="Document not found")

        return ApiResponse(
            success=True, status_code=200, message="Document found",
            data={
                "document_id":   row.document_id,
                "document_name": row.document_name,
                "file_path":     row.file_path,
                "file_url":      f"{SERVER_BASE_URL}/pdfs/{row.document_name}",
                "type_id":       row.type_id,
                "created_at":    str(row.created_at)
            }
        )
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@document_router.put("/update-document/{document_id}", response_model=ApiResponse, summary="Update Document")
async def update_document(
    document_id:   int,
    document_name: str           = Body(...),
    type_id:       Optional[int] = Body(None),
    db: AsyncSession = Depends(get_db)
):
    try:
        result = await db.execute(
            text("SELECT id FROM faq_documents WHERE id = :id AND status = true"),
            {"id": document_id}
        )
        if not result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Document not found")

        await db.execute(text("""
            UPDATE faq_documents
            SET file_name = :name,
                type_id   = COALESCE(:type_id, type_id)
            WHERE id = :id
        """), {"name": document_name, "type_id": type_id, "id": document_id})
        await db.commit()

        return ApiResponse(
            success=True, status_code=200, message="Document updated successfully",
            data={"document_id": document_id, "document_name": document_name}
        )
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@document_router.delete("/delete-document/{document_id}", response_model=ApiResponse, summary="Delete Document")
async def delete_document(document_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(
            text("SELECT id, file_name FROM faq_documents WHERE id = :id"),
            {"id": document_id}
        )
        row = result.fetchone()
        if not row:
            return ApiResponse(success=False, status_code=404, message="Document not found")

        # Pehle related answers aur questions delete karo
        await db.execute(text("""
            DELETE FROM faq_answers
            WHERE question_id IN (
                SELECT id FROM faq_questions WHERE document_id = :did
            )
        """), {"did": document_id})
        await db.execute(text("DELETE FROM faq_questions WHERE document_id = :did"), {"did": document_id})
        await db.execute(text("DELETE FROM faq_documents WHERE id = :id"),           {"id": document_id})
        await db.commit()

        # Physical files bhi hatao
        for folder in [UPLOAD_DIR, BACKUP_DIR_PDFS, BACKUP_DIR_FAQ]:
            path = os.path.join(folder, row.file_name)
            if os.path.exists(path):
                os.remove(path)

        return ApiResponse(
            success=True, status_code=200, message="Document deleted successfully",
            data={"deleted_document_id": document_id}
        )
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))