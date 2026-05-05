from app.services.faq_service import get_answers
from app.services.chunk_service import search_pdf_chunks
from app.services.rag_service import build_context
from app.utilis.llm_service import generate_llm_answer
from app.utilis.query_processing import process_query
from app.utilis.google_search import google_search  

from app.core.config_values import (
    FAQ_STRONG_THRESHOLD,
    FAQ_MEDIUM_THRESHOLD,
    RAG_THRESHOLD
)
async def get_hybrid_answer(query: str, db, type_id: int = 30):

    # Step 1: Process the query (e.g., normalization, removing stop words)
    normalized_query = process_query(query)

    # -----------------------------
    # 1. FAQ SEARCH
    # -----------------------------
    faq_results = await get_answers(normalized_query, db)
    best_faq = faq_results[0] if faq_results else None

    if best_faq and best_faq["similarity"] >= FAQ_STRONG_THRESHOLD:
        return {
            "answer": best_faq["answer"],
            "source": "faq",
            "confidence": round(best_faq["similarity"], 2)
        }

    if best_faq and FAQ_MEDIUM_THRESHOLD <= best_faq["similarity"] < FAQ_STRONG_THRESHOLD:

        context = f"""
You are improving an FAQ answer.

RULES:
- Do NOT add new information
- Only refine the given answer
- Keep it concise and clear

User Query:
{normalized_query}

Original Answer:
{best_faq['answer']}
"""

        improved_answer = await generate_llm_answer(normalized_query, context)

        if not improved_answer or not improved_answer.strip():
            improved_answer = best_faq["answer"]

        return {
            "answer": improved_answer,
            "source": "faq+llm",
            "confidence": round(best_faq["similarity"], 2)
        }

    # -----------------------------
    # 2. RAG SEARCH
    # -----------------------------
    rag_chunks = await search_pdf_chunks(
        db,
        normalized_query,
        type_master_id=type_id,
        top_k=5
    )

    best_rag = rag_chunks[0] if rag_chunks else None

    if best_rag and best_rag.get("score", 0) >= RAG_THRESHOLD:

        context = build_context(rag_chunks)

        if not context.strip():
            return {
                "answer": "Answer not available in system",
                "source": None,
                "confidence": 0
            }

        llm_answer = await generate_llm_answer(normalized_query, context)

        if not llm_answer or not llm_answer.strip():
            llm_answer = "Answer not available in system"

        return {
            "answer": llm_answer,
            "source": "pdf",
            "confidence": round(best_rag["score"], 2),
            "sources": rag_chunks[:3]
        }

    # -----------------------------
    # 3. GOOGLE SEARCH FALLBACK ✅
    # -----------------------------
    search_results = await google_search(normalized_query)

    if search_results:
        context = "\n\n".join([
            f"Title: {r['title']}\n{r['snippet']}"
            for r in search_results
        ])

        answer = await generate_llm_answer(normalized_query, context)

        if not answer or not answer.strip():
            answer = search_results[0]["snippet"]

        return {
            "answer": answer,
            "source": "google",
            "confidence": 0,
            "sources": search_results
        }
    
    return {
        "answer": "Answer not available in system",
        "source": None,
        "confidence": 0
    }