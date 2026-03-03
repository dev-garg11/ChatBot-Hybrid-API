from pydantic import BaseModel
class Faq(BaseModel):
    typeMasterId: int
    question: str
    answer: str