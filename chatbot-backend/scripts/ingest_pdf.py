# scripts/ingest_pdf.py

from app.services.pdf_loader import load_pdf_to_db

db_config = {
    "host": "localhost",
    "database": "chatbot-db",
    "user": "postgres",
    "password": "1234"
}

pdf_path = "data/sample.pdf"

load_pdf_to_db(pdf_path, db_config)