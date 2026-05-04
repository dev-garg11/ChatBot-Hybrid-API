# ChatBot-Hybrid-API

Ye project ab FastAPI ko Neon PostgreSQL ke saath async mode me connect karta hai. Isme ek simple `notes` table aur working CRUD endpoints diye gaye hain jisse aap Neon setup ko jaldi verify kar sakte ho.

## 1. Neon DB connection setup

1. Neon dashboard me jao aur apna project open karo.
2. `Connection Details` se PostgreSQL connection string copy karo.
3. Root folder me `.env` file banao ya update karo.
4. `DATABASE_URL` me Neon ka connection string paste karo.

Example:

```env
DATABASE_URL=postgresql://YOUR_USERNAME:YOUR_PASSWORD@YOUR_NEON_HOST/YOUR_DATABASE?sslmode=require
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

Important:

- `sslmode=require` Neon ke saath zaroor rakho.
- Real credentials ko git me commit mat karo.
- Agar aapka password ya host galat hai to `/health/database` helpful message dega.

## 2. FastAPI me database connect karna

Database connection file: [app/core/database.py](C:/Users/lenovo/OneDrive/Documents/GitHub/ChatBot-Hybrid-API/app/core/database.py)

Is file me:

- normal PostgreSQL URL ko automatically `postgresql+asyncpg://` me convert kiya jata hai
- async SQLAlchemy engine create hota hai
- session factory banti hai
- DNS issue, timeout, invalid credentials, SSL issue ke friendly messages milte hain

Beginner note:

- `engine` actual database connection manager hota hai
- `AsyncSessionLocal` har request ke liye session banata hai
- `get_async_session()` FastAPI dependency hai jo endpoint me session inject karta hai

## 3. Simple model/table create karna

Example model: [app/entites/note_entity.py](C:/Users/lenovo/OneDrive/Documents/GitHub/ChatBot-Hybrid-API/app/entites/note_entity.py)

```python
class Note(Base):
    __tablename__ = "notes"
```

Fields:

- `id`
- `title`
- `content`
- `created_at`
- `updated_at`

Startup ke time [app/main.py](C:/Users/lenovo/OneDrive/Documents/GitHub/ChatBot-Hybrid-API/app/main.py) `init_models()` call karta hai, jo `notes` table ko create kar deta hai agar wo pehle se exist nahi karti.

## 4. API endpoints banana

Router file: [app/api/neon_demo_api.py](C:/Users/lenovo/OneDrive/Documents/GitHub/ChatBot-Hybrid-API/app/api/neon_demo_api.py)

Available endpoints:

- `POST /api/v1/neon-notes` -> note create karega
- `GET /api/v1/neon-notes` -> saari notes fetch karega
- `GET /api/v1/neon-notes/{note_id}` -> single note fetch karega
- `PUT /api/v1/neon-notes/{note_id}` -> note update karega
- `DELETE /api/v1/neon-notes/{note_id}` -> note delete karega

## 5. Data add + fetch example

Create note:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/neon-notes" \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"First Neon Note\",\"content\":\"Stored in Neon from FastAPI.\"}"
```

Fetch all notes:

```bash
curl "http://127.0.0.1:8000/api/v1/neon-notes"
```

## 6. Project run karna

1. Virtual environment activate karo.
2. Dependencies install karo:

```bash
pip install -r requirements.txt
```

3. Server start karo:

```bash
uvicorn app.main:app --reload
```

4. Browser me open karo:

- Swagger docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- DB health: [http://127.0.0.1:8000/health/database](http://127.0.0.1:8000/health/database)

## 7. Error handling kaise kaam kar rahi hai

`app/core/database.py` me common problems ke liye readable messages diye gaye hain:

- DNS issue: Neon host galat ho to
- Connection timeout: network slow ya blocked ho to
- Invalid credentials: username/password galat ho to
- SSL issue: `sslmode=require` missing ho to

Isse beginner ko raw stack trace ke bajaye samajhne layak message milta hai.

## 8. Async support kyu useful hai

Yeh setup `asyncpg` + SQLAlchemy async engine use karta hai.

Benefits:

- zyada concurrent requests handle kar sakta hai
- database wait time me server block nahi hota
- Neon jaise hosted PostgreSQL ke saath better performance pattern milta hai

## 9. Important files

- [app/core/config.py](C:/Users/lenovo/OneDrive/Documents/GitHub/ChatBot-Hybrid-API/app/core/config.py)
- [app/core/database.py](C:/Users/lenovo/OneDrive/Documents/GitHub/ChatBot-Hybrid-API/app/core/database.py)
- [app/entites/note_entity.py](C:/Users/lenovo/OneDrive/Documents/GitHub/ChatBot-Hybrid-API/app/entites/note_entity.py)
- [app/schemas/note_schema.py](C:/Users/lenovo/OneDrive/Documents/GitHub/ChatBot-Hybrid-API/app/schemas/note_schema.py)
- [app/api/neon_demo_api.py](C:/Users/lenovo/OneDrive/Documents/GitHub/ChatBot-Hybrid-API/app/api/neon_demo_api.py)
- [app/main.py](C:/Users/lenovo/OneDrive/Documents/GitHub/ChatBot-Hybrid-API/app/main.py)

## 10. Quick summary

- Neon connection string `.env` me rakho
- FastAPI async SQLAlchemy engine use karega
- `notes` table startup pe auto-create ho jayegi
- CRUD endpoints ready hain
- `/health/database` se connection test kar sakte ho
