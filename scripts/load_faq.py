
import asyncio
import os
import sys
import selectors
import re

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text
from app.core.database import AsyncSessionLocal
from app.entites.faq_entities import FaqDocument  
from app.utilis.pdf_extracter import extract_faq_from_pdf
from app.utilis.vector_service import get_vector
from dotenv import load_dotenv
load_dotenv()

# ==============================
# CONFIG — .env se load hoga
# ==============================
BASE_URL   = os.getenv("BASE_URL", "http://10.147.8.83:70/")
PDF_FOLDER = os.getenv("PDF_FOLDER", r"http://10.147.8.83:70/")
TYPE_ID    = int(os.getenv("TYPE_ID", 30))


# ==============================
# INDEX FILTER FUNCTION
# ==============================
def is_index_question(question: str):
    pattern = r'^\d+(\.\d+)*\s+[A-Za-z ]+$'
    return bool(re.match(pattern, question.strip()))


# ==============================
# SAFE VECTOR FUNCTION
# ==============================
def safe_vector(text):
    try:
        vector = get_vector(text)

        if vector is None or len(vector) == 0:
            return None

        vector = "[" + ",".join(map(str, vector)) + "]"
        return vector

    except Exception as e:
        print("⚠️ Vector error:", e)
        return None


async def load_faq(pdf_path: str):

    print(f"\n📄 Processing PDF: {pdf_path}")

    async with AsyncSessionLocal() as db:

        result = await db.execute(
            select(FaqDocument).where(FaqDocument.file_path == pdf_path)
        )

        existing_doc = result.scalar_one_or_none()

        if existing_doc:
            print("⚠️ FAQ already loaded — reusing existing document")
            document_id = existing_doc.id

        else:
            doc_result = await db.execute(text("""
                INSERT INTO faq_documents
                (file_name, file_path, type_id, is_active, status)
                VALUES (:name, :path, :type_id, true, true)
                RETURNING id
            """), {
                "name":    os.path.basename(pdf_path),
                "path":    BASE_URL + os.path.basename(pdf_path),
                "type_id": TYPE_ID
            })

            document_id = doc_result.scalar()
            await db.commit()

            print(f"✅ Document saved — ID: {document_id}")

    print("Step 1 — Extracting Q&A from PDF...")

    qa_pairs = extract_faq_from_pdf(pdf_path)

    if not qa_pairs:
        print("❌ No Q&A found — check PDF format")
        return

    print(f"✅ Total Q&A found: {len(qa_pairs)}")

    async with AsyncSessionLocal() as db:

        print("Step 2 — Creating vectors and saving...")

        saved   = 0
        skipped = 0

        for index, pair in enumerate(qa_pairs):

            question_text = pair["question"].strip()
            answer_text   = pair["answer"].strip()

            if not question_text or not answer_text:
                skipped += 1
                continue

            if is_index_question(question_text):
                print("⚠️ Index skipped")
                skipped += 1
                continue

            print(f"[{index+1}/{len(qa_pairs)}] {question_text[:60]}")

            existing_q = await db.execute(
                text("""
                    SELECT id FROM faq_questions
                    WHERE question_text = :q AND document_id = :doc
                """),
                {"q": question_text, "doc": document_id}
            )

            if existing_q.first():
                print("⚠️ Duplicate — skipping")
                skipped += 1
                continue

            question_vector = safe_vector(question_text)

            if question_vector is None:
                print("⚠️ Vector generation failed — skipping")
                skipped += 1
                continue

            q_result = await db.execute(text("""
                INSERT INTO faq_questions
                (document_id, type_master_id, question_text, question_vector, status)
                VALUES (:doc, :type, :question, :vector, true)
                RETURNING id
            """), {
                "doc":      document_id,
                "type":     TYPE_ID,
                "question": question_text,
                "vector":   question_vector
            })

            question_id = q_result.scalar()


            await db.execute(text("""
                INSERT INTO faq_answers
                (question_id, answer_text, status)
                VALUES (:qid, :answer, true)
            """), {
                "qid":    question_id,
                "answer": answer_text
            })

            saved += 1

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



async def load_all_pdfs():
    for file in os.listdir(PDF_FOLDER):
        if file.endswith(".pdf"):
            pdf_path = os.path.join(PDF_FOLDER, file)
            await load_faq(pdf_path)


if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    loop.run_until_complete(load_all_pdfs())

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

