"""
clarification_engine.py
-----------------------
Generates exactly ONE clarifying question based on the highest-priority
missing required field in the current intent.

Priority order (see references/clarification-rules.md):
    1. subject   — can't analyze anything without knowing what to analyze
    2. market    — scope needed before data fetch
    3. goal      — determines which analysis lens to apply

Language detection:
    Detects Vietnamese vs. English from conversation history and returns
    the question in the appropriate language.

Usage (CLI):
    python tools/clarification_engine.py \
        --missing '["market","goal"]' \
        --history '[{"role":"user","message":"Analyze MoMo"}]' \
        --subject "MoMo"

Output (stdout, JSON):
    {
        "field": "market",
        "question": "Which market would you like to analyze?",
        "language": "en"
    }
"""

import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# Priority order
# ---------------------------------------------------------------------------

FIELD_PRIORITY = ["subject", "market", "goal"]

# ---------------------------------------------------------------------------
# Question templates
# ---------------------------------------------------------------------------

QUESTIONS = {
    "subject": {
        "en": "Which product or app would you like to analyze?",
        "vi": "Bạn muốn phân tích sản phẩm hoặc ứng dụng nào?",
    },
    "market": {
        "en": "Which market would you like to focus on? (e.g., Vietnam, Southeast Asia)",
        "vi": "Bạn muốn phân tích thị trường nào? (ví dụ: Việt Nam, Đông Nam Á)",
    },
    "goal": {
        "en": "Is the goal of this analysis for **Product** insights or **Marketing** insights?",
        "vi": "Mục tiêu phân tích này là cho **Product** hay **Marketing**?",
    },
}

# Contextual overrides when subject is already known
QUESTIONS_WITH_SUBJECT = {
    "market": {
        "en": "Which market should I analyze {subject} in?",
        "vi": "Tôi nên phân tích {subject} ở thị trường nào?",
    },
    "goal": {
        "en": "Is this analysis of {subject} for Product insights or Marketing insights?",
        "vi": "Phân tích {subject} này dành cho Product hay Marketing?",
    },
}

# ---------------------------------------------------------------------------
# Confirmation keywords (language-aware)
# ---------------------------------------------------------------------------

CONFIRMATION_KEYWORDS_EN = {
    "yes", "confirm", "ok", "okay", "approve", "proceed",
    "go ahead", "do it", "ship it", "lgtm", "sure", "correct",
    "sounds good", "looks good", "go",
}
CONFIRMATION_KEYWORDS_VI = {
    "có", "đúng", "ổn", "được", "tiến hành", "làm đi",
    "ok", "đồng ý", "chính xác", "chuẩn", "tiếp tục",
}

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_VI_PATTERN = re.compile(
    r"[àáâãèéêìíòóôõùúýăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỷỹỵ]",
    re.IGNORECASE,
)


def detect_language(history: list[dict]) -> str:
    """
    Returns 'vi' if any user message in history contains Vietnamese diacritics,
    otherwise returns 'en'.
    """
    for turn in reversed(history):
        if turn.get("role") == "user":
            if _VI_PATTERN.search(turn.get("message", "")):
                return "vi"
    return "en"


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def get_clarification_question(
    missing: list[str],
    history: list[dict],
    subject: str | None = None,
) -> dict:
    """
    Returns a dict with:
        field    — the field being asked about
        question — the question string in the detected language
        language — 'en' or 'vi'
    Returns None if there are no missing required fields.
    """
    if not missing:
        return None

    # Sort by priority
    prioritized = [f for f in FIELD_PRIORITY if f in missing]
    if not prioritized:
        return None

    field = prioritized[0]
    lang = detect_language(history)

    # Use contextual template if subject is known and template exists
    if subject and field in QUESTIONS_WITH_SUBJECT:
        template = QUESTIONS_WITH_SUBJECT[field][lang]
        question = template.format(subject=subject)
    else:
        question = QUESTIONS[field][lang]

    return {
        "field": field,
        "question": question,
        "language": lang,
    }


def is_confirmation(message: str, language: str = "en") -> bool:
    """
    Returns True if `message` is a confirmation keyword.
    Checks both languages to be safe.
    """
    msg = message.strip().lower()
    all_keywords = CONFIRMATION_KEYWORDS_EN | CONFIRMATION_KEYWORDS_VI
    return msg in all_keywords


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate a single clarifying question for the highest-priority missing field."
    )
    parser.add_argument(
        "--missing",
        required=True,
        help='JSON array of missing field names, e.g. \'["market","goal"]\'',
    )
    parser.add_argument(
        "--history",
        default="[]",
        help="Conversation history JSON array",
    )
    parser.add_argument(
        "--subject",
        default=None,
        help="Already-resolved subject (for contextual question templates)",
    )
    args = parser.parse_args()

    try:
        missing = json.loads(args.missing)
        history = json.loads(args.history)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}), file=sys.stderr)
        sys.exit(1)

    result = get_clarification_question(missing, history, subject=args.subject)

    if result is None:
        print(json.dumps({"field": None, "question": None, "language": "en"}))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
