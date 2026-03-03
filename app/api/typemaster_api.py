from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession 
from app.core.database import get_db
from app.dtos.TypeMaster.request_dto import TypeMasterRequestDto
from app.dtos.TypeMaster.response_dto import TypeMasterRequestDto
from app.entites.type_master_entitie import TypeMaster
from app.utilis.response import ApiResponse
from datetime import datetime
router = APIRouter(prefix="/TypeMaster", tags=["TypeMaster"])

@router.post("", response_model=ApiResponse)
async def AddTypeMaster(
    request: TypeMasterRequestDto,
    db: AsyncSession = Depends(get_db)
):
    mapped_data = TypeMaster(
        type_name=request.type_name,
        description=request.description,
        created_at=datetime.utcnow(),
        is_active=True
    )
    db.add(mapped_data)
    await db.commit()
    await db.refresh(mapped_data)
    
    return ApiResponse(
        success=True,
        status_code=201,
        message="TypeMaster created successfully",
        data={
            "id": request.type_name,
            "name": request.description
        }
    )