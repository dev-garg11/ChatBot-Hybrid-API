import httpx
from app.core.config import settings


OLLAMA_URL = settings.OLLAMA_URL
OLLAMA_MODEL = settings.OLLAMA_MODEL
OLLAMA_TIMEOUT = 60


async def generate_llm_answer(user_query: str, context: str) -> str:
    prompt = f"""
You are an expert FAQ assistant.

STRICT RULES:
1. Answer ONLY using the provided context
2. Do NOT add any extra information
3. If answer is not found, respond exactly: "Answer not available in system"
4. Keep answer short, clear, and structured

---------------------
CONTEXT:
{context}
---------------------

USER QUESTION:
{user_query}

FINAL ANSWER:"""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False      # ✅ Ollama ek saath poora answer dega
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(OLLAMA_TIMEOUT)) as client:
            response =await client.post(
                OLLAMA_URL,
                json=payload,
                timeout=OLLAMA_TIMEOUT
            )

        if response.status_code == 200:
            data = response.json()
            return data.get("response", "No response from LLM").strip()
        else:
            print(f"LLM API error: {response.status_code} - {response.text}")
            return "LLM response failed."

    except httpx.ConnectionError:
        print("⚠️ Cannot connect to Ollama server")
        return "LLM server is not reachable."

    except httpx.Timeout:
        print("⚠️ Ollama request timed out")
        return "LLM request timed out."

    except Exception as e:
        print(f"⚠️ Unexpected error: {e}")
        return "LLM service error."