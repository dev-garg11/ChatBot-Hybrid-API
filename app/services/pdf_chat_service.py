from app.services.chunk_service import search_pdf_chunks
from app.utilis.llm_service import generate_llm_answer
from app.utilis.query_processing import process_query

from app.core.config_values import (
    SIMILARITY_THRESHOLD,
    PDF_CONTEXT_LIMIT,
    PDF_SOURCE_LIMIT
)

async def get_pdf_answer(query: str, db, type_master_id: int):

    query = process_query(query)

    if not query:
        return {
            "answer": "Please enter a valid query",
            "sources": []
        }

    chunks = await search_pdf_chunks(
        db,
        query,
        type_master_id=type_master_id,
        top_k=10
    )

    if not chunks:
        return {
            "answer": "Answer not available in documents",
            "sources": []
        }

    filtered_chunks = [
        c for c in chunks if c.get("score", 0) >= SIMILARITY_THRESHOLD
    ]

    if not filtered_chunks:
        return {
            "answer": "No relevant document content found",
            "sources": []
        }

    filtered_chunks = sorted(
        filtered_chunks,
        key=lambda x: x["score"],
        reverse=True
    )

    context_parts = []

    for chunk in filtered_chunks[:PDF_CONTEXT_LIMIT]:
        text = chunk.get("content", "").strip().replace("\n", " ")

        if len(text) < 30:
            continue

        context_parts.append(f"- {text}")

    context = "\n\n".join(context_parts)

    if not context:
        return {
            "answer": "Answer not available in documents",
            "sources": []
        }

    answer = await generate_llm_answer(query, context)

    if not answer or not answer.strip():
        answer = "Answer not available in system"

    return {
        "answer": answer,
        "sources": filtered_chunks[:PDF_SOURCE_LIMIT]
    }