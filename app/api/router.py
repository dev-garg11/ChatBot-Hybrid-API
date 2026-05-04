from fastapi import APIRouter

from app.api.typemaster_api import router as typemaster_router
from app.api.faq_api import faq_router
from app.api.questions_api import question_router
from app.api.answers_api import answer_router
from app.api.Documents_api import document_router


router = APIRouter(prefix="/api/v1")

# Sirf include karo — prefix/tags already router files mein hain
router.include_router(faq_router)
router.include_router(question_router)
router.include_router(answer_router)
router.include_router(document_router)
router.include_router(typemaster_router)

