from fastapi import APIRouter
from pydantic import BaseModel

from app.services.faq_service import  search_faq
from app.services.search_service import search_similar_chunks


router = APIRouter()


# @router.get("/scripts")
# async def scripts():
#     return await get_all_scripts()

db_config = {
    "host": "localhost",
    "database": "chatbot-db",
    "user": "postgres",
    "password": "1234"
}

class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
async def chat(request: ChatRequest):

   query = request.message.strip()

   # Search FAQ
   faq_answer = search_faq(query, db_config)

   if faq_answer:
      return {
         "source": "faq",
         "reply": faq_answer["answer"]
      }
   
   # If not found in FAQ, search Script

   # Search Script
#    script_answer = await search_script(query)

#    if script_answer:
#         return {
#             "source": "script",
#             "reply": script_answer
#         }
    
#       # 2️⃣ Search Documents
#    doc_answer = search_pdf(query, db_config)
#    if doc_answer:
#         return {
#             "source": "document",
#             "reply": doc_answer[0][0], 
#         }
   
   # NOt found
   return {
       "source": "none",
       "reply":"sorry, i dont have an answer to that question"}