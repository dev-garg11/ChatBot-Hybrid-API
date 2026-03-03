import asyncpg

DATABASE_URL = "postgresql://postgres:1234@localhost:5432/chatbot-db"


async def connect_db():
    
    # connecting to PostgreSQL using this link
    return await asyncpg.connect(DATABASE_URL)