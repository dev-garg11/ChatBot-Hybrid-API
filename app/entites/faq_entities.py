from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, String, Boolean
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.core.base import Base
from datetime import datetime


class FaqDocument(Base):
    __tablename__ = "faq_documents"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    file_name   = Column(String(255), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    is_active   = Column(Boolean, default=True)

    questions = relationship("FaqQuestion", back_populates="document")


class FaqQuestion(Base):
    __tablename__ = "faq_questions"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    document_id     = Column(Integer, ForeignKey("faq_documents.id"), nullable=False)
    question_text   = Column(Text, nullable=False)
    question_vector = Column(Vector(384))
    created_at      = Column(DateTime, default=datetime.utcnow)

    document = relationship("FaqDocument", back_populates="questions")
    answer   = relationship("FaqAnswer", back_populates="question", uselist=False)

class FaqAnswer(Base):
    __tablename__ = "faq_answers"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    question_id   = Column(Integer, ForeignKey("faq_questions.id"), nullable=False)
    answer_text   = Column(Text, nullable=False)
    answer_vector = Column(Vector(384))
    created_at    = Column(DateTime, default=datetime.utcnow)

    question = relationship("FaqQuestion", back_populates="answer")


    
class PdfQuestion(Base):
    __tablename__ = "pdf_questions"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("faq_documents.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    question_vector = Column(Vector(384))  # all-MiniLM = 384 dimensions
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(Boolean, default=True)

    # Relationship
    answers = relationship("PdfAnswer", back_populates="question")


class PdfAnswer(Base):
   __tablename__ = "pdf_answers"

   id = Column(Integer, primary_key=True, index=True)
   question_id = Column(Integer, ForeignKey("pdf_questions.id"), nullable=False)
   answer_text = Column(Text, nullable=False)
   answer_vector = Column(Vector(384))  # all-MiniLM = 384 dimensions
   created_at = Column(DateTime, default=datetime.utcnow)
   status = Column(Boolean, default=True)
   image_paths = Column(Text, nullable=True)  # ✅ JSON string
   
   # Relationship
   question = relationship("PdfQuestion", back_populates="answers")