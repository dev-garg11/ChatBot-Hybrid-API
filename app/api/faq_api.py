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
from app.utilis.pdf_search import search_pdf
from rapidfuzz import process

# ----------------------------
# LOGGER
# ----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("faq")

router = APIRouter(prefix="/faq", tags=["FAQ"])

SIMILARITY_THRESHOLD = 0.4
TOP_N_RESULTS = 5
MAX_QUERY_LENGTH = 300

RESPONSE_CACHE = {}
VECTOR_CACHE = {}

# ----------------------------
# SMART RANKING
# ----------------------------
def calculate_score(item):
    base = item["score"]
    text = item["text"].lower()

    length_bonus = min(len(text) / 500, 1) * 0.1

    keyword_bonus = 0
    if any(word in text for word in ["step", "how", "process", "procedure"]):
        keyword_bonus = 0.1

    source_bonus = 0.05 if item.get("source") == "faq" else 0

    return base + length_bonus + keyword_bonus + source_bonus


# ----------------------------
# PREPROCESSING
# ----------------------------
def normalize_text(input_text: str):
    input_text = input_text.lower()
    input_text = re.sub(r"[^a-z0-9\s]", "", input_text)
    return input_text.strip()


def preprocess_query(input_text: str, vocab: list):
    input_text = normalize_text(input_text)
    input_text = correct_sentence(input_text)

    words = input_text.split()
    words = [process.extractOne(w, vocab)[0] if len(w) > 2 else w for w in words]

    return " ".join(words)


# ----------------------------
# VECTOR CACHE
# ----------------------------
async def get_vector_cached(text: str):
    if text in VECTOR_CACHE:
        return VECTOR_CACHE[text]

    vector = await asyncio.to_thread(get_vector, text)
    VECTOR_CACHE[text] = vector
    return vector


def vector_to_str(vector):
    return "[" + ",".join(map(str, vector)) + "]"


# ----------------------------
# FAQ SEARCH
# ----------------------------
async def get_answers(query: str, db: AsyncSession):
    vocab = VOCAB_CACHE

    clean_query = preprocess_query(query, vocab)
    query_vector = await get_vector_cached(clean_query)

    sql = sql_text("""
        SELECT fq.question_text, fa.answer_text,
        1 - (fq.question_vector <=> CAST(:qv AS vector)) AS similarity
        FROM faq_questions fq
        JOIN faq_answers fa ON fa.question_id = fq.id
        ORDER BY fq.question_vector <=> CAST(:qv AS vector)
        LIMIT 5
    """)

    result = await db.execute(sql, {"qv": vector_to_str(query_vector)})
    rows = result.fetchall()

    results = []

    for row in rows:
        sim = float(row.similarity)

        if sim < SIMILARITY_THRESHOLD:
            continue

        results.append({
            "question": row.question_text,
            "answer": row.answer_text,
            "similarity": sim
        })

    return results


# ----------------------------
# MAIN SEARCH LOGIC
# ----------------------------
async def get_best_results(query: str, db: AsyncSession):

    # Step 1: FAQ
    faq_results = await get_answers(query, db)

    if faq_results:
        logger.info("✅ FAQ hit")

        results = [{
            "text": f"Question: {a['question']}\nAnswer: {a['answer']}",
            "score": a["similarity"],
            "source": "faq"
        } for a in faq_results]

        sorted_results = sorted(results, key=calculate_score, reverse=True)
        return sorted_results[0], "faq"   # 🔥 ONLY BEST ONE

    # Step 2: PDF
    logger.info("⚠️ FAQ miss → PDF search")

    pdf_results = await search_pdf(query)

    if pdf_results:
        results = [{
            "text": p["content"],
            "score": p["similarity"],
            "source": "pdf"
        } for p in pdf_results]

        sorted_results = sorted(results, key=calculate_score, reverse=True)
        return sorted_results[0], "pdf"   # 🔥 ONLY BEST ONE

    return None, "none"


# ----------------------------
# NORMAL API
# ----------------------------
@router.get("/search", response_model=ApiResponse)
async def search_faq(query: str = Query(...), db: AsyncSession = Depends(get_db)):

    start_time = time.time()

    if len(query) > MAX_QUERY_LENGTH:
        return ApiResponse(
            success=False,
            status_code=400,
            message="Query too long",
            data={}
        )

    clean_query = query.lower()

    if clean_query in RESPONSE_CACHE:
        return RESPONSE_CACHE[clean_query]

    best_result, source = await get_best_results(clean_query, db)

    if not best_result:
        return ApiResponse(
            success=False,
            status_code=404,
            message="No relevant answers found in FAQ or PDF",
            data={"query": query}
        )

    context = best_result["text"]

    llm_response = await generate_llm_answer(clean_query, context)

    # 🔥 fallback if LLM down
    if not llm_response or "not reachable" in llm_response.lower():
        llm_response = context

    response = ApiResponse(
        success=True,
        status_code=200,
        message="Answer generated",
        data={
            "original_query": query,
            "source": source,
            "llm_answer": llm_response,
            "results": [best_result]   # 🔥 only 1 result
        }
    )

    RESPONSE_CACHE[clean_query] = response

    logger.info(f"✅ Done in {time.time() - start_time:.2f}s | Source: {source}")

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

    clean_query = query.lower()

    best_result, source = await get_best_results(clean_query, db)

    if not best_result:
        return StreamingResponse(
            iter(["data: No relevant answers found\n\n"]),
            media_type="text/event-stream"
        )

    context = best_result["text"]

    async def event_generator():
        yield f"event: source\ndata: {source}\n\n"
        yield "event: start\ndata: Generating answer...\n\n"

        async for chunk in generate_llm_stream(clean_query, context):
            if await request.is_disconnected():
                break
            yield f"data: {chunk}\n\n"

        yield "event: end\ndata: done\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")