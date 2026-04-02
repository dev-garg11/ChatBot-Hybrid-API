from typing import Generic, TypeVar, Optional
from pydantic import BaseModel

T = TypeVar('T') 

class ApiResponse(BaseModel, Generic[T]):
    success: bool
    status_code: Optional[int]
    message: str
    data: Optional[T] = None