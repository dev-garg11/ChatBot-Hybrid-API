from pydantic import BaseModel
class TypeMasterRequestDto(BaseModel):
    type_name: str
    description: str