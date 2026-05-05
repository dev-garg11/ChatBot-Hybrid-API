from sqlalchemy import Column, Integer, Text, ForeignKey, DateTime, Boolean
from datetime import datetime
from app.core.base import Base
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import relationship

class PDFChunk(Base):
    __tablename__ = "pdf_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("faq_documents.id"), nullable=False)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(384))
    chunk_index = Column(Integer)             
    image_paths = Column(Text)           
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(Boolean, default=True)

    document = relationship("FaqDocument")