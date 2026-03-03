import psycopg2
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")


def search_similar_chunks(query, db_config, top_k=5):
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()

    query_embedding = model.encode(query).tolist()

    cursor.execute(
        """
        SELECT content, source_file
        FROM pdf_chunks
        ORDER BY embedding <-> %s::vector
        LIMIT %s
        """,
        (query_embedding, top_k)
    )

    results = cursor.fetchall()

    cursor.close()
    conn.close()

    return results