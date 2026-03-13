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
from app.utilis.llm_service import generate_llm_answer

router = APIRouter(prefix="/faq", tags=["FAQ"])

SIMILARITY_THRESHOLD = 0.65


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


# ----------------------------
# Dynamic Word Fix
# ----------------------------
def dynamic_word_fix(word, vocab):

    if len(word) < 3:
        return word

    match = process.extractOne(word, vocab)

    if match and match[1] > 60:
        return match[0]

    return word


# ----------------------------
# Query Preprocessing
# ----------------------------
def preprocess_query(text: str, vocab: list):

    text = normalize_text(text)
    text = correct_sentence(text)
    text = split_words(text, vocab)

    words = text.split()
    words = [dynamic_word_fix(w, vocab) for w in words]

    return " ".join(words)


# ----------------------------
# Query Splitting
# ----------------------------
def split_query(query: str):

    parts = re.split(r'\band\b|[.,?&/;]', query)

    questions = []

    for p in parts:
        p = p.strip()

        if len(p) > 3:
            questions.append(p)

    return questions


# ----------------------------
# Search API
# ----------------------------
@router.get("/search", response_model=ApiResponse)
async def search_faq(
    query: str = Query(..., description="User question"),
    db: AsyncSession = Depends(get_db)
):

    vocab = VOCAB_CACHE

    print(f"Original Query: {query}")

    # Split query into multiple questions
    questions = split_query(query)
    print("Split Questions:", questions)

    answers = []

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
        LIMIT 5
    """)

    # Search loop for each question
    for q in questions:

        if "receipt" not in q:
            q = q + " receipt"

        clean_query = preprocess_query(q, vocab)

        print(f"Processing Question: {q}")
        print(f"Clean Query: {clean_query}")

        query_vector = get_vector(clean_query)

        result = await db.execute(sql, {"qv": str(query_vector)})
        rows = result.fetchall()

        for row in rows:

            similarity = float(row.similarity)

            if similarity < SIMILARITY_THRESHOLD:
                continue

            answers.append({
                "question": row.question_text,
                "answer": row.answer_text,
                "similarity": round(similarity, 3)
            })

    if not answers:
        return ApiResponse(
            success=False,
            status_code=404,
            message="No relevant answers found",
            data={"query": query}
        )

    # Remove duplicate answers
    unique_answers = {a["question"]: a for a in answers}
    answers = list(unique_answers.values())

        # ----------------------------
    # Build context for LLM
    # ----------------------------
    context = ""

    for a in answers:
            context += f"""
    Question: {a['question']}
    Answer: {a['answer']}
    """
            
    # ----------------------------
    # LLM Call
    # ----------------------------
    llm_response = generate_llm_answer(query, context)


    return ApiResponse(
        success=True,
        status_code=200,
        message="Answers genrated successfully",
        data={
            "original_query": query,
            "llm_answer": llm_response,
            "vector_results": answers
        }
    )