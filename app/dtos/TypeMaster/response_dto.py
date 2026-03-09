from pydantic import BaseModel
class TypeMasterResponseDto(BaseModel):
    type_name: str
    description: str