"""
clarification_engine.py
-----------------------
Generates exactly ONE clarifying question based on the highest-priority
missing required field in the current intent.

Fix #8: respects max_retries_per_field — returns None when cap is reached.
Fix #11: goal question now includes 'competitive' as a third option.

Priority order (see references/clarification-rules.md):
    1. subject   — can't analyze anything without knowing what to analyze
    2. market    — scope needed before data fetch
    3. goal      — determines which analysis lens to apply

Language detection:
    Detects Vietnamese vs. English from conversation history.

Usage (CLI):
    python tools/clarification_engine.py \
        --missing '["market","goal"]' \
        --history '[{"role":"user","message":"Analyze MoMo"}]' \
        --subject "MoMo" \
        --attempts '{"market":0,"goal":0}'

Output (stdout, JSON):
    {
        "field": "market",
        "question": "Which market should I analyze MoMo in?",
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
MAX_RETRIES_PER_FIELD = 2  # Fix #8

# ---------------------------------------------------------------------------
# Question templates
# ---------------------------------------------------------------------------

QUESTIONS = {
    "subject": {
        "en": "Which product or app would you like to analyze?",
        "vi": "Bạn muốn phân tích sản phẩm hoặc ứng dụng nào?",
    },
    "market": {
        "en": "Which market would you like to focus on?",
        "vi": "Bạn muốn phân tích thị trường nào?",
    },
    "goal": {
        "en": "What is the goal of this analysis?",
        "vi": "Mục tiêu phân tích này là gì?",
    },
    "data_source": {
        "en": "Which data sources should I pull from?",
        "vi": "Bạn muốn lấy dữ liệu từ nguồn nào?",
    },
}

QUESTIONS_WITH_SUBJECT = {
    "market": {
        "en": "Which market should I analyze {subject} in?",
        "vi": "Tôi nên phân tích {subject} ở thị trường nào?",
    },
    "goal": {
        "en": "What is the goal of this {subject} analysis?",
        "vi": "Mục tiêu phân tích {subject} này là gì?",
    },
}

# Retry prompts when first answer was ambiguous
RETRY_QUESTIONS = {
    "goal": {
        "en": "Please choose one: Product (feature/UX), Marketing (brand & perception), or Quality (bugs & ratings).",
        "vi": "Vui lòng chọn một: Product (tính năng/UX), Marketing (thương hiệu), hoặc Quality (lỗi & chất lượng).",
    },
    "market": {
        "en": "Please specify a market or region (e.g., Vietnam, Southeast Asia, Global).",
        "vi": "Vui lòng chỉ định thị trường hoặc khu vực (ví dụ: Việt Nam, Đông Nam Á, Toàn cầu).",
    },
    "subject": {
        "en": "Please provide the product or app name you want to analyze.",
        "vi": "Vui lòng cung cấp tên sản phẩm hoặc ứng dụng bạn muốn phân tích.",
    },
}

# Options for each field — presented as clickable choices; user can always type their own
QUESTION_OPTIONS = {
    "subject": None,  # free-text only
    "market": {
        "en": ["Vietnam", "Southeast Asia", "Global"],
        "vi": ["Việt Nam", "Đông Nam Á", "Toàn cầu"],
    },
    "goal": {
        "en": ["Product", "Marketing", "Quality"],
        "vi": ["Product", "Marketing", "Quality"],
    },
    "data_source": {
        "en": ["App Store", "CH Play", "Youtube", "Voz", "Tinhte", "Reddit", "All sources"],
        "vi": ["App Store", "CH Play", "Youtube", "Voz", "Tinhte", "Reddit", "Tất cả"],
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
    attempts: dict | None = None,
) -> dict | None:
    """
    Returns a dict with field / question / language, or None if nothing to ask.

    Fix #8: if attempts[field] >= MAX_RETRIES_PER_FIELD, skip that field.
    Uses retry question template on second attempt.
    """
    if not missing:
        return None

    attempts = attempts or {}
    lang = detect_language(history)

    for field in FIELD_PRIORITY:
        if field not in missing:
            continue

        field_attempts = attempts.get(field, 0)

        # Fix #8: cap reached — caller should use default, not ask again
        if field_attempts >= MAX_RETRIES_PER_FIELD:
            continue

        # Choose question template
        if field_attempts > 0 and field in RETRY_QUESTIONS:
            # Second attempt: use stricter retry prompt
            question = RETRY_QUESTIONS[field][lang]
        elif subject and field in QUESTIONS_WITH_SUBJECT:
            question = QUESTIONS_WITH_SUBJECT[field][lang].format(subject=subject)
        else:
            question = QUESTIONS[field][lang]

        # Attach options if available for this field
        field_opts = QUESTION_OPTIONS.get(field)
        options = field_opts[lang] if isinstance(field_opts, dict) else None

        result = {
            "field": field,
            "question": question,
            "language": lang,
            "attempt_number": field_attempts + 1,
        }
        if options:
            result["options"] = options
        return result

    # All missing fields have hit max retries
    return None


def is_confirmation(message: str, language: str = "en") -> bool:
    msg = message.strip().lower()
    return msg in (CONFIRMATION_KEYWORDS_EN | CONFIRMATION_KEYWORDS_VI)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate a single clarifying question for the highest-priority missing field."
    )
    parser.add_argument("--missing", required=True, help='JSON array, e.g. \'["market","goal"]\'')
    parser.add_argument("--history", default="[]", help="Conversation history JSON array")
    parser.add_argument("--subject", default=None)
    parser.add_argument(
        "--attempts",
        default="{}",
        help='JSON object of attempt counts per field, e.g. \'{"market":1,"goal":0}\'',
    )
    args = parser.parse_args()

    try:
        missing = json.loads(args.missing)
        history = json.loads(args.history)
        attempts = json.loads(args.attempts)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}), file=sys.stderr)
        sys.exit(1)

    result = get_clarification_question(missing, history, subject=args.subject, attempts=attempts)

    if result is None:
        print(json.dumps({"field": None, "question": None, "language": "en"}))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
