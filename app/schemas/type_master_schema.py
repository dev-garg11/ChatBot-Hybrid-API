from pydantic import BaseModel
from typing import Optional

class TypeMasterCreate(BaseModel):
    type_name: str
    description: Optional[str] = None
    is_active: bool = True