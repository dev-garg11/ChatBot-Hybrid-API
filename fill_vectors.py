import os, asyncio, logging
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

async def fill_answer_vectors():
    import asyncpg
    from sentence_transformers import SentenceTransformer
    DATABASE_URL = os.getenv('DATABASE_URL')
    db_url = DATABASE_URL.replace('postgresql://', 'postgres://', 1).replace('?sslmode=require', '').replace('&sslmode=require', '')
    logger.info('Model load ho raha hai...')
    model = SentenceTransformer('all-MiniLM-L6-v2')
    conn = await asyncpg.connect(db_url, ssl='require')
    rows = await conn.fetch('SELECT id, answer_text FROM public.faq_answers WHERE answer_vector IS NULL')
    logger.info(f'Total NULL rows: {len(rows)}')
    updated = 0
    for i in range(0, len(rows), 50):
        batch = rows[i:i+50]
        ids = [r['id'] for r in batch]
        texts = [r['answer_text'] or '' for r in batch]
        embeddings = model.encode(texts, normalize_embeddings=True)
        for row_id, embedding in zip(ids, embeddings):
            vector_str = '[' + ','.join(str(round(float(x), 8)) for x in embedding) + ']'
            await conn.execute('UPDATE public.faq_answers SET answer_vector = $1::vector WHERE id = $2', vector_str, row_id)
            updated += 1
        logger.info(f'{updated}/{len(rows)} updated')
    await conn.close()
    logger.info(f'Done! {updated} rows complete!')

asyncio.run(fill_answer_vectors())