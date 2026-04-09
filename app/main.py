import asyncio
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.api.router import router
from app.utilis.spell_service import load_dictionary
from app.utilis.cache import VOCAB_CACHE

app = FastAPI(
    title="ChatBot API",
    version="1.0.0"
)

# ----------------------------
# Root endpoint
# ----------------------------

@app.get("/")
async def home():
    return {"message": "ChatBot API running successfully"}

# ----------------------------
# CORS
# ----------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Background vocabulary loader
# ----------------------------

async def load_vocab():
    try:
        print("🔄 Starting vocabulary cache loading...")
        async with AsyncSessionLocal() as db:

            result = await db.execute(
                text("SELECT question_text FROM faq_questions")
            )

            rows = result.fetchall()

            vocab = []

            for row in rows:
                vocab.extend(row[0].lower().split())

            vocab = list(set(vocab))

            VOCAB_CACHE.extend(vocab)

            load_dictionary(vocab)

            print(f"✅ Vocabulary cache loaded successfully ({len(vocab)} words)")

    except Exception as e:
        print(f"⚠️ Vocabulary load warning: {e}")

# ----------------------------
# Database connection check
# ----------------------------

async def check_database_connection():
    """Test database connection with timeout"""
    try:
        print("🔄 Testing database connection...")
        async with AsyncSessionLocal() as db:
            await asyncio.wait_for(
                db.execute(text("SELECT 1")),
                timeout=10.0  # 10 second timeout
            )
        print("✅ Database connection successful")
        return True
    except asyncio.TimeoutError:
        print("⚠️ Database connection timeout (10s)")
        return False
    except Exception as e:
        print(f"⚠️ Database connection failed: {e}")
        return False

# ----------------------------
# Startup event
# ----------------------------

@app.on_event("startup")
async def startup_event():
    try:
        db_url = os.getenv("DATABASE_URL", "Not set")
        print(f"📌 DATABASE_URL: {db_url[:50]}..." if len(str(db_url)) > 50 else f"📌 DATABASE_URL: {db_url}")
        
        # Check database connection
        db_connected = await check_database_connection()
        
        if db_connected:
            # Load vocabulary in background if database is ready
            asyncio.create_task(load_vocab())
            print("🚀 Background vocabulary loader started")
        else:
            print("⚠️ Database not ready - vocabulary cache will be loaded manually later")
            
    except Exception as e:
        print(f"⚠️ Startup error: {e}")

# ----------------------------
# Routers
# ----------------------------

app.include_router(router)