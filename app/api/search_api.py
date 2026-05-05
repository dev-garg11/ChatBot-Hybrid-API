from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.core.database import get_db
from app.services.chunk_service import search_pdf_chunks
from app.utilis.response import ApiResponse
from app.utilis.query_processing import process_query
from app.utilis.query_service import rewrite_query
from app.utilis.query_control import should_rewrite

# 🔥 CONFIG
from app.core.config_values import MAX_TOP_K, MIN_QUERY_LENGTH, MAX_QUERY_LENGTH

router = APIRouter(prefix="/search", tags=["Search"])
logger = logging.getLogger(__name__)


# ============================================================
# 🔍 SEARCH PDF CHUNKS
# ============================================================

@router.get("/", response_model=ApiResponse)
async def search(
    query: str = Query(...),
    top_k: int = Query(5, ge=1, le=MAX_TOP_K),
    db: AsyncSession = Depends(get_db)
):
    try:
        query = query.strip()

        # 🔥 VALIDATION
        if not query:
            raise HTTPException(400, "Query cannot be empty")

        if len(query) < MIN_QUERY_LENGTH:
            raise HTTPException(400, "Query too short")

        if len(query) > MAX_QUERY_LENGTH:
            raise HTTPException(400, "Query too long")

        # 🔥 CLEAN
        query = process_query(query)

        # 🔥 CONDITIONAL REWRITE
        if should_rewrite(query):
            logger.info("🔁 Rewriting query...")
            query = await rewrite_query(query)

        # 🔥 SEARCH
        results = await search_pdf_chunks(db, query, top_k)

        if not results:
            return ApiResponse(False, 404, "No results found")

        return ApiResponse(
            True,
            200,
            "Results found",
            {
                "query": query,
                "count": len(results),
                "results": results
            }
        )

    except HTTPException as e:
        raise e

    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        raise HTTPException(500, "Search failed")