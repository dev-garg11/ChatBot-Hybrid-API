from sqlalchemy import Column, Integer, String,   DateTime,  Boolean
from app.core.base import Base

class TypeMaster(Base):
    __tablename__ = "type_master"

    type_master_id = Column(Integer, primary_key=True) 
    type_name = Column(String(255), nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)