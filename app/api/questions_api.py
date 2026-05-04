from fastapi import APIRouter, Depends, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Any
from sqlalchemy import text
import re
import asyncio
import logging

from app.core.database import NeonHTTPSession, get_db
from app.utilis.vector_service import get_vector

question_router = APIRouter(
    prefix="/questions",
    tags=["Questions"]
)

logger = logging.getLogger(__name__)


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

def error_response(
    status_code: int,
    message: str
) -> JSONResponse:

    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "status_code": status_code,
            "message": message,
            "data": None
        }
    )


def success_response(
    message: str,
    data: Any = None,
    status_code: int = 200
) -> JSONResponse:

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
# NORMALIZE TEXT
# ============================================================

def normalize_text(text_input: str) -> str:

    text_input = text_input.lower()

    text_input = re.sub(
        r"[^a-z0-9]",
        "",
        text_input
    )

    return text_input.strip()


# ============================================================
# SAFE VECTOR
# ============================================================

async def safe_vector(
    txt: str,
    retries: int = 3
) -> Optional[list]:

    for attempt in range(retries):

        try:

            vec = await asyncio.wait_for(
                asyncio.to_thread(get_vector, txt),
                timeout=10
            )

            if vec and len(vec) > 0:
                return vec

        except asyncio.TimeoutError:

            logger.warning(
                f"Vector timeout {attempt + 1}/{retries}"
            )

        except Exception as e:

            logger.error(
                f"Vector error: {str(e)}"
            )

    return None


# ============================================================
# AUTO DOCUMENT MATCH
# ============================================================

DOCUMENT_SIMILARITY_THRESHOLD = 0.75


async def auto_find_document(
    vector: list,
    db: NeonHTTPSession
) -> Optional[int]:

    try:

        vector_str = (
            "[" + ",".join(
                f"{x:.6f}" for x in vector
            ) + "]"
        )

        result = await db.execute(
            text("""
                SELECT
                    id,
                    file_name,
                    1 - (
                        document_vector <=> CAST(:vec AS vector)
                    ) AS similarity

                FROM faq_documents

                WHERE status = true
                AND document_vector IS NOT NULL

                ORDER BY
                    document_vector <=> CAST(:vec AS vector)

                LIMIT 1
            """),
            {"vec": vector_str}
        )

        row = result.fetchone()

        if not row:
            return None

        similarity = float(
            row.similarity or 0.0
        )

        logger.info(
            f"AUTO DOC MATCH -> "
            f"id={row.id} "
            f"similarity={similarity}"
        )

        if similarity >= DOCUMENT_SIMILARITY_THRESHOLD:
            return row.id

        return None

    except Exception as e:

        logger.error(
            f"Auto document error: {str(e)}"
        )

        return None


# ============================================================
# FETCH QUESTION + ANSWERS
# ============================================================
# ============================================================
# FETCH QUESTION + ANSWERS
# ============================================================

async def fetch_question_with_answers(
    question_id: int,
    db: NeonHTTPSession
) -> Optional[dict]:

    result = await db.execute(
        text("""
            SELECT
                q.id,
                q.question_text,
                q.type_master_id,
                q.document_id,
                q.status,
                q.created_at,
                q.updated_at,

                tm.type_name,

                d.file_name AS document_name

            FROM faq_questions q

            LEFT JOIN type_master tm
            ON tm.type_master_id = q.type_master_id

            LEFT JOIN faq_documents d
            ON d.id = q.document_id

            WHERE q.id = :id
            AND q.status = true
        """),
        {"id": question_id}
    )

    row = result.fetchone()

    if not row:
        return None

    # ============================================================
    # FETCH ANSWER IDS ONLY
    # ============================================================

    answers_result = await db.execute(
        text("""
            SELECT
                id AS answer_id

            FROM faq_answers

            WHERE question_id = :qid
            AND status = true

            ORDER BY id ASC
        """),
        {"qid": question_id}
    )

    answers = answers_result.fetchall()

    return {
        "question_id": str(row.id),

        "question": row.question_text,

        "type_master_id": (
            str(row.type_master_id)
            if row.type_master_id else None
        ),

        "type_name": row.type_name,

        "document_id": (
            str(row.document_id)
            if row.document_id else None
        ),

        "document_name": row.document_name,

        # ONLY ANSWER IDS
        "answer_ids": [
            str(ans.answer_id)
            for ans in answers
        ],

        "status": row.status,

        "created_at": (
            str(row.created_at)
            if row.created_at else None
        ),

        "updated_at": (
            str(row.updated_at)
            if row.updated_at else None
        )
    }

# ============================================================
# ADD QUESTION
# ============================================================

@question_router.post(
    "/add-question",
    response_model=StandardResponse,
    status_code=201
)
async def add_question(
    question: str = Body(
        ...,
        embed=True,
        min_length=3,
        max_length=500
    ),

    type_id: int = Body(
        ...,
        embed=True
    ),

    db: NeonHTTPSession = Depends(get_db)
):

    try:

        question = question.strip()

        norm = normalize_text(question)

        if not norm:

            return error_response(
                400,
                "Question cannot be empty"
            )

        # ============================================================
        # TYPE VALIDATION
        # ============================================================

        type_check = await db.execute(
            text("""
                SELECT 1
                FROM type_master
                WHERE type_master_id = :tid
                AND is_active = true
            """),
            {"tid": type_id}
        )

        if not type_check.scalar():

            return error_response(
                400,
                f"Invalid type_id: {type_id}"
            )

        # ============================================================
        # DUPLICATE CHECK
        # ============================================================

        dup = await db.execute(
            text("""
                SELECT id
                FROM faq_questions

                WHERE REGEXP_REPLACE(
                    LOWER(question_text),
                    '[^a-z0-9]',
                    '',
                    'g'
                ) = :norm

                AND status = true

                LIMIT 1
            """),
            {"norm": norm}
        )

        dup_row = dup.fetchone()

        if dup_row:

            existing_data = await fetch_question_with_answers(
                dup_row.id,
                db
            )

            return success_response(
                "Question already exists",
                existing_data,
                200
            )

        # ============================================================
        # VECTOR
        # ============================================================

        vector = await safe_vector(question)

        vector_str = None

        if vector:

            vector_str = (
                "[" + ",".join(
                    f"{x:.6f}" for x in vector
                ) + "]"
            )

        # ============================================================
        # AUTO DOCUMENT MATCH
        # ============================================================

        document_id = None
        document_auto_matched = False

        if vector is not None:

            auto_doc = await auto_find_document(
                vector,
                db
            )

            if auto_doc is not None:

                document_id = auto_doc

                document_auto_matched = True

                logger.info(
                    f"DOCUMENT AUTO MATCHED: {document_id}"
                )

        # ============================================================
        # INSERT QUESTION
        # ============================================================

        if vector_str:

            result = await db.execute(
                text("""
                    INSERT INTO faq_questions
                    (
                        question_text,
                        type_master_id,
                        document_id,
                        question_vector,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES
                    (
                        :q,
                        :tid,
                        :did,
                        CAST(:vec AS vector),
                        true,
                        NOW(),
                        NOW()
                    )

                    RETURNING id
                """),
                {
                    "q": question,
                    "tid": type_id,
                    "did": document_id,
                    "vec": vector_str
                }
            )

        else:

            result = await db.execute(
                text("""
                    INSERT INTO faq_questions
                    (
                        question_text,
                        type_master_id,
                        document_id,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES
                    (
                        :q,
                        :tid,
                        :did,
                        true,
                        NOW(),
                        NOW()
                    )

                    RETURNING id
                """),
                {
                    "q": question,
                    "tid": type_id,
                    "did": document_id
                }
            )

        row = result.fetchone()

        question_id = row.id

        # ============================================================
        # AUTO ANSWER INSERT
        # ============================================================

        auto_answer = (
            "Answer not added yet"
        )

        answer_result = await db.execute(
            text("""
                INSERT INTO faq_answers
                (
                    question_id,
                    answer_text,
                    status,
                    created_at,
                    updated_at
                )
                VALUES
                (
                    :qid,
                    :answer,
                    true,
                    NOW(),
                    NOW()
                )

                RETURNING id
            """),
            {
                "qid": question_id,
                "answer": auto_answer
            }
        )

        answer_row = answer_result.fetchone()

        await db.commit()

        # ============================================================
        # FINAL RESPONSE
        # ============================================================

        final_data = await fetch_question_with_answers(
            question_id,
            db
        )

        if final_data:

            final_data["vector_saved"] = (
                vector_str is not None
            )

            final_data["document_auto_matched"] = (
                document_auto_matched
            )

            final_data["auto_answer_id"] = (
                str(answer_row.id)
                if answer_row else None
            )

        return success_response(
            "Question created successfully",
            final_data,
            201
        )

    except Exception as e:

        await db.rollback()

        logger.exception(
            f"ADD QUESTION ERROR: {str(e)}"
        )

        return error_response(
            500,
            "Internal server error"
        )


# ============================================================
# GET ALL QUESTIONS
# ============================================================

@question_router.get(
    "/all",
    response_model=StandardResponse
)
async def get_all_questions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: NeonHTTPSession = Depends(get_db)
):

    try:

        result = await db.execute(
            text("""
                SELECT
                    id
                FROM faq_questions
                WHERE status = true
                ORDER BY id DESC
                LIMIT :limit
                OFFSET :offset
            """),
            {
                "limit": limit,
                "offset": offset
            }
        )

        rows = result.fetchall()

        items = []

        for row in rows:

            data = await fetch_question_with_answers(
                row.id,
                db
            )

            if data:
                items.append(data)

        return success_response(
            "Questions fetched successfully",
            {
                "items": items,
                "count": len(items)
            }
        )

    except Exception as e:

        logger.exception(
            f"GET ALL ERROR: {str(e)}"
        )

        return error_response(
            500,
            "Internal server error"
        )


# ============================================================
# GET QUESTION BY ID
# ============================================================

@question_router.get(
    "/{question_id}",
    response_model=StandardResponse
)
async def get_question_by_id(
    question_id: int,
    db: NeonHTTPSession = Depends(get_db)
):

    try:

        data = await fetch_question_with_answers(
            question_id,
            db
        )

        if not data:

            return error_response(
                404,
                "Question not found"
            )

        return success_response(
            "Question fetched successfully",
            data
        )

    except Exception as e:

        logger.exception(
            f"GET QUESTION ERROR: {str(e)}"
        )

        return error_response(
            500,
            "Internal server error"
        )


# ============================================================
# UPDATE QUESTION
# ============================================================

@question_router.put(
    "/{question_id}",
    response_model=StandardResponse
)
async def update_question(
    question_id: int,

    question: str = Body(
        ...,
        embed=True
    ),

    type_id: int = Body(
        ...,
        embed=True
    ),

    db: NeonHTTPSession = Depends(get_db)
):

    try:

        exists = await db.execute(
            text("""
                SELECT 1
                FROM faq_questions
                WHERE id = :id
                AND status = true
            """),
            {"id": question_id}
        )

        if not exists.scalar():

            return error_response(
                404,
                "Question not found"
            )

        vector = await safe_vector(question)

        vector_str = None

        if vector:

            vector_str = (
                "[" + ",".join(
                    f"{x:.6f}" for x in vector
                ) + "]"
            )

        document_id = None

        if vector:

            document_id = await auto_find_document(
                vector,
                db
            )

        await db.execute(
            text("""
                UPDATE faq_questions
                SET
                    question_text = :q,
                    type_master_id = :tid,
                    document_id = :did,
                    question_vector = CAST(:vec AS vector),
                    updated_at = NOW()

                WHERE id = :id
            """),
            {
                "q": question,
                "tid": type_id,
                "did": document_id,
                "vec": vector_str,
                "id": question_id
            }
        )

        await db.commit()

        updated_data = await fetch_question_with_answers(
            question_id,
            db
        )

        return success_response(
            "Question updated successfully",
            updated_data
        )

    except Exception as e:

        await db.rollback()

        logger.exception(
            f"UPDATE ERROR: {str(e)}"
        )

        return error_response(
            500,
            "Internal server error"
        )


# ============================================================
# DELETE QUESTION
# ============================================================

@question_router.delete(
    "/{question_id}",
    response_model=StandardResponse
)
async def delete_question(
    question_id: int,
    db: NeonHTTPSession = Depends(get_db)
):

    try:

        exists = await db.execute(
            text("""
                SELECT 1
                FROM faq_questions
                WHERE id = :id
                AND status = true
            """),
            {"id": question_id}
        )

        if not exists.scalar():

            return error_response(
                404,
                "Question not found"
            )

        await db.execute(
            text("""
                UPDATE faq_questions
                SET
                    status = false,
                    updated_at = NOW()

                WHERE id = :id
            """),
            {"id": question_id}
        )

        await db.execute(
            text("""
                UPDATE faq_answers
                SET
                    status = false,
                    updated_at = NOW()

                WHERE question_id = :id
            """),
            {"id": question_id}
        )

        await db.commit()

        return success_response(
            "Question deleted successfully",
            {
                "question_id": str(question_id)
            }
        )

    except Exception as e:

        await db.rollback()

        logger.exception(
            f"DELETE ERROR: {str(e)}"
        )

        return error_response(
            500,
            "Internal server error"
        )