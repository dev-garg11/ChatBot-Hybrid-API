import logging
import time
import asyncio
from ddgs import DDGS

logger = logging.getLogger(__name__)

async def google_search(query: str, num_results: int = 5):
    start_time = time.time()

    try:
        logger.info(f"🔍 Search started: '{query}'")

        results = await asyncio.to_thread(_ddg_search, query, num_results)

        total_time = time.time() - start_time
        logger.info(f"✅ Search complete: {len(results)} results in {total_time:.2f}s")

        return results

    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"❌ Search error ({total_time:.2f}s): {e}")
        return []


def _ddg_search(query: str, num_results: int):
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=num_results):
            results.append({
                "title": r.get("title", ""),
                "link": r.get("href", ""),
                "snippet": r.get("body", "")
            })
    return results