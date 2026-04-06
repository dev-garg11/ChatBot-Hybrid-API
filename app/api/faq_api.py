from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
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
from app.utilis.cache import VOCAB_CACHE
from app.utilis.llm_service import generate_llm_answer
from app.utilis.llm_stream_service import generate_llm_stream
from rapidfuzz import process
from dotenv import load_dotenv

load_dotenv()

# ----------------------------
# LOGGER
# ----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("faq")

# ----------------------------
# CONFIG — sab kuch .env se
# ----------------------------
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", 0.65))
TOP_N_RESULTS        = int(os.getenv("TOP_N_RESULTS", 5))
MAX_QUERY_LENGTH     = int(os.getenv("MAX_QUERY_LENGTH", 300))
SERVER_BASE_URL      = os.getenv("SERVER_BASE_URL", "http://localhost:8000")

RESPONSE_CACHE = {}
VECTOR_CACHE   = {}

# ----------------------------
# ROUTERS
# ----------------------------
router     = APIRouter()
faq_router = APIRouter(prefix="/faq", tags=["FAQ"])


# ----------------------------
# HELPER FUNCTIONS
# ----------------------------
def normalize_text(input_text: str) -> str:
    input_text = input_text.lower()
    input_text = re.sub(r"[^a-z0-9\s]", "", input_text)
    return input_text.strip()


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
    words      = input_text.split()
    words      = [dynamic_word_fix(w, vocab) for w in words]
    return " ".join(words)


def split_query(query: str) -> list[str]:
    parts     = re.split(r'\band\b|[.,?&/;]', query)
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
        JOIN faq_answers   fa ON fa.question_id  = fq.id
        JOIN faq_documents fd ON fd.id           = fq.document_id
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
    question: Optional[str] = Query(None, description="User question"),
    query:    Optional[str] = Query(None, description="User query (same as question)"),
    db: AsyncSession = Depends(get_db)
):
    # ✅ dono parameter accept karo - question ya query
    search_text = question or query
    if not search_text:
        return ApiResponse(
            success=False, status_code=400,
            message="Please provide 'question' or 'query' parameter"
        )

    try:
        vocab        = VOCAB_CACHE or []
        clean_query  = preprocess_query(search_text, vocab)
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
            return ApiResponse(
                success=False, status_code=404, message="No relevant answer found",
                data={"similarity": round(similarity, 3)}
            )

        answers_result = await db.execute(text("""
            SELECT id AS answer_id, answer_text FROM faq_answers
            WHERE question_id = :qid AND status = true
        """), {"qid": row.question_id})
        answers = answers_result.fetchall()

        return ApiResponse(
            success=True, status_code=200, message="Answer found",
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
            data=[
                {
                    "question_id": r.question_id,
                    "document_id": r.document_id,
                    "type_id":     r.type_id,
                    "question":    r.question_text,
                    "answers":     r.answers
                }
                for r in rows
            ]
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
            data=[
                {
                    "question_id": r.question_id,
                    "document_id": r.document_id,
                    "type_id":     r.type_master_id,
                    "question":    r.question_text,
                    "answers":     r.answers
                }
                for r in rows
            ]
        )
    except Exception as e:
        return ApiResponse(success=False, status_code=500, message="Something went wrong", data=str(e))


# ============================================================
# SEARCH API (LLM)
# ============================================================

@router.get("/search", response_model=ApiResponse, summary="Search FAQ with LLM")
async def search_faq(
    query: str = Query(..., description="User query"),
    db: AsyncSession = Depends(get_db)
):
    start_time = time.time()

    if len(query) > MAX_QUERY_LENGTH:
        return ApiResponse(False, 400, "Query too long", {})

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
        success=True, status_code=200,
        message="Answers generated successfully",
        data={
            "original_query": query,
            "llm_answer":     llm_response,
            "vector_results": answers
        }
    )

    RESPONSE_CACHE[query] = response
    logger.info(f"Time taken: {time.time() - start_time:.2f}s")
    return response


# ============================================================
# STREAMING API
# ============================================================

@router.get("/search-stream", summary="Search FAQ Stream")
async def search_faq_stream(
    request: Request,
    query:   str = Query(..., description="User query"),
    db: AsyncSession = Depends(get_db)
):
    if len(query) > MAX_QUERY_LENGTH:
        return StreamingResponse(iter(["data: Query too long\n\n"]), media_type="text/event-stream")

    answers = await get_answers(query, db)

    if not answers:
        return StreamingResponse(iter(["data: No relevant answers found\n\n"]), media_type="text/event-stream")

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