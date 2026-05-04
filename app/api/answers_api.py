from fastapi import APIRouter, Depends, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Any
from sqlalchemy import text
import asyncio
import logging
import os

from app.core.database import NeonHTTPSession, get_db
from app.utilis.vector_service import get_vector

answer_router = APIRouter(
    prefix="/answers",
    tags=["Answers"]
)

logger = logging.getLogger("answers")


# ============================================================
# RESPONSE SCHEMA
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
            "success": False,
            "status_code": status_code,
            "message": message,
            "data": None
        }
    )


def success_response(message: str, data: Any = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "status_code": status_code,
            "message": message,
            "data": data
        }
    )


# ============================================================
# VECTOR GENERATOR
# ============================================================

async def safe_vector(txt: str, retries: int = 3) -> Optional[list]:
    for attempt in range(retries):
        try:
            logger.info(f"[VECTOR] Attempt {attempt + 1}/{retries} for text: '{txt[:60]}...'")

            vector = await asyncio.wait_for(
                asyncio.to_thread(get_vector, txt),
                timeout=10
            )

            logger.info(f"[VECTOR] Raw result type: {type(vector)}, preview: {str(vector)[:80]}")

            if vector is None:
                logger.warning("[VECTOR] get_vector returned None")
                continue

            if not isinstance(vector, list):
                logger.warning(f"[VECTOR] Expected list, got {type(vector)}")
                continue

            if len(vector) == 0:
                logger.warning("[VECTOR] Empty list returned")
                continue

            logger.info(f"[VECTOR] Success — {len(vector)} dimensions")
            return vector

        except asyncio.TimeoutError:
            logger.warning(f"[VECTOR] Timeout on attempt {attempt + 1}/{retries}")

        except Exception as e:
            logger.exception(f"[VECTOR] Exception on attempt {attempt + 1}: {str(e)}")

    logger.error("[VECTOR] All retries exhausted — returning None")
    return None


# ============================================================
# VECTOR FORMATTER
# ============================================================

def format_vector(vector: Optional[list]) -> Optional[str]:
    try:
        if not vector or not isinstance(vector, list):
            logger.warning(f"[FORMAT] Invalid vector input: {type(vector)}")
            return None

        formatted = "[" + ",".join(f"{float(x):.6f}" for x in vector) + "]"
        logger.info(f"[FORMAT] Formatted vector length: {len(vector)}, preview: {formatted[:60]}...")
        return formatted

    except Exception as e:
        logger.exception(f"[FORMAT] Formatting failed: {str(e)}")
        return None


# ============================================================
# ADD ANSWER
# ============================================================

@answer_router.post(
    "/{question_id}",
    response_model=StandardResponse,
    status_code=201,
)
async def add_answer(
    question_id: int,
    answer: str = Body(..., embed=True, min_length=1, max_length=2000),
    db: NeonHTTPSession = Depends(get_db)
):
    try:

        # QUESTION CHECK + TEXT FETCH
        q_result = await db.execute(
            text("""
                SELECT id, question_text
                FROM faq_questions
                WHERE id = :qid
                AND status = true
            """),
            {"qid": question_id}
        )
        question_row = q_result.fetchone()

        if not question_row:
            return error_response(404, "Question not found")

        clean_answer = answer.strip()

        if not clean_answer:
            return error_response(400, "Answer cannot be empty")

        # DUPLICATE CHECK — answer_text match karo
        duplicate = await db.execute(
            text("""
                SELECT
                    id,
                    answer_text,
                    answer_vector IS NOT NULL AS has_vector,
                    created_at
                FROM faq_answers
                WHERE question_id = :qid
                AND answer_text = :ans
                AND status = true
                LIMIT 1
            """),
            {"qid": question_id, "ans": clean_answer}
        )

        dup_row = duplicate.fetchone()

        if dup_row:
            return success_response(
                "Answer already exists",
                {
                    "answer_id": dup_row.id,
                    "question_id": question_id,
                    "question_text": question_row.question_text,
                    "answer_text": dup_row.answer_text,
                    "vector_saved": dup_row.has_vector,
                    "created_at": (
                        str(dup_row.created_at)
                        if dup_row.created_at
                        else None
                    )
                },
                status_code=200
            )

        # VECTOR
        vector = await safe_vector(clean_answer)
        vector_str = format_vector(vector)

        if not vector_str:
            logger.warning("[ADD_ANSWER] Proceeding WITHOUT vector — answer_vector will be NULL")

        # INSERT
        if vector_str:
            result = await db.execute(
                text("""
                    INSERT INTO faq_answers
                        (question_id, answer_text, answer_vector, status, created_at, updated_at)
                    VALUES
                        (:qid, :answer, CAST(:vec AS vector), true, NOW(), NOW())
                    RETURNING id, created_at
                """),
                {"qid": question_id, "answer": clean_answer, "vec": vector_str}
            )
        else:
            result = await db.execute(
                text("""
                    INSERT INTO faq_answers
                        (question_id, answer_text, status, created_at, updated_at)
                    VALUES
                        (:qid, :answer, true, NOW(), NOW())
                    RETURNING id, created_at
                """),
                {"qid": question_id, "answer": clean_answer}
            )

        await db.commit()
        row = result.fetchone()

        return success_response(
            "Answer added successfully",
            {
                "answer_id": row.id,
                "question_id": question_id,
                "question_text": question_row.question_text,
                "answer_text": clean_answer,
                "vector_saved": vector_str is not None,
                "created_at": str(row.created_at) if row.created_at else None
            },
            status_code=201
        )

    except Exception:
        await db.rollback()
        logger.exception("ADD ANSWER ERROR")
        return error_response(500, "Internal server error")


# ============================================================
# GET ANSWERS BY QUESTION — DISTINCT ON to remove duplicates
# ============================================================

@answer_router.get(
    "/question/{question_id}",
    response_model=StandardResponse,
)
async def get_answers_by_question(
    question_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    db: NeonHTTPSession = Depends(get_db)
):
    try:
        # QUESTION CHECK + TEXT FETCH
        q_result = await db.execute(
            text("""
                SELECT id, question_text
                FROM faq_questions
                WHERE id = :qid
                AND status = true
            """),
            {"qid": question_id}
        )
        question_row = q_result.fetchone()

        if not question_row:
            return error_response(404, "Question not found")

        offset = (page - 1) * limit

        # COUNT — unique answers only
        count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM (
                    SELECT DISTINCT ON (answer_text) id
                    FROM faq_answers
                    WHERE question_id = :qid
                    AND status = true
                    ORDER BY answer_text, id ASC
                ) AS unique_answers
            """),
            {"qid": question_id}
        )
        total_items = count_result.scalar() or 0

        if total_items == 0:
            return success_response(
                "No answers found for this question",
                {
                    "question_id": question_id,
                    "question_text": question_row.question_text,
                    "page": page,
                    "limit": limit,
                    "total_items": 0,
                    "total_pages": 0,
                    "answers": []
                }
            )

        total_pages = (total_items + limit - 1) // limit

        if page > total_pages:
            return error_response(400, "Invalid page number")

        # FETCH ANSWERS — DISTINCT ON answer_text to remove duplicates
        result = await db.execute(
            text("""
                SELECT answer_id, answer_text, created_at, updated_at
                FROM (
                    SELECT DISTINCT ON (answer_text)
                        id          AS answer_id,
                        answer_text,
                        created_at,
                        updated_at
                    FROM faq_answers
                    WHERE question_id = :qid
                    AND status = true
                    ORDER BY answer_text, id ASC
                ) AS unique_answers
                ORDER BY created_at DESC, answer_id DESC
                LIMIT :limit OFFSET :offset
            """),
            {"qid": question_id, "limit": limit, "offset": offset}
        )
        rows = result.fetchall()

        return success_response(
            "Answers fetched successfully",
            {
                "question_id": question_id,
                "question_text": question_row.question_text,
                "page": page,
                "limit": limit,
                "total_items": total_items,
                "total_pages": total_pages,
                "answers": [
                    {
                        "answer_id": row.answer_id,
                        "answer_text": row.answer_text,
                        "created_at": str(row.created_at) if row.created_at else None,
                        "updated_at": str(row.updated_at) if row.updated_at else None
                    }
                    for row in rows
                ]
            }
        )

    except Exception:
        logger.exception("GET ANSWERS ERROR")
        return error_response(500, "Internal server error")


# ============================================================
# GET ANSWER BY ID
# ============================================================

@answer_router.get(
    "/{answer_id}",
    response_model=StandardResponse,
)
async def get_answer_by_id(
    answer_id: int,
    db: NeonHTTPSession = Depends(get_db)
):
    try:
        result = await db.execute(
            text("""
                SELECT
                    id          AS answer_id,
                    question_id,
                    answer_text,
                    created_at,
                    updated_at
                FROM faq_answers
                WHERE id = :id
                AND status = true
            """),
            {"id": answer_id}
        )
        row = result.fetchone()

        if not row:
            return error_response(404, "Answer not found")

        return success_response(
            "Answer fetched successfully",
            {
                "answer_id": row.answer_id,
                "question_id": row.question_id,
                "answer_text": row.answer_text,
                "created_at": str(row.created_at) if row.created_at else None,
                "updated_at": str(row.updated_at) if row.updated_at else None
            }
        )

    except Exception:
        logger.exception("GET ANSWER BY ID ERROR")
        return error_response(500, "Internal server error")


# ============================================================
# UPDATE ANSWER
# ============================================================

@answer_router.put(
    "/{answer_id}",
    response_model=StandardResponse,
)
async def update_answer(
    answer_id: int,
    answer: str = Body(..., embed=True, min_length=1, max_length=2000),
    db: NeonHTTPSession = Depends(get_db)
):
    try:
        clean_answer = answer.strip()

        if not clean_answer:
            return error_response(400, "Answer cannot be empty")

        # EXIST CHECK
        existing = await db.execute(
            text("""
                SELECT id
                FROM faq_answers
                WHERE id = :id
                AND status = true
            """),
            {"id": answer_id}
        )
        if not existing.scalar():
            return error_response(404, "Answer not found")

        # VECTOR
        vector = await safe_vector(clean_answer)
        vector_str = format_vector(vector)

        if not vector_str:
            logger.warning("[UPDATE_ANSWER] Updating WITHOUT vector — answer_vector stays NULL")

        # UPDATE
        if vector_str:
            await db.execute(
                text("""
                    UPDATE faq_answers
                    SET
                        answer_text = :answer,
                        answer_vector = CAST(:vec AS vector),
                        updated_at = NOW()
                    WHERE id = :id
                    AND status = true
                """),
                {"answer": clean_answer, "vec": vector_str, "id": answer_id}
            )
        else:
            await db.execute(
                text("""
                    UPDATE faq_answers
                    SET
                        answer_text = :answer,
                        updated_at = NOW()
                    WHERE id = :id
                    AND status = true
                """),
                {"answer": clean_answer, "id": answer_id}
            )

        await db.commit()

        return success_response(
            "Answer updated successfully",
            {
                "answer_id": answer_id,
                "answer_text": clean_answer,
                "vector_saved": vector_str is not None
            }
        )

    except Exception:
        await db.rollback()
        logger.exception("UPDATE ANSWER ERROR")
        return error_response(500, "Internal server error")


# ============================================================
# DELETE ANSWER
# ============================================================

@answer_router.delete(
    "/{answer_id}",
    response_model=StandardResponse,
)
async def delete_answer(
    answer_id: int,
    db: NeonHTTPSession = Depends(get_db)
):
    try:
        result = await db.execute(
            text("""
                SELECT id
                FROM faq_answers
                WHERE id = :id
                AND status = true
            """),
            {"id": answer_id}
        )
        if not result.scalar():
            return error_response(404, "Answer not found")

        await db.execute(
            text("""
                UPDATE faq_answers
                SET
                    status = false,
                    updated_at = NOW()
                WHERE id = :id
            """),
            {"id": answer_id}
        )
        await db.commit()

        return success_response(
            "Answer deleted successfully",
            {"deleted_answer_id": answer_id}
        )

    except Exception:
        await db.rollback()
        logger.exception("DELETE ANSWER ERROR")
        return error_response(500, "Internal server error")