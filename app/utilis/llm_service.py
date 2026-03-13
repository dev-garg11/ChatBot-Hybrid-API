import requests

OLLAMA_URL = "http://10.147.8.83:11434/api/generate"

def generate_llm_answer(user_query: str, context: str):

    prompt = f"""
You are an e-office assistant.

Use the context below to answer the user's question.

Context:
{context}

Question:
{user_query}

Answer clearly in steps.
"""

    payload = {
        "model": "llama3:8b",
        "prompt": prompt,
        "stream": False
    }

    response = requests.post(OLLAMA_URL, json=payload)

    if response.status_code == 200:
        return response.json()["response"]

    return "LLM response failed"