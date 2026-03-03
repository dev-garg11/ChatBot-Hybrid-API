#purpose  PDF -> text -> chunks -> vector embeddings -> store in database

from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
import psycopg2
from psycopg2.extras import execute_batch
import os
# Load the pre-trained model for generating embeddings
model = SentenceTransformer("all-MiniLM-L6-v2")


def chunk_text(text: str, chunk_size: int = 500):
    """
    Split large text into smaller chunks for better embeddings.
    """
    words = text.split()
    chunks = []

    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)

    return chunks


def extract_text_from_pdf(pdf_path: str):
    """
    Extract text from PDF file page by page.
    """
    reader = PdfReader(pdf_path)
    full_text = []

    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text()
        if page_text:
            full_text.append(page_text)

    return "\n".join(full_text)


def load_pdf_to_db(pdf_path: str, db_config: dict):
    """
    Main function:
    Reads PDF → creates embeddings → stores in database
    """

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    conn = None

    try:
        # Connect to database
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()

        print("📄 Reading PDF...")
        text = extract_text_from_pdf(pdf_path)

        if not text.strip():
            print("⚠️ No text found in PDF")
            return

        print("✂️ Creating chunks...")
        chunks = chunk_text(text)

        print(f"Total chunks created: {len(chunks)}")

        data_to_insert = []

        for chunk in chunks:
            embedding = model.encode(chunk).tolist()

            data_to_insert.append(
                (chunk, embedding, os.path.basename(pdf_path))
            )

        print("💾 Inserting into database...")

        execute_batch(
            cursor,
            """
            INSERT INTO pdf_chunks (content, embedding, source_file)
            VALUES (%s, %s, %s)
            """,
            data_to_insert
        )

        
        conn.commit()

        print("✅ PDF stored successfully")

    except Exception as e:
        print("❌ Error:", e)

        if conn:
            conn.rollback()

    finally:
        if conn:
            cursor.close()
            conn.close()