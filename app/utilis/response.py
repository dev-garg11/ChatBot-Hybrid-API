from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel

T = TypeVar('T')

class ApiResponse(BaseModel, Generic[T]):
    success: bool
    status_code: Optional[int]
    message: str
    data: Optional[T] = None

    def __init__(self, success: bool, status_code: Optional[int] = None, message: str = "", data: Any = None):
        super().__init__(
            success=success,
            status_code=status_code,
            message=message,
            data=data
        )