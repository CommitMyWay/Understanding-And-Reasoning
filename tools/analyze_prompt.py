"""
analyze_prompt.py
-----------------
Parses a raw user message and merges the result with the current session context
to produce an updated intent state.

Fixes applied:
  - #6: _extract_focus now skips FOCUS_STOP_WORDS (Why, Tell, Show, etc.)
  - #7: mode=deep_dive only set when ALL required fields are already resolved
  - #10: _extract_market expanded with broader country list + pattern-first approach

Usage (CLI):
    python tools/analyze_prompt.py \
        --message "Analyze MoMo in Vietnam for product insights" \
        --context '{"subject":null,"market":null,"goal":null,"focus":null,"filters":{},"clarifications_done":[],"plan_steps":[]}'

Output (stdout, JSON):
    {
        "subject": "MoMo",
        "market": "Vietnam",
        "goal": "product",
        "focus": null,
        "filters": {},
        "clarifications_done": [],
        "plan_steps": [],
        "missing_required": [],
        "mode": "planning"
    }
"""

import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = ["subject", "market", "goal"]

GOAL_KEYWORDS = {
    "product": [
        "product", "feature", "ux", "user experience", "usability",
        "flow", "ui", "roadmap", "sản phẩm", "tính năng", "trải nghiệm",
    ],
    "marketing": [
        "marketing", "brand", "perception", "awareness", "campaign",
        "acquisition", "retention", "thương hiệu", "quảng cáo", "nhận thức",
    ],
    "quality": [
        "quality", "bug", "crash", "error", "defect", "qe", "test",
        "performance", "rating", "lỗi", "chất lượng", "kiểm thử", "sự cố",
    ],
}

# Supported data sources (shown to user as options)
ALL_DATA_SOURCES = ["App Store", "CH Play", "Youtube", "Voz", "Tinhte", "Reddit"]

DATA_SOURCE_TOKENS = {
    "app store": "App Store",
    "appstore": "App Store",
    "ios": "App Store",
    "ch play": "CH Play",
    "chplay": "CH Play",
    "google play": "CH Play",
    "play store": "CH Play",
    "android": "CH Play",
    "youtube": "Youtube",
    "voz": "Voz",
    "tinhte": "Tinhte",
    "tinh tế": "Tinhte",
    "reddit": "Reddit",
}

DEEP_DIVE_PATTERNS = [
    r"\bwhy\b",
    r"\bwhat cause",
    r"\broot cause",
    r"\bdeep.?dive\b",
    r"\banalyze\s+(?:the\s+)?(\w+)\s+(?:group|cluster|issue|complaint|problem)",
    r"\btell me more about\b",
    r"\bbreak down\b",
    r"\bphân tích sâu\b",
    r"\btại sao\b",
    r"\bvì sao\b",
    r"\bchi tiết\b",
]

# Fix #6: words that look like focus topics but are sentence starters / question words
FOCUS_STOP_WORDS = {
    "Why", "What", "How", "When", "Where", "Who", "Which",
    "Tell", "Show", "Give", "Let", "Break", "Find", "Get", "Can",
    "Please", "Help", "Make", "Does", "Is", "Are", "Was", "Were",
    # Vietnamese
    "Phân", "Tại", "Vì", "Hãy", "Cho", "Bạn", "Tôi",
}

PII_PATTERNS = [
    r"\b[\w.+-]+@[\w-]+\.\w{2,}\b",          # email
    r"\b(?:\+84|0)\d{9,10}\b",               # VN phone
    r"\b\d{9,12}\b",                          # numeric ID
]

# Fix #10: expanded market token list
MARKET_TOKENS = [
    "vietnam", "việt nam",
    "southeast asia", "sea",
    "indonesia", "thailand", "philippines", "singapore", "malaysia",
    "japan", "korea", "south korea", "china", "india",
    "usa", "united states", "us", "uk", "united kingdom",
    "australia", "europe", "global", "worldwide",
    "hồ chí minh", "hà nội", "hanoi", "ho chi minh",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_pii(text: str) -> str:
    for pattern in PII_PATTERNS:
        text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)
    return text


def _detect_goal(text: str) -> str | None:
    text_lower = text.lower()
    for goal, keywords in GOAL_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return goal
    return None


def _detect_deep_dive(text: str) -> bool:
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in DEEP_DIVE_PATTERNS)


def _extract_focus(text: str, subject: str | None) -> str | None:
    """
    Extracts a focus topic from a deep-dive question.
    E.g. "Why is Login complained about?" → "Login"

    Fix #6: skips FOCUS_STOP_WORDS so "Why", "Tell", etc. are never returned as focus.
    Uses finditer to try all matches, not just the first one.
    """
    # English pattern: capitalized word(s) optionally followed by feature/flow/etc.
    for match in re.finditer(
        r"\b([A-Z][a-zA-Z0-9]+(?:\s[A-Z][a-zA-Z0-9]+)?)\b"
        r"(?:\s+(?:is|are|flow|feature|group|cluster|issue|complaint|problem|error|bug))?",
        text,
    ):
        candidate = match.group(1)
        # Skip stop words
        if candidate in FOCUS_STOP_WORDS:
            continue
        # Skip subject itself
        if subject and candidate.lower() == subject.lower():
            continue
        # Skip known market names
        if candidate.lower() in MARKET_TOKENS:
            continue
        return candidate

    # Vietnamese pattern: "nhóm Login", "vấn đề Login", "tính năng Login"
    match_vi = re.search(
        r"(?:nhóm|vấn đề|tính năng|màn hình|chức năng)\s+([A-Za-zÀ-ɏ0-9]+)",
        text,
    )
    if match_vi:
        return match_vi.group(1)

    return None


def _extract_subject(text: str) -> str | None:
    """
    Heuristic: proper noun after 'analyze/phân tích/review', or before 'app/platform'.
    Also handles standalone product names as the first token when no trigger verb present.
    """
    patterns = [
        r"(?:analyze|analyse|phân tích|review|đánh giá|compare)\s+([A-Za-z0-9À-ɏ]+)",
        r"^([A-Za-z0-9À-ɏ]+)\s+(?:app|platform|product|service|ứng dụng)",
        # "MoMo in Vietnam" or "MoMo for product" — subject as first token
        r"^([A-Z][a-zA-Z0-9]+)\s+(?:in|for|ở|tại|cho)",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _extract_data_sources(text: str) -> list[str] | None:
    """
    Detects explicit data source mentions in the user message.
    Returns a list of matched sources, or None if none found.
    """
    text_lower = text.lower()
    found = []
    for token, source in DATA_SOURCE_TOKENS.items():
        if token in text_lower and source not in found:
            found.append(source)
    return found if found else None


def _extract_market(text: str) -> str | None:
    """
    Fix #10: pattern-first approach, then token list fallback.
    Handles broader country list and preposition patterns.
    """
    # Primary: explicit preposition pattern — "in Vietnam", "tại Việt Nam", "ở Korea"
    m = re.search(
        r"(?:\bin\b|\bat\b|tại|ở|cho thị trường)\s+([A-Za-zÀ-ɏ][\w\s]{1,30}?)(?:\s+(?:for|with|to|and|,|$))",
        text,
        re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip().rstrip(",.")
        # Make sure it's not a goal keyword
        if candidate.lower() not in ("product", "marketing", "competitive", "the"):
            return candidate.title()

    # Simpler preposition fallback (word boundary prevents matching inside "Login")
    m2 = re.search(r"\b(?:in|at|tại|ở)\b\s+([A-Za-zÀ-ɏ]{3,})", text, re.IGNORECASE)
    if m2:
        candidate = m2.group(1).strip().title()
        if candidate.lower() not in ("product", "marketing", "competitive", "the"):
            return candidate

    # Token list fallback
    text_lower = text.lower()
    for token in MARKET_TOKENS:
        if token in text_lower:
            return token.title()

    return None


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------

def parse(message: str, context: dict) -> dict:
    """
    Merges parsed fields from `message` into `context`.
    Returns updated intent dict with `missing_required` and `mode` added.
    """
    message = _strip_pii(message)

    is_deep_dive = _detect_deep_dive(message)

    # Extract new information from message
    extracted_subject = _extract_subject(message)
    extracted_market = _extract_market(message)
    extracted_goal = _detect_goal(message)
    extracted_focus = (
        _extract_focus(message, context.get("subject") or extracted_subject)
        if is_deep_dive else None
    )
    extracted_sources = _extract_data_sources(message)

    # Merge: only fill fields still null/missing in context
    intent = dict(context)
    if not intent.get("subject") and extracted_subject:
        intent["subject"] = extracted_subject
    if not intent.get("market") and extracted_market:
        intent["market"] = extracted_market
    if not intent.get("goal") and extracted_goal:
        intent["goal"] = extracted_goal
    if extracted_focus:
        intent["focus"] = extracted_focus
    # data_source: overwrite only if user explicitly named sources
    if extracted_sources:
        intent["data_source"] = extracted_sources

    # Fix #7: deep_dive mode only when ALL required fields already resolved
    all_resolved = all(intent.get(f) for f in REQUIRED_FIELDS)
    if is_deep_dive and all_resolved:
        mode = "deep_dive"
    elif all_resolved:
        mode = "planning"
    else:
        mode = "clarification" if context.get("clarifications_done") else "initial"

    # Identify still-missing required fields
    missing = [f for f in REQUIRED_FIELDS if not intent.get(f)]

    intent["missing_required"] = missing
    intent["mode"] = mode

    # Ensure keys exist
    intent.setdefault("focus", None)
    intent.setdefault("data_source", list(ALL_DATA_SOURCES))  # default = all sources
    intent.setdefault("filters", {})
    intent.setdefault("clarifications_done", [])
    intent.setdefault("plan_steps", [])

    return intent


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Parse a VoC user prompt into intent fields.")
    parser.add_argument("--message", required=True, help="Raw user message")
    parser.add_argument(
        "--context",
        default="{}",
        help="Current session context as JSON string",
    )
    args = parser.parse_args()

    try:
        context = json.loads(args.context)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid context JSON: {e}"}), file=sys.stderr)
        sys.exit(1)

    result = parse(args.message, context)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
