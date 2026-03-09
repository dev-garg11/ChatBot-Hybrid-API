from pydantic import BaseModel

class FaqSearchRequestDto(BaseModel):
    query: str