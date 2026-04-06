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
# ANSWER ENDPOINTS
# ============================================================

@answer_router.post("/add-answer/{question_id}", response_model=ApiResponse, summary="Add Answer to FAQ Question")
async def add_answer(
    question_id: int,
    answer: str = Body(...),
    db: AsyncSession = Depends(get_db)
):
    try:
        q_result = await db.execute(
            text("SELECT id FROM faq_questions WHERE id = :qid AND status = true"),
            {"qid": question_id}
        )
        if not q_result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Question not found")

        result = await db.execute(
            text("INSERT INTO faq_answers (question_id, answer_text) VALUES (:qid, :answer) RETURNING id"),
            {"qid": question_id, "answer": answer}
        )
        answer_id = result.scalar()
        await db.commit()

        return ApiResponse(
            success=True, status_code=201, message="Answer added successfully",
            data={
                "answer_id":   answer_id,
                "question_id": question_id,
                "answer_text": answer
            }
        )
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@answer_router.get("/answers/{question_id}", response_model=ApiResponse, summary="Get All Answers by Question ID")
async def get_answers_by_question(question_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("""
            SELECT fa.id AS answer_id, fa.answer_text, fa.created_at
            FROM faq_answers fa
            WHERE fa.question_id = :qid AND fa.status = true
        """), {"qid": question_id})
        rows = result.fetchall()

        if not rows:
            return ApiResponse(success=False, status_code=404, message="No answers found")

        return ApiResponse(
            success=True, status_code=200, message="Answers fetched",
            data={
                "question_id":   question_id,
                "total_answers": len(rows),
                "answers": [
                    {
                        "answer_id":   r.answer_id,
                        "answer_text": r.answer_text,
                        "created_at":  str(r.created_at)
                    }
                    for r in rows
                ]
            }
        )
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@answer_router.put("/update-answer/{answer_id}", response_model=ApiResponse, summary="Update Answer")
async def update_answer(
    answer_id: int,
    answer: str = Body(...),
    db: AsyncSession = Depends(get_db)
):
    try:
        result = await db.execute(
            text("SELECT id FROM faq_answers WHERE id = :id"),
            {"id": answer_id}
        )
        if not result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Answer not found")

        await db.execute(
            text("UPDATE faq_answers SET answer_text = :answer WHERE id = :id"),
            {"answer": answer, "id": answer_id}
        )
        await db.commit()

        return ApiResponse(
            success=True, status_code=200, message="Answer updated successfully",
            data={"answer_id": answer_id, "answer_text": answer}
        )
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@answer_router.delete("/delete-answer/{answer_id}", response_model=ApiResponse, summary="Delete Single Answer")
async def delete_answer(answer_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(
            text("SELECT id FROM faq_answers WHERE id = :id"),
            {"id": answer_id}
        )
        if not result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Answer not found")

        await db.execute(text("DELETE FROM faq_answers WHERE id = :id"), {"id": answer_id})
        await db.commit()

        return ApiResponse(
            success=True, status_code=200, message="Answer deleted successfully",
            data={"deleted_answer_id": answer_id}
        )
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))