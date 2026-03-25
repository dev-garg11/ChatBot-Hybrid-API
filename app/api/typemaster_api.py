from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from datetime import datetime

from app.core.database import get_db
from app.dtos.TypeMaster.request_dto import TypeMasterRequestDto
from app.entites.type_master_entitie import TypeMaster
from app.utilis.response import ApiResponse

router = APIRouter(prefix="/typemaster", tags=["TypeMaster"])

# -------------------------------
# CREATE TYPE MASTER
# -------------------------------
@router.post("", response_model=ApiResponse)
async def add_type_master(
    request: TypeMasterRequestDto,
    db: AsyncSession = Depends(get_db)
):
    try:
        # Check for existing type_name
        result = await db.execute(
            select(TypeMaster).where(TypeMaster.type_name == request.type_name)
        )
        existing_type = result.scalar_one_or_none()

        if existing_type:
            return ApiResponse(
                success=False,
                status_code=400,
                message=f"TypeMaster '{request.type_name}' already exists",
                data=None
            )

        new_type = TypeMaster(
            type_name=request.type_name,
            description=request.description,
            created_at=datetime.utcnow(),
            updated_at=None,
            is_active=True
        )

        db.add(new_type)
        await db.commit()
        await db.refresh(new_type)

        return ApiResponse(
            success=True,
            status_code=201,
            message="TypeMaster created successfully",
            data={
                "id": new_type.type_master_id,
                "type_name": new_type.type_name,
                "description": new_type.description,
                "is_active": new_type.is_active
            }
        )

    except IntegrityError:
        await db.rollback()
        return ApiResponse(
            success=False,
            status_code=400,
            message="Duplicate type name",
            data=None
        )
    except Exception as e:
        await db.rollback()
        return ApiResponse(
            success=False,
            status_code=500,
            message="Something went wrong",
            data=str(e)
        )


# -------------------------------
# GET ALL TYPES
# -------------------------------
@router.get("", response_model=ApiResponse)
async def get_all_types(
    search: str = Query(None, description="Search by type name"),
    is_active: bool = Query(None, description="Filter by active status"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    db: AsyncSession = Depends(get_db)
):
    query = select(TypeMaster)

    if search:
        query = query.where(TypeMaster.type_name.ilike(f"%{search}%"))

    if is_active is not None:
        query = query.where(TypeMaster.is_active == is_active)

    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    types = result.scalars().all()

    # Total items for pagination
    total_query = select(func.count(TypeMaster.type_master_id))
    if search:
        total_query = total_query.where(TypeMaster.type_name.ilike(f"%{search}%"))
    if is_active is not None:
        total_query = total_query.where(TypeMaster.is_active == is_active)
    total_result = await db.execute(total_query)
    total_items = total_result.scalar()

    data = [
        {
            "id": t.type_master_id,
            "type_name": t.type_name,
            "description": t.description,
            "is_active": t.is_active
        }
        for t in types
    ]

    return ApiResponse(
        success=True,
        status_code=200,
        message="TypeMaster list fetched successfully",
        data={
            "items": data,
            "page": page,
            "limit": limit,
            "total_items": total_items
        }
    )


# -------------------------------
# GET TYPE BY ID
# -------------------------------
@router.get("/{type_id}", response_model=ApiResponse)
async def get_type_by_id(
    type_id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(TypeMaster).where(TypeMaster.type_master_id == type_id)
    )
    type_data = result.scalar_one_or_none()

    if not type_data:
        return ApiResponse(
            success=False,
            status_code=404,
            message="TypeMaster not found",
            data=None
        )

    return ApiResponse(
        success=True,
        status_code=200,
        message="TypeMaster fetched successfully",
        data={
            "id": type_data.type_master_id,
            "type_name": type_data.type_name,
            "description": type_data.description,
            "is_active": type_data.is_active
        }
    )


# -------------------------------
# UPDATE TYPE
# -------------------------------
@router.put("/{type_id}", response_model=ApiResponse)
async def update_type_master(
    type_id: int,
    request: TypeMasterRequestDto,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(TypeMaster).where(TypeMaster.type_master_id == type_id)
    )
    type_data = result.scalar_one_or_none()

    if not type_data:
        return ApiResponse(
            success=False,
            status_code=404,
            message="TypeMaster not found",
            data=None
        )

    type_data.type_name = request.type_name
    type_data.description = request.description
    type_data.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(type_data)

    return ApiResponse(
        success=True,
        status_code=200,
        message="TypeMaster updated successfully",
        data={
            "id": type_data.type_master_id,
            "type_name": type_data.type_name,
            "description": type_data.description,
            "is_active": type_data.is_active
        }
    )


# -------------------------------
# DELETE TYPE
# -------------------------------
@router.delete("/{type_id}", response_model=ApiResponse)
async def delete_type_master(
    type_id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(TypeMaster).where(TypeMaster.type_master_id == type_id)
    )
    type_data = result.scalar_one_or_none()

    if not type_data:
        return ApiResponse(
            success=False,
            status_code=404,
            message="TypeMaster not found",
            data=None
        )

    await db.delete(type_data)
    await db.commit()

    return ApiResponse(
        success=True,
        status_code=200,
        message="TypeMaster deleted successfully",
        data={"deleted_id": type_id}
    )