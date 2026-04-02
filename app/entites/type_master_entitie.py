from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from app.core.base import Base
from datetime import datetime
from sqlalchemy.sql import func


class TypeMaster(Base):
    __tablename__ = "type_master"

    type_master_id = Column(Integer, primary_key=True, index=True)
    type_name = Column(String(255), nullable=False)
    description = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    is_active = Column(Boolean, default=True)

    questions = relationship("FaqQuestion", back_populates="type_master")