from fastapi import APIRouter, Depends, Query, Body, UploadFile, File, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from sqlalchemy import text as sql_text
from typing import Optional
import asyncio
import re
import time
import logging
import os
from fastapi.responses import StreamingResponse
from app.core.database import get_db
from app.utilis.vector_service import get_vector
from app.utilis.response import ApiResponse
from app.utilis.spell_service import correct_sentence
from app.utilis.pdf_extracter import extract_faq_from_pdf
from app.utilis.cache import VOCAB_CACHE
from app.utilis.llm_service import generate_llm_answer
from app.utilis.llm_stream_service import generate_llm_stream
from rapidfuzz import process
from dotenv import load_dotenv
from app.entites.faq_entities import FaqQuestion
load_dotenv()
# ----------------------------
# LOGGER
# ----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("faq")

# ----------------------------
# CONFIG
# ----------------------------
SIMILARITY_THRESHOLD = 0.65
TOP_N_RESULTS = 5   
MAX_QUERY_LENGTH = 300
UPLOAD_DIR      = "data"
BACKUP_DIR_FAQ  = r"C:\chatbot_data\faq"
BACKUP_DIR_PDFS = r"C:\chatbot_data\pdfs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR_FAQ, exist_ok=True)
os.makedirs(BACKUP_DIR_PDFS, exist_ok=True)
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000")

RESPONSE_CACHE = {}

# Vector cache
VECTOR_CACHE = {}

# ----------------------------
# 4 Alag Routers
# ----------------------------
router = APIRouter()

faq_router      = APIRouter(prefix="/faq", tags=["FAQ"])
question_router = APIRouter(prefix="/faq", tags=["Question"])
answer_router   = APIRouter(prefix="/faq", tags=["Answer"])
document_router = APIRouter(prefix="/faq", tags=["Document"])

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------
def normalize_text(input_text: str) -> str:

    input_text = input_text.lower()
    input_text = re.sub(r"[^a-z0-9\s]", "", input_text)
    return input_text.strip()

# ----------------------------
# Word Splitting
# ----------------------------
def split_words(input_text: str, vocab: list) -> str:
    result = []

    for word in input_text.split():
        if word in vocab:
            result.append(word)
            continue
        split_found = False
        for i in range(3, len(word) - 2):
            left, right = word[:i], word[i:]
            if left in vocab and right in vocab:
                result.append(left)
                result.append(right)
                split_found = True
                break
        if not split_found:
            result.append(word)
    return " ".join(result)


def dynamic_word_fix(word: str, vocab: list) -> str:
    if len(word) < 3:
        return word
    match = process.extractOne(word, vocab)
    if match and match[1] > 60:
        return match[0]
    return word


def preprocess_query(input_text: str, vocab: list) -> str:
    input_text = normalize_text(input_text)
    input_text = correct_sentence(input_text)
    input_text = split_words(input_text, vocab)

    words = input_text.split()

    words = [dynamic_word_fix(w, vocab) for w in words]
    return " ".join(words)




def split_query(query: str) -> list[str]:
    parts = re.split(r'\band\b|[.,?&/;]', query)
    questions = [p.strip() for p in parts if len(p.strip()) > 2]
    return questions if questions else [query.strip()]


def vector_to_str(vector) -> str:
    return "[" + ",".join(map(str, vector)) + "]"


async def get_vector_cached(clean_query: str):
    if clean_query in VECTOR_CACHE:
        return VECTOR_CACHE[clean_query]
    vector = await asyncio.to_thread(get_vector, clean_query)
    VECTOR_CACHE[clean_query] = vector
    return vector


# ----------------------------
# CORE RETRIEVAL
# ----------------------------
async def process_single_query(q, db, vocab, sql):
    clean_query  = preprocess_query(q, vocab)
    query_vector = await get_vector_cached(clean_query)
    result       = await db.execute(sql, {"qv": vector_to_str(query_vector)})
    rows         = result.fetchall()

    temp_answers = []
    for row in rows:
        similarity = float(row.similarity)
        if similarity < SIMILARITY_THRESHOLD:
            continue
        query_words    = set(clean_query.split())
        question_words = set(row.question_text.lower().split())
        keyword_score  = len(query_words & question_words) / max(len(query_words), 1)
        temp_answers.append({
            "question":   row.question_text,
            "answer":     row.answer_text,
            "similarity": similarity + keyword_score
        })
    return temp_answers


async def get_answers(query: str, db: AsyncSession):
    vocab         = VOCAB_CACHE
    sub_questions = split_query(query)
    all_queries   = list(dict.fromkeys([query] + sub_questions))

    sql = sql_text("""
        SELECT
            fq.question_text,
            fa.answer_text,
            1 - (fq.question_vector <=> CAST(:qv AS vector)) AS similarity
        FROM faq_questions fq
        JOIN faq_answers fa  ON fa.question_id = fq.id
        JOIN faq_documents fd ON fd.id = fq.document_id
        WHERE fd.status = true
        ORDER BY fq.question_vector <=> CAST(:qv AS vector)
        LIMIT 5
    """)

    task_list = [process_single_query(q, db, vocab, sql) for q in all_queries]
    results   = await asyncio.gather(*task_list, return_exceptions=True)

    answers = []
    for res in results:
        if isinstance(res, Exception):
            logger.error(f"Error processing query: {res}")
        else:
            answers.extend(res)

    unique_answers = {}
    for a in answers:
        key = a["question"]
        if key not in unique_answers or a["similarity"] > unique_answers[key]["similarity"]:
            unique_answers[key] = a

    return sorted(unique_answers.values(), key=lambda x: x["similarity"], reverse=True)[:TOP_N_RESULTS]


# ============================================================
# FAQ ENDPOINTS
# ============================================================
@faq_router.get("/search", response_model=ApiResponse, summary="Search FAQ Question")
async def search_faq_simple(
    question: str = Query(..., description="User question"),
    db: AsyncSession = Depends(get_db)
):
    try:
        vocab       = VOCAB_CACHE or []
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
        row    = result.fetchone()

        if not row:
            return ApiResponse(success=False, status_code=404, message="No answer found")

        similarity = float(row.similarity or 0)
        if similarity < SIMILARITY_THRESHOLD:
            return ApiResponse(success=False, status_code=404, message="No relevant answer found",
                               data={"similarity": round(similarity, 3)})

        answers_result = await db.execute(text("""
            SELECT id AS answer_id, answer_text FROM faq_answers
            WHERE question_id = :qid AND status = true
        """), {"qid": row.question_id})
        answers = answers_result.fetchall()

        return ApiResponse(success=True, status_code=200, message="Answer found",
                           data={"question_id": row.question_id, "document_id": row.document_id,
                                 "type_id": row.type_id, "question": row.question_text,
                                 "similarity": round(similarity, 3), "total_answers": len(answers),
                                 "answers": [{"answer_id": a.answer_id, "answer_text": a.answer_text}
                                             for a in answers]})
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

        return ApiResponse(success=True, status_code=200, message="FAQs fetched",
                           data=[{"question_id": r.question_id, "document_id": r.document_id,
                                  "type_id": r.type_id, "question": r.question_text,
                                  "answers": r.answers} for r in rows])
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

        return ApiResponse(success=True, status_code=200, message="FAQ list fetched",
                           data=[{"question_id": r.question_id, "document_id": r.document_id,
                                  "type_id": r.type_master_id, "question": r.question_text,
                                  "answers": r.answers} for r in rows])
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

        vector           = get_vector(clean_question)
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
    document_id: Optional[int] = Body(None),
    db: AsyncSession = Depends(get_db)
):
    try:
        result = await db.execute(text("SELECT id FROM faq_questions WHERE id = :id AND status = true"), {"id": question_id})
        if not result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Question not found")

        clean_question   = normalize_text(question)
        vector           = get_vector(clean_question)
        safe_document_id = document_id if document_id and document_id > 0 else None

        await db.execute(text("""
            UPDATE faq_questions
            SET question_text = :question, question_vector = :vector,
                type_master_id = COALESCE(:type_id, type_master_id),
                document_id = COALESCE(:doc_id, document_id)
            WHERE id = :id
        """), {"question": clean_question, "vector": str(vector), "type_id": type_id,
               "doc_id": safe_document_id, "id": question_id})
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

        result    = await db.execute(text("INSERT INTO faq_answers (question_id, answer_text) VALUES (:qid, :answer) RETURNING id"),
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
@document_router.post("/add-document", response_model=ApiResponse, summary="Upload PDF & Save Q&A")
async def add_document(type_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    try:
        if not file.filename.endswith(".pdf"):
            return ApiResponse(success=False, status_code=400, message="Only PDF files are allowed")

        file_bytes = await file.read()

        # ✅ Server pe save karo
        server_file_path = os.path.join(BACKUP_DIR_PDFS, file.filename)
        os.makedirs(BACKUP_DIR_PDFS, exist_ok=True)
        with open(server_file_path, "wb") as f:
            f.write(file_bytes)

        # ✅ Local data folder mein bhi save karo (processing ke liye)
        local_file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(local_file_path, "wb") as f:
            f.write(file_bytes)

        # ✅ Public URL generate karo
        public_url = f"{SERVER_BASE_URL}/pdfs/{file.filename}"

        # ✅ Database mein register karo
        doc_result = await db.execute(text("""
    INSERT INTO faq_documents (file_name, file_path, type_id, is_active, status)
    VALUES (:name, :file_path, :type_id, true, true) RETURNING id
"""), {
    "name": file.filename,
    "file_path": public_url,
    "type_id": type_id
})
        document_id = doc_result.scalar()
        await db.commit()

        # ✅ Q&A extract karo
        qa_pairs = extract_faq_from_pdf(local_file_path)
        if not qa_pairs:
            return ApiResponse(success=False, status_code=404, message="No Q&A found in PDF",
                               data={"document_id": document_id, "file_url": public_url})

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

            vector   = get_vector(clean_question)
            q_result = await db.execute(text("""
                INSERT INTO faq_questions (document_id, type_master_id, question_text, question_vector)
                VALUES (:doc, :type, :question, :vector) RETURNING id
            """), {"doc": document_id, "type": type_id, "question": clean_question, "vector": str(vector)})
            question_id = q_result.scalar()

            await db.execute(text("INSERT INTO faq_answers (question_id, answer_text) VALUES (:qid, :answer)"),
                             {"qid": question_id, "answer": answer_text})
            saved += 1

        await db.commit()

        return ApiResponse(success=True, status_code=201, message="Document uploaded and Q&A saved successfully",
                           data={"document_id": document_id, "document_name": file.filename,
                                 "file_path": server_file_path,
                                 "file_url": public_url,
                                 "type_id": type_id,
                                 "total_extracted": len(qa_pairs),
                                 "saved": saved,
                                 "skipped": skipped})
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


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
                                  "file_path": r.file_path,
                                  "file_url": f"{SERVER_BASE_URL}/pdfs/{r.document_name}",
                                  "type_id": r.type_id,
                                  "created_at": str(r.created_at)} for r in rows])
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


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
                                 "file_path": row.file_path,
                                 "file_url": f"{SERVER_BASE_URL}/{row.document_name}",  
                                 "type_id": row.type_id,
                                 "created_at": str(row.created_at)})
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
        result = await db.execute(text("SELECT id FROM faq_documents WHERE id = :id AND status = true"), {"id": document_id})
        if not result.fetchone():
            return ApiResponse(success=False, status_code=404, message="Document not found")

        await db.execute(text("""
            UPDATE faq_documents SET file_name = :name, type_id = COALESCE(:type_id, type_id)
            WHERE id = :id
        """), {"name": document_name, "type_id": type_id, "id": document_id})
        await db.commit()

        return ApiResponse(success=True, status_code=200, message="Document updated successfully",
                           data={"document_id": document_id, "document_name": document_name})
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


@document_router.delete("/delete-document/{document_id}", response_model=ApiResponse, summary="Delete Document")
async def delete_document(document_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("SELECT id, file_name FROM faq_documents WHERE id = :id"), {"id": document_id})
        row    = result.fetchone()
        if not row:
            return ApiResponse(success=False, status_code=404, message="Document not found")

        await db.execute(text("""
            DELETE FROM faq_answers WHERE question_id IN (
                SELECT id FROM faq_questions WHERE document_id = :did
            )
        """), {"did": document_id})
        await db.execute(text("DELETE FROM faq_questions WHERE document_id = :did"), {"did": document_id})
        await db.execute(text("DELETE FROM faq_documents WHERE id = :id"), {"id": document_id})
        await db.commit()

        # File bhi delete karo
        for folder in [UPLOAD_DIR, BACKUP_DIR_PDFS, BACKUP_DIR_FAQ]:
            path = os.path.join(folder, row.file_name)
            if os.path.exists(path):
                os.remove(path)

        return ApiResponse(success=True, status_code=200, message="Document deleted successfully",
                           data={"deleted_document_id": document_id})
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))

# ----------------------------
# Query Splitting
# ----------------------------
def split_query(query: str) -> list[str]:
    parts = re.split(r'\band\b|[.,?&/;]', query)

    questions = []
    for p in parts:
        p = p.strip()
        if len(p) > 2:
            questions.append(p)

    return questions if questions else [query.strip()]

# ----------------------------
# Vector formatter
# ----------------------------
def vector_to_str(vector) -> str:
    return "[" + ",".join(map(str, vector)) + "]"

# ----------------------------
# Cached vector retrieval
# ----------------------------
async def get_vector_cached(clean_query: str):
    if clean_query in VECTOR_CACHE:
        return VECTOR_CACHE[clean_query]

    vector = await asyncio.to_thread(get_vector, clean_query)

    VECTOR_CACHE[clean_query] = vector
    return vector


# ----------------------------
# CORE RETRIEVAL FUNCTION
# ----------------------------

# ----------------------------
# Process single query (mainly for streaming API)
# ----------------------------
async def process_single_query(q, db, vocab, sql):
    clean_query = preprocess_query(q, vocab)

    query_vector = await get_vector_cached(clean_query)

    result = await db.execute(sql, {"qv": vector_to_str(query_vector)})
    rows = result.fetchall()

    temp_answers = []

    for row in rows:
        similarity = float(row.similarity)

        if similarity < SIMILARITY_THRESHOLD:
            continue

        query_words = set(clean_query.split())
        question_words = set(row.question_text.lower().split())

        common_words = query_words & question_words
        keyword_score = len(common_words) / max(len(query_words), 1)

        temp_answers.append({
            "question": row.question_text,
            "answer": row.answer_text,
            "similarity": similarity + keyword_score
        })

    return temp_answers

# ----------------------------
# Get answers for a query (used by both normal and streaming API)
# ----------------------------

async def get_answers(query: str, db: AsyncSession):

    vocab = VOCAB_CACHE
    sub_questions = split_query(query)
    all_queries = list(dict.fromkeys([query] + sub_questions))

    answers = []

    sql = sql_text("""
        SELECT
            fq.question_text,
            fa.answer_text,
            1 - (fq.question_vector <=> CAST(:qv AS vector)) AS similarity
        FROM faq_questions fq
        JOIN faq_answers fa ON fa.question_id = fq.id
        JOIN faq_documents fd ON fd.id = fq.document_id
        WHERE fd.status = true
        ORDER BY fq.question_vector <=> CAST(:qv AS vector)
        LIMIT 5
    """)

    tasks = [
    process_single_query(q, db, vocab, sql)
    for q in all_queries
            ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    answers = []
    for res in results:
        if isinstance(res, Exception):
            logger.error(f"Error processing query: {res}")
        else:
            answers.extend(res)

    unique_answers = {}
    for a in answers:
        key = a["question"]
        if key not in unique_answers or a["similarity"] > unique_answers[key]["similarity"]:
            unique_answers[key] = a

    return sorted(unique_answers.values(), key=lambda x: x["similarity"], reverse=True)[:TOP_N_RESULTS]

# ----------------------------
# NORMAL API
# ----------------------------
@router.get("/search", response_model=ApiResponse)
async def search_faq(
    query: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    # performance tracker
    start_time = time.time()

    if len(query) > MAX_QUERY_LENGTH:
        return ApiResponse(False, 400, "Query too long", {})

    # ✅ cache check
    if query in RESPONSE_CACHE:
        logger.info("Cache hit")
        return RESPONSE_CACHE[query]

    logger.info(f"Query received: {query}")

    answers = await get_answers(query, db)

    if not answers:
        return ApiResponse(False, 404, "No relevant answers found", {"query": query})

    context = "\n\n".join(
        f"Question: {a['question']}\nAnswer: {a['answer']}"
        for a in answers
    )

    try:
        llm_response = await generate_llm_answer(query, context)
    except Exception as e:
        logger.error(f"LLM Error: {e}")
        llm_response = "LLM failed"

    response = ApiResponse(
        success=True,
        status_code=200,
        message="Answers generated successfully",
        data={
            "original_query": query,
            "llm_answer": llm_response,
            "vector_results": answers
        }
    )

    # ✅ cache store
    RESPONSE_CACHE[query] = response

    logger.info(f"Time taken: {time.time() - start_time:.2f}s")

    return response

# ----------------------------
# STREAMING API
# ----------------------------
@router.get("/search-stream")
async def search_faq_stream(
    request: Request,
    query:   str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    if len(query) > MAX_QUERY_LENGTH:
        return StreamingResponse(
            iter(["data: Query too long\n\n"]),
            media_type="text/event-stream"
        )

    answers = await get_answers(query, db)

    if not answers:
        return StreamingResponse(
            iter(["data: No relevant answers found\n\n"]),
            media_type="text/event-stream"
        )

    context = "\n\n".join(
        f"Question: {a['question']}\nAnswer: {a['answer']}"
        for a in answers
    )

    async def event_generator():
        yield "event: start\ndata: Generating answer...\n\n"
        buffer = ""
        async for chunk in generate_llm_stream(query, context):

            if await request.is_disconnected():
                break

            if chunk == "[DONE]":
                break

            buffer += chunk

            if len(buffer) > 30:
                yield f"data: {buffer}\n\n"
                buffer = ""

        if buffer:
            yield f"data: {buffer}\n\n"

        yield "event: end\ndata: done\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream") 