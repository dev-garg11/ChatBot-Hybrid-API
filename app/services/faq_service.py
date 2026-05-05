import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.utilis.query_processing import process_query
from app.utilis.vector_service import get_vector

from app.core.config_values import (
    FAQ_TOP_N_RESULTS,
    FAQ_SIMILARITY_THRESHOLD,
    FAQ_SQL_FETCH_LIMIT
)

def vector_to_str(vector):
    return "[" + ",".join(map(str, vector)) + "]"


def fallback(query):
    return [{
        "question": query,
        "answer": "Answer not available in system",
        "similarity": 0
    }]

async def get_answers(query: str, db: AsyncSession):

    query = query.strip()

    if not query:
        return []

    clean_q = process_query(query)

    query_vector = await asyncio.to_thread(get_vector, clean_q)

    if not query_vector:
        return fallback(query)

    result = await db.execute(
        text("""
            SELECT
                fq.question_text,
                fa.answer_text,
                1 - (fq.question_vector <=> CAST(:qv AS vector)) AS similarity
            FROM faq_questions fq
            JOIN faq_answers fa ON fa.question_id = fq.id
            JOIN faq_documents fd ON fd.id = fq.document_id
            WHERE fq.status = true
            AND fd.status = 'completed'
            ORDER BY fq.question_vector <=> CAST(:qv AS vector)
            LIMIT :limit
        """),
        {
            "qv": vector_to_str(query_vector),
            "limit": FAQ_SQL_FETCH_LIMIT
        }
    )

    rows = result.fetchall()

    answers = []

    for row in rows:
        sim = float(row.similarity or 0)

        if sim < FAQ_SIMILARITY_THRESHOLD:
            continue

        answers.append({
            "question": row.question_text,
            "answer": row.answer_text,
            "similarity": sim
        })

    if not answers:
        return fallback(query)

    unique_answers = {}

    for a in answers:
        key = a["question"]

        if key not in unique_answers or a["similarity"] > unique_answers[key]["similarity"]:
            unique_answers[key] = a

    return sorted(
        unique_answers.values(),
        key=lambda x: x["similarity"],
        reverse=True
    )[:FAQ_TOP_N_RESULTS]