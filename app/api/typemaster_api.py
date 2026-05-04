from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy import text
import logging
import re

from app.core.database import NeonHTTPSession, get_db
from app.dtos.TypeMaster.request_dto import TypeMasterRequestDto
from app.utilis.response import ApiResponse

router = APIRouter(
    prefix="/types",
    tags=["TypeMaster"]
)

logger = logging.getLogger(__name__)


# ============================================================
# NORMALIZE
# ============================================================

def normalize_text(text_value: str) -> str:

    if not text_value:
        return ""

    text_value = text_value.lower().strip()

    text_value = re.sub(
        r"[^a-z0-9\s]",
        "",
        text_value
    )

    text_value = re.sub(
        r"\s+",
        " ",
        text_value
    )

    return text_value


# ============================================================
# CREATE
# ============================================================

@router.post("", response_model=ApiResponse)
async def add_type_master(
    request: TypeMasterRequestDto,
    db: NeonHTTPSession = Depends(get_db)
):

    try:

        original_name = request.type_name.strip()

        normalized_name = normalize_text(original_name)

        if not normalized_name:

            return ApiResponse(
                False, 400,
                "Type name cannot be empty"
            )

        # DUPLICATE CHECK
        duplicate = await db.execute(
            text("""
                SELECT 1
                FROM type_master
                WHERE LOWER(
                    REGEXP_REPLACE(
                        TRIM(type_name),
                        '[^a-zA-Z0-9\\s]',
                        '',
                        'g'
                    )
                ) = :name
                AND is_active = true
            """),
            {"name": normalized_name}
        )

        if duplicate.scalar():

            return ApiResponse(
                False, 400,
                "Type already exists"
            )

        # INSERT
        result = await db.execute(
            text("""
                INSERT INTO type_master
                (
                    type_name,
                    description,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES
                (
                    :name,
                    :description,
                    true,
                    NOW(),
                    NOW()
                )
                RETURNING
                    type_master_id,
                    type_name,
                    description,
                    is_active,
                    created_at,
                    updated_at
            """),
            {
                "name": original_name,
                "description": request.description
            }
        )

        await db.commit()

        row = result.fetchone()

        return ApiResponse(
            True, 201,
            "Created successfully",
            {
                "type_master_id":   row.type_master_id,
                "type_id":          row.type_master_id,
                "type_name":        row.type_name,
                "description":      row.description,
                "is_active":        row.is_active,
                "total_documents":  0,
                "total_questions":  0,
                "created_at":       str(row.created_at),
                "updated_at":       str(row.updated_at)
            }
        )

    except Exception as e:

        await db.rollback()

        logger.exception(f"Add TypeMaster failed: {str(e)}")

        return ApiResponse(False, 500, "Internal server error")


# ============================================================
# GET BY ID
# ============================================================

@router.get("/{type_id}", response_model=ApiResponse)
async def get_type_by_id(
    type_id: int,
    db: NeonHTTPSession = Depends(get_db)
):

    try:

        result = await db.execute(
            text("""
                SELECT
                    t.type_master_id,
                    t.type_name,
                    t.description,
                    t.is_active,
                    t.created_at,
                    t.updated_at,

                    COUNT(DISTINCT d.id)
                        FILTER (WHERE d.status = true)
                        AS total_documents,

                    COUNT(DISTINCT q.id)
                        FILTER (WHERE q.status = true)
                        AS total_questions

                FROM type_master t

                LEFT JOIN faq_documents d
                ON d.type_id = t.type_master_id

                LEFT JOIN faq_questions q
                ON q.type_master_id = t.type_master_id

                WHERE t.type_master_id = :id
                AND t.is_active = true

                GROUP BY
                    t.type_master_id,
                    t.type_name,
                    t.description,
                    t.is_active,
                    t.created_at,
                    t.updated_at
            """),
            {"id": type_id}
        )

        row = result.fetchone()

        if not row:

            return ApiResponse(
                False, 404,
                "Type not found"
            )

        return ApiResponse(
            True, 200,
            "Fetched successfully",
            {
                "type_master_id":  row.type_master_id,
                "type_id":         row.type_master_id,
                "type_name":       row.type_name,
                "description":     row.description,
                "is_active":       row.is_active,
                "total_documents": row.total_documents or 0,
                "total_questions": row.total_questions or 0,
                "created_at":      str(row.created_at),
                "updated_at":      str(row.updated_at)
            }
        )

    except Exception as e:

        logger.exception(f"Get TypeMaster by ID failed: {str(e)}")

        return ApiResponse(False, 500, "Internal server error")


# ============================================================
# GET ALL
# ============================================================

@router.get("", response_model=ApiResponse)
async def get_all_types(
    search: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(True),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: NeonHTTPSession = Depends(get_db)
):

    try:

        conditions = []
        params = {}

        if is_active is not None:

            conditions.append("t.is_active = :is_active")
            params["is_active"] = is_active

        if search:

            conditions.append("t.type_name ILIKE :search")
            params["search"] = f"%{search.strip()}%"

        where_clause = (
            "WHERE " + " AND ".join(conditions)
            if conditions else ""
        )

        offset = (page - 1) * limit

        params["limit"] = limit
        params["offset"] = offset

        # COUNT
        count_result = await db.execute(
            text(f"""
                SELECT COUNT(*)
                FROM type_master t
                {where_clause}
            """),
            params
        )

        total_items = count_result.scalar() or 0

        total_pages = (
            total_items + limit - 1
        ) // limit

        if total_items > 0 and page > total_pages:

            return ApiResponse(
                False, 400,
                "Invalid page number"
            )

        # FETCH WITH COUNTS
        result = await db.execute(
            text(f"""
                SELECT
                    t.type_master_id,
                    t.type_name,
                    t.description,
                    t.is_active,
                    t.created_at,
                    t.updated_at,

                    COUNT(DISTINCT d.id)
                        FILTER (WHERE d.status = true)
                        AS total_documents,

                    COUNT(DISTINCT q.id)
                        FILTER (WHERE q.status = true)
                        AS total_questions

                FROM type_master t

                LEFT JOIN faq_documents d
                ON d.type_id = t.type_master_id

                LEFT JOIN faq_questions q
                ON q.type_master_id = t.type_master_id

                {where_clause}

                GROUP BY
                    t.type_master_id,
                    t.type_name,
                    t.description,
                    t.is_active,
                    t.created_at,
                    t.updated_at

                ORDER BY t.updated_at DESC NULLS LAST

                LIMIT :limit
                OFFSET :offset
            """),
            params
        )

        rows = result.fetchall()

        return ApiResponse(
            True, 200,
            "Fetched successfully",
            {
                "items": [
                    {
                        "type_master_id":  row.type_master_id,
                        "type_id":         row.type_master_id,
                        "type_name":       row.type_name,
                        "description":     row.description,
                        "is_active":       row.is_active,
                        "total_documents": row.total_documents or 0,
                        "total_questions": row.total_questions or 0,
                        "created_at":      str(row.created_at),
                        "updated_at":      str(row.updated_at)
                    }
                    for row in rows
                ],
                "page":        page,
                "limit":       limit,
                "total_items": total_items,
                "total_pages": total_pages
            }
        )

    except Exception as e:

        logger.exception(f"Get all TypeMaster failed: {str(e)}")

        return ApiResponse(False, 500, "Internal server error")


# ============================================================
# UPDATE
# ============================================================

@router.put("/{type_id}", response_model=ApiResponse)
async def update_type_master(
    type_id: int,
    request: TypeMasterRequestDto,
    db: NeonHTTPSession = Depends(get_db)
):

    try:

        original_name = request.type_name.strip()

        normalized_name = normalize_text(original_name)

        if not normalized_name:

            return ApiResponse(
                False, 400,
                "Type name cannot be empty"
            )

        # EXIST CHECK
        existing = await db.execute(
            text("""
                SELECT 1
                FROM type_master
                WHERE type_master_id = :id
                AND is_active = true
            """),
            {"id": type_id}
        )

        if not existing.scalar():

            return ApiResponse(
                False, 404,
                "Type not found"
            )

        # DUPLICATE CHECK
        duplicate = await db.execute(
            text("""
                SELECT 1
                FROM type_master
                WHERE LOWER(
                    REGEXP_REPLACE(
                        TRIM(type_name),
                        '[^a-zA-Z0-9\\s]',
                        '',
                        'g'
                    )
                ) = :name
                AND type_master_id != :id
                AND is_active = true
            """),
            {
                "name": normalized_name,
                "id": type_id
            }
        )

        if duplicate.scalar():

            return ApiResponse(
                False, 400,
                "Type already exists"
            )

        # UPDATE
        result = await db.execute(
            text("""
                UPDATE type_master
                SET
                    type_name   = :name,
                    description = :description,
                    updated_at  = NOW()
                WHERE type_master_id = :id
                RETURNING
                    type_master_id,
                    type_name,
                    description,
                    is_active,
                    created_at,
                    updated_at
            """),
            {
                "name":        original_name,
                "description": request.description,
                "id":          type_id
            }
        )

        await db.commit()

        row = result.fetchone()

        if not row:

            return ApiResponse(
                False, 404,
                "Type not found"
            )

        return ApiResponse(
            True, 200,
            "Updated successfully",
            {
                "type_master_id": row.type_master_id,
                "type_id":        row.type_master_id,
                "type_name":      row.type_name,
                "description":    row.description,
                "is_active":      row.is_active,
                "created_at":     str(row.created_at),
                "updated_at":     str(row.updated_at)
            }
        )

    except Exception as e:

        await db.rollback()

        logger.exception(f"Update TypeMaster failed: {str(e)}")

        return ApiResponse(False, 500, "Internal server error")


# ============================================================
# DELETE (SOFT DELETE)
# ============================================================

@router.delete("/{type_id}", response_model=ApiResponse)
async def delete_type_master(
    type_id: int,
    db: NeonHTTPSession = Depends(get_db)
):

    try:

        existing = await db.execute(
            text("""
                SELECT is_active
                FROM type_master
                WHERE type_master_id = :id
            """),
            {"id": type_id}
        )

        row = existing.fetchone()

        if not row:

            return ApiResponse(
                False, 404,
                "Type not found"
            )

        if not row.is_active:

            return ApiResponse(
                False, 400,
                "Type already deleted"
            )

        # DEPENDENCY CHECK
        dependency = await db.execute(
            text("""
                SELECT 1
                FROM faq_documents
                WHERE type_id = :id
                AND status = true
                LIMIT 1
            """),
            {"id": type_id}
        )

        if dependency.scalar():

            return ApiResponse(
                False, 400,
                "Cannot delete type because documents are using it"
            )

        # SOFT DELETE
        await db.execute(
            text("""
                UPDATE type_master
                SET
                    is_active  = false,
                    updated_at = NOW()
                WHERE type_master_id = :id
            """),
            {"id": type_id}
        )

        await db.commit()

        return ApiResponse(
            True, 200,
            "Deleted successfully",
            {
                "type_master_id": type_id,
                "type_id":        type_id
            }
        )

    except Exception as e:

        await db.rollback()

        logger.exception(f"Delete TypeMaster failed: {str(e)}")

        return ApiResponse(False, 500, "Internal server error")