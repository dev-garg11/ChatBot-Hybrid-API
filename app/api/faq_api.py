from fastapi import APIRouter, Depends, Query, Body, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from typing import Optional
from app.core.database import get_db
from app.utilis.vector_service import get_vector
from app.utilis.response import ApiResponse
from app.utilis.spell_service import correct_sentence
from app.utilis.pdf_extracter import extract_faq_from_pdf
from rapidfuzz import process
import re
import os
import shutil

from app.utilis.cache import VOCAB_CACHE
from app.entites.faq_entities import FaqQuestion

SIMILARITY_THRESHOLD = 0.75

UPLOAD_DIR      = "data"
BACKUP_DIR_FAQ  = r"C:\chatbot_data\faq"
BACKUP_DIR_PDFS = r"C:\chatbot_data\pdfs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR_FAQ, exist_ok=True)
os.makedirs(BACKUP_DIR_PDFS, exist_ok=True)

# ----------------------------
# 4 Alag Routers
# ----------------------------
faq_router      = APIRouter(prefix="/faq", tags=["FAQ"])
question_router = APIRouter(prefix="/faq", tags=["Question"])
answer_router   = APIRouter(prefix="/faq", tags=["Answer"])
document_router = APIRouter(prefix="/faq", tags=["Document"])


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return text.strip()


def dynamic_word_fix(word, vocab):
    if len(word) < 3:
        return word
    match = process.extractOne(word, vocab)
    if match and match[1] > 60:
        return match[0]
    return word


def preprocess_query(text: str, vocab: list):
    text = normalize_text(text)
    text = correct_sentence(text)
    words = text.split()
    words = [dynamic_word_fix(w, vocab) for w in words]
    return " ".join(words)


# ============================================================
# FAQ ENDPOINTS
# ============================================================

@faq_router.get("/search", response_model=ApiResponse, summary="Search FAQ Question")
async def search_faq(
    question: str = Query(..., description="User question"),
    db: AsyncSession = Depends(get_db)
):
    try:
        vocab = VOCAB_CACHE or []
        clean_query = preprocess_query(question, vocab)

        query_vector = get_vector(clean_query)
        if not query_vector:
            return ApiResponse(success=False, status_code=500, message="Vector generation failed")

        sql = text("""
            SELECT
                fq.id             AS question_id,
                fq.document_id    AS document_id,
                fq.type_master_id AS type_id,
                fq.question_text,
                COALESCE(1 - (fq.question_vector <=> CAST(:qv AS vector)), 0) AS similarity
            FROM faq_questions fq
            LEFT JOIN faq_documents fd ON fd.id = fq.document_id
            WHERE (fd.status = true OR fd.id IS NULL)
            AND fq.status = true
            ORDER BY fq.question_vector <=> CAST(:qv AS vector)
            LIMIT 1
        """)

        result = await db.execute(sql, {"qv": str(query_vector)})
        row = result.fetchone()

        if not row:
            return ApiResponse(success=False, status_code=404, message="No answer found")

        similarity = float(row.similarity or 0)

        if similarity < SIMILARITY_THRESHOLD:
            return ApiResponse(
                success=False,
                status_code=404,
                message="No relevant answer found",
                data={"similarity": round(similarity, 3)}
            )

        answers_result = await db.execute(text("""
            SELECT id AS answer_id, answer_text
            FROM faq_answers
            WHERE question_id = :qid AND status = true
        """), {"qid": row.question_id})

        answers = answers_result.fetchall()

        return ApiResponse(
            success=True,
            status_code=200,
            message="Answer found",
            data={
                "question_id":   row.question_id,
                "document_id":   row.document_id,
                "type_id":       row.type_id,
                "question":      row.question_text,
                "similarity":    round(similarity, 3),
                "total_answers": len(answers),
                "answers": [
                    {"answer_id": a.answer_id, "answer_text": a.answer_text}
                    for a in answers
                ]
            }
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@faq_router.get("/faqs", response_model=ApiResponse, summary="Get All FAQs")
async def get_all_faqs(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("""
            SELECT fq.id AS question_id, fq.document_id,
                   fq.type_master_id AS type_id, fq.question_text,
                   json_agg(json_build_object('answer_id', fa.id, 'answer_text', fa.answer_text)) AS answers
            FROM faq_questions fq
            LEFT JOIN faq_answers fa ON fa.question_id = fq.id
            WHERE fq.status = true
            GROUP BY fq.id, fq.document_id, fq.type_master_id, fq.question_text
            ORDER BY fq.id DESC
        """))

        rows = result.fetchall()

        if not rows:
            return ApiResponse(success=False, status_code=404, message="No FAQs found")

        return ApiResponse(
            success=True, status_code=200, message="FAQs fetched",
            data=[{"question_id": r.question_id, "document_id": r.document_id,
                   "type_id": r.type_id, "question": r.question_text, "answers": r.answers}
                  for r in rows]
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@faq_router.get("/type/{type_id}", response_model=ApiResponse, summary="Get FAQ by Type")
async def get_faq_by_type(type_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("""
            SELECT fq.id AS question_id, fq.document_id, fq.type_master_id,
                   fq.question_text,
                   json_agg(json_build_object('answer_id', fa.id, 'answer_text', fa.answer_text)) AS answers
            FROM faq_questions fq
            LEFT JOIN faq_answers fa ON fa.question_id = fq.id
            WHERE fq.type_master_id = :type_id AND fq.status = true
            GROUP BY fq.id, fq.document_id, fq.type_master_id, fq.question_text
        """), {"type_id": type_id})

        rows = result.fetchall()

        return ApiResponse(
            success=True, status_code=200, message="FAQ list fetched",
            data=[{"question_id": r.question_id, "document_id": r.document_id,
                   "type_id": r.type_master_id, "question": r.question_text, "answers": r.answers}
                  for r in rows]
        )

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ============================================================
# QUESTION ENDPOINTS
# ============================================================

@question_router.post("/add-question", response_model=ApiResponse, summary="Add Question Only")
async def add_question_only(
    question:    str           = Body(...),
    type_id:     int           = Body(...),
    document_id: Optional[int] = Body(None),
    db: AsyncSession = Depends(get_db)
):
    try:
        clean_question = normalize_text(question)
        if not clean_question:
            return ApiResponse(success=False, status_code=400, message="Question cannot be empty")

        existing = await db.execute(select(FaqQuestion).where(FaqQuestion.question_text == clean_question))
        if existing.scalar_one_or_none():
            return ApiResponse(success=False, status_code=400, message="Question already exists")

        vector = get_vector(clean_question)

        # ✅ 0 aaye toh None karo
        safe_document_id = document_id if document_id and document_id > 0 else None

        result = await db.execute(text("""
            INSERT INTO faq_questions (document_id, type_master_id, question_text, question_vector)
            VALUES (:doc, :type, :question, :vector) RETURNING id
        """), {"doc": safe_document_id, "type": type_id, "question": clean_question, "vector": str(vector)})

        question_id = result.scalar()
        await db.commit()

        return ApiResponse(success=True, status_code=201, message="Question added successfully",
                           data={"question_id": question_id, "document_id": safe_document_id,
                                 "type_id": type_id, "question": clean_question})

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))

@question_router.get("/questions", response_model=ApiResponse, summary="Get All Questions")
async def get_all_questions(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("""
            SELECT fq.id AS question_id, fq.document_id, fq.type_master_id AS type_id, fq.question_text
            FROM faq_questions fq WHERE fq.status = true ORDER BY fq.id DESC
        """))
        rows = result.fetchall()
        if not rows:
            return ApiResponse(success=False, status_code=404, message="No questions found")

        return ApiResponse(success=True, status_code=200, message="Questions fetched",
                           data=[{"question_id": r.question_id, "document_id": r.document_id,
                                  "type_id": r.type_id, "question": r.question_text} for r in rows])

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@question_router.get("/question/{question_id}", response_model=ApiResponse, summary="Get Question by ID")
async def get_question_by_id(question_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("""
            SELECT fq.id AS question_id, fq.document_id, fq.type_master_id AS type_id, fq.question_text
            FROM faq_questions fq WHERE fq.id = :qid AND fq.status = true
        """), {"qid": question_id})
        row = result.fetchone()
        if not row:
            return ApiResponse(success=False, status_code=404, message="Question not found")

        return ApiResponse(success=True, status_code=200, message="Question found",
                           data={"question_id": row.question_id, "document_id": row.document_id,
                                 "type_id": row.type_id, "question": row.question_text})

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))

@question_router.put("/update-question/{question_id}", response_model=ApiResponse, summary="Update Question Only")
async def update_question(
    question_id: int,
    question:    str           = Body(...),
    type_id:     Optional[int] = Body(None),
    document_id: Optional[int] = Body(None),  # ✅ Comma theek kiya
    db: AsyncSession = Depends(get_db)
):
    try:
        result = await db.execute(text("SELECT id FROM faq_questions WHERE id = :id AND status = true"), {"id": question_id})
        if not result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Question not found")

        clean_question = normalize_text(question)
        vector = get_vector(clean_question)

        # ✅ 0 aaye toh None karo
        safe_document_id = document_id if document_id and document_id > 0 else None

        await db.execute(text("""
            UPDATE faq_questions
            SET question_text = :question, question_vector = :vector,
                type_master_id = COALESCE(:type_id, type_master_id),
                document_id = COALESCE(:doc_id, document_id)
            WHERE id = :id
        """), {"question": clean_question, "vector": str(vector), "type_id": type_id, "doc_id": safe_document_id, "id": question_id})

        await db.commit()
        return ApiResponse(success=True, status_code=200, message="Question updated successfully",
                           data={"question_id": question_id, "question": clean_question})

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))

@question_router.delete("/delete-question/{question_id}", response_model=ApiResponse, summary="Delete Question Only")
async def delete_question(question_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("SELECT id FROM faq_questions WHERE id = :id"), {"id": question_id})
        if not result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Question not found")

        await db.execute(text("DELETE FROM faq_answers WHERE question_id = :id"), {"id": question_id})
        await db.execute(text("DELETE FROM faq_questions WHERE id = :id"), {"id": question_id})
        await db.commit()

        return ApiResponse(success=True, status_code=200, message="Question deleted successfully",
                           data={"deleted_question_id": question_id})

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ============================================================
# ANSWER ENDPOINTS
# ============================================================

@answer_router.post("/add-answer/{question_id}", response_model=ApiResponse, summary="Add Answer to FAQ Question")
async def add_answer(question_id: int, answer: str = Body(...), db: AsyncSession = Depends(get_db)):
    try:
        q_result = await db.execute(text("SELECT id FROM faq_questions WHERE id = :qid AND status = true"), {"qid": question_id})
        if not q_result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Question not found")

        result = await db.execute(text("INSERT INTO faq_answers (question_id, answer_text) VALUES (:qid, :answer) RETURNING id"),
                                  {"qid": question_id, "answer": answer})
        answer_id = result.scalar()
        await db.commit()

        return ApiResponse(success=True, status_code=201, message="Answer added successfully",
                           data={"answer_id": answer_id, "question_id": question_id, "answer_text": answer})

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@answer_router.get("/answers/{question_id}", response_model=ApiResponse, summary="Get All Answers by Question ID")
async def get_answers_by_question(question_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("""
            SELECT fa.id AS answer_id, fa.answer_text, fa.created_at
            FROM faq_answers fa WHERE fa.question_id = :qid AND fa.status = true
        """), {"qid": question_id})
        rows = result.fetchall()

        if not rows:
            return ApiResponse(success=False, status_code=404, message="No answers found")

        return ApiResponse(success=True, status_code=200, message="Answers fetched",
                           data={"question_id": question_id, "total_answers": len(rows),
                                 "answers": [{"answer_id": r.answer_id, "answer_text": r.answer_text,
                                              "created_at": str(r.created_at)} for r in rows]})

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@answer_router.put("/update-answer/{answer_id}", response_model=ApiResponse, summary="Update Answer")
async def update_answer(answer_id: int, answer: str = Body(...), db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("SELECT id FROM faq_answers WHERE id = :id"), {"id": answer_id})
        if not result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Answer not found")

        await db.execute(text("UPDATE faq_answers SET answer_text = :answer WHERE id = :id"), {"answer": answer, "id": answer_id})
        await db.commit()

        return ApiResponse(success=True, status_code=200, message="Answer updated successfully",
                           data={"answer_id": answer_id, "answer_text": answer})

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@answer_router.delete("/delete-answer/{answer_id}", response_model=ApiResponse, summary="Delete Single Answer")
async def delete_answer(answer_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("SELECT id FROM faq_answers WHERE id = :id"), {"id": answer_id})
        if not result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Answer not found")

        await db.execute(text("DELETE FROM faq_answers WHERE id = :id"), {"id": answer_id})
        await db.commit()

        return ApiResponse(success=True, status_code=200, message="Answer deleted successfully",
                           data={"deleted_answer_id": answer_id})

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ============================================================
# DOCUMENT ENDPOINTS
# ============================================================

# ----------------------------
# Add Document — Teeno jagah save + Q&A Extract + DB Save ✅
# ----------------------------
@document_router.post("/add-document", response_model=ApiResponse, summary="Add Document")
async def add_document(
    type_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    try:
        if not file.filename.endswith(".pdf"):
            return ApiResponse(success=False, status_code=400, message="Only PDF files are allowed")

        # Teeno jagah save karo ✅
        file_path = os.path.join(UPLOAD_DIR, file.filename)

        file_bytes = await file.read()

        # 1. project/data/ folder
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        # 2. C:\chatbot_data\faq\ folder
        with open(os.path.join(BACKUP_DIR_FAQ, file.filename), "wb") as f:
            f.write(file_bytes)

        # 3. C:\chatbot_data\pdfs\ folder
        with open(os.path.join(BACKUP_DIR_PDFS, file.filename), "wb") as f:
            f.write(file_bytes)

        # DB mein pdfs wala path store karo
        full_path = os.path.abspath(os.path.join(BACKUP_DIR_PDFS, file.filename))

        # Document DB mein save karo
        doc_result = await db.execute(text("""
            INSERT INTO faq_documents (file_name, file_path, type_id,is_active,status)
            VALUES (:name, :file_path, :type_id,true, true) RETURNING id
        """), {"name": file.filename, "file_path": full_path, "type_id": type_id})

        document_id = doc_result.scalar()
        await db.commit()

        # PDF se Q&A extract karo
        qa_pairs = extract_faq_from_pdf(file_path)

        if not qa_pairs:
            return ApiResponse(success=False, status_code=404, message="No Q&A found in PDF",
                               data={"document_id": document_id})

        saved = 0
        skipped = 0

        for qa in qa_pairs:
            clean_question = normalize_text(qa["question"])
            answer_text = qa["answer"].strip()

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

            await db.execute(text("""
                INSERT INTO faq_answers (question_id, answer_text)
                VALUES (:qid, :answer)
            """), {"qid": question_id, "answer": answer_text})

            saved += 1

        await db.commit()

        return ApiResponse(
            success=True,
            status_code=201,
            message="Document uploaded and Q&A saved successfully",
            data={
                "document_id":     document_id,
                "document_name":   file.filename,
                "file_path":       full_path,
                "type_id":         type_id,
                "total_extracted": len(qa_pairs),
                "saved":           saved,
                "skipped":         skipped
            }
        )

    except Exception as e:
        print("❌ PDF PROCESS ERROR:", str(e))
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ----------------------------
# Get All Documents
# ----------------------------
@document_router.get("/documents", response_model=ApiResponse, summary="Get All Documents")
async def get_all_documents(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("""
            SELECT id AS document_id, file_name AS document_name,
                   file_path, type_id, uploaded_at AS created_at
            FROM faq_documents WHERE status = true
        """))
        rows = result.fetchall()

        return ApiResponse(success=True, status_code=200, message="Documents fetched",
                           data=[{"document_id": r.document_id, "document_name": r.document_name,
                                  "file_path": r.file_path, "type_id": r.type_id,
                                  "created_at": str(r.created_at)} for r in rows])

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ----------------------------
# Get Document by ID
# ----------------------------
@document_router.get("/document/{document_id}", response_model=ApiResponse, summary="Get Document by ID")
async def get_document_by_id(document_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("""
            SELECT id AS document_id, file_name AS document_name,
                   file_path, type_id, uploaded_at AS created_at
            FROM faq_documents WHERE id = :did AND status = true
        """), {"did": document_id})
        row = result.fetchone()

        if not row:
            return ApiResponse(success=False, status_code=404, message="Document not found")

        return ApiResponse(success=True, status_code=200, message="Document found",
                           data={"document_id": row.document_id, "document_name": row.document_name,
                                 "file_path": row.file_path, "type_id": row.type_id,
                                 "created_at": str(row.created_at)})

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ----------------------------
# Update Document
# ----------------------------
@document_router.put("/update-document/{document_id}", response_model=ApiResponse, summary="Update Document")
async def update_document(
    document_id: int,
    document_name: str = Body(...),
    type_id: Optional[int] = Body(None),
    db: AsyncSession = Depends(get_db)
):
    try:
        result = await db.execute(text("SELECT id FROM faq_documents WHERE id = :id AND status = true"), {"id": document_id})
        if not result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Document not found")

        await db.execute(text("""
            UPDATE faq_documents
            SET file_name = :name, type_id = COALESCE(:type_id, type_id)
            WHERE id = :id
        """), {"name": document_name, "type_id": type_id, "id": document_id})
        await db.commit()

        return ApiResponse(success=True, status_code=200, message="Document updated successfully",
                           data={"document_id": document_id, "document_name": document_name})

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ----------------------------
# Delete Document — Cascade Delete (answers → questions → document) ✅
# ----------------------------
@document_router.delete("/delete-document/{document_id}", response_model=ApiResponse, summary="Delete Document")
async def delete_document(document_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("SELECT id, file_name FROM faq_documents WHERE id = :id"), {"id": document_id})
        row = result.fetchone()
        if not row:
            return ApiResponse(success=False, status_code=404, message="Document not found")

        # Step 1: Pehle answers delete karo
        await db.execute(text("""
            DELETE FROM faq_answers
            WHERE question_id IN (
                SELECT id FROM faq_questions WHERE document_id = :did
            )
        """), {"did": document_id})

        # Step 2: Phir questions delete 
        await db.execute(text("DELETE FROM faq_questions WHERE document_id = :did"), {"did": document_id})

        # Step 3: Ab document delete 
        await db.execute(text("DELETE FROM faq_documents WHERE id = :id"), {"id": document_id})
        await db.commit()

        # Step 4: Teeno jagah se file hata do ✅
        for folder in [UPLOAD_DIR, BACKUP_DIR_FAQ, BACKUP_DIR_PDFS]:
            path = os.path.join(folder, row.file_name)
            if os.path.exists(path):
                os.remove(path)

        return ApiResponse(success=True, status_code=200, message="Document deleted successfully",
                           data={"deleted_document_id": document_id})

    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))