from fastapi import APIRouter 
from app.api.typemaster_api import router as typemaster_router
from app.api.faq_api import router as faq_router
router = APIRouter()

router.include_router(faq_router)
router.include_router(typemaster_router)