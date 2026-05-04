import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router
from app.core.database import check_database_connection, init_models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ChatBot API",
    version="1.0.0",
    description="FastAPI + Neon PostgreSQL example with async CRUD support.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    try:
        await init_models()
        logger.info("Database models initialized successfully.")
    except Exception as e:
        logger.warning("init_models failed (non-fatal): %s", e)

    db_connected, message = await check_database_connection()
    if db_connected:
        logger.info("Database startup check passed: %s", message)
    else:
        logger.warning("Database startup check failed: %s", message)


@app.get("/")
async def root():
    return {
        "message": "FastAPI server is running.",
        "docs": "/docs",
        "neon_demo_endpoints": "/api/v1/neon-notes",
    }


@app.get("/health/database")
async def database_health():
    ok, message = await check_database_connection()
    return {"ok": ok, "message": message}


app.include_router(router)