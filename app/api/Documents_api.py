from fastapi import APIRouter, Depends, UploadFile, File, Query, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Any
from sqlalchemy import text
import os
import re
import uuid
import logging
import asyncio

from app.core.database import NeonHTTPSession, get_db
from app.utilis.vector_service import get_vector
from app.utilis.pdf_extracter import extract_faq_from_pdf

document_router = APIRouter(
    prefix="/documents",
    tags=["Documents"]
)

# ============================================================
# CONFIG
# ============================================================

SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000")
MAX_FILE_SIZE   = int(os.getenv("MAX_FILE_SIZE", 5 * 1024 * 1024))

logger = logging.getLogger(__name__)


def _make_writable_dir(env_key: str, fallback: str) -> str:
    """
    Return a guaranteed-writable directory.
    Tries the env var value first; if that path raises PermissionError
    (e.g. PDF_FOLDER=/data on Render free tier), silently uses fallback.
    """
    candidate = os.getenv(env_key, fallback)
    try:
        os.makedirs(candidate, exist_ok=True)
        test = os.path.join(candidate, ".write_test")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
        return candidate
    except (PermissionError, OSError) as exc:
        logger.warning(
            f"[startup] {env_key}='{candidate}' not writable ({exc}). "
            f"Falling back to '{fallback}'."
        )
        os.makedirs(fallback, exist_ok=True)
        return fallback


# Resolved at import time — guaranteed writable regardless of env var values
UPLOAD_DIR      = _make_writable_dir("UPLOAD_DIR", "/tmp/uploads")
BACKUP_DIR_PDFS = _make_writable_dir("PDF_FOLDER", "/tmp/pdfs")


# ============================================================
# RESPONSE MODEL
# ============================================================

class StandardResponse(BaseModel):
    success: bool
    status_code: int
    message: str
    data: Optional[Any] = None


# ============================================================
# RESPONSE HELPERS
# ============================================================

def error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success":     False,
            "status_code": status_code,
            "message":     message,
            "data":        None,
        },
    )


def success_response(message: str, data: Any = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success":     True,
            "status_code": status_code,
            "message":     message,
            "data":        data,
        },
    )


# ============================================================
# HELPERS
# ============================================================

def normalize_text(txt: str) -> str:
    """Lowercase, strip punctuation and spaces — used for duplicate detection."""
    if not txt:
        return ""
    txt = txt.lower().strip()
    txt = re.sub(r"[^a-z0-9\s]", "", txt)
    txt = re.sub(r"\s+", "", txt)
    return txt


def safe_remove(path: Optional[str]) -> None:
    """Delete a file silently — ignores missing-file errors."""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError as exc:
            logger.warning(f"Could not delete temp file {path}: {exc}")


async def safe_vector(txt: str, retries: int = 3) -> Optional[list]:
    """Generate embedding vector with retry + 30-second timeout."""
    for attempt in range(retries):
        try:
            vec = await asyncio.wait_for(
                asyncio.to_thread(get_vector, txt),
                timeout=30,
            )
            if vec:
                return vec
        except asyncio.TimeoutError:
            logger.warning(f"Vector timeout — attempt {attempt + 1}/{retries}")
        except Exception as exc:
            logger.error(f"Vector error: {exc}")
    return None


def format_vector(vector: Optional[list]) -> Optional[str]:
    """Convert float list → pgvector literal '[0.123,...,0.456]'."""
    if not vector:
        return None
    try:
        return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
    except Exception as exc:
        logger.error(f"Vector format error: {exc}")
        return None


# ============================================================
# GET ALL DOCUMENTS
# ============================================================

@document_router.get("/", response_model=StandardResponse)
async def get_all_documents(
    type_id: Optional[int] = Query(None, ge=1),
    page:    int           = Query(1,    ge=1),
    limit:   int           = Query(10,   ge=1, le=100),
    db:      NeonHTTPSession = Depends(get_db),
):
    try:
        conditions: list[str] = ["d.status = true"]
        params: dict = {}

        if type_id:
            type_check = await db.execute(
                text("""
                    SELECT 1 FROM type_master
                    WHERE type_master_id = :tid AND is_active = true
                """),
                {"tid": type_id},
            )
            if not type_check.scalar():
                return error_response(404, f"type_id {type_id} not found")

            conditions.append("d.type_id = :type_id")
            params["type_id"] = type_id

        where_clause = "WHERE " + " AND ".join(conditions)
        offset = (page - 1) * limit
        params.update({"limit": limit, "offset": offset})

        # total count
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM faq_documents d {where_clause}"),
            params,
        )
        total_items = count_result.scalar() or 0

        if total_items == 0:
            return success_response(
                "No documents found",
                {"items": [], "page": page, "limit": limit,
                 "total_items": 0, "total_pages": 0},
            )

        total_pages = (total_items + limit - 1) // limit

        if page > total_pages:
            return error_response(400, "Invalid page number")

        result = await db.execute(
            text(f"""
                SELECT
                    d.id,
                    d.file_name,
                    d.file_path,
                    d.type_id,
                    d.status,
                    d.uploaded_at,
                    t.type_name,
                    COUNT(q.id) FILTER (WHERE q.status = true) AS total_questions
                FROM faq_documents d
                LEFT JOIN type_master t  ON t.type_master_id = d.type_id
                LEFT JOIN faq_questions q ON q.document_id   = d.id
                {where_clause}
                GROUP BY
                    d.id, d.file_name, d.file_path,
                    d.type_id, d.status, d.uploaded_at,
                    t.type_name
                ORDER BY d.uploaded_at DESC NULLS LAST
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()

        return success_response(
            "Documents fetched successfully",
            {
                "items": [
                    {
                        "document_id":     str(row.id),
                        "file_name":       row.file_name,
                        "file_url":        row.file_path,
                        "type_id":         str(row.type_id),
                        "type_name":       row.type_name,
                        "status":          row.status,
                        "total_questions": row.total_questions or 0,
                        "uploaded_at":     str(row.uploaded_at) if row.uploaded_at else None,
                    }
                    for row in rows
                ],
                "page":        page,
                "limit":       limit,
                "total_items": total_items,
                "total_pages": total_pages,
            },
        )

    except Exception as exc:
        logger.exception(f"GET ALL DOCUMENTS ERROR: {exc}")
        return error_response(500, f"Internal server error: {exc}")


# ============================================================
# GET DOCUMENT BY ID
# ============================================================

@document_router.get("/{document_id}", response_model=StandardResponse)
async def get_document_by_id(
    document_id: int,
    db: NeonHTTPSession = Depends(get_db),
):
    try:
        result = await db.execute(
            text("""
                SELECT
                    d.id,
                    d.file_name,
                    d.file_path,
                    d.type_id,
                    d.status,
                    d.uploaded_at,
                    t.type_name,
                    COUNT(q.id) FILTER (WHERE q.status = true) AS total_questions
                FROM faq_documents d
                LEFT JOIN type_master t   ON t.type_master_id = d.type_id
                LEFT JOIN faq_questions q ON q.document_id    = d.id
                WHERE d.id = :id AND d.status = true
                GROUP BY
                    d.id, d.file_name, d.file_path,
                    d.type_id, d.status, d.uploaded_at,
                    t.type_name
            """),
            {"id": document_id},
        )
        row = result.fetchone()

        if not row:
            return error_response(404, "Document not found")

        return success_response(
            "Document fetched successfully",
            {
                "document_id":     str(row.id),
                "file_name":       row.file_name,
                "file_url":        row.file_path,
                "type_id":         str(row.type_id),
                "type_name":       row.type_name,
                "status":          row.status,
                "total_questions": row.total_questions or 0,
                "uploaded_at":     str(row.uploaded_at) if row.uploaded_at else None,
            },
        )

    except Exception as exc:
        logger.exception(f"GET DOCUMENT ERROR: {exc}")
        return error_response(500, f"Internal server error: {exc}")


# ============================================================
# ADD DOCUMENT — PDF UPLOAD
# ============================================================

@document_router.post("/upload", response_model=StandardResponse, status_code=201)
async def add_document(
    type_id: int         = Form(..., ge=1),
    file:    UploadFile  = File(...),
    db:      NeonHTTPSession = Depends(get_db),
):
    # Track temp paths so we can clean up on any failure
    file_path   = None
    backup_path = None

    try:
        # ── type validation ──────────────────────────────────
        type_check = await db.execute(
            text("""
                SELECT 1 FROM type_master
                WHERE type_master_id = :tid AND is_active = true
            """),
            {"tid": type_id},
        )
        if not type_check.scalar():
            return error_response(400, "Invalid type_id")

        # ── file validation ──────────────────────────────────
        if not file.filename:
            return error_response(400, "File is required")

        if not file.filename.lower().endswith(".pdf"):
            return error_response(400, "Only PDF files are allowed")

        content = await file.read()

        if not content:
            return error_response(400, "Empty file uploaded")

        if len(content) > MAX_FILE_SIZE:
            return error_response(
                400,
                f"File too large. Max size: {MAX_FILE_SIZE // (1024 * 1024)} MB",
            )

        # ── save to /tmp ─────────────────────────────────────
        safe_name       = re.sub(r"[^\w\-.]", "_", file.filename)
        unique_filename = f"{uuid.uuid4()}_{safe_name}"
        file_path       = os.path.join(UPLOAD_DIR,      unique_filename)
        backup_path     = os.path.join(BACKUP_DIR_PDFS, unique_filename)

        with open(file_path, "wb") as fh:
            fh.write(content)
        with open(backup_path, "wb") as fh:
            fh.write(content)

        public_url = f"{SERVER_BASE_URL}/pdfs/{unique_filename}"

        # ── extract Q&A ──────────────────────────────────────
        logger.info(f"[PDF] Extracting FAQ from: {unique_filename}")
        qa_pairs = extract_faq_from_pdf(file_path)
        logger.info(f"[PDF] Extracted {len(qa_pairs) if qa_pairs else 0} QA pairs")

        if not qa_pairs:
            safe_remove(file_path)
            safe_remove(backup_path)
            return error_response(422, "No Q&A pairs found in PDF")

        # ── insert document row ──────────────────────────────
        doc_result = await db.execute(
            text("""
                INSERT INTO faq_documents
                    (file_name, file_path, type_id, status, uploaded_at)
                VALUES
                    (:name, :path, :type_id, true, NOW())
                RETURNING id
            """),
            {"name": unique_filename, "path": public_url, "type_id": type_id},
        )
        document_id = doc_result.scalar()
        logger.info(f"[PDF] Document saved — id: {document_id}")

        saved   = 0
        skipped = 0

        # ── process each Q&A pair ────────────────────────────
        for qa in qa_pairs:
            try:
                raw_q   = qa.get("question", "").strip()
                raw_ans = qa.get("answer",   "").strip()

                if not raw_q or not raw_ans:
                    skipped += 1
                    continue

                norm_q = normalize_text(raw_q)

                # duplicate check (within same document)
                dup = await db.execute(
                    text("""
                        SELECT 1 FROM faq_questions
                        WHERE document_id = :doc
                          AND LOWER(REGEXP_REPLACE(question_text, '[^a-z0-9]', '', 'g')) = :norm
                          AND status = true
                    """),
                    {"doc": document_id, "norm": norm_q},
                )
                if dup.scalar():
                    skipped += 1
                    continue

                # question vector
                q_vec_str = format_vector(await safe_vector(raw_q))

                if q_vec_str:
                    q_result = await db.execute(
                        text("""
                            INSERT INTO faq_questions
                                (document_id, type_master_id, question_text,
                                 question_vector, status, created_at, updated_at)
                            VALUES
                                (:doc, :type_id, :question,
                                 CAST(:vec AS vector), true, NOW(), NOW())
                            RETURNING id
                        """),
                        {"doc": document_id, "type_id": type_id,
                         "question": raw_q, "vec": q_vec_str},
                    )
                else:
                    q_result = await db.execute(
                        text("""
                            INSERT INTO faq_questions
                                (document_id, type_master_id, question_text,
                                 status, created_at, updated_at)
                            VALUES
                                (:doc, :type_id, :question, true, NOW(), NOW())
                            RETURNING id
                        """),
                        {"doc": document_id, "type_id": type_id, "question": raw_q},
                    )

                question_id = q_result.scalar()

                # answer vector
                ans_vec_str = format_vector(await safe_vector(raw_ans))

                if ans_vec_str:
                    await db.execute(
                        text("""
                            INSERT INTO faq_answers
                                (question_id, answer_text, answer_vector,
                                 status, created_at, updated_at)
                            VALUES
                                (:qid, :answer, CAST(:vec AS vector),
                                 true, NOW(), NOW())
                        """),
                        {"qid": question_id, "answer": raw_ans, "vec": ans_vec_str},
                    )
                else:
                    await db.execute(
                        text("""
                            INSERT INTO faq_answers
                                (question_id, answer_text, status, created_at, updated_at)
                            VALUES
                                (:qid, :answer, true, NOW(), NOW())
                        """),
                        {"qid": question_id, "answer": raw_ans},
                    )

                saved += 1
                logger.info(f"[PDF] Saved QA {saved}: {raw_q[:60]}...")

            except Exception as inner:
                logger.warning(f"[PDF] Skipping QA pair — {inner}")
                skipped += 1

        await db.commit()

        # ── clean up temp files after successful processing ──
        # (Q&A is now in DB; keeping raw PDFs on /tmp is pointless
        #  and wastes ephemeral disk space)
        safe_remove(file_path)
        safe_remove(backup_path)

        logger.info(f"[PDF] Done — saved: {saved}, skipped: {skipped}")

        return success_response(
            "Document uploaded successfully",
            {
                "document_id":     str(document_id),
                "file_name":       unique_filename,
                "file_url":        public_url,
                "total_extracted": len(qa_pairs),
                "saved":           saved,
                "skipped":         skipped,
            },
            201,
        )

    except Exception as exc:
        await db.rollback()
        safe_remove(file_path)
        safe_remove(backup_path)
        logger.exception(f"DOCUMENT UPLOAD ERROR: {exc}")
        return error_response(500, f"Internal server error: {exc}")


# ============================================================
# UPDATE DOCUMENT
# ============================================================

@document_router.put("/{document_id}", response_model=StandardResponse)
async def update_document(
    document_id: int,
    type_id: Optional[int]          = Form(None),
    file:    Optional[UploadFile]   = File(None),
    db:      NeonHTTPSession        = Depends(get_db),
):
    new_file_path   = None
    new_backup_path = None

    try:
        existing = await db.execute(
            text("SELECT id, file_name, status FROM faq_documents WHERE id = :id"),
            {"id": document_id},
        )
        existing_doc = existing.fetchone()

        if not existing_doc:
            return error_response(404, "Document not found")
        if not existing_doc.status:
            return error_response(400, "Document already deleted")

        update_fields: list[str] = []
        params: dict = {"id": document_id}

        # ── optional type update ─────────────────────────────
        if type_id is not None:
            type_check = await db.execute(
                text("""
                    SELECT 1 FROM type_master
                    WHERE type_master_id = :tid AND is_active = true
                """),
                {"tid": type_id},
            )
            if not type_check.scalar():
                return error_response(400, "Invalid type_id")

            update_fields.append("type_id = :type_id")
            params["type_id"] = type_id

            await db.execute(
                text("""
                    UPDATE faq_questions
                    SET type_master_id = :tid, updated_at = NOW()
                    WHERE document_id = :doc
                """),
                {"tid": type_id, "doc": document_id},
            )

        # ── optional file replacement ────────────────────────
        if file:
            if not file.filename.lower().endswith(".pdf"):
                return error_response(400, "Only PDF files are allowed")

            content = await file.read()
            if len(content) > MAX_FILE_SIZE:
                return error_response(400, "File too large")

            safe_name       = re.sub(r"[^\w\-.]", "_", file.filename)
            unique_filename = f"{uuid.uuid4()}_{safe_name}"
            new_file_path   = os.path.join(UPLOAD_DIR,      unique_filename)
            new_backup_path = os.path.join(BACKUP_DIR_PDFS, unique_filename)

            with open(new_file_path, "wb") as fh:
                fh.write(content)
            with open(new_backup_path, "wb") as fh:
                fh.write(content)

            public_url = f"{SERVER_BASE_URL}/pdfs/{unique_filename}"
            update_fields.extend(["file_name = :file_name", "file_path = :file_path"])
            params.update({"file_name": unique_filename, "file_path": public_url})

        if not update_fields:
            return error_response(400, "No update data provided")

        set_clause = ", ".join(update_fields)
        result = await db.execute(
            text(f"""
                UPDATE faq_documents
                SET {set_clause}
                WHERE id = :id
                RETURNING id, file_name, file_path, type_id, status, uploaded_at
            """),
            params,
        )
        updated = result.fetchone()

        # clean up old temp files (best-effort)
        if file:
            safe_remove(os.path.join(UPLOAD_DIR,      existing_doc.file_name))
            safe_remove(os.path.join(BACKUP_DIR_PDFS, existing_doc.file_name))

        await db.commit()

        return success_response(
            "Document updated successfully",
            {
                "document_id": str(updated.id),
                "file_name":   updated.file_name,
                "file_url":    updated.file_path,
                "type_id":     str(updated.type_id),
                "status":      updated.status,
                "uploaded_at": str(updated.uploaded_at) if updated.uploaded_at else None,
            },
        )

    except Exception as exc:
        await db.rollback()
        safe_remove(new_file_path)
        safe_remove(new_backup_path)
        logger.exception(f"UPDATE DOCUMENT ERROR: {exc}")
        return error_response(500, f"Internal server error: {exc}")


# ============================================================
# DELETE DOCUMENT  (soft delete)
# ============================================================

@document_router.delete("/{document_id}", response_model=StandardResponse)
async def delete_document(
    document_id: int,
    db: NeonHTTPSession = Depends(get_db),
):
    try:
        exists = await db.execute(
            text("SELECT 1 FROM faq_documents WHERE id = :id AND status = true"),
            {"id": document_id},
        )
        if not exists.scalar():
            return error_response(404, "Document not found")

        await db.execute(
            text("UPDATE faq_documents SET status = false WHERE id = :id"),
            {"id": document_id},
        )
        await db.execute(
            text("""
                UPDATE faq_questions
                SET status = false, updated_at = NOW()
                WHERE document_id = :id
            """),
            {"id": document_id},
        )
        await db.execute(
            text("""
                UPDATE faq_answers
                SET status = false, updated_at = NOW()
                WHERE question_id IN (
                    SELECT id FROM faq_questions WHERE document_id = :id
                )
            """),
            {"id": document_id},
        )

        await db.commit()
        return success_response(
            "Document deleted successfully",
            {"document_id": str(document_id)},
        )

    except Exception as exc:
        await db.rollback()
        logger.exception(f"DELETE DOCUMENT ERROR: {exc}")
        return error_response(500, f"Internal server error: {exc}")