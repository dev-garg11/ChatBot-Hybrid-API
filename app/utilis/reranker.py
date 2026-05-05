import re
import asyncio
import json
import logging
from google import genai
from app.core.config import settings

logger = logging.getLogger(__name__)
client = genai.Client(api_key=settings.GEMINI_API_KEY)

MAX_RETRIES = 3
BASE_DELAY = 5


async def gemini_rerank(query: str, chunks, top_k: int = 5):

    if not chunks:
        return []

    chunks = chunks[:8]

    context_text = ""
    for i, c in enumerate(chunks):
        context_text += f"{i+1}. {c['content'][:300]}\n\n"

    prompt = f"""
You are a ranking system.

Task:
Rank chunks from MOST relevant to LEAST relevant.

Rules:
- Return ONLY a JSON array of numbers
- Example: [2,1,3]
- Do NOT explain anything
- Do NOT use markdown or backticks

Query:
{query}

Chunks:
{context_text}
"""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.5-flash",
                contents=prompt
            )

            if not response or not response.text:
                return _fallback_sort(chunks, top_k)

            raw = response.text.strip()

            # ✅ Backticks clean karo agar Gemini ne diye
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()

            # ✅ JSON parse
            try:
                order = json.loads(raw)
            except Exception:
                # ✅ Last resort: array dhundho string mein
                match = re.search(r"\[[\d,\s]+\]", raw)
                if match:
                    order = json.loads(match.group())
                else:
                    logger.warning(f"Invalid JSON from reranker (attempt {attempt}): {raw[:100]}")
                    return _fallback_sort(chunks, top_k)

            # ✅ Validate indices
            valid_order = []
            seen = set()

            for idx in order:
                if isinstance(idx, int) and 1 <= idx <= len(chunks) and idx not in seen:
                    valid_order.append(idx)
                    seen.add(idx)

            if not valid_order:
                return _fallback_sort(chunks, top_k)

            ranked = [chunks[i - 1] for i in valid_order]
            return ranked[:top_k]

        except Exception as e:
            error_str = str(e)

            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                delay = _extract_retry_delay(error_str) or (BASE_DELAY * attempt)

                if attempt < MAX_RETRIES:
                    logger.warning(
                        f"Reranker rate limit (attempt {attempt}/{MAX_RETRIES}), "
                        f"retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error("Reranker quota exhausted, using similarity sort.")
                    return _fallback_sort(chunks, top_k)
            else:
                logger.error(f"Gemini rerank error: {e}")
                return _fallback_sort(chunks, top_k)

    return _fallback_sort(chunks, top_k)


def _fallback_sort(chunks, top_k: int):
    """Similarity score se sort karo jab Gemini fail ho."""
    return sorted(
        chunks,
        key=lambda x: x.get("score", 0),
        reverse=True
    )[:top_k]


def _extract_retry_delay(error_str: str) -> float | None:
    match = re.search(r"retry[^\d]*(\d+(?:\.\d+)?)\s*s", error_str, re.IGNORECASE)
    if match:
        return float(match.group(1)) + 1
    return None