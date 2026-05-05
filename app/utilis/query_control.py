import re  # ✅ Fix kiya
def should_rewrite(query: str) -> bool:
    query = query.strip().lower()

    if not query:
        return False

    words = query.split()
    score = 0

    # 1. Bahut chhoti query
    if len(words) <= 2:
        score += 1

    # 2. Bahut kam characters
    if len(query) < 15:
        score += 1

    # 3. Query mein verb hi nahi (no action word feel)
    #    Simple check: koi bhi common action word nahi
    action_indicators = {"how", "what", "why", "when", "where", "can", "does", 
                        "is", "are", "do", "tell", "explain", "show", "help",
                        "kaise", "kya", "kab", "kyun", "batao", "samjhao"}
    
    if not any(w in action_indicators for w in words):
        score += 1

    # 4. Query question mark ke bina aur sirf 1 word
    if len(words) == 1:
        score += 2

    return score >= 2