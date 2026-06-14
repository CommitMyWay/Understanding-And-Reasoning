"""
analyze_prompt.py
-----------------
Parses a raw user message and merges the result with the current session context
to produce an updated intent state.

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
        "mode": "initial"   // "initial" | "clarification" | "deep_dive"
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
        "bug", "crash", "performance", "flow", "ui", "sản phẩm", "tính năng",
    ],
    "marketing": [
        "marketing", "brand", "perception", "awareness", "campaign",
        "acquisition", "retention", "thương hiệu", "quảng cáo",
    ],
    "competitive": [
        "competitive", "competitor", "vs", "versus", "compare",
        "benchmark", "đối thủ", "so sánh",
    ],
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

PII_PATTERNS = [
    r"\b[\w.+-]+@[\w-]+\.\w{2,}\b",          # email
    r"\b(?:\+84|0)\d{9,10}\b",               # VN phone
    r"\b\d{9,12}\b",                          # numeric ID
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
    """
    # Pattern: "Login is ...", "the Login flow", "Login complaints"
    match = re.search(
        r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b(?:\s+(?:is|are|flow|feature|group|cluster|issue|complaint|problem))?",
        text,
    )
    if match:
        candidate = match.group(1)
        # Exclude the subject itself from being the focus
        if subject and candidate.lower() == subject.lower():
            return None
        return candidate

    # Vietnamese pattern: "nhóm Login", "vấn đề Login"
    match_vi = re.search(r"(?:nhóm|vấn đề|tính năng|màn hình)\s+([A-Za-zÀ-ɏ]+)", text)
    if match_vi:
        return match_vi.group(1)

    return None


def _extract_subject(text: str) -> str | None:
    """
    Heuristic: first proper noun after 'analyze', 'phân tích', etc.
    """
    patterns = [
        r"(?:analyze|analyse|phân tích|review|đánh giá)\s+([A-Za-z0-9À-ɏ]+)",
        r"^([A-Za-z0-9À-ɏ]+)\s+(?:app|platform|product|service|ứng dụng)",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _extract_market(text: str) -> str | None:
    """
    Heuristic: common market tokens in the message.
    """
    market_tokens = [
        "vietnam", "việt nam", "southeast asia", "sea", "indonesia",
        "thailand", "philippines", "singapore", "malaysia", "global",
    ]
    text_lower = text.lower()
    for token in market_tokens:
        if token in text_lower:
            return token.title()
    # Also match "in <Country>" or "tại <Country>"
    m = re.search(r"(?:in|at|tại|ở)\s+([A-Za-zÀ-ɏ]{3,})", text, re.IGNORECASE)
    if m:
        return m.group(1).strip().title()
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
    extracted_focus = _extract_focus(message, context.get("subject") or extracted_subject) if is_deep_dive else None

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

    # Determine mode
    if is_deep_dive and intent.get("subject"):
        mode = "deep_dive"
    elif all(intent.get(f) for f in REQUIRED_FIELDS):
        mode = "planning"
    else:
        # Check if this message was a direct answer to a clarification
        mode = "clarification" if context.get("clarifications_done") else "initial"

    # Identify still-missing required fields
    missing = [f for f in REQUIRED_FIELDS if not intent.get(f)]

    intent["missing_required"] = missing
    intent["mode"] = mode

    # Ensure keys exist
    intent.setdefault("focus", None)
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
