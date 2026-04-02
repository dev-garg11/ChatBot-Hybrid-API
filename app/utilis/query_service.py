from app.utilis.llm_service import generate_llm_answer

async def rewrite_query(user_query: str) -> str:
    prompt = f"""
Convert the user query into a short, clear FAQ-style question.

Rules:
- Keep it short
- Remove extra words
- Keep intent same

Examples:
"I want to know how to close receipt"
→ "how to close receipt"

User Query:
{user_query}

Rewritten Query:
"""

    response = await generate_llm_answer(user_query=prompt,context="")
    return response.strip().lower()