from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

def get_vector(text: str):
    try:
        vector = model.encode(text)
        return vector.tolist()   # numpy → list
    except Exception as e:
        print("Vector error:", e)
        return None