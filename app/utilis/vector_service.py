from sentence_transformers import SentenceTransformer
from typing import List

model = SentenceTransformer("all-MiniLM-L6-v2")


def get_vector(text: str) -> List[float]:
    return model.encode(text, normalize_embeddings=True).tolist()