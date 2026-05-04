from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy import text
import asyncio
import re
import logging
import os
from collections import OrderedDict
from threading import Lock

from app.core.database import NeonHTTPSession, get_db
from app.utilis.vector_service import get_vector
from app.utilis.response import ApiResponse
from app.utilis.spell_service import correct_sentence

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("faq")

SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", 0.65))
MAX_QUERY_LENGTH     = int(os.getenv("MAX_QUERY_LENGTH", 300))


# ============================================================
# LRU CACHE
# ============================================================

class LRUCache:

    def __init__(self, max_size=100):
        self.cache    = OrderedDict()
        self.max_size = max_size
        self.lock     = Lock()

    def get(self, key):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    def set(self, key, value):
        with self.lock:
            self.cache[key] = value
            self.cache.move_to_end(key)
            if len(self.cache) > self.max_size:
                self.cache.popitem(last=False)


RESPONSE_CACHE = LRUCache(100)
VECTOR_CACHE   = LRUCache(200)

faq_router = APIRouter(prefix="/faq", tags=["FAQ"])


# ============================================================
# HELPERS
# ============================================================

def normalize_text(text_input: str) -> str:

    text_input = text_input.lower()
    text_input = re.sub(r"[^a-z0-9\s]", "", text_input)

    return text_input.strip()


def preprocess_query(text_input: str) -> str:

    text_input = normalize_text(text_input)

    return correct_sentence(text_input)


def vector_to_str(vector) -> str:

    try:
        return (
            "[" +
            ",".join(f"{float(x):.6f}" for x in vector) +
            "]"
        )
    except Exception:
        logger.exception("Vector conversion failed")
        return "[]"


async def get_vector_cached(clean_query: str):

    cached = VECTOR_CACHE.get(clean_query)

    if cached:
        return cached

    vector = await asyncio.to_thread(get_vector, clean_query)

    VECTOR_CACHE.set(clean_query, vector)

    return vector


# ============================================================
# FAQ SEARCH
# ============================================================

@faq_router.get("/search", response_model=ApiResponse)
async def search_faq(
    question: Optional[str] = Query(None),
    query: Optional[str]    = Query(None),
    type_id: Optional[int]  = Query(None),
    db: NeonHTTPSession = Depends(get_db)
):

    try:

        search_text = question or query

        if not search_text:
            return ApiResponse(False, 400, "Provide question or query")

        search_text = search_text.strip()

        if not search_text:
            return ApiResponse(False, 400, "Query cannot be empty")

        if len(search_text) > MAX_QUERY_LENGTH:
            return ApiResponse(False, 400, "Query too long")

        clean_query = preprocess_query(search_text)

        # Cache key includes type_id so different types
        # don't return each other's cached results
        cache_key = (
            f"{clean_query}__tid_{type_id}"
            if type_id else clean_query
        )

        cached = RESPONSE_CACHE.get(cache_key)

        if cached:
            return ApiResponse(**cached)

        # VECTOR
        query_vector = await get_vector_cached(clean_query)
        vector_str   = vector_to_str(query_vector)

        # Build WHERE clause — optional type filter
        if type_id is not None:

            result = await db.execute(
                text("""
                    SELECT
                        fq.id            AS question_id,
                        fq.question_text,
                        fq.type_master_id,
                        fq.document_id,
                        1 - (fq.question_vector <=> CAST(:qv AS vector))
                            AS similarity
                    FROM faq_questions fq
                    WHERE fq.status = true
                    AND fq.type_master_id = :tid
                    ORDER BY fq.question_vector <=> CAST(:qv AS vector)
                    LIMIT 1
                """),
                {
                    "qv":  vector_str,
                    "tid": type_id
                }
            )

        else:

            result = await db.execute(
                text("""
                    SELECT
                        fq.id            AS question_id,
                        fq.question_text,
                        fq.type_master_id,
                        fq.document_id,
                        1 - (fq.question_vector <=> CAST(:qv AS vector))
                            AS similarity
                    FROM faq_questions fq
                    WHERE fq.status = true
                    ORDER BY fq.question_vector <=> CAST(:qv AS vector)
                    LIMIT 1
                """),
                {"qv": vector_str}
            )

        row = result.fetchone()

        if not row:
            return ApiResponse(False, 404, "No match found")

        similarity = float(row.similarity or 0)

        if similarity < SIMILARITY_THRESHOLD:
            return ApiResponse(False, 404, "No relevant answer found")

        # FETCH ANSWERS — DISTINCT ON answer_text to remove duplicates
        answers_result = await db.execute(
            text("""
                SELECT DISTINCT ON (answer_text)
                    id          AS answer_id,
                    answer_text
                FROM faq_answers
                WHERE question_id = :qid
                AND status = true
                ORDER BY answer_text, id ASC
            """),
            {"qid": row.question_id}
        )

        answer_rows = answers_result.fetchall()

        answers = [
            {
                "answer_id":   str(a.answer_id),
                "answer_text": a.answer_text
            }
            for a in answer_rows
        ]

        response_data = {
            "question_id":    str(row.question_id),
            "question":       row.question_text,
            "type_master_id": str(row.type_master_id) if row.type_master_id else None,
            "document_id":    str(row.document_id) if row.document_id else None,
            "similarity":     round(similarity, 4),
            "answers":        answers
        }

        response = ApiResponse(True, 200, "Answer found", response_data)

        RESPONSE_CACHE.set(cache_key, response.dict())

        return response

    except Exception:
        logger.exception("FAQ SEARCH ERROR")
        return ApiResponse(False, 500, "Internal server error")


# ============================================================
# FAQ SEARCH — TOP N RESULTS
# ============================================================

@faq_router.get("/search/top", response_model=ApiResponse)
async def search_faq_top(
    question: Optional[str] = Query(None),
    query: Optional[str]    = Query(None),
    type_id: Optional[int]  = Query(None),
    top_k: int              = Query(3, ge=1, le=10),
    db: NeonHTTPSession = Depends(get_db)
):
    """
    Top-N similar questions return karta hai with their answers.
    Useful when frontend ko multiple suggestions dikhane ho.
    """

    try:

        search_text = question or query

        if not search_text:
            return ApiResponse(False, 400, "Provide question or query")

        search_text = search_text.strip()

        if not search_text:
            return ApiResponse(False, 400, "Query cannot be empty")

        if len(search_text) > MAX_QUERY_LENGTH:
            return ApiResponse(False, 400, "Query too long")

        clean_query  = preprocess_query(search_text)
        query_vector = await get_vector_cached(clean_query)
        vector_str   = vector_to_str(query_vector)

        # FETCH TOP-K QUESTIONS
        if type_id is not None:

            result = await db.execute(
                text("""
                    SELECT
                        fq.id            AS question_id,
                        fq.question_text,
                        fq.type_master_id,
                        fq.document_id,
                        1 - (fq.question_vector <=> CAST(:qv AS vector))
                            AS similarity
                    FROM faq_questions fq
                    WHERE fq.status = true
                    AND fq.type_master_id = :tid
                    ORDER BY fq.question_vector <=> CAST(:qv AS vector)
                    LIMIT :topk
                """),
                {
                    "qv":   vector_str,
                    "tid":  type_id,
                    "topk": top_k
                }
            )

        else:

            result = await db.execute(
                text("""
                    SELECT
                        fq.id            AS question_id,
                        fq.question_text,
                        fq.type_master_id,
                        fq.document_id,
                        1 - (fq.question_vector <=> CAST(:qv AS vector))
                            AS similarity
                    FROM faq_questions fq
                    WHERE fq.status = true
                    ORDER BY fq.question_vector <=> CAST(:qv AS vector)
                    LIMIT :topk
                """),
                {
                    "qv":   vector_str,
                    "topk": top_k
                }
            )

        rows = result.fetchall()

        if not rows:
            return ApiResponse(False, 404, "No matches found")

        # Filter by threshold
        matched = [
            r for r in rows
            if float(r.similarity or 0) >= SIMILARITY_THRESHOLD
        ]

        if not matched:
            return ApiResponse(False, 404, "No relevant answers found")

        question_ids = [r.question_id for r in matched]

        # FETCH ANSWERS — DISTINCT ON (question_id, answer_text) to remove duplicates
        answers_result = await db.execute(
            text("""
                SELECT DISTINCT ON (question_id, answer_text)
                    id          AS answer_id,
                    question_id,
                    answer_text
                FROM faq_answers
                WHERE question_id = ANY(:qids)
                AND status = true
                ORDER BY question_id, answer_text, id ASC
            """),
            {"qids": question_ids}
        )

        all_answers = answers_result.fetchall()

        answers_map: dict = {}

        for a in all_answers:
            answers_map.setdefault(a.question_id, []).append(
                {
                    "answer_id":   str(a.answer_id),
                    "answer_text": a.answer_text
                }
            )

        items = [
            {
                "question_id":    str(r.question_id),
                "question":       r.question_text,
                "type_master_id": str(r.type_master_id) if r.type_master_id else None,
                "document_id":    str(r.document_id) if r.document_id else None,
                "similarity":     round(float(r.similarity or 0), 4),
                "answers":        answers_map.get(r.question_id, [])
            }
            for r in matched
        ]

        return ApiResponse(
            True, 200,
            "Results found",
            {
                "total":   len(items),
                "results": items
            }
        )

    except Exception:
        logger.exception("FAQ SEARCH TOP ERROR")
        return ApiResponse(False, 500, "Internal server error")