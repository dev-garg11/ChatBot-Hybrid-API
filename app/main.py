import logging
import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router
from app.core.database import check_database_connection, init_models

# -------------------- LOGGING --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- APP INIT --------------------
app = FastAPI(
    title="ChatBot API",
    version="3.0.0",
    description="FastAPI + Neon PostgreSQL async backend.",
)

# -------------------- CORS --------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- STARTUP --------------------
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 App starting...")

    async def init_db():
        try:
            await init_models()
            logger.info("✅ Database models initialized.")
        except Exception as e:
            logger.warning(f"⚠️ init_models failed: {e}")

    async def check_db():
        try:
            ok, message = await check_database_connection()
            if ok:
                logger.info(f"✅ DB connected: {message}")
            else:
                logger.warning(f"❌ DB check failed: {message}")
        except Exception as e:
            logger.warning(f"❌ DB connection error: {e}")

    asyncio.create_task(init_db())
    asyncio.create_task(check_db())

# -------------------- ROUTES --------------------
@app.get("/")
async def root():
    return {
        "message": "FastAPI server is running 🚀",
        "docs": "/docs",
    }

@app.get("/ping")
async def ping():
    return {"status": "alive"}

@app.get("/health/database")
async def database_health():
    try:
        ok, message = await check_database_connection()
        return {"ok": ok, "message": message}
    except Exception as e:
        return {"ok": False, "message": str(e)}

# -------------------- ROUTER --------------------
app.include_router(router)

# -------------------- LOCAL RUN ONLY --------------------
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))

    logger.info(f"Starting server on port {port}")

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port
    )