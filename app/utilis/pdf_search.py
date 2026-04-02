import asyncio
import json
from sqlalchemy import text
from app.core.database import AsyncSessionLocal
from app.utilis.vector_service import get_vector


def vector_to_str(vector):
    return "[" + ",".join(map(str, vector)) + "]"


async def search_pdf(query: str, top_k=5):

    async with AsyncSessionLocal() as db:

        query_vector = await asyncio.to_thread(get_vector, query)

        result = await db.execute(
            text("""
                SELECT 
                    pq.question_text,
                    pa.answer_text,
                    pa.image_paths,
                    1 - (pq.question_vector <=> CAST(:qv AS vector)) AS similarity
                FROM pdf_questions pq
                JOIN pdf_answers pa ON pa.question_id = pq.id
                ORDER BY pq.question_vector <=> CAST(:qv AS vector)
                LIMIT :limit
            """),
            {
                "qv": vector_to_str(query_vector),
                "limit": top_k
            }
        )

        rows = result.fetchall()

        results = []
        for row in rows:
            # ✅ image_paths JSON parse karo
            images = []
            if row.image_paths:
                try:
                    images = json.loads(row.image_paths)
                except:
                    images = []

            results.append({
                "content": f"Question: {row.question_text}\nAnswer: {row.answer_text}",
                "similarity": float(row.similarity),
                "image_paths": images  # ✅ images bhi return
            })

        return results
