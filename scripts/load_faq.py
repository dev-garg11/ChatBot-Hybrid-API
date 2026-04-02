from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, String, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select
from pgvector.sqlalchemy import Vector
from app.core.base import Base
from app.entites.type_master_entitie import TypeMaster
from datetime import datetime
from typing import Optional


# ----------------------------
# Document Table
# ----------------------------
class FaqDocument(Base):
    __tablename__ = "faq_documents"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    file_name   = Column(String(255), nullable=False)
    file_path   = Column(String(500), nullable=True)
    type_id     = Column(Integer, ForeignKey("type_master.type_master_id"), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    is_active   = Column(Boolean, default=True)
    status      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    questions = relationship(
        "FaqQuestion",
        back_populates="document",
        cascade="all, delete"
    )

    @classmethod
    async def create(cls, db: AsyncSession, file_name: str):
        doc = cls(file_name=file_name)
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc

    @classmethod
    async def get_by_id(cls, db: AsyncSession, document_id: int):
        result = await db.execute(
            select(cls).where(and_(cls.id == document_id, cls.status == True))
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_all(cls, db: AsyncSession, skip: int = 0, limit: int = 100):
        result = await db.execute(
            select(cls).where(cls.status == True).offset(skip).limit(limit)
        )
        return result.scalars().all()

    @classmethod
    async def delete(cls, db: AsyncSession, document_id: int, soft: bool = True):
        result = await db.execute(select(cls).where(cls.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return False
        if soft:
            doc.status = False
            await db.commit()
        else:
            await db.delete(doc)
            await db.commit()
        return True


# ----------------------------
# Question Table
# ----------------------------
class FaqQuestion(Base):
    __tablename__ = "faq_questions"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    document_id     = Column(Integer, ForeignKey("faq_documents.id"), nullable=False)
    type_master_id  = Column(Integer, ForeignKey("type_master.type_master_id"), nullable=True)
    question_text   = Column(Text, nullable=False)
    question_vector = Column(Vector(384))
    created_at      = Column(DateTime, default=datetime.utcnow)
    status          = Column(Boolean, default=True)

    document    = relationship("FaqDocument", back_populates="questions")
    answers     = relationship("FaqAnswer", back_populates="question", cascade="all, delete")
    type_master = relationship("TypeMaster", back_populates="questions")

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        document_id: int,
        question_text: str,
        question_vector: Optional[list[float]] = None,
        type_master_id: Optional[int] = None,
    ):
        question = cls(
            document_id=document_id,
            question_text=question_text,
            question_vector=question_vector,
            type_master_id=type_master_id,
        )
        db.add(question)
        await db.commit()
        await db.refresh(question)
        return question

    @classmethod
    async def get_by_id(cls, db: AsyncSession, question_id: int):
        result = await db.execute(
            select(cls).where(and_(cls.id == question_id, cls.status == True))
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_document(cls, db: AsyncSession, document_id: int):
        result = await db.execute(
            select(cls).where(and_(cls.document_id == document_id, cls.status == True))
        )
        return result.scalars().all()


# ----------------------------
# Answer Table
# ----------------------------
class FaqAnswer(Base):
    __tablename__ = "faq_answers"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    question_id   = Column(Integer, ForeignKey("faq_questions.id"), nullable=False)
    answer_text   = Column(Text, nullable=False)
    answer_vector = Column(Vector(384))
    created_at    = Column(DateTime, default=datetime.utcnow)
    status        = Column(Boolean, default=True)

    question = relationship("FaqQuestion", back_populates="answers")

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        question_id: int,
        answer_text: str,
        answer_vector: Optional[list[float]] = None,
    ):
        answer = cls(
            question_id=question_id,
            answer_text=answer_text,
            answer_vector=answer_vector,
        )
        db.add(answer)
        await db.commit()
        await db.refresh(answer)
        return answer


# ----------------------------
# PDF Question Table
# ----------------------------
class PdfQuestion(Base):
    __tablename__ = "pdf_questions"

    id              = Column(Integer, primary_key=True, index=True)
    document_id     = Column(Integer, ForeignKey("faq_documents.id"), nullable=False)
    question_text   = Column(Text, nullable=False)
    question_vector = Column(Vector(384))
    created_at      = Column(DateTime, default=datetime.utcnow)
    status          = Column(Boolean, default=True)

    answers = relationship("PdfAnswer", back_populates="question")


# ----------------------------
# PDF Answer Table
# ----------------------------
class PdfAnswer(Base):
    __tablename__ = "pdf_answers"

    id            = Column(Integer, primary_key=True, index=True)
    question_id   = Column(Integer, ForeignKey("pdf_questions.id"), nullable=False)
    answer_text   = Column(Text, nullable=False)
    answer_vector = Column(Vector(384))
    image_paths   = Column(Text, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    status        = Column(Boolean, default=True)

    question = relationship("PdfQuestion", back_populates="answers")