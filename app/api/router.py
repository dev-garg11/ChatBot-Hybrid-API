from fastapi import APIRouter
from app.api.typemaster_api import router as typemaster_router
from app.api.faq_api import faq_router, question_router, answer_router, document_router

router = APIRouter()

router.include_router(faq_router)
router.include_router(question_router)
router.include_router(answer_router)
router.include_router(document_router)
router.include_router(typemaster_router)