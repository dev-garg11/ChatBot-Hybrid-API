from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from typing import Optional
import re
import json

from app.core.database import get_db
from app.utilis.vector_service import get_vector
from app.utilis.response import ApiResponse
from app.entites.faq_entities import FaqQuestion

# ----------------------------
# ROUTER
# ----------------------------
question_router = APIRouter(prefix="/faq", tags=["Question"])


# ----------------------------
# HELPER
# ----------------------------
def normalize_text(input_text: str) -> str:
    input_text = input_text.lower()
    input_text = re.sub(r"[^a-z0-9\s]", "", input_text)
    return input_text.strip()


# ============================================================
# ADD QUESTION
# ============================================================

@question_router.post("/add-question", response_model=ApiResponse, summary="Add Question Only")
async def add_question_only(
    question: str = Body(..., embed=True),
    type_id: int = Body(..., embed=True),
    document_id: Optional[int] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db)
):
    try:

        clean_question = normalize_text(question)

        if not clean_question:
            return ApiResponse(
                success=False,
                status_code=400,
                message="Question cannot be empty"
            )

        # Duplicate check
        existing = await db.execute(
            select(FaqQuestion).where(FaqQuestion.question_text.ilike(clean_question))
        )

        if existing.scalar_one_or_none():
            return ApiResponse(
                success=False,
                status_code=400,
                message="Question already exists"
            )

        vector = get_vector(clean_question)
        safe_document_id = document_id if document_id and document_id > 0 else None

        result = await db.execute(text("""
            INSERT INTO faq_questions
            (document_id, type_master_id, question_text, question_vector, status)
            VALUES (:doc, :type, :question, :vector, true)
            RETURNING id
        """), {
            "doc": safe_document_id,
            "type": type_id,
            "question": clean_question,
            "vector": json.dumps(vector)
        })

        question_id = result.scalar()
        await db.commit()

        return ApiResponse(
            success=True,
            status_code=201,
            message="Question added successfully",
            data={
                "question_id": question_id,
                "document_id": safe_document_id,
                "type_id": type_id,
                "question": clean_question
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
# GET ALL QUESTIONS
# ============================================================

@question_router.get("/questions", response_model=ApiResponse, summary="Get All Questions")
async def get_all_questions(db: AsyncSession = Depends(get_db)):
    try:

        result = await db.execute(text("""
            SELECT id AS question_id,
                   document_id,
                   type_master_id AS type_id,
                   question_text
            FROM faq_questions
            WHERE status = true
            ORDER BY id DESC
        """))

        rows = result.fetchall()

        if not rows:
            return ApiResponse(success=False, status_code=404, message="No questions found")

        questions = []

        for r in rows:
            questions.append({
                "question_id": r.question_id,
                "document_id": r.document_id,
                "type_id": r.type_id,
                "question": r.question_text
            })

        return ApiResponse(
            success=True,
            status_code=200,
            message="Questions fetched",
            data=questions
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ============================================================
# GET QUESTION BY ID
# ============================================================

@question_router.get("/question/{question_id}", response_model=ApiResponse)
async def get_question_by_id(question_id: int, db: AsyncSession = Depends(get_db)):
    try:

        result = await db.execute(text("""
            SELECT id AS question_id,
                   document_id,
                   type_master_id AS type_id,
                   question_text
            FROM faq_questions
            WHERE id = :qid AND status = true
        """), {"qid": question_id})

        row = result.fetchone()

        if not row:
            return ApiResponse(success=False, status_code=404, message="Question not found")

        return ApiResponse(
            success=True,
            status_code=200,
            message="Question found",
            data={
                "question_id": row.question_id,
                "document_id": row.document_id,
                "type_id": row.type_id,
                "question": row.question_text
            }
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ============================================================
# UPDATE QUESTION
# ============================================================

@question_router.put("/update-question/{question_id}", response_model=ApiResponse)
async def update_question(
    question_id: int,
    question: str = Body(..., embed=True),
    type_id: Optional[int] = Body(None, embed=True),
    document_id: Optional[int] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db)
):
    try:

        result = await db.execute(
            text("SELECT id FROM faq_questions WHERE id = :id AND status = true"),
            {"id": question_id}
        )

        if not result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Question not found")

        clean_question = normalize_text(question)

        if not clean_question:
            return ApiResponse(success=False, status_code=400, message="Question cannot be empty")

        vector = get_vector(clean_question)
        safe_document_id = document_id if document_id and document_id > 0 else None

        await db.execute(text("""
            UPDATE faq_questions
            SET question_text = :question,
                question_vector = :vector,
                type_master_id = COALESCE(:type_id, type_master_id),
                document_id = COALESCE(:doc_id, document_id)
            WHERE id = :id
        """), {
            "question": clean_question,
            "vector": json.dumps(vector),
            "type_id": type_id,
            "doc_id": safe_document_id,
            "id": question_id
        })

        await db.commit()

        return ApiResponse(
            success=True,
            status_code=200,
            message="Question updated successfully",
            data={
                "question_id": question_id,
                "question": clean_question
            }
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ============================================================
# DELETE QUESTION (SOFT DELETE)
# ============================================================

@question_router.delete("/delete-question/{question_id}", response_model=ApiResponse)
async def delete_question(question_id: int, db: AsyncSession = Depends(get_db)):
    try:

        result = await db.execute(
            text("SELECT id FROM faq_questions WHERE id = :id AND status = true"),
            {"id": question_id}
        )

        if not result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Question not found")

        await db.execute(
            text("UPDATE faq_questions SET status = false WHERE id = :id"),
            {"id": question_id}
        )

        await db.execute(
            text("UPDATE faq_answers SET status = false WHERE question_id = :id"),
            {"id": question_id}
        )

        await db.commit()

        return ApiResponse(
            success=True,
            status_code=200,
            message="Question deleted successfully",
            data={"deleted_question_id": question_id}
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))