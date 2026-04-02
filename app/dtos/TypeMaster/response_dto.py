from pydantic import BaseModel

class TypeMasterResponseDto(BaseModel):
    type_master_id: int
    type_name: str
    description: str