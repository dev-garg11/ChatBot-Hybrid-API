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

import logging
logger = logging.getLogger(__name__)


# ✅ Context Builder (fixed + structured)
def build_context(chunks, top_n=3, max_chars_per_chunk=1000):
    selected = chunks[:top_n]

    context_parts = []
    for i, c in enumerate(selected, 1):
        content = (c.get("content") or "")[:max_chars_per_chunk]
        source = c.get("source", "unknown")

        context_parts.append(f"[Source {i}: {source}]\n{content}")

    return "\n\n".join(context_parts)


# ✅ Main RAG Function
async def get_rag_answer(query: str, db, top_k: int = 5,type_id: int = None):

    try:
        # 🔍 Retrieve
        chunks = await search_pdf_chunks(db, query,type_master_id=type_id, top_k=top_k)
        logger.info(f"Chunks fetched: {len(chunks)}")

        if not chunks:
            logger.info("No chunks found, using Google Search...")
            search_results = await google_search(query)

            if not search_results:
                return {
                    "answer": "Answer not available in system",
                    "sources": []
                }

            # Google results se context banao
            context = "\n\n".join([
                f"Title: {r['title']}\n{r['snippet']}"
                for r in search_results
            ])

            answer = await generate_llm_answer(query, context)

            return {
                "answer": answer,
                "sources": search_results
            }

        # 🔥 Filter
        filtered_chunks = [
            c for c in chunks if c.get("similarity", 0) >= RAG_SIMILARITY_THRESHOLD
        ]

        logger.info(f"Filtered chunks: {len(filtered_chunks)}")

        # ⚠️ Fallback if filter too strict
        if not filtered_chunks:
            logger.warning("No chunks passed threshold, using fallback")
            filtered_chunks = chunks[:top_k]

        # 🔥 Sort
        filtered_chunks = sorted(
            filtered_chunks,
            key=lambda x: x.get("similarity", 0),
            reverse=True
        )

        best_score = filtered_chunks[0].get("similarity", 0)
        logger.info(f"Top similarity: {best_score}")

        # 🚀 DIRECT ANSWER (fast path)
        if best_score >= RAG_DIRECT_THRESHOLD:
            context = build_context(filtered_chunks, top_n=2)

            try:
                answer = await generate_llm_answer(query, context)
            except Exception as e:
                logger.warning(f"LLM failed (direct path): {e}")
                answer = filtered_chunks[0].get("content", "")

            return {
                "answer": answer,
                "sources": filtered_chunks[:RAG_SOURCE_LIMIT]
            }

        # 🚀 RERANK (safe)
        if len(filtered_chunks) >= RAG_RERANK_MIN:
            try:
                logger.info("🔁 Running reranker...")
                filtered_chunks = await gemini_rerank(query, filtered_chunks)
            except Exception as e:
                logger.warning(f"Reranker failed: {e}")

        # 🔥 Build Context
        context = build_context(filtered_chunks, top_n=RAG_CONTEXT_TOP_N)

        if not context.strip():
            return {
                "answer": "Answer not available in system",
                "sources": []
            }

        # 🤖 LLM Answer (safe)
        try:
            answer = await generate_llm_answer(query, context)
        except Exception as e:
            logger.warning(f"LLM failed: {e}")
            answer = filtered_chunks[0].get("content", "")

        # 🔁 Fallback if LLM returns empty
        if not answer or not answer.strip():
            answer = filtered_chunks[0].get("content", "")

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