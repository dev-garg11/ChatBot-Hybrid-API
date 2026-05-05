import asyncio
import json
from typing import List
from sqlalchemy import text

from app.utilis.vector_service import get_vector
from app.utilis.reranker import gemini_rerank
from app.core.config_values import PDF_SIMILARITY_THRESHOLD, RERANK_MIN_RESULTS

import logging
logger = logging.getLogger(__name__)

VECTOR_CACHE = {}


def vector_to_str(vector: List[float]) -> str:
    return "[" + ",".join(map(str, vector)) + "]"

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100):
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        start += chunk_size - overlap

    return chunks

async def search_pdf_chunks(db, query: str, type_master_id: int = None, top_k: int = 5):

    key = query.strip().lower()

    # 🔥 CACHE
    if key in VECTOR_CACHE:
        query_vector = VECTOR_CACHE[key]
    else:
        query_vector = await asyncio.to_thread(get_vector, query)
        VECTOR_CACHE[key] = query_vector

    logger.info(f"Query vector length: {len(query_vector) if query_vector else 'NONE'}")  # ✅ add

    if not query_vector:
        return []

    limit = max(top_k * 3, 10)
    qv_str = vector_to_str(query_vector)
    logger.info(f"type_master_id: {type_master_id}")  # ✅ add
    logger.info(f"SQL limit: {limit}")                 # ✅ add


    # ✅ type_master_id ke basis pe alag query
    if type_master_id is not None:
        sql = text("""
            SELECT 
                pc.chunk_text,
                pc.image_paths,
                fd.type_id,
                1 - (pc.embedding <=> CAST(:qv AS vector)) AS similarity
            FROM pdf_chunks pc
            JOIN faq_documents fd ON fd.id = pc.document_id
            WHERE fd.status = 'completed'
            AND fd.type_id = :type_id
            ORDER BY pc.embedding <=> CAST(:qv AS vector)
            LIMIT :limit
        """)
        params = {"qv": qv_str, "type_id": type_master_id, "limit": limit}
    else:
        sql = text("""
            SELECT 
                pc.chunk_text,
                pc.image_paths,
                fd.type_id,
                1 - (pc.embedding <=> CAST(:qv AS vector)) AS similarity
            FROM pdf_chunks pc
            JOIN faq_documents fd ON fd.id = pc.document_id
            WHERE fd.status = 'completed'
            ORDER BY pc.embedding <=> CAST(:qv AS vector)
            LIMIT :limit
        """)
        params = {"qv": qv_str, "limit": limit}

    result = await db.execute(sql, params)
    rows = result.fetchall()
    results = []
    logger.info(f"Raw SQL rows returned: {len(rows)}")  # ✅ add — MOST IMPORTANT

    for row in rows:
        similarity = float(row.similarity or 0)

        if similarity < PDF_SIMILARITY_THRESHOLD:
            continue

        logger.info(f"Row similarity: {similarity}")    # ✅ add

        results.append({
            "content": row.chunk_text,
            "similarity": similarity,
            "score": similarity,
            "type_id": row.type_id,
            "image_paths": json.loads(row.image_paths) if row.image_paths else []
        })

    if not results:
        return []

    # 🔥 RERANK
    if len(results) >= RERANK_MIN_RESULTS:
        results = await gemini_rerank(query, results)

    # 🔥 DEDUP
    seen = set()
    unique_results = []

    for r in results:
        key = r["content"].strip().lower()

        if key not in seen:
            seen.add(key)
            unique_results.append(r)

    return unique_results[:top_k]