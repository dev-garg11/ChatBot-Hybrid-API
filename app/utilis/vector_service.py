from sentence_transformers import SentenceTransformer
from typing import List, Optional

# Global model cache
_model: Optional[SentenceTransformer] = None


def get_model() -> SentenceTransformer:
    global _model

    if _model is None:
        try:
            print("⏳ Loading embedding model...")
            _model = SentenceTransformer("all-MiniLM-L6-v2")
            print("✅ Model loaded successfully")
        except Exception as e:
            print(f"⚠️ Model loading error: {e}")
            raise

    return _model


def get_vector(text: str) -> Optional[List[float]]:
    try:
        model = get_model()

        vector = model.encode(
            text,
            normalize_embeddings=True
        )

        return vector.tolist()

    except Exception as e:
        print(f"⚠️ Vector generation error: {e}")
        return None