from pydantic import BaseModel

class FaqAnswerResponseDto(BaseModel):
    question: str
    answer: str
    similarity: float