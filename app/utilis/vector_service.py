from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sentence_transformers import SentenceTransformer

# Global model variable
_model: Optional[SentenceTransformer] = None

# FastAPI app
app = FastAPI(title="Embedding API")

# Pydantic model for request body
class TextRequest(BaseModel):
    text: str

# Function to load/reuse model
def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print("⏳ Loading embedding model...")
        _model = SentenceTransformer("paraphrase-MiniLM-L3-v2")
        print("✅ Model loaded")
    return _model

# Function to get vector
def get_vector(text: str) -> Optional[List[float]]:
    try:
        model = get_model()
        vector = model.encode(
            text,
            normalize_embeddings=True,
            device="cpu"  # explicitly CPU
        )
        return vector.tolist()
    except Exception as e:
        print(f"Vector error: {e}")
        return None

# API endpoint to get vector
@app.post("/embed")
def embed_text(request: TextRequest):
    vector = get_vector(request.text)
    if vector is None:
        raise HTTPException(status_code=500, detail="Vectorization failed")
    return {"vector": vector}