import asyncio
import logging

from app.services.chunk_service import search_pdf_chunks
from app.utilis.llm_service import generate_llm_answer
from app.utilis.reranker import gemini_rerank
from app.utilis.query_processing import process_query
from app.utilis.google_search import google_search

from app.core.config_values import (
    RAG_SIMILARITY_THRESHOLD,
    RAG_DIRECT_THRESHOLD,
    RAG_RERANK_MIN,
    RAG_CONTEXT_TOP_N,
    RAG_SOURCE_LIMIT
)

logger = logging.getLogger(__name__)


# =========================
# SAFE ASYNC CALL (NEW)
# =========================
async def safe_call(coro, timeout=15):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except Exception as e:
        logger.warning(f"⚠️ Timeout/Error: {e}")
        return None


# =========================
# CONTEXT BUILDER
# =========================
def build_context(chunks, top_n=3, max_chars_per_chunk=1000):
    selected = chunks[:top_n]

    context_parts = []
    for i, c in enumerate(selected, 1):
        content = (c.get("content") or "")[:max_chars_per_chunk]
        source = c.get("source", "unknown")

        context_parts.append(f"[Source {i}: {source}]\n{content}")

    return "\n\n".join(context_parts)


# =========================
# MAIN RAG FUNCTION
# =========================
async def get_rag_answer(query: str, db, top_k: int = 5, type_id: int = None):

    try:
        # 🔍 Step 1: Retrieve (safe)
        chunks = await safe_call(
            search_pdf_chunks(db, query, type_master_id=type_id, top_k=top_k)
        )

        if not chunks:
            logger.info("No chunks found, fallback to Google")

            search_results = await safe_call(google_search(query))

            if not search_results:
                return {
                    "answer": "Answer not available in system",
                    "sources": []
                }

            context = "\n\n".join([
                f"Title: {r['title']}\n{r['snippet']}"
                for r in search_results
            ])

            answer = await safe_call(generate_llm_answer(query, context)) \
                     or "No answer available"

            return {
                "answer": answer,
                "sources": search_results
            }

        logger.info(f"Chunks fetched: {len(chunks)}")

        # 🔥 Step 2: Filter
        filtered_chunks = [
            c for c in chunks if c.get("similarity", 0) >= RAG_SIMILARITY_THRESHOLD
        ]

        if not filtered_chunks:
            logger.warning("No chunks passed threshold, fallback")
            filtered_chunks = chunks[:top_k]

        # 🔥 Step 3: Sort
        filtered_chunks = sorted(
            filtered_chunks,
            key=lambda x: x.get("similarity", 0),
            reverse=True
        )

        best_score = filtered_chunks[0].get("similarity", 0)
        logger.info(f"Top similarity: {best_score}")

        # 🚀 Step 4: Direct Answer
        if best_score >= RAG_DIRECT_THRESHOLD:
            context = build_context(filtered_chunks, top_n=2)

            answer = await safe_call(generate_llm_answer(query, context)) \
                     or filtered_chunks[0].get("content", "")

            return {
                "answer": answer,
                "sources": filtered_chunks[:RAG_SOURCE_LIMIT]
            }

        # 🔁 Step 5: Rerank
        if len(filtered_chunks) >= RAG_RERANK_MIN:
            logger.info("🔁 Running reranker...")
            reranked = await safe_call(gemini_rerank(query, filtered_chunks))
            if reranked:
                filtered_chunks = reranked

        # 🔥 Step 6: Context build
        context = build_context(filtered_chunks, top_n=RAG_CONTEXT_TOP_N)

        if not context.strip():
            return {
                "answer": "Answer not available in system",
                "sources": []
            }

        # 🤖 Step 7: LLM Answer
        answer = await safe_call(generate_llm_answer(query, context)) \
                 or filtered_chunks[0].get("content", "")

        return {
            "answer": answer,
            "sources": filtered_chunks[:RAG_SOURCE_LIMIT]
        }

    except Exception as e:
        logger.error(f"❌ RAG error: {e}")
        return {
            "answer": "Service error occurred",
            "sources": []
        }