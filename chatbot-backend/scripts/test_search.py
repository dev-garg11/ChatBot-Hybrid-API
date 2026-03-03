import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.services.faq_service import search_faq

db_config = {
    "host": "localhost",
    "database": "chatbot-db",
    "user": "postgres",
    "password": "1234"
}

result = search_faq("How to track receipt?", db_config)

print(result)