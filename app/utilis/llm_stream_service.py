import json
import httpx
from app.core.config import settings

OLLAMA_URL = settings.OLLAMA_URL
OLLAMA_MODEL = settings.OLLAMA_MODEL
OLLAMA_TIMEOUT = 60

# ✅ Global client (connection pooling)
client = httpx.AsyncClient(
    timeout=httpx.Timeout(OLLAMA_TIMEOUT),
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
)


async def generate_llm_stream(user_query: str, context: str):

    prompt = f"""
You are an expert FAQ assistant.

STRICT RULES:
1. Answer ONLY using the provided context
2. Do NOT add any extra information
3. If answer is not found, respond exactly: "Answer not available in system"
4. Keep answer short and clear

---------------------
CONTEXT:
{context}
---------------------

USER QUESTION:
{user_query}

FINAL ANSWER:
"""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": 0.2,
            "num_predict": 200
        }
    }

    try:
        async with client.stream("POST", OLLAMA_URL, json=payload) as response:

            if response.status_code != 200:
                yield "data: LLM response failed\n\n"
                return

            async for line in response.aiter_lines():

                # 🔥 keep-alive heartbeat
                if not line:
                    yield ":\n\n"
                    continue

                try:
                    json_data = json.loads(line)

                    if json_data.get("done"):
                        break

                    chunk = json_data.get("response", "")
                    if chunk:
                        yield chunk

                except Exception as e:
                    print(f"Stream parse error: {e}")
                    continue

            # ✅ signal completion
            yield "[DONE]"

    except httpx.ReadTimeout:
        yield "LLM request timed out"

    except httpx.ConnectError:
        yield "LLM server not reachable"

    except Exception as e:
        yield f"data: LLM error: {str(e)}\n\n"