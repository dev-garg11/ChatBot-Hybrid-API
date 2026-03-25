
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

# entities import (tables)
from app.entites.type_master_entitie import TypeMaster
from app.entites.faq_entities import FaqDocument, FaqQuestion

# router
from app.api.router import router

# database session
from app.core.database import AsyncSessionLocal

# utilities
from app.utilis.spell_service import load_dictionary
from app.utilis.cache import VOCAB_CACHE


# ----------------------------
# FastAPI App
# ----------------------------
app = FastAPI(
    title="ChatBot API",
    version="1.0.0"
)


# ----------------------------
# Startup Event
# ----------------------------
@app.on_event("startup")
async def load_resources():

    print("🚀 Starting ChatBot API...")

    try:
        async with AsyncSessionLocal() as db:

            # Fetch all questions from database
            result = await db.execute(
                text("SELECT question_text FROM faq_questions")
            )

            rows = result.fetchall()

            if not rows:
                print("⚠ No FAQ questions found in database")
                return

            vocab = []

            # Create vocabulary list
            for row in rows:
                question = row[0]
                if question:
                    vocab.extend(question.lower().split())

            # remove duplicates
            vocab = list(set(vocab))

            # update cache
            VOCAB_CACHE.clear()
            VOCAB_CACHE.extend(vocab)

            # load spell dictionary
            load_dictionary(vocab)

            print("✅ Vocabulary cache loaded")
            print("✅ Spell dictionary loaded")

    except Exception as e:
        print("❌ Database/Vocabulary load failed:", e)


# ----------------------------
# CORS Middleware
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
# Include Router
# ----------------------------
app.include_router(router)


# ----------------------------
# Root API
# ----------------------------
@app.get("/")
async def root():
    return {
        "message": "ChatBot API is running",
        "docs": "/docs"
    }