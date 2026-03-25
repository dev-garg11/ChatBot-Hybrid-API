from pydantic import BaseModel
from typing import Optional

class TypeMasterRequestDto(BaseModel):
    type_name: str
    description: Optional[str] = None   