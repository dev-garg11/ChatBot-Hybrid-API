import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.services.faq_pdf_loader import load_faq_pdf_to_db

db_config = {
    "host": "localhost",
    "database": "chatbot-db",
    "user": "postgres",
    "password": "1234"
}

pdf_path = "data/faq/FAQ_0.pdf"

load_faq_pdf_to_db(pdf_path, db_config)