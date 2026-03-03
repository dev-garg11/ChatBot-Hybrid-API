# question -> text clean -> spelling correct -> ai search -> answer

from sentence_transformers import SentenceTransformer
import psycopg2
import re
from rapidfuzz import process

model = SentenceTransformer("all-MiniLM-L6-v2")


def load_domain_vocabulary(cursor):
    """
    Load words from database questions to build dynamic vocabulary.
    """
    cursor.execute("SELECT question_text FROM questions")
    rows = cursor.fetchall()

    vocab = set()

    for row in rows:
        words = row[0].lower().split()
        for w in words:
            vocab.add(w)

    return list(vocab)

# ⭐ normalize text
def normalize_text(text: str) -> str:
    text = text.lower()

    # numbers → letters
    text = text.replace("0", "o").replace("1", "i").replace("3", "e")

    # remove repeated letters (clooooose → close)
    text = re.sub(r"(.)\1{2,}", r"\1", text)

    # remove special chars
    text = re.sub(r"[^a-z0-9\s]", "", text)

    return text.strip()


# ⭐ fuzzy correction
def fuzzy_correct_word(word: str, vocab: list) -> str:
    match = process.extractOne(word, vocab)

    if match and match[1] > 65:   # little relaxed threshold
        return match[0]

    return word


# ⭐ full preprocess
def preprocess_query(text: str, vocab: list) -> str:
    text = normalize_text(text)

    words = text.split()

    corrected_words = [fuzzy_correct_word(w, vocab) for w in words]

    return " ".join(corrected_words)


def search_faq(question, db_config, limit=3):
    conn = None
    try:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()

        # load vocabulary from DB
        vocab = load_domain_vocabulary(cursor)

        # preprocess user query
        clean_question = preprocess_query(question, vocab)
        
        query_embedding = model.encode(clean_question).tolist()

        cursor.execute(
            """
            SELECT 
                q.question_text, 
                a.answer_text, 
                a.image_url,
                a.embedding <-> %s::vector AS distance
            FROM answers a
            JOIN questions q ON a.question_id = q.id
            ORDER BY distance
            LIMIT %s
            """,
            (query_embedding, limit)
        )

        result = cursor.fetchone()

        if result:
            question_text, answer_text, image_url, distance = result

            if distance > 0.9:
                return None

            return {
                "question": question_text,
                "answer": answer_text,
                "image": image_url,
                "distance": float(distance)
            }

        return None

    finally:
        if conn:
            cursor.close()
            conn.close()