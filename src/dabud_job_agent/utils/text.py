from __future__ import annotations

import re

INTENT_KEYWORDS = [
    "seo",
    "organic growth",
    "geo",
    "aeo",
    "ai search",
    "llm seo",
    "generative engine optimization",
    "answer engine optimization",
    "ai overviews",
    "perplexity",
]

AI_SIGNAL_KEYWORDS = [
    "geo",
    "aeo",
    "ai search",
    "llm",
    "chatgpt",
    "ai overviews",
    "perplexity",
]

COMPETITOR_KEYWORDS = [
    "profound",
    "athenahq",
    "llm pulse",
    "peec ai",
    "peec.ai",
    "quattr",
    "bluefish",
    "otterly",
    "surfseo",
    "limy ai",
    "conductor",
    "scrunch",
    "aiclicks",
]


def summarize_text(text: str, max_len: int = 280) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= max_len:
        return clean
    return f"{clean[: max_len - 3]}..."


def keyword_score(text: str, keywords: list[str]) -> float:
    lower = text.lower()
    if not keywords:
        return 0.0
    matches = sum(1 for kw in keywords if kw in lower)
    return round(matches / len(keywords), 4)


def detect_mentions(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def parse_salary_aud(salary_raw: str | None) -> tuple[float | None, float | None]:
    if not salary_raw:
        return None, None
    lower = salary_raw.lower().replace(",", "")
    numbers = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)", lower)]
    if not numbers:
        return None, None

    min_salary = numbers[0]
    max_salary = numbers[1] if len(numbers) > 1 else numbers[0]

    if "hour" in lower:
        min_salary *= 38 * 52
        max_salary *= 38 * 52
    elif "week" in lower:
        min_salary *= 52
        max_salary *= 52
    elif "month" in lower:
        min_salary *= 12
        max_salary *= 12

    return round(min_salary, 2), round(max_salary, 2)
