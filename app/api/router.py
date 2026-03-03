from fastapi import APIRouter 
from app.api.typemaster_api import router as typemaster_router
router = APIRouter()
 
router.include_router(typemaster_router)