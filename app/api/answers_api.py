from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db
from app.utilis.response import ApiResponse

# ----------------------------
# ROUTER
# ----------------------------
answer_router = APIRouter(prefix="/faq", tags=["Answer"])


# ============================================================
# ADD ANSWER
# ============================================================

@answer_router.post("/add-answer/{question_id}", response_model=ApiResponse, summary="Add Answer to FAQ Question")
async def add_answer(
    question_id: int,
    answer: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    try:

        if not answer.strip():
            return ApiResponse(
                success=False,
                status_code=400,
                message="Answer cannot be empty"
            )

        # Check if question exists
        q_result = await db.execute(
            text("SELECT id FROM faq_questions WHERE id = :qid AND status = true"),
            {"qid": question_id}
        )

        if not q_result.fetchone():
            return ApiResponse(
                success=False,
                status_code=404,
                message="Question not found"
            )

        # Insert answer
        result = await db.execute(
            text("""
                INSERT INTO faq_answers (question_id, answer_text, status)
                VALUES (:qid, :answer, true)
                RETURNING id
            """),
            {"qid": question_id, "answer": answer}
        )

        answer_id = result.scalar()
        await db.commit()

        return ApiResponse(
            success=True,
            status_code=201,
            message="Answer added successfully",
            data={
                "answer_id": answer_id,
                "question_id": question_id,
                "answer_text": answer
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
# GET ANSWERS BY QUESTION
# ============================================================

@answer_router.get("/answers/{question_id}", response_model=ApiResponse, summary="Get All Answers by Question ID")
async def get_answers_by_question(question_id: int, db: AsyncSession = Depends(get_db)):
    try:

        result = await db.execute(text("""
            SELECT id AS answer_id, answer_text, created_at
            FROM faq_answers
            WHERE question_id = :qid AND status = true
        """), {"qid": question_id})

        rows = result.fetchall()

        if not rows:
            return ApiResponse(
                success=False,
                status_code=404,
                message="No answers found"
            )

        answers = []

        for r in rows:
            answers.append({
                "answer_id": r.answer_id,
                "answer_text": r.answer_text,
                "created_at": str(r.created_at)
            })

        return ApiResponse(
            success=True,
            status_code=200,
            message="Answers fetched",
            data={
                "question_id": question_id,
                "total_answers": len(rows),
                "answers": answers
            }
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ============================================================
# UPDATE ANSWER
# ============================================================

@answer_router.put("/update-answer/{answer_id}", response_model=ApiResponse, summary="Update Answer")
async def update_answer(
    answer_id: int,
    answer: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    try:

        if not answer.strip():
            return ApiResponse(
                success=False,
                status_code=400,
                message="Answer cannot be empty"
            )

        result = await db.execute(
            text("SELECT id FROM faq_answers WHERE id = :id AND status = true"),
            {"id": answer_id}
        )

        if not result.fetchone():
            return ApiResponse(
                success=False,
                status_code=404,
                message="Answer not found"
            )

        await db.execute(
            text("""
                UPDATE faq_answers
                SET answer_text = :answer
                WHERE id = :id
            """),
            {"answer": answer, "id": answer_id}
        )

        await db.commit()

        return ApiResponse(
            success=True,
            status_code=200,
            message="Answer updated successfully",
            data={
                "answer_id": answer_id,
                "answer_text": answer
            }
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ============================================================
# DELETE ANSWER (SOFT DELETE)
# ============================================================

@answer_router.delete("/delete-answer/{answer_id}", response_model=ApiResponse, summary="Delete Answer")
async def delete_answer(answer_id: int, db: AsyncSession = Depends(get_db)):
    try:

        result = await db.execute(
            text("SELECT id FROM faq_answers WHERE id = :id AND status = true"),
            {"id": answer_id}
        )

        if not result.fetchone():
            return ApiResponse(
                success=False,
                status_code=404,
                message="Answer not found"
            )

        await db.execute(
            text("""
                UPDATE faq_answers
                SET status = false
                WHERE id = :id
            """),
            {"id": answer_id}
        )

        await db.commit()

        return ApiResponse(
            success=True,
            status_code=200,
            message="Answer deleted successfully",
            data={"deleted_answer_id": answer_id}
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))