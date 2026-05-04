import logging
import asyncio

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
    version="1.0.0",
    description="FastAPI + Neon PostgreSQL example with async CRUD support.",
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
async def startup_event() -> None:
    logger.info("🚀 Starting application...")

    # Init DB models (safe timeout)
    try:
        await asyncio.wait_for(init_models(), timeout=10)
        logger.info("✅ Database models initialized successfully.")
    except Exception as e:
        logger.warning(f"⚠️ init_models failed: {e}")

    # DB connection check (safe timeout)
    try:
        db_connected, message = await asyncio.wait_for(
            check_database_connection(), timeout=10
        )
        if db_connected:
            logger.info(f"✅ Database connected: {message}")
        else:
            logger.warning(f"❌ Database check failed: {message}")
    except Exception as e:
        logger.warning(f"❌ Database connection error: {e}")

# -------------------- ROUTES --------------------
@app.get("/")
async def root():
    return {
        "message": "FastAPI server is running 🚀",
        "docs": "/docs",
    }

# simple health check (VERY IMPORTANT for Render)
@app.get("/ping")
async def ping():
    return {"status": "alive"}

@app.get("/health/database")
async def database_health():
    ok, message = await check_database_connection()
    return {"ok": ok, "message": message}

# -------------------- INCLUDE ROUTER --------------------
app.include_router(router)