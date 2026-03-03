from pypdf import PdfReader
import psycopg2
import re
import os

from app.services.embedding_service import generate_embedding


def extract_faq_from_pdf(pdf_path):
    reader = PdfReader(pdf_path)

    full_text = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            full_text += text + "\n"

    # Pattern for numbered questions like 1.7 Question...
    pattern = r"(\d+\.\d+\s+.*?)(?=\n\d+\.\d+\s+|\Z)"

    matches = re.findall(pattern, full_text, re.DOTALL)

    faq_data = []

    for block in matches:
        lines = block.strip().split("\n")

        question = lines[0].strip()
        answer = " ".join(lines[1:]).strip()

        faq_data.append((question, answer))

    return faq_data


def insert_faq(cursor, question, answer, source_file, image_url=None):

    # Question embedding
    q_embedding = generate_embedding(question)

    cursor.execute(
        """
        INSERT INTO questions (question_text, embedding, source_file)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (question, q_embedding, source_file)
    )

    # Get the generated question ID
    question_id = cursor.fetchone()[0]

    # Answer embedding (question + answer)
    a_embedding = generate_embedding(question + " " + answer)

    cursor.execute(
        """
        INSERT INTO answers (question_id, answer_text, image_url, embedding)
        VALUES (%s, %s, %s, %s)
        """,
        (question_id, answer, image_url, a_embedding)
    )


def load_faq_pdf_to_db(pdf_path, db_config):

    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()

    faq_data = extract_faq_from_pdf(pdf_path)

    print(f"Found FAQs: {len(faq_data)}")

    source_file = os.path.basename(pdf_path)

    for question, answer in faq_data:
        insert_faq(cursor, question, answer, source_file)

    conn.commit()
    cursor.close()
    conn.close()

    print("✅ FAQ inserted into questions & answers tables successfully")