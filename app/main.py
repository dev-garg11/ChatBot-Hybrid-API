from app.core.database import AsyncSessionLocal
from sqlalchemy import text
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import router
from app.utilis.spell_service import load_dictionary
from app.utilis.cache import VOCAB_CACHE

app = FastAPI(
    title="ChatBot API",
    version="1.0.0"
)

# ----------------------------
# Startup Event
# ----------------------------
@app.on_event("startup")
async def load_resources():

    async with AsyncSessionLocal() as db:

        result = await db.execute(
            text("SELECT question_text FROM faq_questions")
        )

        rows = result.fetchall()

        vocab = []

        for row in rows:
            vocab.extend(row[0].lower().split())

        vocab = list(set(vocab))

        # vocab cache
        VOCAB_CACHE.extend(vocab)

        # spell dictionary
        load_dictionary(vocab)

        print("✅ Vocabulary cache loaded")
        print("✅ Spell dictionary loaded")


# ----------------------------
# CORS
# ----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Router
# ----------------------------
app.include_router(router)