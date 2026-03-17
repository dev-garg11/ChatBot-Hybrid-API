import asyncio
import re
import time
import logging
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text as sql_text
from fastapi.responses import StreamingResponse

from app.core.database import get_db
from app.utilis.vector_service import get_vector
from app.utilis.response import ApiResponse
from app.utilis.spell_service import correct_sentence
from app.utilis.cache import VOCAB_CACHE
from app.utilis.llm_service import generate_llm_answer
from app.utilis.llm_stream_service import generate_llm_stream
from rapidfuzz import process

# ----------------------------
# LOGGER
# ----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("faq")

router = APIRouter(prefix="/faq", tags=["FAQ"])

# ----------------------------
# CONFIG
# ----------------------------
SIMILARITY_THRESHOLD = 0.65
TOP_N_RESULTS = 5   
MAX_QUERY_LENGTH = 300

# simple in-memory cache
RESPONSE_CACHE = {}

# ----------------------------
# Text Normalize
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
            left = word[:i]
            right = word[i:]

            if left in vocab and right in vocab:
                result.append(left)
                result.append(right)
                split_found = True
                break

        if not split_found:
            result.append(word)

    return " ".join(result)

# ----------------------------
# Dynamic Word Fix
# ----------------------------
def dynamic_word_fix(word: str, vocab: list) -> str:
    if len(word) < 3:
        return word

    match = process.extractOne(word, vocab)
    if match and match[1] > 60:
        return match[0]

    return word

# ----------------------------
# Query Preprocessing
# ----------------------------
def preprocess_query(input_text: str, vocab: list) -> str:
    input_text = normalize_text(input_text)
    input_text = correct_sentence(input_text)
    input_text = split_words(input_text, vocab)

    words = input_text.split()
    words = [dynamic_word_fix(w, vocab) for w in words]

    return " ".join(words)

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
# CORE RETRIEVAL FUNCTION
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

    for q in all_queries:
        clean_query = await asyncio.to_thread(preprocess_query, q, vocab)
        query_vector = await asyncio.to_thread(get_vector, clean_query)

        result = await db.execute(sql, {"qv": vector_to_str(query_vector)})
        rows = result.fetchall()

        for row in rows:
            similarity = float(row.similarity)

            if similarity < SIMILARITY_THRESHOLD:
                continue

            # ✅ keyword boost (hybrid ranking)
            keyword_score = 0.1 if clean_query in row.question_text.lower() else 0

            answers.append({
                "question": row.question_text,
                "answer": row.answer_text,
                "similarity": similarity + keyword_score
            })

    if not answers:
        return []

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

    # ✅ validation
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
        llm_response = await asyncio.to_thread(generate_llm_answer, query, context)
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
    query: str = Query(...),
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

        async for chunk in generate_llm_stream(query, context):

            # ✅ client disconnect handling
            if await request.is_disconnected():
                logger.info("Client disconnected")
                break

            yield f"event: chunk\ndata: {chunk}\n\n"

        yield "event: end\ndata: done\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")