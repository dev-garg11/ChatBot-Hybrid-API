from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_db
from app.utilis.vector_service import get_vector
from app.utilis.response import ApiResponse
from app.utilis.spell_service import correct_sentence
from rapidfuzz import process
import re
from app.utilis.cache import VOCAB_CACHE

router = APIRouter(prefix="/faq", tags=["FAQ"])

SIMILARITY_THRESHOLD = 0.75


# ----------------------------
# Text Normalize
# ----------------------------
def normalize_text(text: str) -> str:

    text = text.lower()

    text = re.sub(r"[^a-z0-9\s]", "", text)

    return text.strip()


# ----------------------------
# Fuzzy Word Correction
# ----------------------------
def fuzzy_correct_word(word: str, vocab: list):

    if len(word) < 3:
        return word

    match = process.extractOne(word, vocab)

    if match and match[1] > 80:
        return match[0]

    return word


# ----------------------------
# Word Splitting
# ----------------------------
def split_words(text: str, vocab: list):

    result = []

    for word in text.split():

        if word in vocab:
            result.append(word)
            continue

        split_found = False

        for i in range(3, len(word) - 2):

            left = word[:i]
            right = word[i:]

            if left in vocab and right in vocab:
                result.append(left)
                result.append(right)
                split_found = True
                break

        if not split_found:
            result.append(word)

    return " ".join(result)


# fixed typo dynamically
def dynamic_word_fix(word, vocab):

    if len(word) < 3:
        return word

    match = process.extractOne(word, vocab)

    if match and match[1] > 60:
        return match[0]

    return word


# ----------------------------
# Query Preprocessing Pipeline
# ----------------------------
def preprocess_query(text: str, vocab: list):

    # 1 normalize
    text = normalize_text(text)

    # 2 spell correction
    text = correct_sentence(text)

    # 3 split compound words
    text = split_words(text, vocab)

    # 4 dynamic fuzzy correction
    words = text.split()
    words = [dynamic_word_fix(w, vocab) for w in words]

    return " ".join(words)

# ----------------------------
# Search API
# ----------------------------
@router.get("/search", response_model=ApiResponse)
async def search_faq(
    query: str = Query(..., description="User question"),
    db: AsyncSession = Depends(get_db)
):

    # load vocab from cache
    vocab = VOCAB_CACHE

    # Query cleaning
    clean_query = preprocess_query(query, vocab)

    print(f"Original Query: {query}")
    print(f"Clean Query: {clean_query}")

    # Generate vector
    query_vector = get_vector(clean_query)

    sql = text("""
        SELECT
            fq.question_text,
            fa.answer_text,
            1 - (fq.question_vector <=> CAST(:qv AS vector)) AS similarity
        FROM faq_questions fq
        JOIN faq_answers fa ON fa.question_id = fq.id
        JOIN faq_documents fd ON fd.id = fq.document_id
        WHERE fd.is_active = true
        ORDER BY fq.question_vector <=> CAST(:qv AS vector)
        LIMIT 1
    """)

    result = await db.execute(sql, {"qv": str(query_vector)})

    row = result.fetchone()

    if not row:
        return ApiResponse(
            success=False,
            status_code=404,
            message="No answer found for the query",
            data=None
        )

    similarity = float(row.similarity)

    if similarity < SIMILARITY_THRESHOLD:
        return ApiResponse(
            success=False,
            status_code=404,
            message="No relevant answer found for the query",
            data={
                "original_query": query,
                "cleaned_query": clean_query,
                "similarity": round(similarity, 3)
            }
        )

    return ApiResponse(
        success=True,
        status_code=200,
        message="Answer found for the query",
        data={
            "original_query": query,
            "cleaned_query": clean_query,
            "question": row.question_text,
            "answer": row.answer_text,
            "similarity": round(similarity, 3)
        }
    )