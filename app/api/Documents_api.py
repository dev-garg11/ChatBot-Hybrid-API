from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from typing import Optional
import os
import re
import uuid
import json

from pydantic import BaseModel

from app.core.database import get_db
from app.utilis.vector_service import get_vector
from app.utilis.response import ApiResponse
from app.utilis.pdf_extracter import extract_faq_from_pdf
from app.entites.faq_entities import FaqQuestion
from dotenv import load_dotenv

load_dotenv()

document_router = APIRouter(prefix="/faq", tags=["Document"])

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "data")
BACKUP_DIR_PDFS = os.getenv("PDF_FOLDER", r"C:\chatbot_data\pdfs")
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR_PDFS, exist_ok=True)


def normalize_text(input_text: str) -> str:
    input_text = input_text.lower()
    input_text = re.sub(r"[^a-z0-9\s]", "", input_text)
    return input_text.strip()


# ============================================================
# PYDANTIC MODEL FOR UPDATE
# ============================================================

class DocumentUpdateRequest(BaseModel):
    type_id: Optional[int] = None
    is_active: Optional[bool] = None
    status: Optional[bool] = None


# ============================================================
# ADD DOCUMENT
# ============================================================

@document_router.post("/add-document", response_model=ApiResponse)
async def add_document(
    type_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    try:
        if not file.filename.lower().endswith(".pdf"):
            return ApiResponse(False, 400, "Only PDF files are allowed")

        file_bytes = await file.read()

        unique_filename = f"{uuid.uuid4()}_{file.filename}"
        server_file_path = os.path.join(BACKUP_DIR_PDFS, unique_filename)
        local_file_path = os.path.join(UPLOAD_DIR, unique_filename)

        with open(server_file_path, "wb") as f:
            f.write(file_bytes)

        with open(local_file_path, "wb") as f:
            f.write(file_bytes)

        public_url = f"{SERVER_BASE_URL}/pdfs/{unique_filename}"

        qa_pairs = extract_faq_from_pdf(local_file_path)

        if not qa_pairs:
            return ApiResponse(False, 404, "No Q&A found in PDF")

        doc_result = await db.execute(text("""
            INSERT INTO faq_documents (file_name, file_path, type_id, is_active, status)
            VALUES (:name, :file_path, :type_id, true, true)
            RETURNING id
        """), {
            "name": unique_filename,
            "file_path": public_url,
            "type_id": type_id
        })

        document_id = doc_result.scalar()

        saved = 0
        skipped = 0

        for qa in qa_pairs:

            clean_question = normalize_text(qa["question"])
            answer_text = qa["answer"].strip()

            if not clean_question or not answer_text:
                skipped += 1
                continue

            existing = await db.execute(
                select(FaqQuestion).where(
                    FaqQuestion.question_text == clean_question,
                    FaqQuestion.document_id == document_id
                )
            )

            if existing.scalar_one_or_none():
                skipped += 1
                continue

            vector = get_vector(clean_question)

            if not vector:
                skipped += 1
                continue

            q_result = await db.execute(text("""
                INSERT INTO faq_questions (document_id, type_master_id, question_text, question_vector)
                VALUES (:doc, :type, :question, :vector)
                RETURNING id
            """), {
                "doc": document_id,
                "type": type_id,
                "question": clean_question,
                "vector": json.dumps(vector)
            })

            question_id = q_result.scalar()

            await db.execute(text("""
                INSERT INTO faq_answers (question_id, answer_text)
                VALUES (:qid, :answer)
            """), {
                "qid": question_id,
                "answer": answer_text
            })

            saved += 1

        await db.commit()

        return ApiResponse(
            True,
            201,
            "Document uploaded and Q&A saved successfully",
            {
                "document_id": document_id,
                "document_name": unique_filename,
                "file_url": public_url,
                "type_id": type_id,
                "total_extracted": len(qa_pairs),
                "saved": saved,
                "skipped": skipped
            }
        )

    except Exception as e:
        await db.rollback()
        return ApiResponse(False, 500, "Something went wrong", str(e))


# ============================================================
# GET ALL DOCUMENTS
# ============================================================

@document_router.get("/documents", response_model=ApiResponse)
async def get_all_documents(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("""
            SELECT id AS document_id,
                   file_name AS document_name,
                   file_path,
                   type_id,
                   uploaded_at AS created_at
            FROM faq_documents
            WHERE status = true
        """))

        rows = result.fetchall()

        documents = []

        for r in rows:
            documents.append({
                "document_id": r.document_id,
                "document_name": r.document_name,
                "file_path": r.file_path,
                "file_url": f"{SERVER_BASE_URL}/pdfs/{r.document_name}",
                "type_id": r.type_id,
                "created_at": str(r.created_at)
            })

        return ApiResponse(True, 200, "Documents fetched", documents)

    except Exception as e:
        return ApiResponse(False, 500, "Something went wrong", str(e))


# ============================================================
# UPDATE DOCUMENT
# ============================================================

@document_router.put("/update-document/{document_id}", response_model=ApiResponse)
async def update_document(
    document_id: int,
    body: DocumentUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    try:
        result = await db.execute(
            text("SELECT id FROM faq_documents WHERE id = :id"),
            {"id": document_id}
        )

        if not result.fetchone():
            return ApiResponse(False, 404, "Document not found")

        fields = []
        params = {"id": document_id}

        if body.type_id is not None:
            fields.append("type_id = :type_id")
            params["type_id"] = body.type_id

        if body.is_active is not None:
            fields.append("is_active = :is_active")
            params["is_active"] = body.is_active

        if body.status is not None:
            fields.append("status = :status")
            params["status"] = body.status

        if not fields:
            return ApiResponse(False, 400, "No fields provided to update")

        query = f"UPDATE faq_documents SET {', '.join(fields)} WHERE id = :id"

        await db.execute(text(query), params)
        await db.commit()

        return ApiResponse(True, 200, "Document updated successfully", {"document_id": document_id})

    except Exception as e:
        await db.rollback()
        return ApiResponse(False, 500, "Update failed", str(e))


# ============================================================
# DELETE DOCUMENT
# ============================================================

@document_router.delete("/delete-document/{document_id}", response_model=ApiResponse)
async def delete_document(document_id: int, db: AsyncSession = Depends(get_db)):
    try:

        result = await db.execute(
            text("SELECT file_name FROM faq_documents WHERE id = :id"),
            {"id": document_id}
        )

        row = result.fetchone()

        if not row:
            return ApiResponse(False, 404, "Document not found")

        await db.execute(text("""
            DELETE FROM faq_answers
            WHERE question_id IN (
                SELECT id FROM faq_questions WHERE document_id = :did
            )
        """), {"did": document_id})

        await db.execute(
            text("DELETE FROM faq_questions WHERE document_id = :did"),
            {"did": document_id}
        )

        await db.execute(
            text("DELETE FROM faq_documents WHERE id = :id"),
            {"id": document_id}
        )

        await db.commit()

        filename = row.file_name

        for folder in [UPLOAD_DIR, BACKUP_DIR_PDFS]:
            path = os.path.join(folder, filename)
            if os.path.exists(path):
                os.remove(path)

        return ApiResponse(True, 200, "Document deleted successfully")

    except Exception as e:
        await db.rollback()
        return ApiResponse(False, 500, "Something went wrong", str(e))