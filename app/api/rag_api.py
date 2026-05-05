from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, field_validator
import logging

from app.core.database import get_db
from app.services.rag_service import get_rag_answer
from app.services.hybrid_service import get_hybrid_answer
from app.utilis.query_service import rewrite_query
from app.utilis.query_processing import process_query
from app.utilis.query_control import should_rewrite
from app.utilis.response import ApiResponse

# 🔥 CONFIG
from app.core.config_values import (
    MAX_TOP_K,
    MIN_QUERY_LENGTH,
    MAX_QUERY_LENGTH
)

router = APIRouter(prefix="/rag", tags=["RAG"])
logger = logging.getLogger(__name__)


# ============================================================
# 🔥 COMMON PIPELINE (NEW)
# ============================================================

async def process_pipeline(query: str):
    query = process_query(query)

    if should_rewrite(query):
        logger.info("🔁 Rewriting query...")
        query = await rewrite_query(query)
    else:
        logger.info("⚡ Using original query")

    return query


# ============================================================
# REQUEST MODEL
# ============================================================

class AskRequest(BaseModel):
    query: str
    top_k: int = 5

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str):
        v = v.strip()

        if not v:
            raise ValueError("Query cannot be empty")
        if len(v) < MIN_QUERY_LENGTH:
            raise ValueError("Query too short")
        if len(v) > MAX_QUERY_LENGTH:
            raise ValueError("Query too long")

        return v

    @field_validator("top_k")
    @classmethod
    def validate_top_k(cls, v):
        if v <= 0:
            return 5
        return min(v, MAX_TOP_K)


# ============================================================
# RAG API
# ============================================================
@router.post("/ask")
async def ask_question(
    request: AskRequest,
    db: AsyncSession = Depends(get_db)
):
    try:
        logger.info(f"📩 RAG Query: {request.query}")

        query = await process_pipeline(request.query)

        result = await get_rag_answer(query, db, top_k=request.top_k)

        if not result or not result.get("answer"):
            return ApiResponse(success=False, status_code=404, message="No relevant answer found")

        return ApiResponse(
            success=True,
            status_code=200,
            message="Answer found",
            data={
                "query": request.query,
                "processed_query": query,
                "answer": result.get("answer"),
                "sources": result.get("sources", [])
            }
        )

    except Exception as e:
        logger.error(f"❌ RAG Error: {str(e)}")
        raise HTTPException(status_code=500, detail="RAG processing failed")


@router.post("/chat")
async def chat(
    request: AskRequest,
    db: AsyncSession = Depends(get_db)
):
    try:
        logger.info(f"💬 Hybrid Query: {request.query}")

        query = await process_pipeline(request.query)

        result = await get_hybrid_answer(query, db)

        if not result or not result.get("answer"):
            return ApiResponse(success=False, status_code=404, message="No answer found")

        return ApiResponse(
            success=True,
            status_code=200,
            message="Answer found",
            data={
                "query": request.query,
                "processed_query": query,
                "answer": result.get("answer"),
                "sources": result.get("sources", [])
            }
        )

    except Exception as e:
        logger.error(f"❌ Hybrid Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Chat processing failed")