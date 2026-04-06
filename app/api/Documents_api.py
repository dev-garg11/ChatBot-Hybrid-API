from fastapi import APIRouter, Depends, Body, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from typing import Optional
import os
import re
import uuid
import json

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
BACKUP_DIR_FAQ = os.getenv("FAQ_FOLDER", r"C:\chatbot_data\faq")
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR_PDFS, exist_ok=True)
os.makedirs(BACKUP_DIR_FAQ, exist_ok=True)

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

        # -------- PDF VALIDATION --------
        if not file.filename.lower().endswith(".pdf"):
            return ApiResponse(success=False, status_code=400, message="Only PDF files are allowed")

        file_bytes = await file.read()

        # -------- UNIQUE FILE NAME --------
        unique_filename = f"{uuid.uuid4()}_{file.filename}"

        server_file_path = os.path.join(BACKUP_DIR_PDFS, unique_filename)
        local_file_path = os.path.join(UPLOAD_DIR, unique_filename)

        # -------- SAVE FILES --------
        with open(server_file_path, "wb") as f:
            f.write(file_bytes)

        with open(local_file_path, "wb") as f:
            f.write(file_bytes)

        public_url = f"{SERVER_BASE_URL}/pdfs/{unique_filename}"

        # -------- INSERT DOCUMENT --------
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
        await db.commit()

        # -------- EXTRACT FAQ --------
        qa_pairs = extract_faq_from_pdf(local_file_path)

        if not qa_pairs:
            return ApiResponse(
                success=False,
                status_code=404,
                message="No Q&A found in PDF",
                data={
                    "document_id": document_id,
                    "file_url": public_url
                }
            )

        saved = 0
        skipped = 0

        for qa in qa_pairs:

            clean_question = normalize_text(qa["question"])
            answer_text = qa["answer"].strip()

            if not clean_question or not answer_text:
                skipped += 1
                continue

            # -------- DUPLICATE CHECK --------
            existing = await db.execute(
                select(FaqQuestion).where(FaqQuestion.question_text.ilike(clean_question))
            )

            if existing.scalar_one_or_none():
                skipped += 1
                continue

            # -------- VECTOR GENERATE --------
            vector = get_vector(clean_question)

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
            success=True,
            status_code=201,
            message="Document uploaded and Q&A saved successfully",
            data={
                "document_id": document_id,
                "document_name": unique_filename,
                "file_path": server_file_path,
                "file_url": public_url,
                "type_id": type_id,
                "total_extracted": len(qa_pairs),
                "saved": saved,
                "skipped": skipped
            }
        )

    except Exception as e:
        return ApiResponse(
            success=False,
            status_code=500,
            message="Something went wrong",
            data=str(e)
        )


# ============================================================
# GET ALL DOCUMENTS
# ============================================================

@document_router.get("/documents", response_model=ApiResponse, summary="Get All Documents")
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

        return ApiResponse(
            success=True,
            status_code=200,
            message="Documents fetched",
            data=documents
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ============================================================
# GET DOCUMENT BY ID
# ============================================================

@document_router.get("/document/{document_id}", response_model=ApiResponse)
async def get_document_by_id(document_id: int, db: AsyncSession = Depends(get_db)):
    try:

        result = await db.execute(text("""
            SELECT id AS document_id,
                   file_name AS document_name,
                   file_path,
                   type_id,
                   uploaded_at AS created_at
            FROM faq_documents
            WHERE id = :did AND status = true
        """), {"did": document_id})

        row = result.fetchone()

        if not row:
            return ApiResponse(success=False, status_code=404, message="Document not found")

        return ApiResponse(
            success=True,
            status_code=200,
            message="Document found",
            data={
                "document_id": row.document_id,
                "document_name": row.document_name,
                "file_path": row.file_path,
                "file_url": f"{SERVER_BASE_URL}/pdfs/{row.document_name}",
                "type_id": row.type_id,
                "created_at": str(row.created_at)
            }
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ============================================================
# DELETE DOCUMENT
# ============================================================

@document_router.delete("/delete-document/{document_id}", response_model=ApiResponse)
async def delete_document(document_id: int, db: AsyncSession = Depends(get_db)):
    try:

        result = await db.execute(
            text("SELECT id, file_name FROM faq_documents WHERE id = :id"),
            {"id": document_id}
        )

        row = result.fetchone()

        if not row:
            return ApiResponse(success=False, status_code=404, message="Document not found")

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

        filename = os.path.basename(row.file_name)

        for folder in [UPLOAD_DIR, BACKUP_DIR_PDFS, BACKUP_DIR_FAQ]:
            path = os.path.join(folder, filename)
            if os.path.exists(path):
                os.remove(path)

        return ApiResponse(
            success=True,
            status_code=200,
            message="Document deleted successfully",
            data={"deleted_document_id": document_id}
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))