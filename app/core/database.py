from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession,async_sessionmaker
from sqlalchemy.orm import sessionmaker
from app.core.config import settings  
engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args={"ssl": "disable"},
    pool_pre_ping=True,
    echo=True
)

AsyncSessionLocal = sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession
)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
